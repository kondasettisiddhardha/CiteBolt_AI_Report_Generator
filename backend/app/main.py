"""Citebolt API.

Auth: email one-time codes, verified into an httpOnly JWT cookie.
Runs: created in SQLite (or Postgres), executed by a background thread, streamed
over SSE, and exportable as Markdown, PDF or Word.
"""

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
import re


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

app = FastAPI(title="Citebolt API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in ALLOWED_ORIGINS.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

REPORT_TYPES = {"auto", "briefing", "deepdive", "architectureblueprint", "researchpaper"}


# Create tables as soon as the module loads as well as on startup, so the app
# works under TestClient and when imported by a worker without a startup hook.
init_db()


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    logger.info("Citebolt API ready")


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

    if not verify_otp(code, record.code_hash):
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
    response.delete_cookie("dossier_session", path="/")
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: User | None = Depends(get_optional_user)) -> dict[str, Any]:
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in.")
    return {"user": {"id": user.id, "email": user.email, "created_at": user.created_at.isoformat()}}


# --- runs --------------------------------------------------------------
def _run_payload(run: Run, full: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": run.id,
        "topic": run.topic,
        "title": run.title or run.topic,
        "report_type": run.report_type,
        "status": run.status,
        "sources_count": run.sources_count,
        "word_count": run.word_count or (len(run.report_markdown.split()) if run.report_markdown else 0),
        "token_count": run.token_count or 0,
        "cost_usd": float(run.cost_usd or 0.0),
        "elapsed_seconds": run.elapsed_seconds or 0,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
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
    topic = str(payload.get("topic") or "").strip()
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

    run = Run(
        id=new_id(),
        user_id=user.id,
        topic=topic,
        report_type=report_type,
        status="running",
        context=context,
        created_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()

    initial_state = {
        "topic": topic,
        "status": {"current_node": "research", "message": "Starting.", "started_at": None},
        "sources": [],
        "insights": {},
        "report": "",
        "errors": [],
        "event_meta": None,
        "context": context,
        "report_type": report_type,
    }

    def finalise(run_id: str, state: dict[str, Any], cancelled: bool) -> None:
        from app.db import SessionLocal

        session = SessionLocal()
        try:
            row = session.get(Run, run_id)
            if row is None:
                return
            now = datetime.now(timezone.utc)
            if cancelled:
                row.status = "failed"
                row.error_message = "Run cancelled."
            elif state.get("report"):
                sources = state.get("sources", [])
                report_title, clean_markdown = prepare_report(
                    str(state["report"]), sources, row.topic
                )
                # Keep every display value computed once per run by the backend.
                cleaned_sources = _normalise_sources_list(sources)
                renumbered_markdown, final_sources = filter_and_renumber_sources(
                    clean_markdown, cleaned_sources
                )
                body_for_word_count = strip_sources_section(
                    strip_leading_title(renumbered_markdown)
                )
                row.status = "completed"
                row.title = report_title
                row.report_markdown = renumbered_markdown
                row.sources_json = json.dumps(final_sources, ensure_ascii=False)
                row.sources_count = len(final_sources)
                row.word_count = len(body_for_word_count.split())
                row.token_count = int(state.get("token_usage") or 0)
                row.cost_usd = float(state.get("cost") or 0.0)
                row.elapsed_seconds = int(state.get("elapsed_seconds") or 0)
                row.error_message = None
            else:
                errors = state.get("errors") or []
                row.status = "failed"
                row.error_message = str(errors[-1].get("error")) if errors else "No report was produced."
            row.completed_at = now
            session.commit()
        finally:
            session.close()

    start_run(run.id, initial_state, finalise)
    return {"run_id": run.id}


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
    topic = str(payload.get("topic") or "").strip()
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
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="That file is not a PDF.")

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
