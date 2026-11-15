"""Analysis Agent.

Reads the sources collected by the Research Agent and extracts key insights,
themes, statistics, and conflicting points as structured JSON.
"""

import logging
import re
import time
from typing import Any

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.config import BACKOFF, RETRIES
from app.llm import get_llm
from app.state import ResearchState

logger = logging.getLogger(__name__)

# Rich, plain-language prompt that asks for structured extraction. The model's
# JSON is parsed into the shared state so the writing agent can trust the shape.
# NOTE: braces in the example JSON are doubled ({{  }}) because the template is
# parsed as an f-string under the hood.
ANALYSIS_PROMPT = ChatPromptTemplate.from_template(
    """You are the analysis team of a research report.

The topic is:

    {topic}

Here are the sources collected during research:

{sources_escaped}

Read them carefully and extract:

1. KEY INSIGHTS - the most important findings, written in plain language (not academic).
2. THEMES - recurring topics that appear across multiple sources.
3. STATISTICS - notable numbers, percentages, figures, or timeframes, with the source where you found them.
4. CONFLICTING POINTS - places where sources disagree or present different views.
5. GAPS - things that are still unclear or missing from the sources.

Return ONLY a valid JSON object with these keys. Do not wrap the JSON in markdown
fences and do not add any prose before or after it.

{{
  "key_insights": ["one plain-language finding", ...],
  "themes": ["theme one", ...],
  "statistics": [
    {{"value": "12%", "context": "of survey respondents", "source": "source title"}}
  ],
  "conflicting_points": ["where sources disagree"],
  "gaps": ["what is still unknown or unclear"]
}}
"""
)


_NUMBER = re.compile(r"\d[\d,.]*\s?(?:%|percent|million|billion|k|m|x)?", re.IGNORECASE)


def _number_tokens(text: str) -> list[str]:
    tokens = []
    for match in _NUMBER.finditer(str(text)):
        token = match.group(0).strip().lower().replace(",", "")
        if len(token) > 1:
            tokens.append(token)
    return tokens


def _verify_numeric_claims(insights: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Drop numeric claims whose figure never appears in the fetched sources."""
    corpus = " ".join(
        str(source.get("title", "")) + " " + str(source.get("content", "")) for source in sources
    ).lower().replace(",", "")

    if not corpus.strip():
        return insights

    kept_statistics = []
    dropped: list[str] = []

    for statistic in insights.get("statistics") or []:
        value = str(statistic.get("value", ""))
        tokens = _number_tokens(value)
        if not tokens or any(token in corpus for token in tokens):
            kept_statistics.append(statistic)
        else:
            dropped.append(f"statistic {value}")

    kept_insights = []
    for insight in insights.get("key_insights") or []:
        tokens = _number_tokens(insight)
        if not tokens or any(token in corpus for token in tokens):
            kept_insights.append(insight)
        else:
            dropped.append(str(insight)[:80])

    if dropped:
        logger.info("Verification removed %d unsupported numeric claims", len(dropped))

    insights["statistics"] = kept_statistics
    insights["key_insights"] = kept_insights
    insights["dropped_claims"] = dropped
    return insights


class AnalysisOutput(BaseModel):
    key_insights: list[str] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    statistics: list[dict] = Field(default_factory=list)
    conflicting_points: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


def analysis_node(state: ResearchState) -> ResearchState:
    """Extract structured insights from the collected sources."""
    topic = state.get("topic", "")
    sources = state.get("sources", [])

    if not topic:
        raise ValueError("Analysis Agent requires a topic")

    if not sources:
        # Nothing to analyse yet; record the error, don't crash the run.
        state.setdefault("errors", []).append(
            {"node": "analysis", "error": "No sources available to analyse", "sources": []}
        )
        return state

    # Build sources string for the prompt.
    source_blocks = []
    for i, src in enumerate(sources, start=1):
        source_blocks.append(
            f"--- Source {i} ---\nTitle: {src.get('title', 'Untitled')}\n"
            f"URL: {src.get('url', '')}\nContent: {src.get('content', '')[:2000]}"
        )
    sources_text = "\n\n".join(source_blocks)

    parser = PydanticOutputParser(pydantic_object=AnalysisOutput)

    sources_text = sources_text or "(No sources available to analyse.)"

    llm = get_llm()
    prompt_val = ANALYSIS_PROMPT.invoke(
        {
            "topic": topic,
            "sources": sources_text,
            "sources_escaped": sources_text.replace("{", "{{").replace("}", "}}"),
            "format_instructions": parser.get_format_instructions(),
        }
    )

    for attempt in range(1, RETRIES + 1):
        try:
            ai_msg = llm.invoke(prompt_val)
            usage = getattr(ai_msg, "usage_metadata", None) or getattr(ai_msg, "response_metadata", {}).get("token_usage", {})
            in_tok = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
            out_tok = usage.get("output_tokens") or usage.get("completion_tokens") or 0
            tot_tok = usage.get("total_tokens") or (in_tok + out_tok)
            state["input_tokens"] = state.get("input_tokens", 0) + in_tok
            state["output_tokens"] = state.get("output_tokens", 0) + out_tok
            state["token_usage"] = state.get("token_usage", 0) + tot_tok

            result = parser.parse(ai_msg.content)
            state["insights"] = result.model_dump()
            # Normalise statistics into a plain list for the writer.
            state["insights"]["statistics"] = result.statistics
            state["insights"] = _verify_numeric_claims(state["insights"], sources)
            return state
        except Exception as exc:  # pragma: no cover - network/environment
            logger.warning("Analysis attempt %d failed: %s", attempt, exc)
            if attempt == RETRIES:
                state.setdefault("errors", []).append(
                    {"node": "analysis", "error": str(exc), "sources": sources}
                )
                # Keep going with partial insights if we have them.
                state["insights"] = {
                    "key_insights": [],
                    "themes": [],
                    "statistics": [],
                    "conflicting_points": [],
                    "gaps": [],
                }
                return state
            time.sleep(BACKOFF * attempt)

    return state
