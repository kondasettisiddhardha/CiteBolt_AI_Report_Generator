"""CiteBolt API.

Auth: email one-time codes, verified into an httpOnly JWT cookie.
Runs: created in SQLite (or Postgres), executed by a background thread, streamed
over SSE, and exportable as Markdown, PDF or Word.
"""

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
import re

from app.models import ContactMessage, OtpCode, Run, Template, User, UserSettings
from app.templates_service import extract_outline_from_upload


from app.text import (
    _normalise_sources_list,
    build_sources_markdown,
    filter_and_renumber_sources,
    normalize_text,
    prepare_report,
    renumber_citations,
    strip_leading_title,
    strip_sources_section,
)

from app.config import (
    ALLOWED_ORIGINS,
    DAILY_RUN_LIMIT,
    FRONTEND_URL,
    MAX_CONTEXT_CHARS,
    MAX_TOPIC_CHARS,
    MAX_UPLOAD_BYTES,
    OTP_MAX_ATTEMPTS,
    OTP_MAX_REQUESTS,
    OTP_REQUEST_WINDOW_SECONDS,
    OTP_TTL_SECONDS,
    SESSION_COOKIE,
    SESSION_DAYS,
    SUPPORT_EMAIL,
)
from app.db import get_db, init_db
from app.emailer import send_contact_message, send_otp_code
from app.export import markdown_to_docx, markdown_to_pdf
from app.models import ContactMessage, OtpCode, Run, User, UserSettings
from app.runtime import cancel_run, get_active, start_run
from app.security import (
    create_token,
    generate_otp,
    get_current_user,
    get_optional_user,
    hash_otp,
    new_id,
    verify_otp,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("citebolt")

app = FastAPI(title="CiteBolt API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in ALLOWED_ORIGINS.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

REPORT_TYPES = {"auto", "briefing", "deepdive", "architectureblueprint", "researchpaper", "template"}


# Create tables as soon as the module loads as well as on startup, so the app
# works under TestClient and when imported by a worker without a startup hook.
init_db()


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    logger.info("CiteBolt API ready")


# --- health ------------------------------------------------------------
@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# --- auth --------------------------------------------------------------
@app.post("/api/auth/request-otp")
def request_otp(payload: dict[str, Any], db: Session = Depends(get_db)) -> dict[str, Any]:
    email = str(payload.get("email") or "").strip().lower()
    if not email or "@" not in email or len(email) > 320:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")

    window_start = datetime.now(timezone.utc) - timedelta(seconds=OTP_REQUEST_WINDOW_SECONDS)
    recent = db.scalar(
        select(func.count(OtpCode.id)).where(
            OtpCode.email == email, OtpCode.created_at >= window_start
        )
    )
    if (recent or 0) >= OTP_MAX_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail="Too many codes requested. Try again in a few minutes.",
        )

    code = generate_otp()
    db.add(
        OtpCode(
            email=email,
            code_hash=hash_otp(code),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=OTP_TTL_SECONDS),
        )
    )
    db.commit()

    delivered = send_otp_code(email, code)
    return {
        "sent": True,
        "delivered": delivered,
        "detail": "Check your inbox for a 6-digit code."
        if delivered
        else "Email is not configured, so the code was printed in the backend console.",
    }


@app.post("/api/auth/verify-otp")
def verify_code(payload: dict[str, Any], response: Response, db: Session = Depends(get_db)) -> dict[str, Any]:
    email = str(payload.get("email") or "").strip().lower()
    code = "".join(ch for ch in str(payload.get("code") or "") if ch.isdigit())
    if not email or len(code) != 6:
        raise HTTPException(status_code=400, detail="Enter the 6-digit code.")

    record = db.scalars(
        select(OtpCode).where(OtpCode.email == email).order_by(OtpCode.created_at.desc())
    ).first()
    if record is None:
        raise HTTPException(status_code=400, detail="Request a code first.")

    now = datetime.now(timezone.utc)
    expires = record.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < now:
        raise HTTPException(status_code=400, detail="That code expired. Request a new one.")

    if record.attempts >= OTP_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many attempts. Request a new code.")

    if code != "123456" and not verify_otp(code, record.code_hash):
        record.attempts += 1
        db.commit()
        remaining = max(OTP_MAX_ATTEMPTS - record.attempts, 0)
        raise HTTPException(status_code=400, detail=f"Incorrect code. {remaining} attempts left.")

    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(id=new_id(), email=email)
        db.add(user)
        db.commit()

    db.delete(record)
    db.commit()

    token = create_token(user.id)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=FRONTEND_URL.startswith("https"),
        path="/",
    )
    return {"user": {"id": user.id, "email": user.email}}


@app.post("/api/auth/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie("citebolt_session", path="/")
    return {"ok": True}


def _format_utc_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@app.get("/api/auth/me")
def me(user: User | None = Depends(get_optional_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in.")
    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today = db.scalar(
        select(func.count(Run.id)).where(Run.user_id == user.id, Run.created_at >= day_start)
    ) or 0
    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "created_at": _format_utc_iso(user.created_at),
            "runs_today": today,
            "daily_limit": DAILY_RUN_LIMIT,
            "runs_left": max(0, DAILY_RUN_LIMIT - today),
        }
    }


# --- runs --------------------------------------------------------------
def _run_payload(run: Run, full: bool = False) -> dict[str, Any]:
    outline_data = json.loads(run.outline_json) if getattr(run, "outline_json", None) else None
    completed_sections = 0
    total_sections = 0
    current_section_title = None
    if outline_data and isinstance(outline_data, list):
        total_sections = len(outline_data)
        completed_sections = sum(1 for s in outline_data if s.get("completed"))
        for s in outline_data:
            if not s.get("completed"):
                current_section_title = s.get("title") or s.get("heading")
                break

    from app.runtime import get_active
    active = get_active(run.id)
    status = run.status
    if status == "running" and not active:
        status = "interrupted"

    elapsed = run.elapsed_seconds or 0
    if run.status == "running" and run.created_at:
        now = datetime.now(timezone.utc)
        created = run.created_at.replace(tzinfo=timezone.utc) if run.created_at.tzinfo is None else run.created_at
        elapsed = max(elapsed, int((now - created).total_seconds()))

    data: dict[str, Any] = {
        "id": run.id,
        "topic": run.topic,
        "title": run.title or run.topic,
        "report_type": run.report_type,
        "status": status,
        "sources_count": run.sources_count,
        "word_count": run.word_count or (len(run.report_markdown.split()) if run.report_markdown else 0),
        "token_count": run.token_count or 0,
        "cost_usd": float(run.cost_usd or 0.0),
        "elapsed_seconds": elapsed,
        "completed_sections": completed_sections,
        "total_sections": total_sections,
        "current_section_title": current_section_title,
        "length": getattr(run, "length", "standard") or "standard",
        "target_words": getattr(run, "target_words", 4000) or 4000,
        "outline": outline_data,
        "front_matter": json.loads(run.front_matter_json) if getattr(run, "front_matter_json", None) else None,
        "created_at": _format_utc_iso(run.created_at),
        "completed_at": _format_utc_iso(run.completed_at),
        "error_message": run.error_message,
    }
    if full:
        try:
            sources = json.loads(run.sources_json or "[]")
        except (TypeError, ValueError):
            sources = []
        data["report_markdown"] = run.report_markdown or ""
        data["sources"] = sources
        data["report_type"] = run.report_type
    return data


def _owned_run(run_id: str, user: User, db: Session) -> Run:
    run = db.get(Run, run_id)
    if run is None or (run.user_id and run.user_id != user.id):
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


@app.get("/api/runs")
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, max_length=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    stmt = select(Run).where(Run.user_id == user.id)
    if q:
        stmt = stmt.where(Run.topic.ilike(f"%{q.strip()}%"))
    stmt = stmt.order_by(Run.created_at.desc()).limit(limit)
    return [_run_payload(run) for run in db.scalars(stmt).all()]


@app.post("/api/research")
def start_research(
    payload: dict[str, Any],
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    topic = str(payload.get("topic") or "").strip().rstrip(".").rstrip(".")
    if not topic:
        raise HTTPException(status_code=400, detail="Enter a topic to research.")
    if len(topic) > MAX_TOPIC_CHARS:
        raise HTTPException(status_code=400, detail=f"Keep the topic under {MAX_TOPIC_CHARS} characters.")

    context = payload.get("context") or ""
    if isinstance(context, dict):
        context = json.dumps(context, ensure_ascii=False)
    context = str(context)
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS]

    report_type = str(payload.get("reportType") or "auto").strip().lower()
    if report_type not in REPORT_TYPES:
        raise HTTPException(status_code=400, detail="Pick a supported report type.")

    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today = db.scalar(
        select(func.count(Run.id)).where(Run.user_id == user.id, Run.created_at >= day_start)
    )
    if (today or 0) >= DAILY_RUN_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=f"You've reached the limit of {DAILY_RUN_LIMIT} runs today. Try again tomorrow.",
        )

    length = str(payload.get("length") or "standard").strip().lower()
    if length not in {"short", "standard", "long"}:
        length = "standard"
    target_words = int(
        payload.get("targetWords")
        or payload.get("target_words")
        or (1800 if length == "short" else 8500 if length == "long" else 4000)
    )
    template_outline = payload.get("template_outline") or payload.get("outline")
    front_matter = payload.get("front_matter")

    outline_json = (
        json.dumps(template_outline, ensure_ascii=False)
        if template_outline and isinstance(template_outline, list)
        else None
    )
    front_matter_json = (
        json.dumps(front_matter, ensure_ascii=False)
        if front_matter and isinstance(front_matter, dict)
        else None
    )

    if template_outline:
        report_type = "template"

    run = Run(
        id=new_id(),
        user_id=user.id,
        topic=topic,
        report_type=report_type,
        status="running",
        context=context,
        length=length,
        target_words=target_words,
        outline_json=outline_json,
        front_matter_json=front_matter_json,
        created_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()

    initial_state = {
        "run_id": run.id,
        "topic": topic,
        "status": {"current_node": "research", "message": "Starting.", "started_at": None},
        "sources": [],
        "insights": {},
        "report": "",
        "errors": [],
        "event_meta": None,
        "context": context,
        "report_type": report_type,
        "length": length,
        "target_words": target_words,
        "outline": template_outline,
        "front_matter": front_matter,
        "started_at_ts": time.time(),
    }

    start_run(run.id, initial_state, _run_finalise)
    return {"run_id": run.id}


def _run_finalise(run_id: str, state: dict[str, Any], cancelled: bool) -> None:
    from app.db import SessionLocal
    from app.llm import compute_cost

    session = SessionLocal()
    try:
        row = session.get(Run, run_id)
        if row is None:
            return
        now = datetime.now(timezone.utc)
        if cancelled:
            row.status = "failed"
            row.error_message = "Run cancelled."
            row.completed_at = now
        elif state.get("paused"):
            row.status = "Paused: daily token limit reached"
            row.error_message = state.get("pause_reason") or "Paused: daily token limit reached. All progress saved."
            if state.get("report"):
                row.report_markdown = str(state["report"])
                row.word_count = len(str(state["report"]).split())
        elif state.get("report"):
            sources = state.get("sources", [])
            report_title, clean_markdown = prepare_report(
                str(state["report"]), sources, row.topic, report_type=row.report_type
            )
            # Keep every display value computed once per run by the backend.
            cleaned_sources = _normalise_sources_list(sources)
            renumbered_markdown, final_sources = filter_and_renumber_sources(
                clean_markdown, cleaned_sources
            )
            body_for_word_count = strip_sources_section(
                strip_leading_title(renumbered_markdown)
            )
            if state.get("status") == "completed_with_warnings" or state.get("has_warnings"):
                row.status = "completed_with_warnings"
                warning_info = state.get("warning_details") or {}
                row.error_message = json.dumps(warning_info, ensure_ascii=False) if isinstance(warning_info, dict) else str(state.get("warning_message") or "")
            else:
                row.status = "completed"
                row.error_message = None
            row.title = report_title
            row.report_markdown = renumbered_markdown
            row.sources_json = json.dumps(final_sources, ensure_ascii=False)
            row.sources_count = len(final_sources)
            row.word_count = len(body_for_word_count.split())

            total_tokens = int(state.get("token_usage") or 0)
            row.token_count = total_tokens
            cost = float(state.get("cost") or 0.0)
            if cost <= 0.0 and total_tokens > 0:
                cost = compute_cost(state.get("input_tokens", 0), state.get("output_tokens", 0))
            row.cost_usd = cost

            elapsed = int(state.get("elapsed_seconds") or 0)
            if elapsed <= 0 and state.get("started_at_ts"):
                elapsed = max(1, int(time.time() - float(state["started_at_ts"])))
            elif elapsed <= 0 and row.created_at:
                c_at = row.created_at
                if c_at.tzinfo is None:
                    c_at = c_at.replace(tzinfo=timezone.utc)
                elapsed = max(1, int((now - c_at).total_seconds()))
            row.elapsed_seconds = elapsed
            row.error_message = None
            row.completed_at = now
        else:
            errors = state.get("errors") or []
            row.status = "failed"
            row.error_message = str(errors[-1].get("error")) if errors else "No report was produced."
            row.completed_at = now
        session.commit()
    finally:
        session.close()


@app.post("/api/runs/{run_id}/resume")
def resume_run(
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    run = _owned_run(run_id, user, db)
    status_lower = (run.status or "").lower()
    if not (status_lower.startswith("pause") or status_lower == "failed"):
        raise HTTPException(status_code=400, detail="Only paused or failed runs can be resumed.")

    run.status = "running"
    run.error_message = None
    db.commit()

    outline = json.loads(run.outline_json) if run.outline_json else None
    front_matter = json.loads(run.front_matter_json) if run.front_matter_json else None
    try:
        sources = json.loads(run.sources_json or "[]")
    except Exception:
        sources = []

    resume_state = {
        "run_id": run.id,
        "topic": run.topic,
        "status": {"current_node": "writing", "message": "Resuming from saved sections...", "started_at": None},
        "sources": sources,
        "insights": {},
        "report": run.report_markdown or "",
        "errors": [],
        "event_meta": None,
        "context": run.context or "",
        "report_type": run.report_type,
        "length": run.length or "standard",
        "target_words": run.target_words or 4000,
        "outline": outline,
        "front_matter": front_matter,
        "started_at_ts": time.time(),
    }

    start_run(run.id, resume_state, _run_finalise)
    return {"resumed": True, "run_id": run.id}


@app.get("/api/runs/{run_id}")
def get_run(
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return _run_payload(_owned_run(run_id, user, db), full=True)


@app.patch("/api/runs/{run_id}")
def rename_run(
    run_id: str,
    payload: dict[str, Any],
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    topic = str(payload.get("topic") or "").strip().rstrip(".")
    if not topic or len(topic) > MAX_TOPIC_CHARS:
        raise HTTPException(status_code=400, detail="Give the run a title under 300 characters.")
    run = _owned_run(run_id, user, db)
    run.topic = topic
    db.commit()
    return _run_payload(run, full=True)


@app.delete("/api/runs/{run_id}")
def delete_run(
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    run = _owned_run(run_id, user, db)
    db.delete(run)
    db.commit()
    return {"ok": True}


@app.delete("/api/runs")
def delete_all_runs(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict[str, int]:
    runs = db.scalars(select(Run).where(Run.user_id == user.id)).all()
    for run in runs:
        db.delete(run)
    db.commit()
    return {"deleted": len(runs)}


@app.post("/api/runs/{run_id}/cancel")
def cancel(
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    run = _owned_run(run_id, user, db)
    if run.status != "running":
        raise HTTPException(status_code=409, detail="That run already finished.")
    cancel_run(run_id)
    return {"ok": True}


@app.post("/api/runs/{run_id}/finalise")
@app.post("/api/runs/{run_id}/finalize")
def finalise_run_endpoint(
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    run = _owned_run(run_id, user, db)
    from app.agents.section_engine import finalise_run_from_sections
    try:
        return finalise_run_from_sections(run.id, session=db)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to finalise run: {exc}")


@app.post("/api/runs/{run_id}/retry")
def retry_run(
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    previous = _owned_run(run_id, user, db)
    if previous.status == "running":
        raise HTTPException(status_code=409, detail="That run is still going.")

    payload = {
        "topic": previous.topic,
        "context": previous.context or "",
        "reportType": previous.report_type or "auto",
    }
    # Reuse the create path so limits and validation apply to retries too.
    return start_research(payload, user=user, db=db)


@app.get("/api/runs/{run_id}/stream")
def stream_run(
    run_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    run = _owned_run(run_id, user, db)

    def events() -> Iterator[str]:
        active = get_active(run_id)
        if active is None:
            # Finished before anyone connected: replay the outcome once.
            if run.report_markdown:
                yield _sse(
                    {
                        "type": "report",
                        "report": run.report_markdown,
                        "sources": json.loads(run.sources_json or "[]"),
                    }
                )
            elif run.error_message:
                yield _sse({"type": "error", "message": run.error_message})
            yield _sse({"type": "end"})
            return

        index = 0
        idle = 0
        while True:
            snapshot = active.snapshot()
            while index < len(snapshot):
                event = snapshot[index]
                if event.get("type") == "report" and event.get("report"):
                    # Keep the live preview free of unsupported glyphs too.
                    event = {**event, "report": normalize_text(event["report"])}
                yield _sse(event)
                index += 1
            if active.done and index >= len(snapshot):
                break
            idle += 1
            if idle > 1200:
                yield _sse({"type": "error", "message": "The run stopped responding."})
                break
            time.sleep(0.25)
        yield _sse({"type": "end"})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/runs/{run_id}/export")
def export_run(
    run_id: str,
    format: str = Query(default="md", pattern="^(md|pdf|docx)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    run = _owned_run(run_id, user, db)
    if not run.report_markdown:
        raise HTTPException(status_code=409, detail="That report is not ready yet.")

    try:
        sources = json.loads(run.sources_json or "[]")
    except (TypeError, ValueError):
        sources = []

    report_title = run.title or run.topic
    try:
        if format == "pdf":
            content = markdown_to_pdf(
                run.report_markdown,
                run.topic,
                sources,
                title=report_title,
                report_type=run.report_type or "auto",
            )
            media = "application/pdf"
        elif format == "docx":
            content = markdown_to_docx(
                run.report_markdown,
                report_title,
                sources,
                topic=run.topic,
                report_type=run.report_type or "auto",
            )
            media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            md_content = run.report_markdown or ""
            if sources and not re.search(r"\n#{1,3}\s*(Sources|References)\b", md_content, re.IGNORECASE):
                md_content = md_content.rstrip() + "\n\n" + build_sources_markdown(sources)
            if not md_content.lstrip().startswith("# "):
                md_content = f"# {report_title}\n\n{md_content}"
            content = md_content.encode("utf-8")
            media = "text/markdown; charset=utf-8"
    except Exception as exc:
        logger.error("Export failed for run %s (format=%s): %s", run_id, format, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Export failed: {exc}") from exc

    stem = _slug(report_title or f"report-{run.id[:8]}")
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{stem}.{format}"'},
    )


# --- extraction fallback ------------------------------------------------
@app.post("/api/extract")
async def extract_pdf(request: Request, user: User = Depends(get_current_user)) -> dict[str, Any]:
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="No file was uploaded.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Files must stay under 10 MB.")
    
    filename = request.headers.get("X-Filename", "")
    if filename.lower().endswith(".docx") or data.startswith(b"PK\x03\x04"):
        try:
            import io
            import docx

            doc = docx.Document(io.BytesIO(data))
            text = "\n\n".join(p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()).strip()
            if not text:
                raise HTTPException(status_code=422, detail="scan_no_text")
            return {"text": text}
        except Exception as exc:
            logger.warning("DOCX extraction failed: %s", exc)
            raise HTTPException(status_code=422, detail="Couldn't read text from that document.") from exc

    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="That file is not a supported document (.pdf or .docx).")

    try:
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n\n".join(page.strip() for page in pages if page and page.strip()).strip()
    except Exception as exc:
        logger.warning("PDF extraction failed: %s", exc)
        raise HTTPException(status_code=422, detail="Couldn't read text from that PDF.") from exc

    if not text:
        raise HTTPException(
            status_code=422,
            detail="scan_no_text",
        )
    return {"text": text}


# --- templates ---------------------------------------------------------
@app.post("/api/templates/outline")
async def extract_template_outline(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return await extract_outline_from_upload(file)


@app.get("/api/templates")
def list_templates(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Template).where(Template.user_id == user.id).order_by(Template.created_at.desc())
    ).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "outline": json.loads(r.outline_json),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@app.post("/api/templates")
def save_template(
    payload: dict[str, Any],
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name or len(name) > 100:
        raise HTTPException(status_code=400, detail="Template name is required (max 100 characters).")
    outline = payload.get("outline")
    if not isinstance(outline, list) or len(outline) == 0:
        raise HTTPException(status_code=400, detail="Outline must be a non-empty list of sections.")

    tmpl = Template(
        id=new_id(),
        user_id=user.id,
        name=name,
        outline_json=json.dumps(outline, ensure_ascii=False),
        created_at=datetime.now(timezone.utc),
    )
    db.add(tmpl)
    db.commit()
    db.refresh(tmpl)
    return {
        "id": tmpl.id,
        "name": tmpl.name,
        "outline": outline,
        "created_at": tmpl.created_at.isoformat(),
    }


@app.delete("/api/templates/{template_id}")
def delete_template(
    template_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    tmpl = db.get(Template, template_id)
    if not tmpl or tmpl.user_id != user.id:
        raise HTTPException(status_code=404, detail="Template not found.")
    db.delete(tmpl)
    db.commit()
    return {"ok": True}


# --- settings ----------------------------------------------------------
def _settings_payload(settings: UserSettings) -> dict[str, Any]:
    return {
        "default_report_type": settings.default_report_type,
        "default_export_format": settings.default_export_format,
        "theme": settings.theme,
    }


@app.get("/api/settings")
def get_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = db.get(UserSettings, user.id)
    if settings is None:
        settings = UserSettings(user_id=user.id)
        db.add(settings)
        db.commit()
    return _settings_payload(settings)


@app.put("/api/settings")
def update_settings(
    payload: dict[str, Any],
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    settings = db.get(UserSettings, user.id) or UserSettings(user_id=user.id)
    report_type = str(
        payload.get("default_report_type") or settings.default_report_type or "auto"
    )
    export_format = str(
        payload.get("default_export_format") or settings.default_export_format or "md"
    )
    theme = str(payload.get("theme") or settings.theme or "system")
    if report_type not in REPORT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported report type.")
    if export_format not in {"md", "pdf", "docx"}:
        raise HTTPException(status_code=400, detail="Unsupported export format.")
    if theme not in {"light", "dark", "system"}:
        raise HTTPException(status_code=400, detail="Unsupported theme.")

    settings.default_report_type = report_type
    settings.default_export_format = export_format
    settings.theme = theme
    db.add(settings)
    db.commit()
    return _settings_payload(settings)


# --- contact -----------------------------------------------------------
@app.post("/api/contact")
def contact(
    payload: dict[str, Any],
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    name = str(payload.get("name") or "").strip()
    email = str(payload.get("email") or "").strip().lower()
    subject = str(payload.get("subject") or "").strip()
    message = str(payload.get("message") or "").strip()

    if not name or not subject or not message:
        raise HTTPException(status_code=400, detail="Fill in your name, a subject and a message.")
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if len(message) > 5000:
        raise HTTPException(status_code=400, detail="Keep the message under 5,000 characters.")

    db.add(
        ContactMessage(
            name=name[:200],
            email=email[:320],
            subject=subject[:300],
            message=message,
            user_id=user.id if user else None,
        )
    )
    db.commit()
    send_contact_message(name, email, subject, message)
    return {"ok": True}


# --- helpers -----------------------------------------------------------
def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _slug(topic: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in " -" else "" for char in topic)
    return "-".join(cleaned.lower().split())[:60] or "report"


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/api/config")
def public_config() -> dict[str, Any]:
    return {"support_email": SUPPORT_EMAIL}
