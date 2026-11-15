"""Shared Groq chat model.

All three agents use the same model, so it lives in one place. The model name and
API key come from the environment (GROQ_MODEL, GROQ_API_KEY, GROQ_FALLBACK_MODELS).
"""

import re
import time
from typing import Any

from app.config import GROQ_API_KEY, GROQ_FALLBACK_MODELS, GROQ_MODEL, MODEL_PRICING


class DailyTokenLimitError(Exception):
    """Raised when Groq daily token/request limits (TPD/RPD) are exceeded."""

    def __init__(self, message: str, model: str, retry_after: str | None = None):
        super().__init__(message)
        self.message = message
        self.model = model
        self.retry_after = retry_after


class ModelNotFoundError(Exception):
    """Raised when a requested model is not accessible or not found on Groq."""

    def __init__(self, message: str, model: str):
        super().__init__(message)
        self.message = message
        self.model = model


def is_daily_limit_error(err_str: str) -> bool:
    """Distinguish per-minute (TPM/RPM) 429s from per-day (TPD/RPD) 429s."""
    lower = err_str.lower()
    return (
        "tokens per day" in lower
        or "(tpd)" in lower
        or "requests per day" in lower
        or "(rpd)" in lower
        or "daily limit" in lower
        or "tpd:" in lower
        or "rpd:" in lower
    )


def compute_cost(input_tokens: int, output_tokens: int, model: str | None = None) -> float:
    """Compute estimated USD cost from token usage."""
    chosen_model = model or GROQ_MODEL
    pricing = MODEL_PRICING.get(chosen_model, MODEL_PRICING["default"])
    cost = (input_tokens / 1_000_000.0) * pricing["input_per_million"] + (
        output_tokens / 1_000_000.0
    ) * pricing["output_per_million"]
    return round(cost, 6)


def get_llm(model: str | None = None) -> Any:
    """Return the Groq chat model for the requested or default model."""
    if not GROQ_API_KEY:
        raise RuntimeError(
            "No GROQ_API_KEY found in the environment. Add it to backend/.env "
            "(get one at https://console.groq.com/keys) and restart the API."
        )

    try:
        from langchain_groq import ChatGroq
    except ImportError as exc:  # pragma: no cover - environment specific
        raise RuntimeError(
            "langchain-groq is required. Run: pip install -r requirements.txt"
        ) from exc

    chosen_model = model or GROQ_MODEL
    kwargs: dict[str, Any] = {
        "model": chosen_model,
        "api_key": GROQ_API_KEY,
        "temperature": 0.2,
        "max_tokens": 8192,
        "max_retries": 0,  # the graph handles retries with backoff
    }
    model_lower = chosen_model.lower()
    if any(k in model_lower for k in ["gpt-oss", "deepseek-r1", "-r1", "qwq", "o1", "o3"]):
        kwargs["reasoning_effort"] = "low"

    try:
        return ChatGroq(**kwargs)
    except Exception:
        kwargs.pop("reasoning_effort", None)
        return ChatGroq(**kwargs)


def generate_text(
    prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    on_rate_limit: Any | None = None,
    model: str | None = None,
) -> tuple[str, dict[str, int]]:
    """Generate text from LLM with token usage tracking, TPM backoff, and TPD fast-exit."""
    chosen_model = model or GROQ_MODEL
    llm = get_llm(model=chosen_model)
    llm.temperature = temperature
    llm.max_tokens = max_tokens

    last_err: Exception | None = None
    for attempt in range(1, 6):
        try:
            resp = llm.invoke(prompt)
            content = str(resp.content) if hasattr(resp, "content") else str(resp)
            usage: dict[str, int] = {}
            finish_reason = "stop"
            if hasattr(resp, "response_metadata") and resp.response_metadata:
                finish_reason = resp.response_metadata.get("finish_reason") or "stop"
            elif hasattr(resp, "additional_kwargs") and resp.additional_kwargs:
                finish_reason = resp.additional_kwargs.get("finish_reason") or "stop"

            if not content or not content.strip():
                raise RuntimeError(
                    f"Model {chosen_model} returned empty content (finish_reason={finish_reason}). "
                    "Completion tokens were likely exhausted by reasoning tokens."
                )

            if hasattr(resp, "response_metadata") and resp.response_metadata.get("token_usage"):
                tu = resp.response_metadata["token_usage"]
                usage = {
                    "input_tokens": int(tu.get("prompt_tokens", 0)),
                    "output_tokens": int(tu.get("completion_tokens", 0)),
                    "total_tokens": int(tu.get("total_tokens", 0)),
                    "finish_reason": finish_reason,
                }
            elif hasattr(resp, "usage_metadata") and resp.usage_metadata:
                tu = resp.usage_metadata
                usage = {
                    "input_tokens": int(tu.get("input_tokens", 0)),
                    "output_tokens": int(tu.get("output_tokens", 0)),
                    "total_tokens": int(tu.get("total_tokens", 0)),
                    "finish_reason": finish_reason,
                }
            else:
                usage = {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "finish_reason": finish_reason,
                }
            return content, usage
        except Exception as exc:
            last_err = exc
            err_str = str(exc)

            # Check for non-existent or inaccessible model (404)
            if "404" in err_str or "does not exist" in err_str.lower():
                raise ModelNotFoundError(
                    message=f"Model {chosen_model} not found or no access: {err_str}",
                    model=chosen_model,
                ) from exc
            
            # Check for per-day limits (TPD/RPD)
            if is_daily_limit_error(err_str):
                # Extract wait time if mentioned
                match = re.search(r"try again in ([0-9a-zA-Z.]+)", err_str, re.IGNORECASE)
                wait_str = match.group(1) if match else None
                # Do NOT retry in a loop for this model - exit immediately so caller can switch models or pause!
                raise DailyTokenLimitError(
                    message=f"Daily token limit reached for model {chosen_model}: {err_str}",
                    model=chosen_model,
                    retry_after=wait_str,
                ) from exc

            is_429 = "429" in err_str.lower() or "rate limit" in err_str.lower() or "rate_limit" in err_str.lower()
            wait_sec = min(35.0, 3.0 * (1.8 ** (attempt - 1)))
            match_sec = re.search(r"try again in ([0-9.]+)s", err_str, re.IGNORECASE)
            if match_sec:
                try:
                    wait_sec = max(wait_sec, float(match_sec.group(1)) + 1.0)
                except Exception:
                    pass

            if is_429 and on_rate_limit:
                try:
                    on_rate_limit(f"waiting for rate limit (retrying in {int(wait_sec)}s)...", wait_sec)
                except Exception:
                    pass

            time.sleep(wait_sec)

    raise last_err or RuntimeError("LLM invocation failed")
