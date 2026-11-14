"""Shared LangGraph state for the research & report generation pipeline.

TypedDict that tracks everything the agents need while they work together:
topic -> sources -> insights -> report, plus progress flags and error handling.
"""

from typing import Literal, TypedDict


# How far along the pipeline we are.
class PipelineStatus(TypedDict):
    current_node: Literal["research", "analysis", "writing", "done"]
    message: str
    started_at: str | None


class ResearchSource(TypedDict):
    """A single source collected by the Research Agent."""

    title: str
    url: str
    content: str
    # Used to help the writing agent cite nicely.
    source_index: int


class ResearchState(TypedDict, total=False):
    """The shared state. Every key is optional so a fresh run starts empty."""

    topic: str
    status: PipelineStatus
    sources: list[ResearchSource]
    insights: dict
    report: str
    errors: list[dict]
    # Optional background material pasted or uploaded by the user.
    context: str
    # Requested report shape: auto | briefing | deepdive | architectureblueprint.
    report_type: str
    # Metadata used by the streaming endpoint to annotate SSE events.
    event_meta: dict | None


# Helper so test code can build a "ready to run" state quickly.
def empty_state() -> ResearchState:
    return {
        "topic": "",
        "status": {"current_node": "research", "message": "", "started_at": None},
        "sources": [],
        "insights": {},
        "report": "",
        "errors": [],
        "event_meta": None,
    }
