"""Shared Groq chat model.

All three agents use the same model, so it lives in one place. The model name and
API key come from the environment (GROQ_MODEL, GROQ_API_KEY).
"""

from typing import Any

from app.config import GROQ_API_KEY, GROQ_MODEL


def get_llm() -> Any:
    """Return the Groq chat model, or raise a clear error if it is not configured."""
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

    return ChatGroq(
        model=GROQ_MODEL,
        api_key=GROQ_API_KEY,
        temperature=0.2,
        max_retries=0,  # the graph handles retries with backoff
    )
