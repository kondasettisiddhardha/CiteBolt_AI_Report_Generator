"""LangGraph pipeline: research -> analysis -> writing.

The graph is the single source of truth for the agent order. For the live UI we
stream the graph node by node and translate each update into a stage event, so
the browser can show each agent starting and finishing in real time.
"""

import logging
import time
from typing import Any, Callable

from langgraph.graph import END, StateGraph

from app.agents.analysis import analysis_node
from app.agents.research import research_node
from app.agents.writer import writer_node
from app.config import BACKOFF, RETRIES
from app.state import ResearchState

logger = logging.getLogger(__name__)

# Order, label and running message for each agent, used by the UI and the API.
STAGES: list[dict[str, str]] = [
    {
        "node": "research",
        "label": "Research",
        "running": "Searching the web and gathering sources.",
    },
    {
        "node": "analysis",
        "label": "Analysis",
        "running": "Reading the sources and extracting insights.",
    },
    {
        "node": "writing",
        "label": "Writing",
        "running": "Drafting the structured report.",
    },
]

_STAGE_BY_NODE = {stage["node"]: stage for stage in STAGES}


def _stage_message(node: str) -> str:
    """Short, specific message describing what a finished stage produced."""
    if node == "research":
        return "Sources collected."
    if node == "analysis":
        return "Insights extracted."
    return "Report drafted."
def _run_with_retry(node_fn, state: ResearchState, node_name: str) -> ResearchState:
    """Run one agent, retrying transient failures before recording an error."""
    for attempt in range(1, RETRIES + 1):
        try:
            return node_fn(state)
        except Exception as exc:  # pragma: no cover - network
            logger.warning("Node '%s' attempt %d failed: %s", node_name, attempt, exc)
            if attempt == RETRIES:
                state.setdefault("errors", []).append(
                    {"node": node_name, "error": str(exc)}
                )
                return state
            time.sleep(BACKOFF * attempt)
    return state


def _node(name: str):
    """Wrap an agent node so every graph run gets retries and error capture."""

    def runner(state: ResearchState) -> ResearchState:
        state["status"] = {
            "current_node": name,
            "message": _STAGE_BY_NODE[name]["running"],
            "started_at": time.strftime("%H:%M:%S"),
        }
        module_node = {
            "research": research_node,
            "analysis": analysis_node,
            "writing": writer_node,
        }[name]
        return _run_with_retry(module_node, state, name)

    return runner


def _node_failed(state: ResearchState, node: str) -> bool:
    return any(error.get("node") == node for error in state.get("errors", []))


def _after_research(state: ResearchState) -> str:
    return END if _node_failed(state, "research") else "analysis"


def _after_analysis(state: ResearchState) -> str:
    return END if _node_failed(state, "analysis") else "writing"


def build_graph():
    """Compile the pipeline: research -> analysis -> writing.

    If a stage records an error, the run stops there rather than asking the next
    agent to work with nothing.
    """
    graph = StateGraph(ResearchState)
    graph.add_node("research", _node("research"))
    graph.add_node("analysis", _node("analysis"))
    graph.add_node("writing", _node("writing"))

    graph.set_entry_point("research")
    graph.add_conditional_edges("research", _after_research, ["analysis", END])
    graph.add_conditional_edges("analysis", _after_analysis, ["writing", END])
    graph.add_edge("writing", END)

    return graph.compile()


def stream_pipeline(
    initial_state: ResearchState,
    emit: Callable[[dict[str, Any]], None],
) -> ResearchState:
    """Run the pipeline, emitting a stage event as each agent starts and ends.

    Events emitted:
      {"type": "stage", "node": ..., "status": "running" | "done", "message": ...}
      {"type": "report", "report": ..., "sources": [...], "insights": {...}}
      {"type": "error", "message": ...}
    """
    graph = build_graph()
    state: ResearchState = dict(initial_state)  # type: ignore[assignment]

    emit(
        {
            "type": "stage",
            "node": STAGES[0]["node"],
            "status": "running",
            "message": STAGES[0]["running"],
        }
    )

    next_index = 1
    try:
        for update in graph.stream(initial_state, stream_mode="updates"):
            for node_name, values in update.items():
                if isinstance(values, dict):
                    state.update(values)  # type: ignore[arg-type]

                error = _first_error_for(node_name, state)
                emit(
                    {
                        "type": "stage",
                        "node": node_name,
                        "status": "error" if error else "done",
                        "message": error or _stage_message(node_name),
                    }
                )

                if error:
                    # Later stages will not run; surface that immediately.
                    for skipped in STAGES[next_index:]:
                        emit(
                            {
                                "type": "stage",
                                "node": skipped["node"],
                                "status": "error",
                                "message": "Skipped because an earlier stage failed.",
                            }
                        )
                    next_index = len(STAGES)
                elif next_index < len(STAGES):
                    stage = STAGES[next_index]
                    emit(
                        {
                            "type": "stage",
                            "node": stage["node"],
                            "status": "running",
                            "message": stage["running"],
                        }
                    )
                    next_index += 1
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Pipeline failed")
        emit({"type": "error", "message": f"The pipeline stopped: {exc}"})
        return state

    report = state.get("report", "")
    if report:
        emit(
            {
                "type": "report",
                "report": report,
                "sources": state.get("sources", []),
                "insights": state.get("insights", {}),
            }
        )
    else:
        errors = state.get("errors") or []
        message = errors[-1].get("error") if errors else "No report was produced."
        emit({"type": "error", "message": message or "No report was produced."})

    return state


def _first_error_for(node: str, state: ResearchState) -> str | None:
    """Return an error message recorded by this node, if any."""
    for error in state.get("errors", []):
        if error.get("node") == node:
            return str(error.get("error"))
    return None
