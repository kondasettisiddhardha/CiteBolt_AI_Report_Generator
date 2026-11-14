"""Writing Agent.

Turns the structured analysis into a plain-language Markdown report with:
Title, Executive Summary, Key Findings, Detailed Analysis, Conclusion, and
Sources (with links). No jargon, written for students and early-career
professionals.
"""

import logging
import time
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.config import BACKOFF, RETRIES
from app.llm import get_llm
from app.state import ResearchState

logger = logging.getLogger(__name__)

# The writing prompt is deliberately written for a non-expert audience: clear
# language, short paragraphs, plain-language summaries, and a complete source
# list at the end.
WRITING_PROMPT = ChatPromptTemplate.from_template(
    """You are an expert report writer. Write a clear, professional report for
students and early-career professionals. Plain language, short paragraphs, no
jargon. Do not sound like a textbook.

The user's request was:

    {topic}

Today's date is {today}. Any pricing information must be introduced with
"As of {today}," and described as a vendor claim unless a review confirms it.

{report_shape}

{background}

Here is the analysis produced by the analysis agent:

{insights}

Here are the numbered sources. Cite ONLY these numbers and never invent one:

{sources}

Formatting rules:
- Use plain ASCII only: a normal hyphen "-", straight quotes, three dots for an
  ellipsis. Never use em dashes, curly quotes or non-breaking spaces.
- Write a short, clean, descriptive title as the first line, as "# Title". Never
  repeat the user's request as the title and never start with "Report about".
- Do not write a Sources section; it is generated from the source data.

Structure the Markdown exactly like this:

# <short descriptive title>

## Executive Summary
3-4 sentences on what the report found and why it matters.

## Key Findings
5-8 bullets, one idea each. Each bullet that makes a factual claim ends with the
citation of the source it came from, like [2].

## Detailed Analysis
2-3 sections with "##" headings, one per theme. Each paragraph is under 5
sentences. Cite [n] only where that exact source supports the sentence. Do not
add findings without cited support. When a claim is a vendor's own claim, say so
("Acme reports...").

If the report compares products, include a Markdown table with the columns
Tool | Real-time vs post-call | Price | Privacy approach | Languages.

## Limitations
2-3 sentences on what the sources could not establish (missing prices, no
independent testing, stale data).

## Conclusion
3-4 sentences restating the main takeaway.

Output ONLY the Markdown report. No preamble, no closing remarks.
"""
)


# Section targets per report type. The user picks one in the composer; it
# shapes the outline and depth the writer aims for.
REPORT_SHAPES: dict[str, str] = {
    "auto": "Choose the shape and length that best suits the topic.",
    "briefing": "Keep it tight: 5-6 sections, fastest to read.",
    "deepdive": "Go deep: 9-11 sections covering foundations, theory, and counterarguments.",
    "architectureblueprint": (
        "Write it as an architecture blueprint: requirements, components, data flow, "
        "trade-offs, and a delivery plan."
    ),
    "researchpaper": (
        "Write it as a research paper: abstract, background, method, findings, "
        "discussion, and limitations."
    ),
}


def _report_shape(report_type: str | None) -> str:
    shape = REPORT_SHAPES.get((report_type or "auto").lower())
    if not shape:
        return ""
    return f"The requested report type is '{report_type}'. {shape}"


def _background(context: str | None) -> str:
    if not context:
        return ""
    return (
        "The user supplied this background material. Use it to steer the report; "
        "do not invent facts that are not in the sources or this material:\n\n"
        + context[:20000]
    )


def writer_node(state: ResearchState) -> ResearchState:
    """Build the Markdown report and store it in the shared state."""
    topic = state.get("topic", "")
    insights = state.get("insights", {})

    if not topic:
        raise ValueError("Writing Agent requires a topic")

    # Never write a report from nothing: without analysis there is nothing to
    # report, and inventing content is worse than failing.
    if not insights or not (insights.get("key_insights") or insights.get("themes")):
        state.setdefault("errors", []).append(
            {"node": "writing", "error": "There were no insights to write up."}
        )
        return state

    # Build the insights payload that the prompt expects.
    insights_text = _format_insights(insights)

    source_blocks = _format_sources(state.get("sources", []))
    insights_text = insights_text or "(No insights were produced - the analysis agent could not extract any.)"

    today = time.strftime("%d %B %Y")
    prompt = WRITING_PROMPT.partial(
        topic=topic,
        insights=insights_text,
        sources=source_blocks,
        report_shape=_report_shape(state.get("report_type")),
        background=_background(state.get("context")),
        today=today,
    )

    chain = prompt | get_llm() | StrOutputParser()

    for attempt in range(1, RETRIES + 1):
        try:
            report = chain.invoke(
                {
                    "topic": topic,
                    "insights": insights_text,
                    "sources": source_blocks,
                    "report_shape": _report_shape(state.get("report_type")),
                    "background": _background(state.get("context")),
                    "today": today,
                }
            )
            # Normalise: strip accidental triple-backtick fences.
            report = report.strip()
            if report.startswith("```"):
                report = report.split("```", 1)[-1].strip()
            if report.startswith("json"):
                report = report.split("\n", 1)[-1].strip()

            state["report"] = report
            state["status"] = {
                "current_node": "done",
                "message": "Report generated and saved.",
                "started_at": state.get("status", {}).get("started_at"),
            }
            return state
        except Exception as exc:  # pragma: no cover - network/environment
            logger.warning("Writing attempt %d failed: %s", attempt, exc)
            if attempt == RETRIES:
                state.setdefault("errors", []).append(
                    {"node": "writing", "error": str(exc), "sources": state.get("sources", [])}
                )
                return state
            time.sleep(BACKOFF * attempt)

    return state


def _format_insights(insights: dict[str, Any]) -> str:
    """Turn the parsed insights dict into a readable block for the prompt."""
    parts = []
    if insights.get("key_insights"):
        parts.append("KEY INSIGHTS:\n" + "\n".join(f"  - {i}" for i in insights["key_insights"]))
    if insights.get("themes"):
        parts.append("THEMES:\n" + "\n".join(f"  - {t}" for t in insights["themes"]))
    if insights.get("statistics"):
        parts.append(
            "STATISTICS:\n"
            + "\n".join(
                f"  - {s.get('value', '')} ({s.get('context', '')}), source: {s.get('source', '')}"
                for s in insights["statistics"]
            )
        )
    if insights.get("conflicting_points"):
        parts.append("CONFLICTING POINTS:\n" + "\n".join(f"  - {p}" for p in insights["conflicting_points"]))
    if insights.get("gaps"):
        parts.append("GAPS:\n" + "\n".join(f"  - {g}" for g in insights["gaps"]))
    return "\n\n".join(parts)


def _format_sources(sources: list[dict[str, Any]]) -> str:
    """Format the sources list as a numbered block the writer can cite."""
    if not sources:
        return "(No sources available.)"
    blocks = []
    for i, src in enumerate(sources, start=1):
        blocks.append(
            f"[{i}] {src.get('title', 'Untitled')}\n"
            f"    URL: {src.get('url', '')}\n"
            f"    Text: {src.get('content', '')[:800]}"
        )
    return "\n\n".join(blocks)
