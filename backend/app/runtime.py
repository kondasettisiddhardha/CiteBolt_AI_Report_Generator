"""In-process run registry.

Each run keeps an append-only event log in memory. The SSE endpoint tails the
log, so a browser that connects late (or reconnects) still receives the whole
sequence. The database remains the source of truth for finished runs.
"""

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from app.graph import stream_pipeline

logger = logging.getLogger(__name__)


@dataclass
class ActiveRun:
    id: str
    events: list[dict[str, Any]] = field(default_factory=list)
    done: bool = False
    cancelled: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    def emit(self, event: dict[str, Any]) -> None:
        with self.lock:
            self.events.append(event)

    def snapshot(self) -> list[dict[str, Any]]:
        with self.lock:
            return list(self.events)

    def mark_cancelled(self) -> None:
        self.cancelled = True
        self.emit({"type": "error", "message": "Run cancelled."})


ACTIVE: dict[str, ActiveRun] = {}
ACTIVE_LOCK = threading.Lock()


def get_active(run_id: str) -> ActiveRun | None:
    return ACTIVE.get(run_id)


def start_run(
    run_id: str,
    initial_state: dict[str, Any],
    on_finish: Any,
) -> ActiveRun:
    """Start the pipeline in a daemon thread and return its event log handle."""
    active = ActiveRun(id=run_id)
    with ACTIVE_LOCK:
        ACTIVE[run_id] = active

    def work() -> None:
        state: dict[str, Any] = dict(initial_state)
        try:
            # Section-by-section generation when outline is provided or length is specified
            if initial_state.get("outline") or initial_state.get("length") in {"short", "standard", "long"}:
                from app.agents.section_engine import run_section_pipeline
                state = run_section_pipeline(initial_state, active.emit, lambda: active.cancelled)
            else:
                state = stream_pipeline(initial_state, active.emit)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Run %s failed", run_id)
            active.emit({"type": "error", "message": f"The run failed: {exc}"})
        finally:
            try:
                on_finish(run_id, state, active.cancelled)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Failed to finalise run %s", run_id)
            active.emit({"type": "complete", "run_id": run_id})
            active.done = True

    threading.Thread(target=work, name=f"run-{run_id[:8]}", daemon=True).start()
    return active


def cancel_run(run_id: str) -> bool:
    active = ACTIVE.get(run_id)
    if active is None or active.done:
        return False
    active.mark_cancelled()
    return True
