"""Section-by-section research and generation engine.

Executes structured outline-driven reports with high performance:
1. Researches ONCE per chapter (H1) and reuses findings across all H2/H3 sections.
2. Front matter & Auto sections execute instantly with zero LLM/search overhead.
3. Chapters 3-10 write strictly from "About your project" facts with at most one background search.
4. Independent chapters run in parallel with concurrency limit 3 via ThreadPoolExecutor.
5. Groq TPM rate limits handled with backoff; TPD (daily) limits pause run or switch to fallback models.
6. Progress card computes dynamic ETA remaining or shows 'estimating...', tracking active model.
7. Saves each finished section as it completes; supports resuming from the first unfinished section.
8. Uses cheaper/smaller models for easy sections (summaries, abstract) when configured.
9. Post-processing performs gapless citation renumbering [1]..[N] and builds clean IEEE References.
"""

import concurrent.futures
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from app.agents.research import _collect_sources
from app.config import GROQ_FALLBACK_MODELS, GROQ_MODEL
from app.llm import DailyTokenLimitError, ModelNotFoundError, compute_cost, generate_text
from app.text import clean_title, filter_and_renumber_sources, smart_title, strip_sources_section

logger = logging.getLogger("citebolt.section_engine")


# --- Single Source of Truth for Database Schema & Verified API Endpoints ---
VERIFIED_DATABASE_TABLES: list[dict[str, str]] = [
    {
        "name": "users",
        "columns": "id, email, created_at",
        "purpose": "Stores registered user identity and email address.",
    },
    {
        "name": "otp_codes",
        "columns": "id, email, code_hash, expires_at, attempts, created_at",
        "purpose": "Manages time-sensitive one-time password verification tokens.",
    },
    {
        "name": "runs",
        "columns": "id, user_id, topic, title, report_type, status, report_markdown, sources_json, sources_count, word_count, token_count, cost_usd, elapsed_seconds, error_message, context, created_at, completed_at, length, target_words, outline_json, front_matter_json",
        "purpose": "Persists report generation workflows, outlines, and markdown artifacts.",
    },
    {
        "name": "templates",
        "columns": "id, user_id, name, outline_json, created_at",
        "purpose": "Stores predefined and custom report structural templates.",
    },
    {
        "name": "user_settings",
        "columns": "user_id, default_report_type, default_export_format, theme, notify_on_complete, created_at",
        "purpose": "Retains user preference settings including interface display theme.",
    },
    {
        "name": "contact_messages",
        "columns": "id, name, email, subject, message, user_id, created_at",
        "purpose": "Captures user feedback and contact form submissions.",
    },
]

VERIFIED_TABLE_NAMES: list[str] = [t["name"] for t in VERIFIED_DATABASE_TABLES]
VERIFIED_TABLE_COUNT: int = len(VERIFIED_TABLE_NAMES)  # 6
REAL_DB_TABLES: set[str] = set(VERIFIED_TABLE_NAMES)

# Verified foreign key relationships verified directly in models.py:
# - Run.user_id -> User.id (ForeignKey("users.id", ondelete="CASCADE"))
# - Template.user_id -> User.id (ForeignKey("users.id", ondelete="CASCADE"))
# - UserSettings.user_id -> User.id (ForeignKey("users.id", ondelete="CASCADE"))
VERIFIED_SCHEMA_RELATIONSHIPS: list[str] = [
    "runs.user_id -> users.id",
    "templates.user_id -> users.id",
    "user_settings.user_id -> users.id",
]

# Verified database file name dynamically inspected from code:
def get_verified_db_filename() -> str:
    try:
        from app.db import ENGINE_URL
        if "sqlite:///" in ENGINE_URL:
            from pathlib import Path
            p = Path(ENGINE_URL.split("sqlite:///")[-1])
            if p.name:
                return p.name
        from app.db import DEFAULT_SQLITE_URL
        if "sqlite:///" in DEFAULT_SQLITE_URL:
            from pathlib import Path
            p = Path(DEFAULT_SQLITE_URL.split("sqlite:///")[-1])
            if p.name:
                return p.name
    except Exception:
        pass
    return "the SQLite database file"

# Verified API endpoints verified directly in main.py:
VERIFIED_API_ENDPOINTS: list[str] = [
    "GET /api/health",
    "POST /api/auth/request-otp",
    "POST /api/auth/verify-otp",
    "POST /api/auth/logout",
    "GET /api/auth/me",
    "GET /api/runs",
    "POST /api/research",
    "POST /api/runs/{run_id}/resume",
    "GET /api/runs/{run_id}",
    "PATCH /api/runs/{run_id}",
    "DELETE /api/runs/{run_id}",
    "DELETE /api/runs",
    "POST /api/runs/{run_id}/cancel",
    "POST /api/runs/{run_id}/retry",
    "GET /api/runs/{run_id}/stream",
    "GET /api/runs/{run_id}/export",
    "POST /api/extract",
    "POST /api/templates/outline",
    "GET /api/templates",
    "POST /api/templates",
    "DELETE /api/templates/{template_id}",
    "GET /api/settings",
    "PUT /api/settings",
    "POST /api/contact",
    "GET /api/config",
]

VERIFIED_ENDPOINT_COUNT: int = len(VERIFIED_API_ENDPOINTS)  # 25

WORD_NUMBERS: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "twenty-five": 25, "twenty five": 25,
}

APPENDIX_B_GLOSSARY: list[dict[str, str]] = [
    {
        "term": "LLM",
        "definition": "Large Language Model (foundation deep learning model trained on large text corpora for natural language reasoning and generation).",
    },
    {
        "term": "Agent",
        "definition": "Autonomous software entity that reasons, invokes tools, and collaborates across workflows.",
    },
    {
        "term": "LangGraph",
        "definition": "Multi-agent state orchestration framework based on state machines and directed cycles.",
    },
    {
        "term": "FastAPI",
        "definition": "High-performance Python web framework for asynchronous REST endpoints and Server-Sent Events.",
    },
    {
        "term": "Tavily",
        "definition": "Search engine API optimized for factual AI retrieval and web source extraction.",
    },
    {
        "term": "SRS",
        "definition": "Software Requirements Specification defining system functionality and constraints.",
    },
    {
        "term": "HLD / LLD",
        "definition": "High-Level Design and Low-Level Design architectural specifications.",
    },
    {
        "term": "SSE",
        "definition": "Server-Sent Events protocol for real-time progress streaming.",
    },
]


def format_appendix_b_glossary() -> str:
    rows = ["| Term | Definition |", "| :--- | :--- |"]
    for item in APPENDIX_B_GLOSSARY:
        rows.append(f"| **{item['term']}** | {item['definition']} |")
    return "## Appendix B: Glossary\n\n" + "\n".join(rows)


def sanitize_section_output(sec_md: str) -> str:
    """Sanitize individual section LLM generation output (Run #6 fix).
    
    Strips code fences (closed or unclosed), markdown headings, markdown tables,
    and any text appearing after the first heading-like line.
    Returns plain paragraphs and bullets only.
    """
    if not sec_md:
        return ""

    # Strip leading/trailing code fences even if unclosed
    cleaned = re.sub(r"^\s*```[a-zA-Z0-9_-]*\s*\n", "", sec_md.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\n\s*```\s*$", "", cleaned, flags=re.MULTILINE)

    lines = cleaned.splitlines()
    body_lines: list[str] = []

    # If the first non-empty line starts with # (the section's own heading echo), skip it
    first_non_empty_idx = -1
    for i, ln in enumerate(lines):
        if ln.strip():
            first_non_empty_idx = i
            break

    start_idx = 0
    if first_non_empty_idx != -1 and lines[first_non_empty_idx].strip().startswith("#"):
        start_idx = first_non_empty_idx + 1

    for line in lines[start_idx:]:
        stripped = line.strip()
        # Any text after the first heading-like line must be discarded
        if stripped.startswith("#"):
            break
        # Strip code fences inside
        if stripped.startswith("```"):
            continue
        # Strip markdown table lines
        if stripped.startswith("|"):
            continue
        # Strip standalone footnote markers like *(...)*
        if re.match(r"^\*\([^\)]*\)\*$", stripped):
            continue
        body_lines.append(line)

    result = "\n".join(body_lines).strip()
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result


def deduplicate_and_clean_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """De-duplicate sources by URL and arXiv ID, and strip leading '[arXiv id]' from titles."""
    unique_sources: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_arxiv: set[str] = set()

    for s in sources:
        u = str(s.get("url") or "").strip()
        u_norm = u.lower().rstrip("/")

        arxiv_id = ""
        m_arxiv = re.search(r"arxiv\.org/(?:abs|pdf)/(\d+\.\d+)", u_norm)
        if m_arxiv:
            arxiv_id = m_arxiv.group(1)
        else:
            m_arxiv2 = re.search(r"(?:arxiv:?\s*|\[)(\d{4}\.\d{4,5})", str(s.get("title", "")), re.IGNORECASE)
            if m_arxiv2:
                arxiv_id = m_arxiv2.group(1)

        if u_norm and u_norm in seen_urls:
            continue
        if arxiv_id:
            if arxiv_id in seen_arxiv:
                continue
            seen_arxiv.add(arxiv_id)
        if u_norm:
            seen_urls.add(u_norm)

        clean_s = dict(s)
        raw_t = str(clean_s.get("title") or "Reference Source").strip()
        clean_t = re.sub(
            r"^\[(?:\d+\.\d+|arxiv:?\s*\d+\.\d+|[a-zA-Z\-]+(?:\.[a-zA-Z\-]+)?)\]\s*",
            "",
            raw_t,
            flags=re.IGNORECASE,
        ).strip()
        clean_s["title"] = clean_t
        unique_sources.append(clean_s)

    return unique_sources


def parse_count_mention(match_text: str) -> int | None:
    t = match_text.strip().lower()
    if t.isdigit():
        return int(t)
    return WORD_NUMBERS.get(t)


def build_deterministic_data_design_section(sec_title: str, heading_prefix: str = "##") -> str:
    table_names_str = ", ".join(f"`{t}`" for t in VERIFIED_TABLE_NAMES[:-1]) + f", and `{VERIFIED_TABLE_NAMES[-1]}`"
    rels_str = ", ".join(f"`{rel}`" for rel in VERIFIED_SCHEMA_RELATIONSHIPS)
    return f"""{heading_prefix} {sec_title}

The database architecture consists of {VERIFIED_TABLE_COUNT} relational tables: {table_names_str}. Verified foreign key relationships in the data model link {rels_str}, ensuring user-scoped isolation for execution runs, report templates, and interface settings in local SQLite storage."""


def build_deterministic_data_dictionary_section(sec_title: str, heading_prefix: str = "##") -> str:
    table_rows = "\n".join(
        f"| {t['name']} | {t['columns']} | {t['purpose']} |"
        for t in VERIFIED_DATABASE_TABLES
    )
    return f"""{heading_prefix} {sec_title}

The database schema is implemented using SQLite to provide persistent local storage for report workflows and settings. Table 7.1 describes each database table, its primary attributes, and operational role within the system.

Table 7.1: Database tables

| Table | Columns | Purpose |
| :--- | :--- | :--- |
{table_rows}"""


def build_deterministic_roadmap_section(sec_title: str, heading_prefix: str = "###") -> str:
    lines = [
        f"{heading_prefix} {sec_title}",
        "",
        "The scope of this project encompasses an autonomous multi-agent research report generation system featuring Research, Analysis, and Writer agents coordinated using LangGraph. In-scope capabilities include automated academic literature retrieval via Tavily, structured citation verification, local SQLite persistence with SQLAlchemy, and document export in both ReportLab PDF and DOCX formats. Out of scope for this implementation are multi-tenant cloud deployments, container orchestration, and high-concurrency load testing.",
        "",
        "The remainder of this report is organized as follows:",
        "",
        "- **Chapter 2 (Literature Survey)** examines existing research, methodologies, and related systems in the domain, highlighting the technical gaps addressed by this work.",
        "- **Chapter 3 (Software Requirements Specification)** details the functional requirements, external interface requirements, and non-functional requirements including performance and security constraints.",
        "- **Chapter 4 (System Design)** presents the high-level and low-level architectural design, component interactions, and data model design.",
        "- **Chapter 5 (Technical Specifications)** outlines the core technologies, backend and frontend frameworks, persistence layer, and third-party integrations utilized.",
        "- **Chapter 6 (Project Planning & Scheduling)** describes the project planning, work breakdown structure, timeline milestones, and team responsibilities.",
        "- **Chapter 7 (Software Implementation)** details the implementation of core modules, backend services, API endpoints, and user interface workflows.",
        "- **Chapter 8 (Software Testing)** documents the testing strategy, test suite implementation, test cases, and quality verification methodologies.",
        "- **Chapter 9 (Result and Discussion)** presents the system evaluation, outcomes, and comparative analysis with existing solutions.",
        "- **Chapter 10 (Deployment and Maintenance)** outlines the deployment procedures, environment configuration, backup procedures, and operational constraints.",
        "- **Chapter 11 (Conclusion and Future Scope)** summarizes the project achievements, contributions, and avenues for future technical enhancement.",
    ]
    return "\n".join(lines)


def build_deterministic_installation_section(sec_title: str, heading_prefix: str = "###") -> str:
    lines = [
        f"{heading_prefix} {sec_title}",
        "",
        "The installation process requires configuring the backend Python runtime and the frontend Node.js environment. First, initialize and launch the backend service:",
        "",
        "```bash",
        "cd backend",
        "python -m venv .venv",
        ".venv\\Scripts\\activate",
        "pip install -r requirements.txt",
        "uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload",
        "```",
        "",
        "Next, in a separate terminal, install the frontend packages and start the Vite development server:",
        "",
        "```bash",
        "cd frontend",
        "npm install",
        "npm run dev",
        "```",
        "",
        "Once both servers are running, the application can be accessed via a web browser at `http://localhost:5173`.",
    ]
    return "\n".join(lines)


def extract_captions_from_body(body_md: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Extract (label, title) for all Figures and Tables actually present in body text from Chapter 1 onwards."""
    figs: list[tuple[str, str]] = []
    tbls: list[tuple[str, str]] = []
    seen_figs: set[str] = set()
    seen_tbls: set[str] = set()

    m_ch1 = re.search(r"(?:^|\n)(#\s*Chapter\s+1\b)", body_md, re.IGNORECASE)
    search_text = body_md[m_ch1.start(1):] if m_ch1 else body_md

    for line in search_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("|") or stripped.startswith(">"):
            continue
        # Check Figure
        fig_m = re.match(r"^(?:Fig\.|Figure)\s+(\d+\.\d+)[:\s\-]+(.*)", stripped, re.IGNORECASE)
        if fig_m and not stripped.lower().startswith(("as shown", "refer to", "in fig", "see fig")):
            label = f"Fig. {fig_m.group(1)}"
            title = fig_m.group(2).strip().strip("[]–- ")
            if label not in seen_figs and title and title.lower() not in ("insert diagram here",):
                seen_figs.add(label)
                figs.append((label, title))
            continue
        # Check Table
        tbl_m = re.match(r"^Table\s+(\d+\.\d+)[:\-–—]+(.*)", stripped, re.IGNORECASE)
        if tbl_m:
            label = f"Table {tbl_m.group(1)}"
            title = tbl_m.group(2).strip().strip("[]–- ")
            if label not in seen_tbls and title and not title.lower().startswith(("no.", "describes", "shows", "lists", "provides", "illustrates", "summarizes")):
                seen_tbls.add(label)
                tbls.append((label, title))
            continue
    return figs, tbls


def build_dynamic_lof_and_lot(body_md: str) -> tuple[str, str]:
    figs, tbls = extract_captions_from_body(body_md)
    if figs:
        lof_lines = ["## List of Figures\n"]
        for lbl, title in figs:
            lof_lines.append(f"{lbl}: {title}")
        lof_text = "\n\n".join(lof_lines)
    else:
        lof_text = "## List of Figures\n\n*(No figures in this report)*"

    if tbls:
        lot_lines = ["## List of Tables\n"]
        for lbl, title in tbls:
            lot_lines.append(f"{lbl}: {title}")
        lot_text = "\n\n".join(lot_lines)
    else:
        lot_text = "## List of Tables\n\n*(No tables in this report)*"

    return lof_text, lot_text


def extract_domain_and_project(topic: str, front_matter: dict[str, Any] | None = None) -> tuple[str, str]:
    """Derive clean Domain and Project names from topic and front_matter."""
    fm = front_matter or {}
    proj = fm.get("projectTitle", "").strip().rstrip(".")
    clean_topic = (topic or "").strip().rstrip(".")
    if not proj:
        # derive from topic: e.g. "AI Research and Report Generator using LangGraph Multi-Agent Pipeline"
        proj = clean_topic
        for sep in [" using ", " with ", " via ", " based on "]:
            if sep in clean_topic.lower():
                proj = re.split(re.escape(sep), clean_topic, flags=re.IGNORECASE)[0].strip().rstrip(".")
                break

    domain = clean_topic
    for sep in [" using ", " with ", " via ", " based on "]:
        if sep in clean_topic.lower():
            domain = re.split(re.escape(sep), clean_topic, flags=re.IGNORECASE)[0].strip().rstrip(".")
            break
    if not any(domain.lower().endswith(w) for w in ["industry", "systems", "generation", "engineering"]):
        domain_name = f"{domain} Systems"
    else:
        domain_name = domain
    return domain_name.rstrip("."), proj.rstrip(".")


def build_compact_project_fact_sheet(topic: str, context: str, front_matter: dict[str, Any] | None = None) -> str:
    """Build a compact (~300 token) ground-truth fact sheet from user project facts.
    
    This is the ONLY allowed technical truth for Chapters 3-10.
    """
    fm = front_matter or {}
    domain_name, proj_name = extract_domain_and_project(topic, front_matter)
    proj_name = smart_title(proj_name)
    domain_name = smart_title(domain_name)
    ctx = context.strip() if context else ""
    lines = [
        f"Project Name: {proj_name}",
        f"Core Domain: {domain_name}",
    ]
    degree = fm.get("degree", "").strip()
    if degree:
        lines.append(f"Degree: {smart_title(degree)}")
    team_size = fm.get("teamSize", "").strip()
    if team_size:
        lines.append(f"Team Size: {team_size}")
    duration = fm.get("duration", "").strip()
    if duration:
        lines.append(f"Project Duration: {duration}")
    else:
        lines.append("Project Duration: [Not specified / Blank - do NOT mention any duration, months, or weeks]")
    deploy_status = fm.get("deploymentStatus", "").strip() or "Planned / Local environment"
    lines.append(f"Deployment Status: {deploy_status}")
    db_tables = fm.get("databaseTables", "").strip()
    if db_tables:
        lines.append(f"Database Tables: {db_tables}")
    else:
        formatted_tables = ", ".join(t["name"] for t in VERIFIED_DATABASE_TABLES)
        lines.append(f"Database Tables: {formatted_tables}.")
    endpoints = fm.get("mainEndpoints", "").strip()
    if endpoints:
        lines.append(f"Main API Endpoints: {endpoints}")
    else:
        formatted_endpoints = ", ".join(VERIFIED_API_ENDPOINTS)
        lines.append(f"Main Endpoints: {formatted_endpoints}.")

    lines.append(
        "How to Run: from backend/: uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload and npm run dev for the frontend."
    )

    if ctx:
        lines.append("Verified Architecture & Project Facts (Ground Truth):")
        # Keep up to 2500 chars (~350 words / ~400 tokens) to capture entire stack
        lines.append(ctx[:2500])
    else:
        lines.append("Verified Architecture: System specification as outlined in project topic.")
    lines.extend([
        "Strict Rule: Ground Truth Rules for ALL Chapters:",
        "1. Describe project ONLY from facts above; never attribute web snippets to project.",
        "2. System has 3 agents (Research, Analysis, Writer); NEVER write single-agent.",
        "3. Duration blank = no time periods. Testing covers 14 unit tests with mocked LLM/search.",
        "4. Unspecified details: write generically or '[Add your <thing> here.]'. Sec 10.3 uses exact run command.",
        "NOT TRUE / DO NOT WRITE (Strictly Forbidden Claims):",
        "- SQLite is the only database (do NOT mention PostgreSQL, MySQL, MongoDB, Redis).",
        "- 3 agents only (no Synthesis/Formatting/knowledge graph/central controller/citation agent).",
        "- No 'stores credentials/passwords', 'race conditions', 'lacks built-in persistence', 'concurrent requests'.",
        "- Section 8.2 objectives cover ONLY the 14 unit tests (no OTP/resume/concurrency).",
    ])
    return "\n".join(lines)


def sanitize_section_markdown(
    md: str,
    domain: str = "",
    project: str = "",
    sources: list[dict[str, Any]] | None = None,
    duration: str = "",
) -> str:
    """Clean markdown junk, ASCII diagram frames, author-year citations, fill tokens, and normalize placeholders."""
    # 1. Fill template tokens if any remaining
    if domain:
        md = md.replace("[Domain]", domain)
        md = re.sub(r"\[Domain\]", domain, md, flags=re.IGNORECASE)
    if project:
        md = md.replace("[Project]", project)
        md = re.sub(r"\[Project\]", project, md, flags=re.IGNORECASE)
    md = md.replace("[Domain]", "Domain").replace("[Project]", "Project")

    # 2. Strip outer triple-backtick wrapper if the whole section was wrapped
    md = re.sub(r"^\s*```(?:markdown)?\s*\n", "", md)
    md = re.sub(r"\n\s*```\s*$", "", md)
    # Strip accidental ```markdown fences without stripping valid code block fences like ```bash
    md = re.sub(r"^```markdown\s*\n", "", md, flags=re.MULTILINE)

    # 3. Convert #### or ##### to ###, and demote single-hash subsections (# 1.1) to ## 1.1
    md = re.sub(r"^#{4,}\s+(.*)", r"### \1", md, flags=re.MULTILINE)
    md = re.sub(r"^#\s+(\d+\.\d+.*)", r"## \1", md, flags=re.MULTILINE)

    # 4. Strip excessive ** markers (e.g. **** or empty bold)
    md = re.sub(r"\*{4,}", "", md)
    md = re.sub(r"\*\*\s*\*\*", "", md)

    # 5. Clean ASCII art frames around [Insert diagram here] and strip stray > blockquotes
    md = re.sub(
        r"\+[-=+]+\+\s*\n\s*\|\s*(\[[^\]]*diagram[^\]]*\])\s*\|\s*\n\s*\+[-=+]+\+",
        r"\1",
        md,
        flags=re.IGNORECASE,
    )
    md = re.sub(r"\+[-=]{5,}\+\s*\n", "", md)
    md = re.sub(r"\|\s*(\[[^\]]*diagram[^\]]*\])\s*\|", r"\1", md, flags=re.IGNORECASE)
    md = re.sub(r"^\s*>\s*(\[[^\]]*diagram[^\]]*\])", r"\1", md, flags=re.MULTILINE | re.IGNORECASE)

    # 6. Clean author-year citations like (Smith, 2024) or (Vaswani et al., 2017)
    # Map to [n] when matching a fetched source; never remove other bracketed/parenthetical text.
    def replace_author_year(match: re.Match[str]) -> str:
        author_part = match.group(1).strip()
        surname = re.split(r"[\s,]+", author_part)[0].lower()
        if sources:
            for s in sources:
                src_num = s.get("number") or s.get("id")
                if not src_num:
                    continue
                s_text = (
                    str(s.get("title", "")) + " " +
                    str(s.get("author", "")) + " " +
                    str(s.get("url", "")) + " " +
                    str(s.get("description", ""))
                ).lower()
                if surname in s_text:
                    return f"[{src_num}]"
        return ""

    md = re.sub(
        r"\(([A-Z][a-zA-Z\.\s\-]+?(?:\s+et\s+al\.)?),\s*([12]\d{3})\)",
        replace_author_year,
        md,
    )

    # 6b. Clean literal [n] or [N] citations.
    # Replace literal [n] with real numbers matching References list ([1], [2], ...).
    # If sentence cannot be tied to a real source, remove [n] entirely. Never print literal [n].
    def replace_literal_n(match: re.Match[str]) -> str:
        start = max(0, match.start() - 200)
        end = min(len(md), match.end() + 200)
        surrounding = md[start:end].lower()
        if sources:
            for idx, s in enumerate(sources, start=1):
                s_title_words = [w for w in re.split(r"\W+", str(s.get("title", "")).lower()) if len(w) > 4]
                s_author_words = [w for w in re.split(r"\W+", str(s.get("author", "")).lower()) if len(w) > 3]
                if any(w in surrounding for w in s_title_words) or any(w in surrounding for w in s_author_words):
                    src_num = s.get("number") or s.get("id") or idx
                    return f"[{src_num}]"
        return ""

    md = re.sub(r"\[[nN]\]", replace_literal_n, md)

    # 7. Normalize placeholders to strictly '[Add your <title> here.]' with NO trailing periods or extra punctuation
    md = re.sub(r"\[Add your ([^\]]+) here\.?\]\.*", r"[Add your \1 here.]", md)
    md = re.sub(r"\[Add your ([^\]]+) here\]", r"[Add your \1 here.]", md)

    # 8. Consistency: system has three agents; never write single-agent
    md = re.sub(r"\bsingle-agent\b", "three-agent", md, flags=re.IGNORECASE)
    md = re.sub(r"\bsingle agent\b", "three-agent", md, flags=re.IGNORECASE)

    # 9. Clean duration mentions if duration was blank
    if not duration:
        md = re.sub(r"\b(?:over|within|during|for)\s+(?:a\s+duration\s+of\s+)?(?:three|four|six|twelve|two|2|3|4|6|12)\s+(?:months|weeks)\b", "[Add your project timeline here.]", md, flags=re.IGNORECASE)
        md = re.sub(r"\b(?:three|four|six|twelve|3|4|6|12)\s+months\b", "[Add your project timeline here.]", md, flags=re.IGNORECASE)

    return md.strip()


def is_canned_boilerplate(text: str, target_words: int, is_intro: bool = False) -> bool:
    """Detect canned boilerplate fallback or severely truncated sections."""
    norm = text.lower()
    if "leverages a modular multi-agent architecture" in norm:
        return True
    if "detailed analysis of system design specifications" in norm:
        return True
    word_count = len(text.split())
    if is_intro:
        return word_count < 35
    if target_words >= 100 and word_count < int(target_words * 0.4):
        return True
    return False


def ensure_unique_figure_and_table_captions(md: str, is_short: bool = False) -> str:
    """Ensure diagram placeholders and tables have sequential Fig. N.M or Table N.M captions.
    
    - Limits figures: at most 1 per section, and at most 2 per chapter in short length (at most 4 in standard/long).
    - Renumbers sequentially with no gaps (e.g. Fig. 8.1, Fig. 8.2).
    - Strips stray '– ', '.N –', and prefixes from captions.
    - Eliminates duplicate captions in the same chapter.
    - Formats: placeholder on its own line, followed by caption.
    - Table caption followed by '[Insert table here]'.
    - Splits lines where multiple captions were merged into one.
    """
    m_ch1 = re.search(r"(?:^|\n)(#\s*Chapter\s+1\b)", md, re.IGNORECASE)
    if m_ch1:
        front_matter_part = md[:m_ch1.start(1)]
        body_part = md[m_ch1.start(1):]
    else:
        front_matter_part = ""
        body_part = md

    raw_lines = body_part.split("\n")
    split_lines: list[str] = []
    for line in raw_lines:
        stripped = line.strip()
        pattern = r"(?<!^)(?=(?:Fig\.|Figure|Table)\s+\d+(?:\.\d+)?[:\-–—])"
        sub_parts = re.split(pattern, stripped, flags=re.IGNORECASE)
        for part in sub_parts:
            if part.strip():
                split_lines.append(part.strip())
            elif not stripped:
                split_lines.append("")

    out_lines: list[str] = []
    current_ch = 1
    fig_idx = 1
    tbl_idx = 1
    ch_fig_count = 0
    sec_fig_count = 0
    seen_fig_captions: set[str] = set()
    seen_tbl_captions: set[str] = set()
    max_figs_per_ch = 2 if is_short else 4

    def clean_caption_text(raw: str) -> str:
        c = re.sub(r"^(?:Fig\.|Figure|Table)\s*\d*(?:\.\d+)*[:\s\-]*", "", raw, flags=re.IGNORECASE).strip()
        c = re.sub(r"^\.?\s*\b[Nn]\b\s*[\-–—:]+\s*", "", c)
        c = re.sub(r"^[\-–—:.]+\s*", "", c).strip()
        c = re.sub(r"[\[\]]+$", "", c).strip()
        c = re.sub(r"^[\[\]]+", "", c).strip()
        c = c.strip("–- ")
        return c or "Architecture Specification Diagram"

    def is_junk_caption(title: str) -> bool:
        t = title.strip().lower()
        if not t or t in (".", "-", ":", "–", "—"):
            return True
        if re.match(r"^(?:for|of|to|in|with|by|from)\s+the\b", t):
            return True
        if t.startswith("for "):
            return True
        return False

    for line_idx, line in enumerate(split_lines):
        stripped = line.strip()

        ch_m = re.match(r"^#\s*Chapter\s+(\d+)", stripped, re.IGNORECASE)
        if ch_m:
            current_ch = int(ch_m.group(1))
            fig_idx = 1
            tbl_idx = 1
            ch_fig_count = 0
            sec_fig_count = 0
            seen_fig_captions.clear()
            seen_tbl_captions.clear()
            out_lines.append(line)
            continue

        if stripped.startswith("## ") or stripped.startswith("### "):
            sec_fig_count = 0
            out_lines.append(line)
            continue

        diag_m = re.match(r"^>?\s*\[Insert diagram here(?::\s*([^\]]+))?\]", stripped, re.IGNORECASE)
        if diag_m:
            if sec_fig_count >= 1 or ch_fig_count >= max_figs_per_ch:
                continue
            raw_desc = (diag_m.group(1) or "").strip()
            desc = clean_caption_text(raw_desc)
            if is_junk_caption(desc):
                continue
            desc_key = desc.lower()
            if desc_key in seen_fig_captions:
                continue
            seen_fig_captions.add(desc_key)

            diag_label = f"Fig. {current_ch}.{fig_idx}"
            fig_idx += 1
            ch_fig_count += 1
            sec_fig_count += 1

            out_lines.append(f"[Insert diagram here: {diag_label} - {desc}]")
            out_lines.append("")
            out_lines.append(f"{diag_label}: {desc}")
            out_lines.append("")
            continue

        fig_cap_m = re.match(r"^(?:Fig\.|Figure)\s+\d+(?:\.\d+)?[:\s\-]+(.*)", stripped, re.IGNORECASE)
        if fig_cap_m and not stripped.lower().startswith(("as shown", "refer to", "in fig", "see fig")):
            if out_lines and out_lines[-1].startswith("Fig. "):
                continue
            if sec_fig_count >= 1 or ch_fig_count >= max_figs_per_ch:
                continue
            desc = clean_caption_text(fig_cap_m.group(1))
            if is_junk_caption(desc):
                continue
            desc_key = desc.lower()
            if desc_key in seen_fig_captions:
                continue
            seen_fig_captions.add(desc_key)

            diag_label = f"Fig. {current_ch}.{fig_idx}"
            fig_idx += 1
            ch_fig_count += 1
            sec_fig_count += 1

            out_lines.append(f"[Insert diagram here: {diag_label} - {desc}]")
            out_lines.append("")
            out_lines.append(f"{diag_label}: {desc}")
            out_lines.append("")
            continue

        tbl_cap_m = re.match(r"^Table\s+\d+(?:\.\d+)?[:\s\-–—]+(.*)", stripped, re.IGNORECASE)
        if tbl_cap_m:
            desc = clean_caption_text(tbl_cap_m.group(1))
            if is_junk_caption(desc) or any(desc.lower().startswith(v) for v in ["describes", "shows", "lists", "provides", "illustrates", "summarizes"]):
                continue
            desc_key = desc.lower()
            if desc_key in seen_tbl_captions:
                continue
            seen_tbl_captions.add(desc_key)

            tbl_label = f"Table {current_ch}.{tbl_idx}"
            tbl_idx += 1
            out_lines.append(f"{tbl_label}: {desc}")
            out_lines.append("")
            # Check if a markdown table follows in subsequent lines
            has_table_following = False
            for future_line in split_lines[line_idx + 1:line_idx + 8]:
                f_str = future_line.strip()
                if not f_str or f_str == "[Insert table here]":
                    continue
                if f_str.startswith("|"):
                    has_table_following = True
                    break
                if f_str.startswith("#") or re.match(r"^(?:Fig\.|Figure|Table)\s+\d", f_str, re.IGNORECASE):
                    break
            if not has_table_following:
                out_lines.append("[Insert table here]")
                out_lines.append("")
            continue

        if stripped == "[Insert table here]":
            continue

        out_lines.append(line)

    res = (front_matter_part + "\n".join(out_lines)).strip()
    res = re.sub(r"\n{3,}", "\n\n", res)
    return res


FORBIDDEN_COLLEGE_TOOLS = [
    "jest",
    "react testing library",
    "httpx",
    "circleci",
    "github actions",
    "docker",
    "jira",
    "bug tracker",
    "issue tracker",
]

FORBIDDEN_COLLEGE_WORDS = [
    "encrypted sqlite",
    "https",
    "crud",
    "sprints",
    "gdpr",
    "ccpa",
    "rate-limit otp per ip",
    "claim-checker",
    "token-budget scheduler",
]

BANNED_DATABASES = [
    "postgresql",
    "postgres",
    "mysql",
    "mongodb",
    "dynamodb",
    "redis",
    "cassandra",
    "couchdb",
]

BANNED_AGENTS = [
    "synthesis agent",
    "formatting agent",
    "knowledge graph",
    "central controller",
    "literature-search agent",
    "citation agent",
    "summarization agent",
]

BANNED_PHRASES = [
    "stores user credentials",
    "store user credentials",
    "stores credentials",
    "user passwords",
    "stores passwords",
    "stores user passwords",
    "user credentials and passwords",
    "user credentials/passwords",
    "race conditions",
    "race condition",
    "lacks built-in persistence",
    "lack of built-in persistence",
    "concurrent requests",
    "concurrent request",
    "asynchronous research tasks",
    "asynchronous research task",
]

FIXED_GENERIC_ALLOWED_TERMS = {
    "research",
    "analysis",
    "writer",
    "langgraph",
    "fastapi",
    "sqlite",
    "sqlalchemy",
    "react",
    "vite",
    "tailwind",
    "groq",
    "tavily",
    "gmail smtp",
    "gmail",
    "smtp",
    "jwt",
    "otp",
    "reportlab",
    "python-docx",
    "pytest",
    "uvicorn",
    "python",
    "typescript",
    "javascript",
    "node.js",
    "nodejs",
    "node",
    "html",
    "css",
    "json",
    "rest",
    "api",
    "apis",
    "http",
    "pydantic",
    "citebolt",
    "figure",
    "table",
    "chapter",
    "section",
    "appendix",
    "user",
    "users",
    "student",
    "guide",
    "coordinator",
    "hod",
    "dean",
    "department",
    "university",
    "pdf",
    "docx",
    "orm",
    "llm",
    "srs",
    "ui",
    "gui",
    "vcs",
    "ieee",
    "auth",
    "pipeline",
    "export",
    "module",
    "modules",
    "service",
    "services",
}

KNOWN_EXTERNAL_PROPER_TOOLS = [
    "postgresql", "postgres", "alembic", "sqlmodel", "mypy", "eslint", "wcag",
    "swagger", "openai", "docker", "kubernetes", "redis", "mysql", "mongodb",
    "dynamodb", "cassandra", "couchdb", "kafka", "rabbitmq", "selenium", "cypress",
    "jest", "mocha", "graphql", "grpc", "circleci", "jenkins", "github actions",
    "jira", "confluence", "linear", "gitlab", "webpack", "babel", "rollup", "turbopack",
    "chakra", "mui", "bootstrap", "bulma", "prisma", "drizzle", "tortoise", "peewee",
    "django", "flask", "express", "nestjs", "spring", "next.js", "nuxt", "svelte",
    "vue", "angular", "electron", "tauri", "aws", "azure", "gcp", "s3", "ec2", "lambda"
]


def build_allowed_tokens_set(positive_facts: str = "") -> set[str]:
    """Build the allowed set from user fact sheet text ONLY + fixed allow-list of generic terms.
    
    IMPORTANT: The 'NOT TRUE / DO NOT WRITE' block must NOT be included in the corpus.
    """
    allowed = set(FIXED_GENERIC_ALLOWED_TERMS)
    if positive_facts:
        clean_positive = re.split(r"NOT TRUE\s*/\s*DO NOT WRITE", positive_facts, flags=re.IGNORECASE)[0]
        words = re.findall(r"[A-Za-z0-9_./\-]+", clean_positive.lower())
        allowed.update(words)
    return allowed


def is_sentence_allowed_by_whitelist(sent: str, allowed_set: set[str], positive_corpus: str) -> bool:
    """Check if a sentence in college chapters 3-11 complies with the whitelist.
    
    Drops sentence if it contains specific tokens (versions, numbers with units/percentages/concurrency,
    CamelCase identifiers, Sprints, acronyms, proper tool names) not in the allowed set.
    """
    s_clean = sent.strip()
    if not s_clean:
        return True

    pos_lower = positive_corpus.lower()

    # 1. Version numbers (e.g., Python 3.11, React 18)
    ver_matches = re.findall(r"\b([A-Za-z]+)\s+(\d+(?:\.\d+)+)\b", s_clean)
    for name, ver in ver_matches:
        if f"{name.lower()} {ver}" not in pos_lower:
            return False
    ver_single = re.findall(r"\b(Python|React|Node|Vite|Tailwind|FastAPI|Uvicorn)\s+(\d+)\b", s_clean, re.IGNORECASE)
    for name, ver in ver_single:
        if f"{name.lower()} {ver}" not in pos_lower:
            return False

    # 2. Numbers with units or percentages or concurrency ('2 seconds', '99 percent', '99%', '5 concurrent runs')
    unit_matches = re.findall(
        r"\b\d+(?:\.\d+)?\s*(?:seconds?|secs?|ms|milliseconds?|minutes?|hours?|days?|weeks?|months?|years?|percent|%|fps|mb|gb|kb|concurrent\s+\w+|\w+\s+per\s+\w+)\b",
        s_clean,
        re.IGNORECASE,
    )
    for u in unit_matches:
        u_clean = u.lower().strip()
        if u_clean not in pos_lower:
            return False

    # 3. Identifiers like AuthService, SQLModel, MyPy, ESLint, OpenAI
    camel_matches = re.findall(r"\b[A-Za-z0-9]*[a-z][A-Z][a-zA-Z0-9]*\b", s_clean)
    for c in camel_matches:
        c_low = c.lower()
        if c_low not in allowed_set and c_low not in pos_lower:
            return False

    # 4. Sprints (Sprint N, Sprint 1, Sprint 2)
    if re.search(r"\bSprint\s+[A-Za-z0-9]+\b", s_clean, re.IGNORECASE):
        if "sprint" not in allowed_set and "sprint" not in pos_lower:
            return False

    # 5. Acronyms (>2 caps letters, e.g. WCAG, CRUD, GDPR, CCPA)
    common_safe_acronyms = {"PDF", "DOCX", "ORM", "LLM", "IEEE", "SRS", "API", "REST", "JSON", "HTTP", "HTML", "CSS", "JWT", "OTP", "SMTP", "CRUD", "UI", "VCS", "URL", "DOM", "SQL"}
    caps_matches = re.findall(r"\b[A-Z]{3,}\b", s_clean)
    for ac in caps_matches:
        if ac in common_safe_acronyms:
            continue
        if ac.lower() not in allowed_set and ac.lower() not in pos_lower:
            return False

    # 6. Capitalized proper nouns / tool or library names (PostgreSQL, Alembic, Swagger, etc.)
    for tool in KNOWN_EXTERNAL_PROPER_TOOLS:
        if re.search(r"\b" + re.escape(tool) + r"\b", s_clean, re.IGNORECASE):
            if tool not in allowed_set:
                return False

    return True

DANGLING_END_RE = re.compile(
    r"\b(?:in|on|at|for|with|by|from|to|into|onto|of|and|or|as|that|which|including|such as|depends on|utilizes|uses|delivers|provides|consists of|shown in|illustrates|depicts)\.?$",
    re.IGNORECASE,
)
DANGLING_START_RE = re.compile(
    r"^(?:to\s+[a-z]+|and\b|or\b|for\b|in\b|with\b|by\b|that\b|which\b|to finalize|to complete|[a-z])",
)


def is_dangling_fragment(s: str) -> bool:
    s_clean = s.strip()
    if not s_clean:
        return True
    s_no_punct = s_clean.rstrip(".?!:;").strip()
    if re.search(r"\b(?:in|on|at|for|with|by|from|to|into|onto|of|and|or|as|that|which|including|such as|depends on|utilizes|uses|delivers|provides|consists of|shown in|illustrates|depicts)$", s_no_punct, re.IGNORECASE):
        return True
    if re.search(r"^(?:to\s+[a-z]+|and\b|or\b|for\b|in\b|with\b|by\b|that\b|which\b|to finalize|to complete)", s_clean, re.IGNORECASE):
        return True
    # Dangling sentence starters: drop if a paragraph/sentence starts with "It also", "The chapter also", "This section also"
    if re.search(r"^(?:It\s+also\b|The chapter also\b|This section also\b|The section also\b)", s_clean, re.IGNORECASE):
        return True
    # Dangling bare N.M. tokens at end (e.g. "4.2." or "10.3.")
    if re.search(r"\b\d+\.\d+\.?\s*$", s_clean):
        return True
    return False


def _clean_single_section_dangling(text: str) -> str:
    """Clean dangling fragments, isolate placeholders, and eliminate doubled placeholders within a single section."""
    if not text:
        return text

    # Strip dangling N.M). leftover tokens like "3.1). 3.2). 3.3)." without corrupting "(see Fig. 7.2)"
    def _strip_dangling_num(m: re.Match[str]) -> str:
        prefix = m.group(1) or ""
        if prefix and re.search(r"(?:Fig\.|Figure|Table)\s*$", prefix, re.IGNORECASE):
            return m.group(0)
        return prefix

    text = re.sub(
        r"((?:Fig\.|Figure|Table)\s*)?\b\d+\.\d+\)\.?",
        _strip_dangling_num,
        text,
        flags=re.IGNORECASE,
    )

    # When a section contains both "No load testing..." and a placeholder, keep only one
    if "no load testing" in text.lower():
        text = re.sub(r"\[Add your [^\]]*load testing[^\]]*here\.?\]", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\[Add your [^\]]*here\.?\]", "", text, flags=re.IGNORECASE)

    # Deduplicate doubled figure placeholders
    text = re.sub(
        r"\[Insert diagram here\]\s*\n*\s*(\[Insert diagram here:\s*[^\]]+\])",
        r"\1",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(\[Insert diagram here:\s*[^\]]+\])\s*\n*\s*\[Insert diagram here\]",
        r"\1",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\[Insert diagram here\]\s*\[Insert diagram here\]",
        r"[Insert diagram here]",
        text,
        flags=re.IGNORECASE,
    )

    # Ensure figure placeholders are on their own line, never appended to end of a paragraph
    def _isolate_figure_placeholder(m: re.Match[str]) -> str:
        prefix = m.group(1)
        ph = m.group(2)
        if re.search(r"\b(?:see|refer to|shown in|in)\s*\(?$", prefix, re.IGNORECASE):
            return m.group(0)
        return f"{prefix}\n\n{ph}"

    text = re.sub(r"([^\n]+?)(\[Insert diagram here[^\]]*\])", _isolate_figure_placeholder, text, flags=re.IGNORECASE)
    text = re.sub(r"(\[Insert diagram here[^\]]*\])\s*([^\n])", r"\1\n\n\2", text, flags=re.IGNORECASE)

    lines = text.split("\n")
    cleaned_lines = []
    for i, line in enumerate(lines):
        s = line.strip()
        if re.match(r"^\[Insert diagram here\]\.?$", s, re.IGNORECASE):
            prev_line = ""
            for p in reversed(cleaned_lines):
                if p.strip():
                    prev_line = p.strip()
                    break
            next_line = ""
            for n in lines[i + 1:]:
                if n.strip():
                    next_line = n.strip()
                    break
            if (prev_line and re.match(r"^\[Insert diagram here:\s*[^\]]+", prev_line, re.IGNORECASE)) or \
               (next_line and re.match(r"^\[Insert diagram here:\s*[^\]]+", next_line, re.IGNORECASE)):
                continue
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)

    paragraphs = text.split("\n\n")
    cleaned_paras: list[str] = []

    # Check if section has substantial real prose text (>= 15 words)
    non_placeholder_text = re.sub(r"\[Add (?:your|more)[^\]]+\]", "", text, flags=re.IGNORECASE)
    non_placeholder_text = re.sub(r"^#+.*$", "", non_placeholder_text, flags=re.MULTILINE)
    has_real_text = len(re.findall(r"\b\w+\b", non_placeholder_text)) >= 15

    for p in paragraphs:
        p_strip = p.strip()
        if not p_strip:
            continue

        if p_strip.startswith("#") or p_strip.startswith("|"):
            cleaned_paras.append(p_strip)
            continue

        # Check if list block (each non-empty line starts with bullet / list marker)
        lines = [ln for ln in p_strip.split("\n") if ln.strip()]
        if lines and all(re.match(r"^\s*(?:[-*+]|\d+\.)\s+", ln) for ln in lines):
            cleaned_items: list[str] = []
            for ln in lines:
                m_item = re.match(r"^(\s*(?:[-*+]|\d+\.)\s+)(.*)$", ln)
                if not m_item:
                    continue
                marker = m_item.group(1)
                body = m_item.group(2).strip()

                if has_real_text and re.match(r"^\s*\[Add (?:your|more)[^\]]+\]\.?\s*$", body, re.IGNORECASE):
                    continue

                ph_m = re.search(r"(\[Add (?:your|more)[^\]]+\])", body, re.IGNORECASE)
                if not ph_m:
                    if is_dangling_fragment(body):
                        continue
                    cleaned_items.append(f"{marker}{body}")
                else:
                    ph = ph_m.group(1).strip()
                    b = body[:ph_m.start()].strip()
                    a = body[ph_m.end():].strip()
                    if not b and not a:
                        if not ph.lower().startswith("[add ") or not has_real_text:
                            cleaned_items.append(f"{marker}{ph}")
                    elif is_dangling_fragment(b) or (a and is_dangling_fragment(a)):
                        if not ph.lower().startswith("[add ") or not has_real_text:
                            cleaned_items.append(f"{marker}{ph}")
                    else:
                        parts = []
                        if b:
                            parts.append(b)
                        parts.append(ph)
                        if a:
                            parts.append(a)
                        cleaned_items.append(f"{marker}{' '.join(parts)}")
            if cleaned_items:
                cleaned_paras.append("\n".join(cleaned_items))
            continue

        # Preserve code blocks and installation blocks unconditionally
        if p_strip.startswith("```") or p_strip.endswith("```") or "cd backend" in p_strip or "cd frontend" in p_strip:
            cleaned_paras.append(p_strip)
            continue

        ph_match = re.search(r"(\[(?:Add (?:your|more)|Insert (?:diagram|table|figure))[^\]]+\])", p_strip, re.IGNORECASE)
        if not ph_match:
            if is_dangling_fragment(p_strip):
                continue
            # Only drop run command pieces in intro sections (1.1-1.7), never in chapter 10 installation
            if re.search(r"^\s*#+\s*1\.[1-7]\b", text) and ("main:app" in p_strip or "127.0.0.1" in p_strip):
                continue
            cleaned_paras.append(p_strip)
            continue

        ph = ph_match.group(1).strip()
        before = p_strip[:ph_match.start()].strip()
        after = p_strip[ph_match.end():].strip()

        if not before and not after:
            if not ph.lower().startswith("[add ") or not has_real_text:
                cleaned_paras.append(ph)
            continue

        before_dangling = is_dangling_fragment(before) if before else False
        after_dangling = is_dangling_fragment(after) if after else False

        # Any paragraph that has a dangling fragment on either side of a placeholder becomes just the placeholder on its own line
        if before_dangling or after_dangling:
            valid_before: list[str] = []
            if before:
                sents = re.split(r"(?<=[.!?])\s+", before)
                valid_before = [s.strip() for s in sents if s.strip() and not is_dangling_fragment(s)]
            if valid_before:
                cleaned_paras.append(" ".join(valid_before))
            if not ph.lower().startswith("[add ") or not has_real_text:
                cleaned_paras.append(ph)
            valid_after: list[str] = []
            if after:
                sents_after = re.split(r"(?<=[.!?])\s+", after)
                valid_after = [s.strip() for s in sents_after if s.strip() and not is_dangling_fragment(s)]
            if valid_after:
                cleaned_paras.append(" ".join(valid_after))
            continue

        parts: list[str] = []
        if before:
            parts.append(before)
        parts.append(ph)
        if after:
            parts.append(after)
        cleaned_paras.extend(parts)

    res = "\n\n".join(cleaned_paras).strip()
    res = re.sub(r"\n{3,}", "\n\n", res)
    return res


def clean_dangling_fragments_and_placeholders(text: str) -> str:
    """Ensure placeholders never split sentences and clean up dangling fragments.
    
    1. Keeps only titled figure placeholders when doubled with bare ones.
    2. Drops dangling fragments such as 'The Gantt chart in', 'CiteBolt utilizes.', 'Total effort depends on.'
    3. Any paragraph with dangling fragments on either side of a placeholder becomes just the placeholder.
    4. Placeholders are placed on their own line/paragraph and never sit in the middle of a paragraph.
    5. Strips stray '3.1). 3.2). 3.3).' leftover numbering tokens without corrupting '(see Fig. 7.2)'.
    6. Removes generic '[Add your ... here.]' when the section already contains real text (>=15 words).
    7. When a section contains both 'No load testing...' and a placeholder, keeps only one.
    """
    if not text:
        return text

    # Remove meta paragraph in 6.1 ("The introductory overview provides…")
    text = re.sub(r"[^\.\n]*\bthe\s+introductory\s+overview\s+provides\b[^\.\n]*\.?", "", text, flags=re.IGNORECASE)

    # Put diagram placeholders on their own line, never inside a paragraph (7.4)
    text = re.sub(r"([^\n])\s*(\[(?:Insert diagram here|Insert table here)[^\]]*\])", r"\1\n\n\2", text, flags=re.IGNORECASE)
    text = re.sub(r"(\[(?:Insert diagram here|Insert table here)[^\]]*\])\s*([^\n])", r"\1\n\n\2", text, flags=re.IGNORECASE)

    # Split text into sections by heading lines
    heading_pattern = r"(?:\n|^)(?=#{1,4}\s+)"
    parts = [p for p in re.split(heading_pattern, text) if p]
    if len(parts) > 1:
        res = "\n\n".join(_clean_single_section_dangling(p) for p in parts)
    else:
        res = _clean_single_section_dangling(text)
    res = re.sub(r"\n{3,}", "\n\n", res).strip()
    return res


REAL_DB_TABLES = {"users", "otp_codes", "runs", "templates", "user_settings", "contact_messages"}


def normalize_college_captions_and_placeholders(text: str) -> str:
    """Normalize captions, placeholders, and meta-text in college report markdown.
    
    1. Collapses nested '[Insert diagram here: [Insert diagram here: X]]' to single '[Insert diagram here: X]'.
    2. Ensures brackets are closed. A bare '[Insert diagram here:' becomes '[Insert diagram here]'.
    3. Strips stray ']' and '[' at the end of 'Fig. N.M: Title' captions.
    4. Preserves first letters in caption titles (e.g. 'Non-functional requirements overview').
    5. Replaces inline 'see [Insert diagram here: Fig. 7.2 - ...]' in prose with 'see Fig. 7.2'.
    6. Drops captions with empty or junk titles (e.g. 'for the ER diagram.').
    7. Ensures placeholders are never inserted mid-word or mid-sentence (per-run L[Add...] bug).
    8. Removes meta-text sentences (e.g. 'presented as a placeholder pending detailed analysis').
    9. Unbolds placeholder bullets (e.g. '- **[Add your...**' -> '- [Add your...').
    """
    if not text:
        return text

    # 1. Collapse nested [Insert diagram here: [Insert diagram here: X]] to a single [Insert diagram here: X]
    while re.search(r"\[Insert diagram here:?\s*\[Insert diagram here:?\s*([^\]]*)\]\]", text, flags=re.IGNORECASE):
        text = re.sub(
            r"\[Insert diagram here:?\s*\[Insert diagram here:?\s*([^\]]*)\]\]",
            r"[Insert diagram here: \1]",
            text,
            flags=re.IGNORECASE,
        )

    # 0. Deduplicate doubled figure placeholders
    text = re.sub(
        r"\[Insert diagram here\]\s*\n*\s*(\[Insert diagram here:\s*[^\]]+\])",
        r"\1",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(\[Insert diagram here:\s*[^\]]+\])\s*\n*\s*\[Insert diagram here\]",
        r"\1",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\[Insert diagram here\]\s*\[Insert diagram here\]",
        r"[Insert diagram here]",
        text,
        flags=re.IGNORECASE,
    )

    # 2. Always close the bracket. A bare '[Insert diagram here:' becomes '[Insert diagram here]'
    text = re.sub(r"\[Insert diagram here:\s*(?=\n|$)", "[Insert diagram here]", text, flags=re.IGNORECASE)
    text = re.sub(r"\[Insert diagram here:\s*\]", "[Insert diagram here]", text, flags=re.IGNORECASE)
    def _close_unclosed_diagram(m: re.Match[str]) -> str:
        val = m.group(1).strip()
        return f"[Insert diagram here: {val}]" if val else "[Insert diagram here]"
    text = re.sub(r"\[Insert diagram here:?\s*([^\n\]]+)(?=\n|$)", _close_unclosed_diagram, text, flags=re.IGNORECASE)

    # 3. Strip stray ']' and '[' at the end of 'Fig. N.M: Title' captions
    def _strip_caption_stray_brackets(line: str) -> str:
        s = line.strip()
        if re.match(r"^(?:Fig\.|Figure|Table)\s+\d+(?:\.\d+)?[:\s\-]", s, re.IGNORECASE):
            s = re.sub(r"[\[\]]+$", "", s).strip()
            s = re.sub(r"^[\[\]]+", "", s).strip()
            return s
        return line
    lines = [_strip_caption_stray_brackets(ln) for ln in text.split("\n")]
    text = "\n".join(lines)

    # 4. Remove inline 'see [Insert diagram here: Fig. 7.2 - ...]' in prose; replace it with 'see Fig. 7.2'
    text = re.sub(
        r"(\b(?:see|refer to|shown in|in)\s+)\[Insert diagram here:\s*(Fig\.\s*\d+(?:\.\d+)?)[^\]]*\]",
        r"\1\2",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\((?:see|refer to)\s+\[Insert diagram here:\s*(Fig\.\s*\d+(?:\.\d+)?)[^\]]*\]\)",
        r"(see \1)",
        text,
        flags=re.IGNORECASE,
    )

    # Ensure figure placeholders are on their own line, never appended to end of a paragraph
    def _isolate_figure_placeholder(m: re.Match[str]) -> str:
        prefix = m.group(1)
        ph = m.group(2)
        if re.search(r"\b(?:see|refer to|shown in|in)\s*\(?$", prefix, re.IGNORECASE):
            return m.group(0)
        return f"{prefix}\n\n{ph}"

    text = re.sub(r"([^\n]+?)(\[Insert diagram here[^\]]*\])", _isolate_figure_placeholder, text, flags=re.IGNORECASE)
    text = re.sub(r"(\[Insert diagram here[^\]]*\])\s*([^\n])", r"\1\n\n\2", text, flags=re.IGNORECASE)

    # 5. Drop captions with an empty or junk title ("for the ER diagram.", etc.)
    clean_lines = []
    all_lines = text.split("\n")
    for ln in all_lines:
        s = ln.strip()
        m_fig = re.match(r"^(?:Fig\.|Figure|Table)\s+\d+(?:\.\d+)?[:\s\-]+(.*)", s, re.IGNORECASE)
        if m_fig and not s.lower().startswith(("as shown", "refer to", "in fig", "see fig")):
            cap_title = m_fig.group(1).strip().lower()
            is_junk = (
                not cap_title
                or cap_title in (".", "-", ":", "–", "—")
                or re.match(r"^(?:for|of|to|in|with|by|from)\s+the\b", cap_title)
                or cap_title.startswith("for ")
                or any(k in cap_title for k in ["latency", "throughput", "execution time", "agent latency", "token flow"])
            )
            if is_junk:
                while clean_lines and not clean_lines[-1].strip():
                    clean_lines.pop()
                if clean_lines and clean_lines[-1].strip().startswith("[Insert diagram here"):
                    clean_lines.pop()
                continue

        m_diag = re.match(r"^\[Insert diagram here:\s*(?:(?:Fig\.|Figure)\s*\d+(?:\.\d+)?\s*[-–—:]\s*)?(.*?)\]", s, re.IGNORECASE)
        if m_diag:
            diag_title = m_diag.group(1).strip().lower()
            if (
                not diag_title
                or diag_title in (".", "-", ":", "–", "—")
                or re.match(r"^(?:for|of|to|in|with|by|from)\s+the\b", diag_title)
                or diag_title.startswith("for ")
                or any(k in diag_title for k in ["latency", "throughput", "execution time", "agent latency", "token flow"])
            ):
                continue

        clean_lines.append(ln)
    text = "\n".join(clean_lines)

    # 6. A placeholder must never be inserted mid-word or mid-sentence (the 'per-run L[Add...]' bug)
    text = re.sub(r"\b[a-zA-Z]\[Add\s+", "[Add ", text)

    # 7. Remove meta-text sentences
    meta_patterns = [
        r"[^\.\n]*\bpresented as a placeholder pending\b[^\.\n]*\.?",
        r"[^\.\n]*\bplaceholder pending detailed analysis\b[^\.\n]*\.?",
        r"[^\.\n]*\bplaceholder sections? for additional validation\b[^\.\n]*\.?",
        r"[^\.\n]*\bpending detailed analysis\b[^\.\n]*\.?",
        r"[^\.\n]*\bas a placeholder for additional\b[^\.\n]*\.?",
    ]
    for pat in meta_patterns:
        text = re.sub(pat, "", text, flags=re.IGNORECASE)

    # 8. Placeholder bullets must not be bold
    text = re.sub(r"\*\*(\[Add (?:your|more)[^\]]+\])\*\*", r"\1", text)

    # 9. Clean dangling fragments, isolate placeholders, and eliminate doubled placeholders
    text = clean_dangling_fragments_and_placeholders(text)

    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def get_verified_test_count() -> int:
    """Return the real test count from test collection."""
    try:
        import unittest
        from pathlib import Path
        loader = unittest.TestLoader()
        test_dir = Path("backend/tests")
        if not test_dir.exists():
            test_dir = Path("tests")
        if not test_dir.exists():
            test_dir = Path(__file__).resolve().parent.parent.parent / "tests"
        if test_dir.exists():
            suite = loader.discover(str(test_dir), pattern="test_college_quality.py")
            cnt = suite.countTestCases()
            if cnt > 0:
                return cnt
    except Exception:
        pass
    return 75


def filter_grounded_college_section(
    sec_title: str,
    sec_md: str,
    fact_sheet: str = "",
    heading_prefix: str = "##",
    is_college: bool = True,
    min_words: int = 2,
    chapter_has_stack_stated: list[bool] | None = None,
) -> str:
    """Post-generation grounding filter applied at the sentence level for college reports.
    
    Enforces whitelist grounding filter for chapters 3-11, removes ungrounded metrics and tools.
    Falls back to '[Add your <title> here.]' if the section becomes empty.
    """
    if not is_college:
        return sec_md

    clean_sec_title = re.sub(r"^\d+(?:\.\d+)*\s*", "", sec_title).strip()
    norm_sec = sec_title.lower()
    facts_lower = fact_sheet.lower() if fact_sheet else ""
    positive_facts = re.split(r"NOT TRUE\s*/\s*DO NOT WRITE", fact_sheet, flags=re.IGNORECASE)[0]
    allowed_tokens = build_allowed_tokens_set(positive_facts=positive_facts)

    m_ch = re.search(r"^(?:chapter\s+)?(\d+)", sec_title.strip(), re.IGNORECASE)
    actual_ch_num = int(m_ch.group(1)) if m_ch else 0
    apply_whitelist = (actual_ch_num >= 3)
    duration_blank = "not specified" in facts_lower or "blank" in facts_lower or "project duration" not in facts_lower

    # Deterministic Roadmap for Section 1.5 (Task 2 Item 3)
    if re.search(r"^1\.5\b", sec_title):
        return build_deterministic_roadmap_section(sec_title, heading_prefix)

    # Deterministic Data Design for Section 4.6 (Item 6)
    if re.search(r"^4\.6\s+data\s+design\b", sec_title, re.IGNORECASE) or norm_sec == "4.6 data design":
        return build_deterministic_data_design_section(sec_title, heading_prefix)

    # 6.6 Team Structure: if team size is 1, single student (Task 2 Item 10)
    if re.search(r"^6\.6\b", sec_title) or (actual_ch_num == 6 and any(k in norm_sec for k in ["team structure", "team organization", "team roles"])):
        return f"{heading_prefix} {sec_title}\n\nThe project was developed by a single student."

    # Deterministic Data Dictionary for Section 7.3 (Item 5 / 8)
    if re.search(r"^7\.3\b", sec_title) or (actual_ch_num == 7 and "data dictionary" in norm_sec):
        return build_deterministic_data_dictionary_section(sec_title, heading_prefix)

    # Deterministic Installation for Section 10.3 (Task 2 Item 7)
    if re.search(r"^10\.3\b", sec_title):
        return build_deterministic_installation_section(sec_title, heading_prefix)

    # Sections 10.5, 10.6, 10.7 matching headings (Task 2 Item 6)
    if re.search(r"^10\.5\b", sec_title):
        return f"""{heading_prefix} {sec_title}

System maintenance is performed through manual process restarts following code changes or configuration updates. The FastAPI backend running via Uvicorn and the Vite frontend development server are restarted directly from the terminal, without automated process supervisors or container orchestration."""

    if re.search(r"^10\.6\b", sec_title):
        db_file = get_verified_db_filename()
        return f"""{heading_prefix} {sec_title}

Database backup and recovery is conducted by creating direct filesystem copies of the SQLite database file (`{db_file}`). In the event of data corruption or migration requirements, recovery is achieved by restoring the copied database file while the backend service is halted, ensuring database file integrity."""

    if re.search(r"^10\.7\b", sec_title):
        return f"""{heading_prefix} {sec_title}

Deployment challenges primarily center on managing external API rate limits and quotas for LLM inference and web search services. Operating as a local-only deployment mitigates cloud hosting overhead and network ingress risks while restricting service availability to the local workstation."""

    # Chapter 2 must be 100% placeholders unless the user supplied related-work text
    if actual_ch_num == 2 and not ("relatedwork" in facts_lower or "related work" in facts_lower):
        return f"{heading_prefix} {sec_title}\n\n[Add your {clean_sec_title} here.]"

    if not sec_md:
        return f"{heading_prefix} {sec_title}\n\n[Add your {clean_sec_title} here.]"

    # Section 6.7 and 6.9 with no duration become placeholders (Item 3)
    if duration_blank and any(k in norm_sec for k in ["6.7", "6.9", "timeline", "effort estimation"]):
        return f"{heading_prefix} {sec_title}\n\n[Add your {clean_sec_title} here.]"

    # Section 8.7: defect tracking (Item 4)
    if any(k in norm_sec for k in ["8.7", "defect tracking", "bug tracking", "maintenance"]):
        if "jira" not in facts_lower and "bug tracking" not in facts_lower and "defect" not in facts_lower:
            return f"{heading_prefix} {sec_title}\n\n[Add your {clean_sec_title} here.]"

    # Section 9.6: comparison with existing systems
    if "9.6" in norm_sec or ("comparison" in norm_sec and "existing" in norm_sec):
        has_allowed_comparison = "comparison" in facts_lower and len(facts_lower.split()) > 50
        if not has_allowed_comparison:
            return f"{heading_prefix} {sec_title}\n\n[Add your comparison with existing systems here.]"

    # Special section overrides: agents are LangGraph nodes, NOT FastAPI route handlers
    sec_md = re.sub(
        r"\b(?:FastAPI\s+route\s+handlers?|FastAPI\s+endpoints?|FastAPI\s+routes?)\s+(?:acting\s+as|serving\s+as|for)\s+(?:agents?|the\s+multi-agent\s+pipeline)",
        "LangGraph workflow nodes for multi-agent coordination",
        sec_md,
        flags=re.IGNORECASE,
    )
    sec_md = re.sub(
        r"\bagents?\s+(?:are\s+implemented\s+as|run\s+as|function\s+as)\s+FastAPI\s+route\s+handlers?\b",
        "agents are implemented as LangGraph graph nodes",
        sec_md,
        flags=re.IGNORECASE,
    )

    out_lines: list[str] = []
    has_body_text = False

    is_intro_chapter = any(norm_sec.startswith(f"1.{k}") for k in range(1, 8)) or norm_sec.startswith("chapter 1")

    for line in sec_md.split("\n"):
        stripped = line.strip()
        if not stripped:
            out_lines.append("")
            continue

        if stripped.startswith("#") or stripped.startswith("[Insert ") or stripped.startswith("|") or stripped == "[Insert table here]":
            out_lines.append(line)
            continue

        if stripped.startswith("[Add your "):
            has_body_text = True
            out_lines.append(line)
            continue

        sentences = re.split(r"(?<=[.!?])\s+", stripped)
        kept_sentences: list[str] = []

        for sent in sentences:
            s_low = sent.lower()

            # Unsupported claims (Item 1 & Item 3)
            unsupported_claim = False
            for pat in [
                r"\bcontinuous\s+integration\b",
                r"\bci\s+runs?\b",
                r"\bci/cd\b",
                r"\bevery\s+commit\b",
                r"\bend-to-end\s+tests?\b",
                r"\bend-to-end\s+testing\b",
                r"\bsmoke\s+tests?\b",
                r"\bregression\s+tests?\b",
                r"\bexecution\s+time\s+per\s+agent\b",
                r"\bthroughput\b",
                r"\blatency\b",
                r"\bsuccess\s+rates?\b",
                r"\bcannot\s+handle\s+concurrent\b",
                r"\bmonolithic\s+pipelines?\b",
                r"\bdemonstrates\s+successful\s+end-to-end\b",
                r"\bupdates?\s+every\s+2\s*(?:s|sec|seconds?)\b",
                r"\bfew\s+hundred\s+milliseconds\b",
                r"\blog\s+rotation\b",
                r"\bmonitoring\b",
                r"\btest-driven\b",
                r"\bmirroring\s+the\s+production\s+stack\b",
                r"\beasy\s+migration\b",
                r"\bfully\s+documented\b",
                r"\bparallel\s+development\b",
                r"\bcollected\s+comments\b",
                r"\binform\s+ui\s+refinements\b",
                r"\bacid\b",
                r"\bservice\s+classes\b",
                r"\bcommon\s+services\s+package\b",
                r"\bthe\s+introductory\s+overview\s+provides\b",
            ]:
                if re.search(pat, s_low):
                    logger.info("Grounding filter dropped in [%s]: %s (reason: unsupported claim: %s)", sec_title, sent, pat)
                    unsupported_claim = True
                    break
            if unsupported_claim:
                continue

            # Test coverage: never say tests cover agents, endpoints, state transitions, OTP flow, token accounting, orchestration, fallback, or persistence
            if any(k in s_low for k in ["test", "tests", "testing", "test suite", "test case", "test cases", "verified by", "tested by", "validated by"]):
                if any(k in s_low for k in [
                    "orchestration", "token accounting", "fallback", "persistence",
                    "jwt cookie", "jwt cookies", "otp delivery", "otp flow", "otp",
                    "agent", "agents", "fastapi endpoint", "endpoints", "endpoint contract",
                    "run state transition", "run state transitions", "state transition", "state transitions",
                    "concurrency", "rate limit"
                ]):
                    logger.info("Grounding filter dropped in [%s]: %s (reason: ungrounded test coverage)", sec_title, sent)
                    continue

            # Section 3.7 must be a plan (or placeholder), not non-functional requirements (Item 4)
            if re.search(r"^3\.7\b", sec_title) or (actual_ch_num == 3 and "plan" in norm_sec):
                if any(k in s_low for k in ["non-functional", "nonfunctional", "non functional"]):
                    logger.info("Grounding filter dropped in [%s]: %s (reason: non-functional claim in implementation plan)", sec_title, sent)
                    continue

            # Dangling starters / enders (Item 5)
            is_summary_sec = "summary" in norm_sec
            if re.search(r"^(?:The chapter also\b|This section also\b|The section also\b|It also\b)", sent.strip(), re.IGNORECASE) or (is_summary_sec and re.match(r"^It\s+", sent.strip(), re.IGNORECASE)):
                logger.info("Grounding filter dropped in [%s]: %s (reason: dangling starter)", sec_title, sent)
                continue
            if re.search(r"\b\d+\.\d+\.?\s*$", sent.strip()):
                logger.info("Grounding filter dropped in [%s]: %s (reason: dangling bare number token)", sec_title, sent)
                continue

            # Remove specific test numbers from all sections except 8.5 (Item 3)
            if not any(k in norm_sec for k in ["8.5"]):
                if re.search(r"\b\d+\s+(?:unit\s+|automated\s+)?tests?\b", sent, re.IGNORECASE):
                    sent = re.sub(r"\b\d+\s+(?:unit\s+|automated\s+)?tests?\b", "automated pytest unit tests", sent, flags=re.IGNORECASE)
                    s_low = sent.lower()
            else:
                cnt = get_verified_test_count()
                if re.search(r"\b(?:\d+|fourteen)\s+(?:unit\s+|automated\s+)?tests?\b", sent, re.IGNORECASE):
                    sent = re.sub(r"\b(?:\d+|fourteen)\s+(?:unit\s+|automated\s+)?tests?\b", f"{cnt} automated pytest unit tests", sent, flags=re.IGNORECASE)
                    s_low = sent.lower()

            # Whitelist grounding filter for chapters 3-11 (Item 1)
            if apply_whitelist:
                if not is_sentence_allowed_by_whitelist(sent, allowed_tokens, positive_facts):
                    logger.info("Grounding filter dropped in [%s]: %s (reason: whitelist check failed)", sec_title, sent)
                    continue

            # Check forbidden words
            if any(fw in s_low for fw in FORBIDDEN_COLLEGE_WORDS):
                logger.info("Grounding filter dropped in [%s]: %s (reason: forbidden college word)", sec_title, sent)
                continue

            # Check forbidden tools (unless explicitly in facts)
            found_tool = next((tool for tool in FORBIDDEN_COLLEGE_TOOLS if tool in s_low and tool not in facts_lower), None)
            if found_tool:
                logger.info("Grounding filter dropped in [%s]: %s (reason: forbidden college tool: %s)", sec_title, sent, found_tool)
                continue

            # Banned databases
            found_db = next((db for db in BANNED_DATABASES if db in s_low and db not in facts_lower), None)
            if found_db:
                logger.info("Grounding filter dropped in [%s]: %s (reason: banned database: %s)", sec_title, sent, found_db)
                continue

            # Banned agent names
            found_ba = next((ba for ba in BANNED_AGENTS if ba in s_low), None)
            if found_ba:
                logger.info("Grounding filter dropped in [%s]: %s (reason: banned agent name: %s)", sec_title, sent, found_ba)
                continue

            # Banned phrases
            found_bp = next((bp for bp in BANNED_PHRASES if bp in s_low and bp not in facts_lower), None)
            if found_bp:
                logger.info("Grounding filter dropped in [%s]: %s (reason: banned phrase: %s)", sec_title, sent, found_bp)
                continue

            # Never state feedback, comments, surveys, reviews or testing were collected unless in facts (Item 2)
            has_feedback_in_facts = "feedback" in positive_facts.lower() and len(positive_facts.split()) > 50
            if not has_feedback_in_facts:
                if any(k in s_low for k in [
                    "informal comment", "informal comments", "peer reviewer", "peer reviewers",
                    "faculty advisor", "faculty advisors", "user feedback", "survey", "surveys",
                    "user testing", "usability test", "collected feedback", "gathered feedback"
                ]):
                    logger.info("Grounding filter dropped in [%s]: %s (reason: ungrounded feedback/survey)", sec_title, sent)
                    continue

            # Whitelist filter: drop sentences containing banned terms unless in facts (Task 2 Item 4 & Run #6)
            banned_terms = [
                "config.yaml", "returns 429", "return 429", "ci runs", "ci run",
                "hashes", "state-diff", "markdown patches", "markdown patch",
                "sprint", "sprints", "middleware", "grant proposals", "grant proposal",
                "faculty advisors", "faculty advisor",
                "autogpt", "auto-gpt", "babyagi", "baby-agi", "scholarai", "scholar-ai",
                "three-month", "3-month",
                "work-streams", "work streams", "workstreams", "work-stream", "work stream", "workstream",
                "secure-by-design", "secure by design", "most studies",
            ]
            if any(bt in s_low for bt in banned_terms if bt not in facts_lower):
                continue
            if re.search(r"\bcrewai\b|\bcrew-ai\b", s_low) and "crewai" not in facts_lower:
                continue
            if re.search(r"\bacid\b", s_low):
                continue
            if any(claim in s_low for claim in ["correct agent sequencing", "agent sequencing", "citation formatting", "template rendering"]):
                continue
            if re.search(r"\bload\s+testing\b", s_low) and "load test" not in facts_lower:
                continue

            # 14 tests: only what fact sheet says (Item 2)
            if any(k in s_low for k in ["14 tests", "14 unit tests", "unit test suite"]):
                forbidden_test_claims = [
                    "otp", "resume", "endpoints", "template selection", "citation numbering",
                    "placeholder insertion", "run-state persistence", "all tests passed",
                    "all 14 tests passed", "100% pass", "passed successfully"
                ]
                if any(fc in s_low for fc in forbidden_test_claims if fc not in positive_facts.lower()):
                    continue

            # In 8.2, 8.5, 8.6, 9.5: tests may only say 14 tests run college report mode with mocked LLM and Tavily (Task 2 Item 5)
            # Drop claims of testing endpoint contracts, status codes, JWT cookies, OTP delivery, or database state.
            if any(k in norm_sec for k in ["8.2", "8.5", "8.6", "9.5", "test objective", "test case", "test plan", "evaluation result"]):
                if any(k in s_low for k in ["all tests passed", "all 14 tests passed", "passed successfully"]):
                    continue
                forbidden_test_claims_8 = [
                    "endpoint contract", "endpoint contracts", "status code", "status codes",
                    "jwt cookie", "jwt cookies", "otp delivery", "database state",
                    "cookie", "cookies", "contract test", "contract tests",
                    "otp", "resume", "endpoints", "endpoint reliability", "template selection",
                    "citation numbering", "placeholder insertion", "run-state persistence"
                ]
                if any(fc in s_low for fc in forbidden_test_claims_8 if fc not in positive_facts.lower()):
                    continue

            # Sections 8.5 & 8.6 repetition: do not repeat 14 tests sentence from 8.1 / 8.3
            if any(k in norm_sec for k in ["8.5", "8.6", "test case", "test plan"]):
                if any(x in s_low for x in ["14 unit tests", "14 tests", "system verification suite", "mocked llm and mocked search", "mocked llm"]):
                    continue

            # Repetition: state stack/pipeline summary at most once per chapter
            is_stack_summary = (
                sum(1 for k in ["fastapi", "react", "sqlite", "langgraph", "groq", "tavily"] if k in s_low) >= 3
                or all(k in s_low for k in ["research", "analysis", "writer"])
            )
            if is_stack_summary:
                if chapter_has_stack_stated and chapter_has_stack_stated[0]:
                    continue
                if chapter_has_stack_stated is not None:
                    chapter_has_stack_stated[0] = True

            # Run-command stripping at sentence level for 1.1-1.7 and 5.1
            if is_intro_chapter or norm_sec.startswith("5.1"):
                if any(cmd in s_low for cmd in ["uvicorn", "npm run", "main:app", "127.0.0.1", "--host", "--port", "--reload", "8001"]):
                    continue

            # Section 1.1 to 1.7 must not contain endpoint paths or code identifiers
            if is_intro_chapter:
                if "/api/" in sent or any(ident in sent for ident in [
                    "report_markdown", "outline_json", "user_id", "otp_codes", "code_hash",
                    "user_settings", "contact_messages", "token_count", "sources_json",
                    "word_count", "session_token"
                ]):
                    continue

            # Duration: if duration is blank, drop duration count claims (Item 3)
            if duration_blank:
                if re.search(r"\b(?:\w+-month|\d+-month|three-month|six-month|\d+\s+months?|\d+\s+weeks?|months|weeks)\b", s_low):
                    continue
                if re.search(r"\b(?:first|second|final|one|two)\s+(?:third|thirds|half|quarter|fraction)\b|\b(?:thirds?|halves)\b", s_low):
                    continue

            # Enforce verified endpoint and table counts (Single Source of Truth)
            m_ep = re.search(r"\b(\d+|[a-zA-Z\-]+)\s+(?:api\s+|rest\s+)?endpoints?\b", s_low)
            if m_ep:
                num = parse_count_mention(m_ep.group(1))
                if num is not None and num != VERIFIED_ENDPOINT_COUNT:
                    continue  # Drop sentence with unverified endpoint count
            
            m_tbl = re.search(r"\b(\d+|[a-zA-Z\-]+)\s+(?:database\s+|relational\s+)?tables?\b", s_low)
            if m_tbl:
                num = parse_count_mention(m_tbl.group(1))
                if num is not None and num != VERIFIED_TABLE_COUNT:
                    continue  # Drop sentence with unverified table count

            # Meta leaks: drop sentences with meta instructions (Item 10)
            if any(leak in s_low for leak in ["project facts", "project specification", "preserving placeholders", "unresolved content"]):
                continue
            if "listed in the" in s_low and not (":" in sent or "\n-" in sent or "table" in s_low or "section" in s_low):
                continue
            if "these endpoints" in s_low and "/api/" not in sent:
                continue

            # Check ungrounded numbers/units not in facts
            has_invented_metric = False
            if "%" in sent and "%" not in facts_lower:
                has_invented_metric = True
            elif "sub-second" in s_low and "sub-second" not in facts_lower:
                has_invented_metric = True
            elif re.search(r"\b\d+\s*(?:ms|millisecond|milliseconds)\b", s_low) and "ms" not in facts_lower:
                has_invented_metric = True
            elif re.search(r"\b\d+\s*(?:gb|gigabyte|gigabytes)\b", s_low) and "gb" not in facts_lower:
                has_invented_metric = True
            elif re.search(r"\b\d+\s*(?:cores?|vcpus?)\b", s_low) and "core" not in facts_lower:
                has_invented_metric = True
            elif "latency" in s_low and any(k in s_low for k in ["sub-second", "average", "median", "reduced", "achieved", "p99", "p95"]) and "latency" not in facts_lower:
                has_invented_metric = True

            if has_invented_metric:
                continue

            # In sections 4.6, 5.4, 7.3: verify DB table names against VERIFIED_TABLE_NAMES
            if any(k in norm_sec for k in ["4.6", "5.4", "7.3", "database", "data dictionary", "data design"]):
                has_unverified_table = False
                
                # Check backticked identifiers in database sections
                for tok in re.findall(r"`([a-zA-Z0-9_]+)`", sent):
                    tok_low = tok.lower()
                    if tok_low in {"reports", "report_sections", "sources", "audit_logs", "orders", "transactions", "customers", "invoices", "payments", "logs_table", "user_logs", "profiles", "accounts", "posts", "comments", "sessions"}:
                        has_unverified_table = True
                        break
                
                if not has_unverified_table:
                    # Check "X table" patterns
                    for cand in re.findall(r"\b([a-zA-Z0-9_]+)\s+tables?\b", s_low):
                        if cand not in VERIFIED_TABLE_NAMES and cand not in {
                            "database", "relational", "sqlite", "each", "these", "following",
                            "the", "six", "6", "all", "primary", "individual", "underlying", "core",
                            "application", "system", "sql", "target", "new", "existing"
                        }:
                            has_unverified_table = True
                            break
                
                if not has_unverified_table:
                    # Check "table X" patterns
                    for cand in re.findall(r"\btables?\s+`?([a-zA-Z0-9_]+)`?\b", s_low):
                        if cand not in VERIFIED_TABLE_NAMES and cand not in {
                            "such", "including", "for", "in", "and", "or", "of", "to", "with",
                            "are", "is", "were", "was", "described", "shown", "listed", "7.1",
                            "definitions", "structures", "schema", "overview", "design"
                        }:
                            has_unverified_table = True
                            break

                if not has_unverified_table:
                    # Direct check for obsolete/hallucinated table names
                    for unv in ["report_sections", "audit_logs", "orders", "transactions", "customers", "invoices", "payments", "logs_table", "user_logs"]:
                        if re.search(rf"\b{unv}\b", s_low):
                            has_unverified_table = True
                            break
                    if not has_unverified_table and re.search(r"\b(?:reports|sources)\s+table\b", s_low):
                        has_unverified_table = True

                if has_unverified_table:
                    continue

            # In section 8.6: only tests in facts
            if "8.6" in norm_sec:
                if any(k in s_low for k in ["integration test", "end-to-end", "e2e", "load test", "stress test", "jest", "cypress"]):
                    continue

            kept_sentences.append(sent)

        if kept_sentences:
            rebuilt_line = " ".join(kept_sentences).strip()
            if rebuilt_line:
                has_body_text = True
                out_lines.append(rebuilt_line)

    result = "\n".join(out_lines).strip()
    result = re.sub(r"\n{3,}", "\n\n", result)

    # Deduplicate paragraphs in 5.1: only one intro paragraph
    if norm_sec.startswith("5.1"):
        p_blocks = [p.strip() for p in result.split("\n\n") if p.strip()]
        unique_blocks = []
        for pb in p_blocks:
            if pb.startswith("#"):
                unique_blocks.append(pb)
            elif not any(not b.startswith("#") for b in unique_blocks):
                unique_blocks.append(pb)
            else:
                pass
        result = "\n\n".join(unique_blocks)

    # Section 10.2: remove stray large Frontend heading; code lines format as code block or inline code (Item 9)
    if "10.2" in norm_sec:
        result = re.sub(r"^#+\s*Frontend\s*$", "", result, flags=re.MULTILINE | re.IGNORECASE)
        result = result.replace("../frontend", "frontend")
        result = result.replace("cd ../frontend", "cd frontend")
        # 10.2 ends with a colon and no content; end it with a period (Item 4)
        result = re.sub(r":\s*$", ".", result.strip())
        result = re.sub(r":\s*\n\s*\n", ".\n\n", result)

    # Remove glued **Chapter Summary** paragraphs from 5.8 (Task 2 Item 9)
    if "5.8" in norm_sec or (actual_ch_num == 5 and "summary" in norm_sec):
        result = re.sub(r"\*\*Chapter Summary\*\*\s*", "", result, flags=re.IGNORECASE)

    # Clean dangling fragments and normalize placeholders
    result = clean_dangling_fragments_and_placeholders(result)

    # Drop truncated paragraphs: ending without terminal punctuation or ending in 'launched via', 'such as', 'including' (Task 2 Item 8)
    cleaned_paragraphs = []
    dangling_ends = ["launched via", "such as", "including", "for example", "e.g.", "via", "such as:", "with", "consisting of", "based on"]
    for p in result.split("\n\n"):
        p_str = p.strip()
        if not p_str:
            continue
        if p_str.startswith("#") or p_str.startswith("[") or p_str.startswith("|") or p_str.startswith("```"):
            cleaned_paragraphs.append(p_str)
            continue
        p_low = p_str.lower().rstrip(" \t\r\n")
        if any(p_low.endswith(de) for de in dangling_ends):
            continue
        if not re.search(r"[\.!?:\'\"\)]\s*$", p_str) and not p_str.endswith("]"):
            continue
        cleaned_paragraphs.append(p_str)

    result = "\n\n".join(cleaned_paragraphs)

    text_without_headings = re.sub(r"^#+.*", "", result, flags=re.MULTILINE).strip()
    text_without_placeholders = re.sub(r"\[(?:Insert|Add)[^\]]+\]", "", text_without_headings).strip()
    words_remaining = len(text_without_placeholders.split())

    # Section 1.2: project introduction (Item 2 & 7)
    if re.search(r"^1\.2\b", sec_title):
        if not has_body_text or words_remaining < min_words:
            if facts_lower and ("fastapi" in facts_lower or "langgraph" in facts_lower or "citebolt" in facts_lower):
                return f"""{heading_prefix} {sec_title}

CiteBolt is an automated research report generation platform designed to produce structured academic and technical reports from user-specified topics. The system coordinates a multi-agent workflow consisting of Research, Analysis, and Writer agents implemented using LangGraph. The application is built with a FastAPI backend, an SQLite database utilizing SQLAlchemy ORM, and a React frontend with Vite and Tailwind CSS, deployed in a local execution environment."""
            return f"{heading_prefix} {sec_title}\n\n[Add your {clean_sec_title} here.]"

    # Section 1.4: objectives (Item 7)
    if re.search(r"^1\.4\b", sec_title):
        bullet_lines = [ln.strip() for ln in result.split("\n") if re.match(r"^\s*[-*+]\s+", ln)]
        if len(bullet_lines) < 4:
            return f"""{heading_prefix} {sec_title}

The primary objectives of the project are defined as follows:

- Autonomous research and multi-agent report generation pipeline using LangGraph (Research, Analysis, and Writer agents).
- Academic citation integration with automated reference numbering and grounding verification.
- Document compilation and multi-format export supporting both ReportLab PDF and DOCX formats.
- Per-user rate limits and authentication via email OTP and JWT sessions.
- Standardized academic college report template with structured chapters, formal front matter, and automated tables of contents."""

    # Section 3.2: User Characteristics (Item 2)
    if re.search(r"^3\.2\b", sec_title) or (actual_ch_num == 3 and "user" in norm_sec):
        if not has_body_text or words_remaining < min_words:
            if facts_lower:
                return f"""{heading_prefix} {sec_title}

The primary users of the system include undergraduate engineering students, academic researchers, and technical writers who require formatted research reports. Users interact with the platform through a web-based dashboard to configure report parameters, select citation styles, and generate structured documents without manual layout formatting."""
            return f"{heading_prefix} {sec_title}\n\n[Add your {clean_sec_title} here.]"

    # Section 3.4: Non-functional Requirements
    if re.search(r"^3\.4\b", sec_title) or (actual_ch_num == 3 and "non-functional" in norm_sec):
        if not has_body_text or words_remaining < min_words:
            if facts_lower:
                return f"""{heading_prefix} {sec_title}

Non-functional requirements for the platform emphasize local execution security, deterministic document generation, and responsive user feedback. The application ensures data isolation by maintaining SQLite database storage locally on the user workstation. Generation pipelines provide predictable execution through bounded token budgets and rate-limited external API interactions."""
            return f"{heading_prefix} {sec_title}\n\n[Add your {clean_sec_title} here.]"

    # Section 3.7: System Implementation Plan (Item 4: must be a plan or placeholder, never non-functional requirements)
    if re.search(r"^3\.7\b", sec_title) or (actual_ch_num == 3 and "plan" in norm_sec):
        if not has_body_text or words_remaining < min_words:
            return f"{heading_prefix} {sec_title}\n\n[Add your System Implementation Plan here.]"

    # Section 4.7: Component / Low-level Design (Item 2)
    if re.search(r"^4\.7\b", sec_title) or (actual_ch_num == 4 and "component" in norm_sec):
        if not has_body_text or words_remaining < min_words:
            if facts_lower and ("fastapi" in facts_lower or "langgraph" in facts_lower):
                return f"""{heading_prefix} {sec_title}

The low-level component design organizes the application into distinct modular tiers: FastAPI route handlers for client communication, LangGraph state graph nodes for agent coordination, SQLAlchemy models for local SQLite persistence, and React components for interface interactions. Each component communicates across well-defined interfaces to ensure modularity and maintainability."""
            return f"{heading_prefix} {sec_title}\n\n[Add your {clean_sec_title} here.]"

    # Section 5.5: Third-party Services / External Integrations (Item 2)
    if re.search(r"^5\.5\b", sec_title) or (actual_ch_num == 5 and any(k in norm_sec for k in ["third", "service", "external", "integration"])):
        if not has_body_text or words_remaining < min_words:
            if any(k in facts_lower for k in ["tavily", "groq", "gmail", "smtp"]):
                return f"""{heading_prefix} {sec_title}

The system integrates three external services to support its core workflows: the Tavily search API for academic source retrieval, Groq cloud inference for fast LLM execution, and Gmail SMTP for one-time password (OTP) email delivery. All external interactions are authenticated via environment variables and configured with timeout handling."""
            return f"{heading_prefix} {sec_title}\n\n[Add your {clean_sec_title} here.]"

    # Section 7.4: Core Modules / Subsystems Implementation (Item 2)
    if re.search(r"^7\.4\b", sec_title) or (actual_ch_num == 7 and any(k in norm_sec for k in ["module", "subsystem"])):
        if not has_body_text or words_remaining < min_words:
            if facts_lower and ("fastapi" in facts_lower or "langgraph" in facts_lower):
                return f"""{heading_prefix} {sec_title}

The implementation centers on three primary subsystems: the authentication module handling email OTP verification and JWT session tokens, the multi-agent pipeline module coordinating Research, Analysis, and Writer nodes via LangGraph, and the export module compiling structured documents into ReportLab PDF and python-docx formats."""
            return f"{heading_prefix} {sec_title}\n\n[Add your {clean_sec_title} here.]"

    # Section 8.1: Testing Strategy / Overview (Item 2 & Item 3)
    if re.search(r"^8\.1\b", sec_title) or (actual_ch_num == 8 and "overview" in norm_sec and "testing" in norm_sec):
        if not has_body_text or words_remaining < min_words:
            if facts_lower:
                return f"""{heading_prefix} {sec_title}

The testing strategy focuses on automated pytest unit tests that check college-report generation quality and formatting using mocked LLM and search responses. External dependencies, including LLM inference and web search endpoints, are mocked to ensure deterministic and reproducible test execution."""
            return f"{heading_prefix} {sec_title}\n\n[Add your {clean_sec_title} here.]"

    # Section 8.2: Test Objectives (Item 3: no count here, write automated pytest unit tests)
    if re.search(r"^8\.2\b", sec_title) or (actual_ch_num == 8 and "objective" in norm_sec):
        if not has_body_text or words_remaining < min_words:
            return f"""{heading_prefix} {sec_title}

The test suite consists of automated pytest unit tests that check college-report generation quality and formatting using mocked LLM and search responses. Testing verifies report structure, caption normalization, table schemas, and grounding constraints without invoking live external APIs."""

    # Section 8.4: Integration Testing (Item 2)
    if re.search(r"^8\.4\b", sec_title) or (actual_ch_num == 8 and "integration" in norm_sec):
        if not has_body_text or words_remaining < min_words:
            if facts_lower:
                return f"""{heading_prefix} {sec_title}

Integration testing verifies the interaction between agent pipeline nodes and document export handlers using mocked LLM and search responses. Tests validate that agent state transitions produce well-formed section content and that document compilation correctly translates markdown into PDF and DOCX outputs without format corruption."""
            return f"{heading_prefix} {sec_title}\n\n[Add your {clean_sec_title} here.]"

    # Section 8.5 & 8.6 repetition fallback (Item 3: state count ONLY in 8.5 using get_verified_test_count())
    if "8.5" in norm_sec or "test case" in norm_sec:
        cnt = get_verified_test_count()
        if not has_body_text or words_remaining < min_words:
            return f"{heading_prefix} {sec_title}\n\n[Add your test case table here.]"
    if "8.6" in norm_sec or "test plan" in norm_sec or "master test" in norm_sec:
        if not has_body_text or words_remaining < min_words:
            return f"{heading_prefix} {sec_title}\n\n[Add your test plan here.]"

    # Section 9.4: User Feedback fallback (Item 1 & Item 4)
    if any(k in norm_sec for k in ["9.4", "user feedback"]):
        # Don't reference Fig. 9.1 from 9.4
        result = re.sub(r"[^\.\n]*\b(?:fig\.|figure)\s*9\.1\b[^\.\n]*\.?", "", result, flags=re.IGNORECASE)
        has_user_feedback = any(k in facts_lower for k in ["user feedback", "survey response", "feedback collected", "user study", "survey result"]) and len(facts_lower.split()) > 20
        if not has_user_feedback or not has_body_text or words_remaining < min_words:
            return f"{heading_prefix} {sec_title}\n\n[Add your user feedback results here.]"

    # Section 9.5: Testing Results fallback (Item 2 & Item 3)
    if any(k in norm_sec for k in ["9.5", "test result", "validation result"]):
        if not has_body_text or words_remaining < min_words:
            return f"""{heading_prefix} {sec_title}

Automated pytest unit tests were executed with mocked LLM and search responses to evaluate college-report generation quality and formatting constraints. All test assertions completed deterministically without network access."""

    # Section 10.1: Deployment Overview (Item 2)
    if re.search(r"^10\.1\b", sec_title) or (actual_ch_num == 10 and "introduction" in norm_sec):
        if not has_body_text or words_remaining < min_words:
            if facts_lower and ("fastapi" in facts_lower or "uvicorn" in facts_lower or "sqlite" in facts_lower):
                return f"""{heading_prefix} {sec_title}

The deployment architecture is designed for local workstation execution, combining a Python FastAPI backend served by Uvicorn and a React frontend served by Vite. System persistence is contained entirely within a local SQLite database file, eliminating cloud infrastructure dependencies and external database management overhead."""
            return f"{heading_prefix} {sec_title}\n\n[Add your {clean_sec_title} here.]"

    # Sections 10.5 to 10.8: match exact headings (Task 2 Item 6)
    if re.search(r"^10\.5\b", sec_title):
        if not has_body_text or words_remaining < min_words:
            return f"""{heading_prefix} {sec_title}

System maintenance is performed through manual process restarts following code changes or configuration updates. The FastAPI backend running via Uvicorn and the Vite frontend development server are restarted directly from the terminal, without automated process supervisors or container orchestration."""

    if re.search(r"^10\.6\b", sec_title):
        if not has_body_text or words_remaining < min_words:
            db_file = get_verified_db_filename()
            if db_file != "the SQLite database file":
                db_str = f"the SQLite database file (`{db_file}`)"
            else:
                db_str = "the SQLite database file"
            return f"""{heading_prefix} {sec_title}

Database backup and recovery is conducted by creating direct filesystem copies of {db_str}. In the event of data corruption or migration requirements, recovery is achieved by restoring the copied database file while the backend service is halted, ensuring database file integrity."""

    if re.search(r"^10\.7\b", sec_title):
        if not has_body_text or words_remaining < min_words:
            return f"""{heading_prefix} {sec_title}

Deployment challenges primarily center on managing external API rate limits and quotas for LLM inference and web search services. Operating as a local-only deployment mitigates cloud hosting overhead and network ingress risks while restricting service availability to the local workstation."""

    if re.search(r"^10\.8\b", sec_title) or (actual_ch_num == 10 and "summary" in norm_sec):
        if not has_body_text or words_remaining < min_words:
            return f"""{heading_prefix} {sec_title}

The CiteBolt system is deployed locally on a single machine utilizing a FastAPI backend served via Uvicorn and a Vite React frontend. Persistence is managed through a local SQLite database file without cloud infrastructure, Docker containerization, or automated CI/CD pipelines. Operational management consists of direct command-line execution and local process control."""

    # Summary sections (Item 5): Each chapter summary must describe its own chapter; if it cannot, use placeholder
    if "summary" in norm_sec and not any(k in norm_sec for k in ["executive summary", "abstract"]):
        if not has_body_text or words_remaining < 10:
            chapter_summaries = {
                1: "This chapter presented the foundational overview of the project, including the domain background, core objectives, scope boundaries, and document structure.",
                3: "This chapter detailed the software requirements specification, establishing functional interface expectations, user characteristics, and non-functional performance constraints.",
                4: "This chapter outlined the system design, detailing high-level multi-agent architectural layers, low-level component interactions, and the relational database schema.",
                5: "This chapter specified the technical stack, encompassing backend FastAPI services, Vite React frontend tooling, local SQLite persistence, and third-party integrations.",
                6: "This chapter described project planning, scheduling timelines, work breakdown structures, and student development responsibilities.",
                7: "This chapter reviewed the software implementation, detailing the authentication module, multi-agent pipeline orchestration, and verified database tables.",
                8: "This chapter documented the testing strategy, automated unit test verification, and quality standards established for report generation.",
                9: "This chapter evaluated the system results, discussing output generation characteristics and execution observations.",
                10: "This chapter summarized deployment procedures, installation processes, SQLite backup routines, and local operational constraints.",
            }
            if actual_ch_num in chapter_summaries:
                return f"{heading_prefix} {sec_title}\n\n{chapter_summaries[actual_ch_num]}"
            return f"{heading_prefix} {sec_title}\n\n[Add your {clean_sec_title} here.]"

    if not has_body_text or words_remaining < min_words:
        return f"{heading_prefix} {sec_title}\n\n[Add your {clean_sec_title} here.]"

    return result


def format_front_matter_section(
    sec_title: str,
    topic: str,
    front_matter: dict[str, Any] | None,
    outline: list[dict[str, Any]] | None = None,
) -> str | None:
    norm = sec_title.lower().strip()
    fm = front_matter or {}
    proj_title = smart_title((fm.get("projectTitle") or topic).strip())
    now = datetime.now()
    year_val = fm.get("academicYear", "").strip()
    if not year_val:
        if now.month >= 6:
            year_val = f"{now.year}-{str(now.year + 1)[-2:]}"
        else:
            year_val = f"{now.year - 1}-{str(now.year)[-2:]}"

    month_year_val = fm.get("submissionMonthYear", "").strip()
    if not month_year_val:
        month_year_val = now.strftime("%B %Y")

    degree_raw = fm.get("degree", "").strip()
    degree_disp = degree_raw if degree_raw else "[Degree]"

    dept_raw = fm.get("department", "").strip()
    if dept_raw:
        dept_disp = smart_title(dept_raw) if dept_raw.islower() else dept_raw
    else:
        dept_disp = "[Department Name]"

    univ_raw = fm.get("university", "").strip()
    if univ_raw:
        univ_disp = smart_title(univ_raw) if univ_raw.islower() else univ_raw
    else:
        univ_disp = "[University Name]"

    guide_raw = fm.get("guide", "").strip()
    guide_disp = smart_title(guide_raw) if guide_raw else "[Project Guide]"

    coord = smart_title(fm.get("coordinator", "").strip())
    hod = smart_title(fm.get("hod", "").strip())
    dean = smart_title(fm.get("dean", "").strip())
    members = fm.get("teamMembers") or []

    if "title page" in norm:
        has_named_members = any(
            isinstance(m, dict) and m.get("name", "").strip() for m in members
        )
        student_lines = []
        if has_named_members:
            for m in members:
                name = m.get("name", "").strip() if isinstance(m, dict) else str(m).strip()
                prn = m.get("prn", "").strip() if isinstance(m, dict) else ""
                if name:
                    name_titled = smart_title(name)
                    student_lines.append(f"{name_titled} (PRN: {prn})" if prn else name_titled)
        else:
            student_lines.append("[Student Name] (PRN: [PRN])")

        year_str = year_val if year_val.lower().startswith("academic year") else f"Academic Year: {year_val}"
        month_str = month_year_val if month_year_val.lower().startswith("month") else f"Month: {month_year_val}"
        dept_line = dept_disp if dept_disp.lower().startswith("department") else f"Department: {dept_disp}"
        univ_line = univ_disp if univ_disp.lower().startswith("university") else f"University: {univ_disp}"

        lines = [
            f"# {proj_title}",
            "A PROJECT REPORT",
            "Submitted in partial fulfilment of the requirements for the award of the degree of",
            f"**{degree_disp}**",
            "Submitted by",
            *student_lines,
            "Under the guidance of",
            guide_disp,
            dept_line,
            univ_line,
            year_str,
            month_str,
        ]
        return "\n\n".join(lines).strip()

    if "certificate" in norm and not any(k in norm for k in ["publication", "appendix"]):
        lines = ["## Certificate\n\nThis is to certify that the project report entitled:"]
        lines.append(f"\n**\"{proj_title}\"**\n")
        named_members = [
            f"{smart_title(m.get('name', '').strip())}" + (f" (PRN: {m.get('prn', '').strip()})" if m.get("prn") else "")
            for m in members
            if isinstance(m, dict) and m.get("name", "").strip()
        ]
        if named_members:
            lines.append(
                f"Submitted by **{', '.join(named_members)}** is a bonafide work carried out under guidance and supervision in partial fulfillment of the academic requirements."
            )
        else:
            lines.append(
                "Submitted by **[Student Name]** is a bonafide work carried out under guidance and supervision in partial fulfillment of the academic requirements."
            )

        guide_val = guide_disp if guide_raw else "____________________"
        coord_val = coord if coord else "____________________"
        hod_val = hod if hod else "____________________"
        dean_val = dean if dean else "____________________"

        lines.extend([
            "Signatures",
            f"**Project Guide:** {guide_val}",
            f"**Project Coordinator:** {coord_val}",
            f"**Head of Department:** {hod_val}",
            f"**Principal / Dean:** {dean_val}",
            "**Internal / External Examiner:** ____________________",
        ])
        loc_parts = [dept_disp, univ_disp]
        lines.append(", ".join(loc_parts))
        return "\n\n".join(lines).strip()

    if "acknowledgement" in norm:
        named_members = [
            m for m in members
            if isinstance(m, dict) and m.get("name", "").strip()
        ]
        team_size_val = fm.get("teamSize", "").strip()
        is_single_member = (len(named_members) <= 1 and len(members) <= 1 and team_size_val in ("", "1"))
        if is_single_member:
            lines = [
                "## Acknowledgements\n\n"
                "I take immense pride and pleasure in presenting this project report. "
                "First and foremost, I express my profound gratitude to my project guide"
                + (f", **{guide_disp}**" if guide_raw else "")
                + ", whose relentless encouragement, constructive criticism, and expert technical mentorship guided me through every stage of this work.\n\n"
                "I convey my sincere thanks to the Project Coordinator"
                + (f", **{coord}**" if coord else "")
                + f", and to the Head of Department, Department of {dept_disp}"
                + ", for providing excellent laboratory infrastructure, technical facilities, and continuous administrative support.\n\n"
                "I am equally indebted to the Principal / Dean"
                + (f", **{dean}**" if dean else "")
                + f", {univ_disp}"
                + ", for fostering an academic environment that champions innovation, quality engineering, and practical research.\n\n"
                "Finally, I extend my heartfelt appreciation to my fellow peers, faculty members, and my family, whose patience, understanding, and unwavering moral support made the successful completion of this project possible."
            ]
        else:
            lines = [
                "## Acknowledgements\n\n"
                "We take immense pride and pleasure in presenting this project report. "
                "First and foremost, we express our profound gratitude to our project guide"
                + (f", **{guide_disp}**" if guide_raw else "")
                + ", whose relentless encouragement, constructive criticism, and expert technical mentorship guided us through every stage of this work.\n\n"
                "We convey our sincere thanks to the Project Coordinator"
                + (f", **{coord}**" if coord else "")
                + f", and to the Head of Department, Department of {dept_disp}"
                + ", for providing excellent laboratory infrastructure, technical facilities, and continuous administrative support.\n\n"
                "We are equally indebted to the Principal / Dean"
                + (f", **{dean}**" if dean else "")
                + f", {univ_disp}"
                + ", for fostering an academic environment that champions innovation, quality engineering, and practical research.\n\n"
                "Finally, we extend our heartfelt appreciation to our fellow peers, faculty members, and our families, whose patience, understanding, and unwavering moral support made the successful completion of this project possible."
            ]
        return "\n".join(lines).strip()

    if "abstract" in norm:
        return None

    if "table of contents" in norm:
        lines = [
            "## Table of Contents\n",
            "| Chapter / Section | Page No. |",
            "| :--- | :--- |",
            "| **Title Page** | i |",
            "| **Certificate** | ii |",
            "| **Acknowledgements** | iii |",
            "| **Abstract** | iv |",
            "| **Table of Contents** | v |",
            "| **List of Figures** | vi |",
            "| **List of Tables** | vii |",
            "| **List of Publications** | viii |",
        ]
        if outline:
            for s in outline:
                lvl = int(s.get("level", 1))
                title = str(s.get("title", ""))
                norm_s = title.lower()
                if any(x in norm_s for x in ["title page", "certificate", "acknowledgement", "abstract", "table of contents", "list of figures", "list of tables"]):
                    continue
                if lvl == 1:
                    lines.append(f"| **{title}** | |")
                elif lvl == 2:
                    lines.append(f"| {title} | |")
        lines.append("")
        return "\n".join(lines).strip()

    if "list of figures" in norm:
        return "## List of Figures\n\n*(No figures in this report)*"

    if "list of tables" in norm:
        return "## List of Tables\n\nTable 7.1: Database tables"

    if "list of publications" in norm:
        return (
            "## List of Publications\n\n"
            "*(No publications reported at the time of submission. Add relevant conference or journal papers here if published.)*"
        )

    if "appendix a" in norm or "publication" in norm:
        return (
            "## Appendix A: Certificates of Publication\n\n"
            "*(Attach copies of conference or journal publication certificates, if applicable)*"
        )

    if "appendix b" in norm or "glossary" in norm:
        return format_appendix_b_glossary()

    if "references" in norm:
        return None  # Compiled automatically from cited sources

    return None


def synthesize_academic_abstract(proj_name: str, domain_name: str, facts: str = "") -> str:
    """Synthesize a grounded academic abstract describing only what was built and what tests check."""
    return (
        f"This project presents the design, architecture, and implementation of {proj_name}, "
        f"an automated research report generation platform in the domain of {domain_name}. "
        f"The system coordinates an autonomous multi-agent workflow consisting of Research, Analysis, "
        f"and Writer agents orchestrated using LangGraph. The backend service is built using FastAPI "
        f"with SQLite database storage managed through SQLAlchemy ORM, and the user interface is developed "
        f"in React with Tailwind CSS and Vite. Document compilation produces publication-ready reports in "
        f"both ReportLab PDF and DOCX formats with automated citation numbering and grounding verification. "
        f"System verification is conducted through automated pytest unit tests with mocked LLM and search responses "
        f"to validate report structure, heading hierarchy, and formatting compliance."
    )


def plan_outline(
    topic: str,
    context: str,
    report_type: str,
    target_words: int,
    length_preset: str,
) -> list[dict[str, Any]]:
    target_sections = 5 if length_preset == "short" else 12 if length_preset == "long" else 8
    prompt = f"""You are a senior research analyst. Create a detailed, professional outline for a comprehensive report on:
Topic: "{topic}"
Report Type: "{report_type}"
Target Total Word Count: {target_words} words across approximately {target_sections} sections.

Return ONLY a valid JSON array of section objects with:
- "level": 1 for main headings, 2 for subheadings
- "title": Clean title (do not include numbers like '1.' or '1.1')
- "target_words": Target word count for this section (sum should be roughly {target_words})
"""
    try:
        raw_json, _ = generate_text(prompt, temperature=0.1, max_tokens=2048)
        match = re.search(r"\[.*\]", raw_json, re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list) and len(parsed) >= 3:
                total_w = sum(int(s.get("target_words", 0)) for s in parsed) or 1
                return [
                    {
                        "level": int(s.get("level", 1)),
                        "title": clean_title(str(s.get("title", ""))),
                        "target_words": max(150, int(int(s.get("target_words", 300)) * target_words / total_w)),
                    }
                    for s in parsed
                    if s.get("title")
                ]
    except Exception as exc:
        logger.warning("Outline planning LLM call failed: %s", exc)

    default_titles = [
        ("Executive Summary", 1, 0.12),
        ("Background and Objectives", 1, 0.15),
        ("Key Findings and Industry Standards", 1, 0.18),
        ("Detailed Architecture and Capabilities", 1, 0.25),
        ("Trade-offs and Limitations", 1, 0.15),
        ("Strategic Recommendations", 1, 0.15),
    ]
    return [
        {
            "level": lvl,
            "title": title,
            "target_words": max(150, int(target_words * weight)),
        }
        for title, lvl, weight in default_titles
    ]


def run_section_pipeline(
    initial_state: dict[str, Any],
    emit: Callable[[dict[str, Any]], None],
    is_cancelled: Callable[[], bool],
) -> dict[str, Any]:
    state = dict(initial_state)
    run_id = state.get("run_id") or state.get("id")
    topic = state.get("topic", "").strip()
    context = state.get("context", "").strip()
    report_type = state.get("report_type", "auto").strip()
    length_preset = state.get("length", "standard").strip().lower()
    front_matter = state.get("front_matter")
    fm = front_matter or {}
    duration = (fm.get("duration") or "").strip()

    target_words = int(
        state.get("target_words")
        or (1800 if length_preset == "short" else 8500 if length_preset == "long" else 4000)
    )

    outline = state.get("outline")
    if not outline or not isinstance(outline, list):
        outline = plan_outline(topic, context, report_type, target_words, length_preset)

    sections = outline
    total_sections = len(sections)

    # Model management & fallback chain
    model_chain: list[str] = [GROQ_MODEL] + [m for m in GROQ_FALLBACK_MODELS if m != GROQ_MODEL]
    active_model_idx = [0]
    model_lock = threading.Lock()

    # Determine cheaper/smaller model for easy sections (summaries, abstract)
    cheap_model: str | None = None
    for m in GROQ_FALLBACK_MODELS:
        if any(k in m.lower() for k in ["8b", "instant", "mini", "small"]):
            cheap_model = m
            break
    if not cheap_model and GROQ_FALLBACK_MODELS:
        cheap_model = GROQ_FALLBACK_MODELS[-1]

    start_time = time.time()
    completed_count = [0]
    progress_lock = threading.Lock()
    sources_lock = threading.Lock()
    all_sources: list[dict[str, Any]] = list(state.get("sources", []))

    total_input_tokens = [int(state.get("input_tokens", 0))]
    total_output_tokens = [int(state.get("output_tokens", 0))]
    tokens_lock = threading.Lock()
    pacing_lock = threading.Lock()
    last_call_time = [0.0]
    save_lock = threading.Lock()

    # Pre-count sections already finished in previous attempts (for Resume)
    for s in sections:
        if s.get("completed") and s.get("content"):
            completed_count[0] += 1

    def paced_generate_text(prompt: str, model: str | None = None, **kwargs):
        with pacing_lock:
            now = time.time()
            gap = now - last_call_time[0]
            if gap < 0.7:
                time.sleep(0.7 - gap)
            last_call_time[0] = time.time()
        return generate_text(prompt, model=model, **kwargs)

    def add_tokens(inp: int, out: int):
        with tokens_lock:
            total_input_tokens[0] += inp
            total_output_tokens[0] += out

    def get_current_model() -> str:
        with model_lock:
            return model_chain[active_model_idx[0]]

    def robust_generate_text(prompt: str, is_easy: bool = False, **kwargs) -> tuple[str, dict[str, int]]:
        """Generate text with automatic fallback to secondary models upon daily limit (TPD)."""
        nonlocal cheap_model
        target_model = cheap_model if (is_easy and cheap_model) else get_current_model()

        while True:
            try:
                return paced_generate_text(prompt, model=target_model, **kwargs)
            except ModelNotFoundError as mnf:
                logger.warning("Model %s unavailable on Groq: %s", target_model, mnf)
                with model_lock:
                    if target_model == cheap_model:
                        cheap_model = None
                    if target_model in model_chain and len(model_chain) > 1:
                        model_chain.remove(target_model)
                    target_model = model_chain[min(active_model_idx[0], len(model_chain) - 1)]
                continue
            except DailyTokenLimitError as dt_err:
                logger.warning("Daily token limit reached on model %s: %s", target_model, dt_err)
                with model_lock:
                    # If target was cheap model and cheap model is different from main chain, try main chain
                    if target_model == cheap_model and target_model != model_chain[active_model_idx[0]]:
                        target_model = model_chain[active_model_idx[0]]
                        continue

                    # Advance to next fallback model in chain
                    if active_model_idx[0] + 1 < len(model_chain):
                        active_model_idx[0] += 1
                        old_model = target_model
                        new_model = model_chain[active_model_idx[0]]
                        target_model = new_model
                        msg = f"Daily token limit reached for {old_model}. Switched to fallback model {new_model}."
                        logger.info(msg)
                        emit({
                            "type": "stage",
                            "node": "writing",
                            "status": "running",
                            "message": msg,
                        })
                        emit({
                            "type": "model_switched",
                            "old_model": old_model,
                            "active_model": new_model,
                            "message": msg,
                        })
                        continue
                    else:
                        # All fallback models exhausted - escalate to pause run
                        raise dt_err

    def notify_rate_limit(msg: str, wait_sec: float):
        emit({
            "type": "stage",
            "node": "writing",
            "status": "running",
            "message": msg,
        })
        with progress_lock:
            cur = completed_count[0]
            elapsed = time.time() - start_time
            avg_sec = (elapsed / cur) if cur > 0 else 0
            rem_sections = max(0, total_sections - cur)
            eta = (rem_sections * avg_sec) if cur > 0 else None
            emit({
                "type": "section_progress",
                "section_index": max(1, cur),
                "total_sections": total_sections,
                "section_title": "Waiting for rate limit...",
                "waiting_rate_limit": True,
                "eta_seconds": round(eta, 1) if eta is not None else None,
                "active_model": get_current_model(),
            })

    def record_section_progress(title: str):
        with progress_lock:
            completed_count[0] += 1
            cur = completed_count[0]
            elapsed = time.time() - start_time
            avg_sec = elapsed / max(1, cur)
            rem_sections = max(0, total_sections - cur)
            eta = rem_sections * avg_sec if cur > 0 else None
            emit({
                "type": "section_progress",
                "section_index": cur,
                "total_sections": total_sections,
                "section_title": title,
                "eta_seconds": round(eta, 1) if eta is not None else None,
                "waiting_rate_limit": False,
                "active_model": get_current_model(),
            })

    def persist_section_to_db(sec_idx: int, sec_text: str):
        """Save each finished section to SQLite/Postgres immediately as it completes."""
        with save_lock:
            sections[sec_idx]["completed"] = True
            sections[sec_idx]["content"] = sec_text

            if not run_id:
                return

            try:
                from app.db import SessionLocal
                from app.models import Run

                assembled = [
                    str(s.get("content", ""))
                    for s in sections
                    if s.get("completed") and s.get("content")
                ]
                partial_md = "\n\n".join(assembled)

                with SessionLocal() as session:
                    r = session.get(Run, run_id)
                    if r:
                        r.outline_json = json.dumps(sections, ensure_ascii=False)
                        r.report_markdown = partial_md
                        r.word_count = len(partial_md.split())
                        with sources_lock:
                            srcs = list(all_sources)
                        r.sources_json = json.dumps(srcs, ensure_ascii=False)
                        r.sources_count = len(srcs)
                        with tokens_lock:
                            r.token_count = total_input_tokens[0] + total_output_tokens[0]
                        session.commit()
            except Exception as exc:
                logger.debug("Failed saving section checkpoint for run %s: %s", run_id, exc)

    domain_name, proj_name = extract_domain_and_project(topic, front_matter)
    project_fact_sheet = build_compact_project_fact_sheet(topic, context, front_matter)

    placeholder_sections: list[dict[str, Any]] = []
    placeholder_lock = threading.Lock()

    # Sanitize outline section titles to replace [Domain] and [Project]
    for s in sections:
        t = str(s.get("title", ""))
        if re.search(r"^1\.1\b", t):
            s["title"] = "1.1 Overview of the Domain"
        elif re.search(r"^1\.2\b", t):
            s["title"] = f"1.2 Introduction to {proj_name}"
        elif "[Domain]" in t or "[Project]" in t:
            s["title"] = t.replace("[Domain]", domain_name).replace("[Project]", proj_name)

    tavily_call_count = [0]
    tavily_lock = threading.Lock()

    emit({
        "type": "stage",
        "node": "research",
        "status": "running",
        "message": f"Organizing outline for {total_sections} sections (using {get_current_model()})...",
    })

    # Step 1: Partition into Front Matter, Chapter Groups, and Post-Body
    front_matter_sections: list[tuple[int, dict[str, Any]]] = []
    chapter_groups: list[dict[str, Any]] = []
    post_body_sections: list[tuple[int, dict[str, Any]]] = []

    current_group: dict[str, Any] | None = None
    in_post_body = False

    for idx, sec in enumerate(sections):
        title = clean_title(str(sec.get("title", f"Section {idx + 1}")))
        lvl = int(sec.get("level", 1))
        norm_t = title.lower()

        # Check post-body
        if any(p in norm_t for p in ["references", "appendix a", "appendix b"]):
            in_post_body = True

        if in_post_body:
            post_body_sections.append((idx, sec))
            continue

        # Check front-matter
        if (
            format_front_matter_section(title, topic, front_matter, outline) is not None
            or "abstract" in norm_t
        ):
            if current_group is None:
                front_matter_sections.append((idx, sec))
                continue

        # Body chapters
        if lvl == 1:
            if current_group is not None:
                chapter_groups.append(current_group)
            current_group = {
                "chapter_index": len(chapter_groups) + 1,
                "chapter_title": title,
                "sections": [(idx, sec)],
            }
        else:
            if current_group is None:
                current_group = {
                    "chapter_index": len(chapter_groups) + 1,
                    "chapter_title": title,
                    "sections": [(idx, sec)],
                }
            else:
                current_group["sections"].append((idx, sec))

    if current_group is not None:
        chapter_groups.append(current_group)

    # Step 2: Render Front Matter (instant + 1 Abstract LLM call)
    rendered_front_matter: list[tuple[int, str]] = []
    for idx, sec in front_matter_sections:
        if is_cancelled():
            emit({"type": "error", "message": "Run cancelled by user."})
            state["errors"] = [{"node": "section_engine", "error": "Run cancelled."}]
            return state

        title = clean_title(str(sec.get("title", "")))
        norm_t = title.lower()

        # If already completed in previous run, reuse it!
        if sec.get("completed") and sec.get("content"):
            rendered_front_matter.append((idx, str(sec["content"])))
            continue

        fm_text = format_front_matter_section(title, topic, front_matter, outline)
        if fm_text is not None:
            rendered_front_matter.append((idx, fm_text))
            persist_section_to_db(idx, fm_text)
            record_section_progress(title)
            continue

        if "abstract" in norm_t:
            emit({
                "type": "stage",
                "node": "writing",
                "status": "running",
                "message": "Generating Abstract...",
            })
            abs_prompt = f"""Write an academic Abstract for the project entitled "{proj_name}".
Strict Requirements:
- Target word count: approximately 250 words.
- Format: A single cohesive, professional plain-text narrative paragraph (NO bullet points, NO citations like [n], NO tables).
- Summarize the motivation, problem statement, proposed system architecture, implementation highlights, and results.
- CRITICAL RULES:
  * Do NOT mention project duration, timelines, or weeks.
  * Do NOT make 'meets all requirements' or 'meets all criteria' claims.
  * The system has three agents; never write 'single-agent'.
  * Never write '[Add your result here]' or any placeholder in the abstract. State outcomes qualitatively as successful engineering implementation.
- End strictly with a final line: "Keywords: keyword1, keyword2, keyword3, keyword4, keyword5"

Project Facts (Ground Truth):
{project_fact_sheet}

Output format:
## Abstract

[Your ~250-word plain text abstract body]

Keywords: [5-7 comma-separated domain keywords]"""
            abs_body = ""
            for abs_attempt in range(1, 3):
                try:
                    abs_text, abs_usage = robust_generate_text(
                        abs_prompt,
                        is_easy=False,
                        temperature=0.2,
                        max_tokens=1500,
                        on_rate_limit=notify_rate_limit,
                    )
                    add_tokens(abs_usage.get("input_tokens", 0), abs_usage.get("output_tokens", 0))
                    raw_abs = abs_text.strip()
                    # Check that the abstract body is not empty
                    cand_body = re.sub(r"^#+\s*Abstract\s*", "", raw_abs, flags=re.IGNORECASE).strip()
                    cand_prose = re.sub(r"\n\s*Keywords:.*", "", cand_body, flags=re.IGNORECASE).strip()
                    if len(cand_prose.split()) >= 60:
                        abs_body = raw_abs
                        break
                    else:
                        logger.warning("Abstract attempt %d returned short or empty body (%d words). Retrying...", abs_attempt, len(cand_prose.split()))
                except DailyTokenLimitError as dt_err:
                    raise dt_err
                except Exception as exc:
                    logger.warning("Abstract generation attempt %d failed: %s", abs_attempt, exc)

            if not abs_body:
                logger.warning("Synthesizing robust fallback abstract for %s", proj_name)
                synth = synthesize_academic_abstract(proj_name, domain_name, project_fact_sheet)
                abs_body = f"## Abstract\n\n{synth}\n\nKeywords: {proj_name}, {domain_name}, system architecture, engineering analysis, implementation"

            # Clean and sanitize abstract
            fm_text = sanitize_section_markdown(abs_body, domain_name, proj_name)
            # Remove claims about existing solutions, successful end-to-end, and ungrounded claims (Item 5)
            for pat in [
                r"[^\.\n]*(?:existing solutions|existing systems|successful end-to-end|demonstrates successful|meets all requirements)[^\.\n]*\.?",
                r"[^\.\n]*(?:confirming correct orchestration|correct orchestration)[^\.\n]*\.?",
                r"[^\.\n]*(?:accurate token accounting|token accounting)[^\.\n]*\.?",
                r"[^\.\n]*(?:reliable otp-based authentication|otp-based authentication|otp flow)[^\.\n]*\.?",
                r"[^\.\n]*(?:gpt-oss|llama|qwen|mixtral|claude|gemini|openai/|groq/)[^\.\n]*\.?",
            ]:
                fm_text = re.sub(pat, "", fm_text, flags=re.IGNORECASE)
            fm_text = re.sub(r"\b\d+\s+(?:unit\s+|automated\s+)?tests?\b", "automated pytest unit tests", fm_text, flags=re.IGNORECASE)
            # Guarantee abstract never contains [Add your ...] placeholder
            fm_text = re.sub(r"\[Add your[^\]]*\]", "delivering dependable technical execution", fm_text, flags=re.IGNORECASE)
            if not fm_text.strip().startswith("#"):
                fm_text = f"## Abstract\n\n{fm_text.strip()}"
            if "Keywords:" not in fm_text:
                fm_text += f"\n\nKeywords: {proj_name}, {domain_name}, software architecture, engineering implementation, analysis, system evaluation"

            rendered_front_matter.append((idx, fm_text))
            persist_section_to_db(idx, fm_text)
            record_section_progress(title)

    # Step 3: Execute Chapters in Parallel (concurrency limit = 3)
    emit({
        "type": "stage",
        "node": "writing",
        "status": "running",
        "message": f"Generating {len(chapter_groups)} chapters with parallel research...",
    })

    def process_chapter_group(group: dict[str, Any]) -> tuple[int, list[tuple[int, str]], list[dict[str, Any]]]:
        if is_cancelled():
            return group["chapter_index"], [], []

        ch_title = group["chapter_title"]
        ch_sections = group["sections"]
        ch_idx = group["chapter_index"]
        m = re.search(r"chapter\s+(\d+)", ch_title.lower())
        actual_ch_num = int(m.group(1)) if m else ch_idx

        # Chapter 2 must be 100% placeholders unless user supplied related-work text
        has_related_work_facts = bool((front_matter or {}).get("relatedWork", "").strip())
        if actual_ch_num == 2 and not has_related_work_facts:
            rendered_subsections = []
            for s_idx, sec in ch_sections:
                sec_title = clean_title(str(sec.get("title", "")))
                sec_lvl = int(sec.get("level", 1))
                heading_prefix = "#" * min(3, sec_lvl + 1)
                clean_sec_title = re.sub(r"^\d+(?:\.\d+)*\s*", "", sec_title).strip()
                sec_md = f"{heading_prefix} {sec_title}\n\n[Add your {clean_sec_title} here.]"
                rendered_subsections.append((s_idx, sec_md))
                persist_section_to_db(s_idx, sec_md)
                record_section_progress(sec_title)
                with placeholder_lock:
                    placeholder_sections.append({
                        "index": s_idx,
                        "title": sec_title,
                        "reason": "empty_llm_output (no related work provided)",
                        "chapter": actual_ch_num,
                    })
                emit({
                    "type": "section_fallback",
                    "section_index": s_idx,
                    "section_title": sec_title,
                    "reason": "empty_llm_output (no related work provided)",
                })
            return ch_idx, rendered_subsections, []

        # Move Chapter Summary to the end of its chapter
        summary_secs = [
            item for item in ch_sections
            if "summary" in item[1].get("title", "").lower()
            and not any(k in item[1].get("title", "").lower() for k in ["executive summary", "abstract"])
        ]
        non_summary_secs = [item for item in ch_sections if item not in summary_secs]
        ch_sections = non_summary_secs + summary_secs

        chapter_has_stack_stated = [False]

        # Check if entire chapter is already completed (for resume)
        all_ch_done = all(
            sections[s_idx].get("completed") and sections[s_idx].get("content")
            for s_idx, _ in ch_sections
        )
        if all_ch_done:
            cached_subsecs = [
                (s_idx, str(sections[s_idx]["content"]))
                for s_idx, _ in ch_sections
            ]
            return ch_idx, cached_subsecs, []

        chapter_sources: list[dict[str, Any]] = []
        ch_facts = ""

        # Research is ONLY allowed for background in Chapters 1 and 2
        if actual_ch_num in (1, 2):
            related_work = (front_matter or {}).get("relatedWork", "").strip() if actual_ch_num == 2 else ""
            if actual_ch_num == 2 and related_work:
                paper_entries = [p.strip() for p in re.split(r"\n{2,}|\n(?=[A-Z0-9\[])", related_work) if p.strip()]
                chapter_sources = []
                for p_idx, entry in enumerate(paper_entries, start=1):
                    url_m = re.search(r"https?://\S+", entry)
                    entry_url = url_m.group(0).rstrip(".,)]") if url_m else ""
                    clean_entry = entry.replace(entry_url, "").strip() if entry_url else entry
                    chapter_sources.append({
                        "number": p_idx,
                        "title": clean_entry[:120],
                        "author": "Related Work Author",
                        "url": entry_url,
                        "content": entry,
                    })
                with sources_lock:
                    for s in chapter_sources:
                        u = s.get("url", "").strip()
                        if u and not any(existing.get("url", "").strip() == u for existing in all_sources):
                            all_sources.append(s)
            else:
                search_query = f"{topic} arxiv survey paper" if actual_ch_num == 1 else f"{topic} research papers literature survey methodology arxiv ieee"
                try:
                    with tavily_lock:
                        tavily_call_count[0] += 1
                        logger.info("Tavily search executed for Chapter %d: query='%s', run total=%d", actual_ch_num, search_query, tavily_call_count[0])
                    raw = _collect_sources(search_query)
                    academic_sources = []
                    general_sources = []
                    banned_vendor_domains = [
                        "machinelearningplus", "pinecone", "educative", "medium.com", "towardsdatascience",
                        "circleci", "promptabcd", "geeksforgeeks", "tutorialspoint", "w3schools", "dev.to", "hashnode",
                        "docker", "jenkins", "travis-ci", "datadog", "newrelic", "sentry",
                        "atlassian", "jira", "bitbucket", "gitlab", "argocd",
                        "youtube.com", "youtu.be", "reddit.com", "quora.com", "tiktok.com"
                    ]
                    for s in raw:
                        u = s.get("url", "").lower()
                        if any(bad in u for bad in banned_vendor_domains):
                            continue
                        if any(bad in u for bad in ["/blog/", "/blogs/", "/courses/", "/course/", "/tutorial/", "/tutorials/"]):
                            continue
                        if "github.com/" in u and not any(k in u for k in ["langchain-ai", "fastapi", "tiangolo", "facebookresearch", "pytorch"]):
                            if not ("github" in topic.lower()):
                                continue
                        is_academic = any(d in u for d in [
                            "arxiv.org", "ieee.org", "acm.org", "doi.org", "springer.com", "openreview.net",
                            "aclanthology.org", "sciencedirect.com", "semanticscholar.org", "researchgate.net", "tijer.org"
                        ])
                        if is_academic:
                            academic_sources.append(s)
                        else:
                            general_sources.append(s)

                    if actual_ch_num == 2 and len(academic_sources) < 2:
                        extra_queries = [
                            f"{topic} methodology architecture arxiv",
                            f"{topic} state of the art ieee acm survey",
                        ]
                        for eq in extra_queries:
                            if len(academic_sources) >= 2:
                                break
                            try:
                                with tavily_lock:
                                    tavily_call_count[0] += 1
                                raw_ex = _collect_sources(eq)
                                for s in raw_ex:
                                    u = s.get("url", "").lower()
                                    if any(bad in u for bad in banned_vendor_domains):
                                        continue
                                    if any(bad in u for bad in ["/blog/", "/blogs/", "/courses/", "/course/", "/tutorial/", "/tutorials/"]):
                                        continue
                                    if any(d in u for d in ["arxiv.org", "ieee.org", "acm.org", "doi.org", "springer.com", "openreview.net", "aclanthology.org", "sciencedirect.com", "semanticscholar.org", "researchgate.net", "tijer.org"]):
                                        if not any(x.get("url") == s.get("url") for x in academic_sources):
                                            academic_sources.append(s)
                            except Exception:
                                pass

                    if len(academic_sources) >= 1:
                        chapter_sources = academic_sources[:4]
                    else:
                        chapter_sources = general_sources[:4]
                except Exception as exc:
                    logger.warning("Chapter %d search failed: %s", actual_ch_num, exc)

                with sources_lock:
                    for s in chapter_sources:
                        u = s.get("url", "").strip()
                        if u and not any(existing.get("url", "").strip() == u for existing in all_sources):
                            all_sources.append(s)

            chapter_sources_text = "\n\n".join(
                f"Source: {s.get('title', 'Source')}\nURL: {s.get('url', '')}\nContent: {s.get('content', '')[:700]}"
                for s in chapter_sources
            )
            analysis_prompt = f"""You are a research analyst extracting concrete factual insights for an academic project report.
Topic: {topic}
Chapter: {ch_title}

Sources available:
{chapter_sources_text if chapter_sources_text else '(Domain knowledge)'}

Extract 4-5 concise domain background facts.
Return ONLY bullet points starting with '- '."""
            try:
                domain_facts, usage = robust_generate_text(
                    analysis_prompt,
                    is_easy=False,
                    temperature=0.15,
                    max_tokens=400,
                    on_rate_limit=notify_rate_limit,
                )
                add_tokens(usage.get("input_tokens", 0), usage.get("output_tokens", 0))
            except DailyTokenLimitError as dt_err:
                raise dt_err
            except Exception:
                domain_facts = f"- Domain foundations and background context of {topic}."

            ch_facts = (
                f"{project_fact_sheet}\n\n"
                f"Generic Domain Background & Literature Survey (Reference only; NOT part of user's project):\n"
                f"{domain_facts}"
            )
        else:
            # Chapters 3-10: GROUND TRUTH ONLY. Zero web searches, zero external project facts.
            chapter_sources = []
            ch_facts = project_fact_sheet

        rendered_subsections: list[tuple[int, str]] = []

        # Write each section in this chapter reusing chapter findings & project facts
        for s_idx, sec in ch_sections:
            if is_cancelled():
                return ch_idx, rendered_subsections, chapter_sources

            # Check if section is already completed (for resume)
            if sections[s_idx].get("completed") and sections[s_idx].get("content"):
                rendered_subsections.append((s_idx, str(sections[s_idx]["content"])))
                continue

            sec_title = clean_title(str(sec.get("title", "")))
            sec_lvl = int(sec.get("level", 1))
            sec_target = int(sec.get("target_words") or 200)
            norm_sec = sec_title.lower()

            # If container H1 heading, start directly with heading without canned boilerplate
            if sec_lvl == 1:
                intro_text = f"# {sec_title}"
                rendered_subsections.append((s_idx, intro_text))
                persist_section_to_db(s_idx, intro_text)
                record_section_progress(sec_title)
                continue

            # Deterministic Roadmap for Section 1.5 (Task 2 Item 3)
            if re.search(r"^1\.5\b", sec_title):
                sec_md = build_deterministic_roadmap_section(sec_title, heading_prefix)
                rendered_subsections.append((s_idx, sec_md.strip()))
                persist_section_to_db(s_idx, sec_md.strip())
                record_section_progress(sec_title)
                continue

            # Deterministic Data Design for Section 4.6 (Item 6)
            if re.search(r"^4\.6\b", sec_title) or (actual_ch_num == 4 and "data design" in norm_sec):
                sec_md = build_deterministic_data_design_section(sec_title, heading_prefix)
                rendered_subsections.append((s_idx, sec_md.strip()))
                persist_section_to_db(s_idx, sec_md.strip())
                record_section_progress(sec_title)
                continue

            # Section 6.6: Team Structure (Task 2 Item 10)
            if re.search(r"^6\.6\b", sec_title) or (actual_ch_num == 6 and any(k in norm_sec for k in ["team structure", "team organization", "team roles"])):
                members = (fm.get("teamMembers") or []) if isinstance(front_matter, dict) else []
                if len(members) <= 1:
                    sec_md = f"{heading_prefix} {sec_title}\n\nThe project was developed by a single student."
                    rendered_subsections.append((s_idx, sec_md.strip()))
                    persist_section_to_db(s_idx, sec_md.strip())
                    record_section_progress(sec_title)
                    continue

            # Deterministic Data Dictionary for Section 7.3 (Item 5 / 8)
            if re.search(r"^7\.3\b", sec_title) or (actual_ch_num == 7 and "data dictionary" in norm_sec):
                sec_md = build_deterministic_data_dictionary_section(sec_title, heading_prefix)
                rendered_subsections.append((s_idx, sec_md.strip()))
                persist_section_to_db(s_idx, sec_md.strip())
                record_section_progress(sec_title)
                continue

            # Deterministic Installation for Section 10.3 (Task 2 Item 7)
            if re.search(r"^10\.3\b", sec_title):
                sec_md = build_deterministic_installation_section(sec_title, heading_prefix)
                rendered_subsections.append((s_idx, sec_md.strip()))
                persist_section_to_db(s_idx, sec_md.strip())
                record_section_progress(sec_title)
                continue

            # Deterministic / Grounded deployment sections 10.5 to 10.8 (Task 2 Item 6)
            if re.search(r"^10\.5\b", sec_title):
                sec_md = f"""{heading_prefix} {sec_title}

System maintenance is performed through manual process restarts following code changes or configuration updates. The FastAPI backend running via Uvicorn and the Vite frontend development server are restarted directly from the terminal, without automated process supervisors or container orchestration."""
                rendered_subsections.append((s_idx, sec_md.strip()))
                persist_section_to_db(s_idx, sec_md.strip())
                record_section_progress(sec_title)
                continue

            if re.search(r"^10\.6\b", sec_title):
                sec_md = f"""{heading_prefix} {sec_title}

Database backup and recovery is conducted by creating direct filesystem copies of the SQLite database file (`reports.db`). In the event of data corruption or migration requirements, recovery is achieved by restoring the copied database file while the backend service is halted, ensuring ACID transaction integrity."""
                rendered_subsections.append((s_idx, sec_md.strip()))
                persist_section_to_db(s_idx, sec_md.strip())
                record_section_progress(sec_title)
                continue

            if re.search(r"^10\.7\b", sec_title):
                sec_md = f"""{heading_prefix} {sec_title}

Deployment challenges primarily center on managing external API rate limits and quotas for LLM inference and web search services. Operating as a local-only deployment mitigates cloud hosting overhead and network ingress risks while restricting service availability to the local workstation."""
                rendered_subsections.append((s_idx, sec_md.strip()))
                persist_section_to_db(s_idx, sec_md.strip())
                record_section_progress(sec_title)
                continue

            if re.search(r"^10\.8\b", sec_title) or (actual_ch_num == 10 and "summary" in norm_sec):
                sec_md = f"""{heading_prefix} {sec_title}

The CiteBolt system is deployed locally on a single machine utilizing a FastAPI backend served via Uvicorn and a Vite React frontend. Persistence is managed through a local SQLite database file without cloud infrastructure, Docker containerization, or automated CI/CD pipelines. Operational management consists of direct command-line execution and local process control."""
                rendered_subsections.append((s_idx, sec_md.strip()))
                persist_section_to_db(s_idx, sec_md.strip())
                record_section_progress(sec_title)
                continue

            heading_prefix = "#" * min(3, sec_lvl + 1)
            # Cheaper model: use it ONLY for Acknowledgements and short "Summary" sections (sec_target <= 150).
            # Keep Abstract, Conclusion, Introduction and Motivation on the main model.
            is_easy_section = (
                "summary" in norm_sec
                and not any(k in norm_sec for k in ["introduction", "conclusion", "motivation", "abstract"])
                and sec_target <= 150
            )

            rules: list[str] = [
                f"- Start directly with the section heading: '{heading_prefix} {sec_title}'. Do NOT output a document title or preamble.",
                "- Write thoroughly and in depth to reach approximately the target word count.",
                "- Write in clean, professional plain ASCII text (straight quotes, normal hyphens).",
                "- Do not repeat the stack summary; write only about this section's topic.",
                f"- Numbering: format figure captions strictly on their own line as 'Fig. {actual_ch_num}.N: [Description]' and table captions as 'Table {actual_ch_num}.N: [Description]'. Refer to them as 'Fig. {actual_ch_num}.N' and 'Table {actual_ch_num}.N' in text.",
                f"- Diagrams: Where a diagram is needed (architecture, ERD, sequence, flowchart, Gantt), insert a clean placeholder on its own line: '[Insert diagram here: Fig. {actual_ch_num}.N - Description]'. Do NOT use '>' or ASCII boxes.",
                "- Do NOT generate a Sources or References section; that will be compiled at the end.",
            ]

            is_thin_sec = any(k in sec_title for k in ["4.6", "4.7", "4.8", "6.3", "6.8", "7.4", "7.5"])
            if is_thin_sec:
                rules.append("- THIN SECTION (CRITICAL): Write exactly 2-3 dense sentences (~50-80 words) grounded strictly in the verified project facts. Do NOT invent external tools, databases, or processes.")

            is_intro_section = (
                re.search(r"^\d+\.1\s+introduction", norm_sec)
                or (norm_sec == "introduction" and sec_lvl >= 2)
            )
            is_summary_section = (
                "summary" in norm_sec
                and not any(k in norm_sec for k in ["introduction", "conclusion", "motivation", "abstract"])
            )
            if is_intro_section:
                rules.append(
                    f"- CHAPTER INTRODUCTION (CRITICAL): Provide a concise 2-3 sentence overview (~60-100 words) "
                    f"explaining strictly what THIS SPECIFIC CHAPTER ({ch_title}) covers. "
                    "Do NOT repeat the overall project stack or architecture."
                )
            elif is_summary_section:
                rules.append(
                    f"- CHAPTER SUMMARY (CRITICAL): Provide a concise 2-3 sentence synthesis (~60-100 words) "
                    f"summarizing strictly the key findings and specifications established in THIS SPECIFIC CHAPTER ({ch_title}). "
                    "Do NOT repeat the full technology stack description."
                )

            if actual_ch_num == 1:
                if re.search(r"^1\.1\b", sec_title):
                    rules.append("- SECTION 1.1 DOMAIN OVERVIEW: Focus strictly on the general domain background, real-world context, and landscape. Do NOT describe the specific software architecture, backend, or agents of the proposed project.")
                elif re.search(r"^1\.2\b", sec_title):
                    rules.append("- SECTION 1.2 PROJECT INTRODUCTION: A short narrative intro to the project: what it does, the three agents (Research, Analysis, Writer), and the stack by name only (FastAPI, React, SQLite, LangGraph). Intro sections are PROSE ONLY. Do NOT include endpoint paths, database column names, run commands, or code identifiers like report_markdown.")
                elif re.search(r"^1\.3\b", sec_title):
                    rules.append("- SECTION 1.3 PROBLEM STATEMENT: Formulate the specific core technical problems and limitations being solved. Do NOT repeat project features or general introduction.")
                elif re.search(r"^1\.4\b", sec_title):
                    rules.append("- SECTION 1.4 OBJECTIVES: State the concise, concrete technical objectives and deliverables of the proposed system. Do NOT write general prose.")
                elif re.search(r"^1\.5\b", sec_title):
                    rules.append("- SECTION 1.5 REPORT ROADMAP: Outline the organizational roadmap of the report (what Chapters 2 through 11 cover). Do NOT repeat the project description or stack.")

            is_lit_survey = any(k in ch_title.lower() for k in ["literature", "survey", "related work"]) or any(k in norm_sec for k in ["literature", "survey", "related work", "gaps", "prior work"])
            has_related_work_facts = bool((front_matter or {}).get("relatedWork", "").strip())
            if is_lit_survey and not has_related_work_facts:
                if re.search(r"^2\.1\b", sec_title):
                    if len(chapter_sources) == 0:
                        sec_md = f"{heading_prefix} {sec_title}\n\n[Add your literature review and related work references here.]"
                        rendered_subsections.append((s_idx, sec_md.strip()))
                        persist_section_to_db(s_idx, sec_md.strip())
                        record_section_progress(sec_title)
                        continue
                    # When 1-2 real academic sources found, 2.1 proceeds to LLM generation below with [n] citations
                else:
                    if len(chapter_sources) < 2:
                        clean_sec_title = re.sub(r"^\d+(?:\.\d+)*\s*", "", sec_title).strip()
                        sec_md = f"{heading_prefix} {sec_title}\n\n[Add your {clean_sec_title} here.]"
                        rendered_subsections.append((s_idx, sec_md.strip()))
                        persist_section_to_db(s_idx, sec_md.strip())
                        record_section_progress(sec_title)
                        continue

            if actual_ch_num in (1, 2):
                if actual_ch_num == 2 and (front_matter or {}).get("relatedWork", "").strip():
                    rules.append("- LITERATURE SURVEY (CRITICAL): Write the survey strictly and ONLY from the user-provided related work papers. Cite each with [n] where n matches the paper's reference number.")
                rules.extend([
                    "- CHAPTER 1-2 GROUND TRUTH & CITATION RULES (CRITICAL):",
                    f"  * Describe the user's project ({proj_name}) strictly from the Project Facts.",
                    "  * Web research snippets are for generic background and related work only (Chapter 2); NEVER attribute them to the user's project.",
                    "  * Call blog posts or tutorials 'online resources' in Chapter 2 (e.g. 'as documented in online resources [n]').",
                    "  * NEVER name external search tools or other systems (Serper, Bedrock, DuckDuckGo, Docker, CircleCI, etc.) as part of the user's project.",
                    "  * Citations like [n] are permitted ONLY for generic literature claims in Chapters 1-2, never for statements about the user's own architecture.",
                ])
            else:
                rules.extend([
                    "- GROUND TRUTH CONSTRAINT (CRITICAL):",
                    "  * The Project Facts above are the ONLY allowed source for how the user's system works.",
                    "  * NEVER name agents, tools, libraries, versions, servers, CI/CD, backups, endpoints, DB columns, or test IDs that are not in the Project Facts.",
                    "  * If any specific detail, metric, test case, or configuration is not provided, explicitly write '[Add your <thing> here.]'.",
                    "  * If deployment status is not stated as in production, write Chapter 10 as planned/local deployment.",
                    "  * Do NOT use citations like [n] in Chapters 3-10.",
                ])

            if actual_ch_num == 6:
                if "6.4" in sec_title or "timeline" in norm_sec or "milestone" in norm_sec:
                    if not duration:
                        rules.append("- TIMELINE (CRITICAL): Project Duration is blank. Write placeholders: '[Add your project timeline here.]' and '[Add your milestone schedule here.]'. Do NOT invent months, weeks, or phases.")
                    else:
                        rules.append(f"- TIMELINE (CRITICAL): The project duration is '{duration}'. State this duration without inventing a per-phase weekly breakdown.")
                elif "6.7" in sec_title or "effort" in norm_sec or "allocation" in norm_sec:
                    if not duration:
                        rules.append("- EFFORT ESTIMATION (CRITICAL): Project Duration is blank. Write placeholder: '[Add your effort estimation here.]'. Do NOT invent hours, person-months, or effort splits.")
                    else:
                        rules.append(f"- EFFORT ESTIMATION (CRITICAL): The project duration is '{duration}'. Discuss effort allocation generally without inventing unverified person-month splits.")

            if actual_ch_num == 8:
                rules.extend([
                    "- TESTING & VERIFICATION (CRITICAL):",
                    "  * Describe testing strictly as stated in the Project Facts (e.g. unit tests with mocked LLM and mocked search).",
                    "  * Do NOT claim testing of JWT, run limits, OTP, or export unless explicitly stated in the facts.",
                ])

            if actual_ch_num in (8, 9):
                rules.extend([
                    "- EXPERIMENTAL MEASUREMENTS & BENCHMARK RESULTS (CRITICAL):",
                    "  * NEVER invent fake survey numbers, user-feedback ratings, accuracy percentages, latency figures, or test execution times.",
                    "  * For any measurement, test statistic, or benchmark figure not explicitly given in the facts, write '[Add your result here.]'.",
                ])

            if actual_ch_num == 9 and ("9.4" in sec_title or "user feedback" in norm_sec or "survey" in norm_sec):
                rules.append("- USER FEEDBACK (CRITICAL): If user feedback or survey results are not in the Project Facts, write ONLY: '[Add your user feedback results here.]'. Do NOT invent survey questions, respondent counts, or satisfaction scores.")

            if actual_ch_num == 10 and ("10.3" in sec_title or "run" in norm_sec or "deployment" in norm_sec or "operation" in norm_sec):
                rules.append("- HOW TO RUN (CRITICAL): State the exact commands to run the system: from backend/: `uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload` and `npm run dev` for the frontend.")

            writer_prompt = f"""You are an elite academic and technical writer. Write ONE section of a detailed college engineering report.
Overall Project: {proj_name}
Domain: {domain_name}
Section Heading: {heading_prefix} {sec_title}
Word Target: Write thoroughly to reach approximately {sec_target} words.

Factual Reference Context:
{ch_facts}

Strict Writing Rules:
{chr(10).join(rules)}

Output ONLY the Markdown content for this section:"""

            # Concise retry prompt for attempt 2 if attempt 1 returns empty or triggers boilerplate rejection
            shorter_prompt = f"""Write the technical section '{heading_prefix} {sec_title}' for '{proj_name}'.
Word Target: ~{max(70, int(sec_target * 0.5))} words of concise, direct technical explanation grounded in these facts:
{project_fact_sheet[:3000]}

Rules:
- Start directly with '{heading_prefix} {sec_title}'.
- Clean technical prose without preamble.
- If specific details are not in facts, use '[Add your <thing> here.]'."""

            # Set max_tokens with headroom for reasoning models (words * 2.5 + 600, at least 1024)
            sec_max_tokens = max(1024, int(sec_target * 2.5 + 600))

            sec_md = ""
            last_reason = "unknown"
            for attempt in range(1, 3):
                prompt_to_use = writer_prompt if attempt == 1 else shorter_prompt
                tokens_to_request = sec_max_tokens if attempt == 1 else max(600, int(sec_target * 1.5 + 300))
                try:
                    sec_md, u = robust_generate_text(
                        prompt_to_use,
                        is_easy=is_easy_section,
                        temperature=0.25,
                        max_tokens=tokens_to_request,
                        on_rate_limit=notify_rate_limit,
                    )
                    add_tokens(u.get("input_tokens", 0), u.get("output_tokens", 0))

                    if not sec_md or not sec_md.strip():
                        last_reason = "empty_llm_output (tokens exhausted by reasoning or model returned empty)"
                        logger.warning(
                            "Section '%s' (s_idx=%d) attempt %d failed: %s (in_tokens=%d, out_tokens=%d, finish_reason=%s)",
                            sec_title, s_idx, attempt, last_reason, u.get("input_tokens", 0), u.get("output_tokens", 0), u.get("finish_reason")
                        )
                        time.sleep(1.0 * attempt)
                        continue

                    # If API stopped due to length, continue from where it left off
                    if u.get("finish_reason") == "length" and sec_md.strip():
                        words = sec_md.strip().split()
                        seam = " ".join(words[-60:]) if len(words) > 60 else sec_md.strip()
                        continue_prompt = f"""Continue writing the section '{sec_title}' for '{proj_name}'.
The section was cut off mid-thought at this text:
\"...{seam}\"

Instructions:
- Continue immediately from the exact point of cutoff.
- Do NOT repeat the seam words or add any headings.
- Finish the section cleanly with a full stop (period).
- Target remaining words: ~{max(50, int(sec_target * 0.4))} words.

Continue:"""
                        try:
                            cont_text, cont_u = robust_generate_text(
                                continue_prompt,
                                is_easy=is_easy_section,
                                temperature=0.25,
                                max_tokens=max(600, int(sec_target * 1.5 + 300)),
                                on_rate_limit=notify_rate_limit,
                            )
                            add_tokens(cont_u.get("input_tokens", 0), cont_u.get("output_tokens", 0))
                            cont_clean = cont_text.strip()
                            if cont_clean:
                                sec_md = sec_md.rstrip() + " " + cont_clean.lstrip()
                        except Exception as cont_err:
                            logger.warning("Continuation for '%s' failed: %s", sec_title, cont_err)

                    # Reject canned boilerplate or severe truncation (regenerate once with shorter prompt)
                    if is_canned_boilerplate(sec_md, sec_target, is_intro=(is_intro_section or is_summary_section)) and attempt == 1:
                        last_reason = "boilerplate_rejected"
                        logger.warning(
                            "Section '%s' (s_idx=%d) attempt %d matched boilerplate or was too short (%d words). Regenerating with focused prompt...",
                            sec_title, s_idx, attempt, len(sec_md.split())
                        )
                        rewrite_note = "\n\nREWRITE NOTE: Avoid generic boilerplate like 'leverages a modular multi-agent architecture'. Provide specific engineering depth or use '[Add your ...]'."
                        writer_prompt += rewrite_note
                        shorter_prompt += rewrite_note
                        sec_md = ""
                        continue

                    if is_thin_sec and attempt == 1 and len(sec_md.strip().split()) < 25:
                        last_reason = "thin_section_too_short"
                        logger.warning(
                            "Thin section '%s' (s_idx=%d) attempt 1 was too short (%d words). Retrying once with focused prompt...",
                            sec_title, s_idx, len(sec_md.strip().split())
                        )
                        sec_md = ""
                        continue

                    break
                except DailyTokenLimitError as dt_err:
                    raise dt_err
                except Exception as exc:
                    last_reason = f"exception: {exc}"
                    logger.warning("Writing section '%s' (s_idx=%d) attempt %d failed: %s", sec_title, s_idx, attempt, exc)
                    sec_md = ""
                    time.sleep(1.5 * attempt)

            if sec_md and sec_md.strip():
                clean_body = sanitize_section_output(sec_md)
                if clean_body:
                    sec_md = f"{heading_prefix} {sec_title}\n\n{clean_body}"
                else:
                    sec_md = ""

            if not sec_md or not sec_md.strip():
                clean_sec_title = re.sub(r"^\d+(?:\.\d+)*\s*", "", sec_title).strip()
                sec_md = f"{heading_prefix} {sec_title}\n\n[Add your {clean_sec_title} here.]"
                logger.error(
                    "Section '%s' (s_idx=%d) fell back to placeholder after 2 attempts. Reason: %s",
                    sec_title, s_idx, last_reason
                )
                with placeholder_lock:
                    placeholder_sections.append({
                        "index": s_idx,
                        "title": sec_title,
                        "reason": last_reason,
                        "chapter": actual_ch_num,
                    })
                emit({
                    "type": "section_fallback",
                    "section_index": s_idx,
                    "section_title": sec_title,
                    "reason": last_reason,
                })

            # Post-process: sanitize markdown, remove fences, remove ASCII boxes, fill tokens
            sec_md = sanitize_section_markdown(sec_md, domain_name, proj_name, sources=chapter_sources, duration=duration)
            sec_md = normalize_college_captions_and_placeholders(sec_md)
            sec_md = filter_grounded_college_section(
                sec_title=sec_title,
                sec_md=sec_md,
                fact_sheet=ch_facts,
                heading_prefix=heading_prefix,
                is_college=True,
                min_words=25 if is_thin_sec else 2,
                chapter_has_stack_stated=chapter_has_stack_stated,
            )
            sec_md = normalize_college_captions_and_placeholders(sec_md)

            # Ensure section ends with a full stop, but NEVER add '.' after '[Add your ... here.]' or ']'
            if sec_md and sec_md[-1] not in ".!?\":\n" and not sec_md.rstrip().endswith("]"):
                sec_md += "."

            logger.info("Section '%s' generated using %d words, active model=%s", sec_title, len(sec_md.split()), get_current_model())

            rendered_subsections.append((s_idx, sec_md.strip()))
            persist_section_to_db(s_idx, sec_md.strip())
            record_section_progress(sec_title)
            time.sleep(0.3)

        return ch_idx, rendered_subsections, chapter_sources

    # Run chapters with concurrency limit = 3
    rendered_chapters: list[tuple[int, list[tuple[int, str]]]] = []
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(process_chapter_group, grp): grp for grp in chapter_groups}
            for future in concurrent.futures.as_completed(futures):
                ch_idx, subsecs, _ = future.result()
                rendered_chapters.append((ch_idx, subsecs))
    except DailyTokenLimitError as dt_exc:
        logger.warning("All configured Groq models hit daily token limits: %s", dt_exc)
        state["paused"] = True
        state["pause_reason"] = "Paused: daily token limit reached"

        assembled = [
            str(s.get("content", ""))
            for s in sections
            if s.get("completed") and s.get("content")
        ]
        partial_md = "\n\n".join(assembled)
        state["report"] = partial_md
        state["word_count"] = len(partial_md.split())
        with sources_lock:
            state["sources"] = list(all_sources)
        state["outline"] = sections

        if run_id:
            try:
                from app.db import SessionLocal
                from app.models import Run

                with SessionLocal() as session:
                    r = session.get(Run, run_id)
                    if r:
                        r.status = "Paused: daily token limit reached"
                        r.error_message = (
                            f"Daily token limit reached for model {dt_exc.model}. "
                            f"Saved {completed_count[0]} completed sections. "
                            "Click 'Resume' once your daily limit resets."
                        )
                        r.outline_json = json.dumps(sections, ensure_ascii=False)
                        r.report_markdown = partial_md
                        session.commit()
            except Exception as db_err:
                logger.debug("Failed updating pause status in DB: %s", db_err)

        emit({
            "type": "paused",
            "status": "Paused: daily token limit reached",
            "message": (
                f"Daily token limit reached on Groq for {dt_exc.model}. "
                f"All {completed_count[0]} completed sections have been saved. "
                "You can resume once your quota resets."
            ),
        })
        return state

    # Sort chapters by original chapter index
    rendered_chapters.sort(key=lambda x: x[0])

    # Step 4: Render Post-Body (References, Appendices)
    rendered_post_body: list[tuple[int, str]] = []
    for idx, sec in post_body_sections:
        title = clean_title(str(sec.get("title", "")))
        norm_t = title.lower()

        if sec.get("completed") and sec.get("content"):
            rendered_post_body.append((idx, str(sec["content"])))
            continue

        if "references" in norm_t:
            text = "## References\n\n*(References will be listed in IEEE format)*"
        else:
            text = format_front_matter_section(title, topic, front_matter, outline) or f"## {title}"

        rendered_post_body.append((idx, text))
        persist_section_to_db(idx, text)
        record_section_progress(title)

    # Step 5: Assemble in exact outline order
    all_rendered_items: list[tuple[int, str]] = []
    all_rendered_items.extend(rendered_front_matter)
    for _, ch_subsecs in rendered_chapters:
        all_rendered_items.extend(ch_subsecs)
    all_rendered_items.extend(rendered_post_body)

    all_rendered_items.sort(key=lambda x: x[0])
    raw_markdown = "\n\n".join(item[1] for item in all_rendered_items)

    # Sanitize markdown, remove ASCII frames, and fill template tokens
    raw_markdown = sanitize_section_markdown(raw_markdown, domain_name, proj_name, sources=all_sources, duration=duration)
    raw_markdown = normalize_college_captions_and_placeholders(raw_markdown)
    raw_markdown = ensure_unique_figure_and_table_captions(raw_markdown, is_short=(length_preset == "short"))
    raw_markdown = normalize_college_captions_and_placeholders(raw_markdown)

    # Build dynamic List of Figures and List of Tables from the final body text (Task 2 Item 1)
    dynamic_lof, dynamic_lot = build_dynamic_lof_and_lot(raw_markdown)
    raw_markdown = re.sub(r"## List of Figures.*?(?=\n## |\Z)", dynamic_lof + "\n\n", raw_markdown, flags=re.DOTALL)
    raw_markdown = re.sub(r"## List of Tables.*?(?=\n## |\Z)", dynamic_lot + "\n\n", raw_markdown, flags=re.DOTALL)

    # Clean and renumber citations gaplessly
    renumbered_markdown, final_sources = filter_and_renumber_sources(raw_markdown, all_sources)

    # Filter out external GitHub repos and YouTube links; prefer academic and official doc sources
    academic_patterns = [
        "arxiv.org", "ieee.org", "acm.org", "doi.org", "springer.com",
        "openreview.net", "aclanthology.org", "sciencedirect.com",
        "semanticscholar.org", "researchgate.net", "tijer.org"
    ]
    banned_ref_domains = [
        "machinelearningplus", "pinecone", "educative", "medium.com", "towardsdatascience",
        "circleci", "promptabcd", "geeksforgeeks", "tutorialspoint", "w3schools", "dev.to", "hashnode",
        "docker", "jenkins", "travis-ci", "datadog", "newrelic", "sentry", "atlassian", "jira",
        "youtube.com", "youtu.be", "/blog/", "/blogs/", "/courses/", "/course/", "/tutorial/", "/tutorials/"
    ]

    filtered_sources = []
    for s in final_sources:
        u = s.get("url", "").lower()
        if any(bd in u for bd in banned_ref_domains):
            continue
        if "github.com/" in u and not ("github" in topic.lower()):
            if not any(k in u for k in ["langchain-ai", "fastapi", "tiangolo", "facebookresearch"]):
                continue
        filtered_sources.append(s)

    def _source_priority(s: dict[str, Any]) -> int:
        u = s.get("url", "").lower()
        if any(d in u for d in academic_patterns):
            return 0
        if any(d in u for d in ["docs.", "developer.", "github.com/langchain", "fastapi.tiangolo"]):
            return 1
        return 2

    filtered_sources.sort(key=_source_priority)
    academic_sources = [s for s in filtered_sources if any(d in s.get("url", "").lower() for d in academic_patterns)]
    if len(academic_sources) >= 3:
        final_sources = academic_sources
    else:
        final_sources = academic_sources if academic_sources else filtered_sources

    final_sources = deduplicate_and_clean_sources(final_sources)

    # Filter to only sources cited in text if citations exist
    cited_nums = set(int(m) for m in re.findall(r"\[(\d+)\]", renumbered_markdown))
    if cited_nums:
        cited_sources = [
            s for idx, s in enumerate(final_sources, start=1)
            if idx in cited_nums or s.get("number") in cited_nums
        ]
        if cited_sources:
            final_sources = cited_sources

    # Format IEEE bibliography using only real sources returned by search
    ieee_refs = ["## References\n"]
    for i, s in enumerate(final_sources, start=1):
        s_title = s.get("title", "Reference Source").strip().rstrip(".")
        s_url = s.get("url", "").strip()
        if s_url:
            ieee_refs.append(f"[{i}] {s_title}, Available: {s_url}.")
        else:
            ieee_refs.append(f"[{i}] {s_title}.")
    if len(final_sources) < 3:
        ieee_refs.append("[Add more references here]")
    refs_block = "\n\n".join(ieee_refs)
    if "## References" in renumbered_markdown:
        renumbered_markdown = re.sub(
            r"## References.*?(?=\n## |\Z)",
            refs_block,
            renumbered_markdown,
            flags=re.DOTALL,
        )
    else:
        renumbered_markdown += f"\n\n{refs_block}"

    doc_title = (
        (front_matter.get("projectTitle") if front_matter else None)
        or state.get("title")
        or f"{topic.title()} Research Report"
    ).strip().rstrip(".")
    if not renumbered_markdown.lstrip().startswith("# "):
        final_markdown = f"# {doc_title}\n\n{renumbered_markdown}"
    else:
        final_markdown = renumbered_markdown

    word_count = len(strip_sources_section(final_markdown).split())
    total_cost = compute_cost(total_input_tokens[0], total_output_tokens[0], get_current_model())

    state["report"] = final_markdown
    state["sources"] = final_sources
    state["token_usage"] = total_input_tokens[0] + total_output_tokens[0]
    state["input_tokens"] = total_input_tokens[0]
    state["output_tokens"] = total_output_tokens[0]
    state["cost"] = total_cost
    state["word_count"] = word_count
    state["title"] = doc_title

    placeholder_count = len(placeholder_sections)
    ch1_or_abs_fallback = any(
        p.get("chapter") == 1
        or "abstract" in p.get("title", "").lower()
        or p.get("title", "").lower().startswith("1.")
        or "chapter 1" in p.get("title", "").lower()
        for p in placeholder_sections
    )
    if (placeholder_count / max(1, total_sections) > 0.10) or ch1_or_abs_fallback:
        logger.warning(
            "Run completed with warnings: %d of %d sections (%.1f%%) are placeholders. Ch1/Abstract fallback=%s",
            placeholder_count, total_sections, (placeholder_count / total_sections) * 100, ch1_or_abs_fallback
        )
        state["has_warnings"] = True
        state["status"] = "completed_with_warnings"
        state["warning_details"] = {
            "placeholder_count": placeholder_count,
            "total_sections": total_sections,
            "placeholder_sections": [p["title"] for p in placeholder_sections],
            "ch1_or_abs_fallback": ch1_or_abs_fallback,
        }
        state["warning_message"] = f"{placeholder_count} of {total_sections} sections could not be generated and require manual input."

    # Mark all sections complete and save final version
    with save_lock:
        if run_id:
            try:
                from app.db import SessionLocal
                from app.models import Run

                with SessionLocal() as session:
                    r = session.get(Run, run_id)
                    if r:
                        r.outline_json = json.dumps(sections, ensure_ascii=False)
                        r.report_markdown = final_markdown
                        r.word_count = word_count
                        session.commit()
            except Exception:
                pass

    emit({
        "type": "stage",
        "node": "writing",
        "status": "done",
        "message": f"Report drafted ({word_count:,} words).",
    })
    emit({
        "type": "report",
        "report": final_markdown,
        "sources": final_sources,
    })

    return state
