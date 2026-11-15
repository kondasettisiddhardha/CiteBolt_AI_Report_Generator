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
from app.text import clean_title, filter_and_renumber_sources, strip_sources_section

logger = logging.getLogger("citebolt.section_engine")


def extract_domain_and_project(topic: str, front_matter: dict[str, Any] | None = None) -> tuple[str, str]:
    """Derive clean Domain and Project names from topic and front_matter."""
    fm = front_matter or {}
    proj = fm.get("projectTitle", "").strip()
    if not proj:
        # derive from topic: e.g. "AI Research and Report Generator using LangGraph Multi-Agent Pipeline"
        proj = topic
        for sep in [" using ", " with ", " via ", " based on "]:
            if sep in topic.lower():
                proj = re.split(re.escape(sep), topic, flags=re.IGNORECASE)[0].strip()
                break

    domain = topic
    for sep in [" using ", " with ", " via ", " based on "]:
        if sep in topic.lower():
            domain = re.split(re.escape(sep), topic, flags=re.IGNORECASE)[0].strip()
            break
    if not any(domain.lower().endswith(w) for w in ["industry", "systems", "generation", "engineering"]):
        domain_name = f"{domain} Systems"
    else:
        domain_name = domain
    return domain_name, proj


def build_compact_project_fact_sheet(topic: str, context: str, front_matter: dict[str, Any] | None = None) -> str:
    """Build a compact (~200-300 token) ground-truth fact sheet from user project facts.
    
    This is the ONLY allowed technical truth for Chapters 3-10.
    """
    domain_name, proj_name = extract_domain_and_project(topic, front_matter)
    ctx = context.strip() if context else ""
    lines = [
        f"Project Name: {proj_name}",
        f"Core Domain: {domain_name}",
    ]
    if ctx:
        lines.append("Verified Architecture & Project Facts (Ground Truth):")
        # Keep compact (~1200 chars / ~200-250 words)
        lines.append(ctx[:1400])
    else:
        lines.append("Verified Architecture: System specification as outlined in project topic.")
    lines.append(
        "Strict Rule: Only describe components, tools, agents, and libraries explicitly present in the facts above. "
        "If any detail, test count, or configuration is missing, explicitly write '[Add your ...]'. Never invent outside agents, tools, or metrics."
    )
    return "\n".join(lines)


def sanitize_section_markdown(
    md: str,
    domain: str = "",
    project: str = "",
    sources: list[dict[str, Any]] | None = None,
) -> str:
    """Clean markdown junk, ASCII diagram frames, author-year citations, and fill tokens."""
    # 1. Fill template tokens if any remaining
    if domain:
        md = md.replace("[Domain]", domain)
        md = re.sub(r"\[Domain\]", domain, md, flags=re.IGNORECASE)
    if project:
        md = md.replace("[Project]", project)
        md = re.sub(r"\[Project\]", project, md, flags=re.IGNORECASE)
    md = md.replace("[Domain]", "Domain").replace("[Project]", "Project")

    # 2. Strip triple-backtick fences around prose
    md = re.sub(r"^```(?:markdown)?\s*\n", "", md, flags=re.MULTILINE)
    md = re.sub(r"\n```\s*$", "", md, flags=re.MULTILINE)

    # 3. Convert #### or ##### to ###
    md = re.sub(r"^#{4,}\s+(.*)", r"### \1", md, flags=re.MULTILINE)

    # 4. Strip excessive ** markers (e.g. **** or empty bold)
    md = re.sub(r"\*{4,}", "", md)
    md = re.sub(r"\*\*\s*\*\*", "", md)

    # 5. Clean ASCII art frames around [Insert diagram here]
    md = re.sub(
        r"\+[-=+]+\+\s*\n\s*\|\s*(\[[^\]]*diagram[^\]]*\])\s*\|\s*\n\s*\+[-=+]+\+",
        r"> \1",
        md,
        flags=re.IGNORECASE,
    )
    md = re.sub(r"\+[-=]{5,}\+\s*\n", "", md)
    md = re.sub(r"\|\s*(\[[^\]]*diagram[^\]]*\])\s*\|", r"\1", md, flags=re.IGNORECASE)

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

    return md.strip()


def is_canned_boilerplate(text: str, target_words: int) -> bool:
    """Detect canned boilerplate fallback or severely truncated sections."""
    norm = text.lower()
    if "leverages a modular multi-agent architecture" in norm:
        return True
    if "detailed analysis of" in norm:
        return True
    word_count = len(text.split())
    if target_words >= 100 and word_count < int(target_words * 0.6):
        return True
    return False


def format_front_matter_section(
    sec_title: str,
    topic: str,
    front_matter: dict[str, Any] | None,
    outline: list[dict[str, Any]] | None = None,
) -> str | None:
    norm = sec_title.lower().strip()
    fm = front_matter or {}
    proj_title = fm.get("projectTitle") or topic
    dept = fm.get("department") or ""
    univ = fm.get("university") or ""
    year = fm.get("academicYear") or ""
    sub_date = fm.get("submissionMonthYear") or ""
    guide = fm.get("guide") or ""
    coord = fm.get("coordinator") or ""
    hod = fm.get("hod") or ""
    dean = fm.get("dean") or ""
    members = fm.get("teamMembers") or []

    if "title page" in norm:
        lines = [
            f"# {proj_title}\n",
            "**A PROJECT REPORT**\n",
            "Submitted in partial fulfillment of the academic requirements for the award of the degree of\n",
            "**BACHELOR OF TECHNOLOGY / ENGINEERING**\n",
        ]
        has_named_members = any(
            isinstance(m, dict) and m.get("name", "").strip() for m in members
        )
        if has_named_members:
            lines.append("Submitted by:\n")
            for m in members:
                name = m.get("name", "").strip() if isinstance(m, dict) else str(m).strip()
                prn = m.get("prn", "").strip() if isinstance(m, dict) else ""
                if name:
                    lines.append(f"- **{name}** (PRN: {prn})" if prn else f"- **{name}**")
            lines.append("")
        else:
            lines.append("Submitted by:\n- **____________________** (PRN: ____________________)\n")

        if guide:
            lines.append(f"Under the guidance of:\n**{guide}**\n")
        else:
            lines.append("Under the guidance of:\n**____________________**\n")

        org_lines = [line for line in [dept, univ, f"Academic Year: {year}" if year else "", sub_date] if line]
        if org_lines:
            lines.append("\n".join(org_lines))
        return "\n".join(lines).strip()

    if "certificate" in norm and not any(k in norm for k in ["publication", "appendix"]):
        lines = ["## Certificate\n\nThis is to certify that the project report entitled:"]
        lines.append(f"\n### \"{proj_title}\"\n")
        named_members = [
            f"{m.get('name', '').strip()}" + (f" (PRN: {m.get('prn', '').strip()})" if m.get("prn") else "")
            for m in members
            if isinstance(m, dict) and m.get("name", "").strip()
        ]
        if named_members:
            lines.append(
                f"Submitted by **{', '.join(named_members)}** is a bonafide work carried out under guidance and supervision in partial fulfillment of the academic requirements.\n"
            )
        else:
            lines.append(
                "Submitted by **____________________** is a bonafide work carried out under guidance and supervision in partial fulfillment of the academic requirements.\n"
            )

        lines.append("**Signatures:**\n")
        lines.append(f"- **Project Guide:** {guide if guide else '____________________'}")
        lines.append(f"- **Project Coordinator:** {coord if coord else '____________________'}")
        lines.append(f"- **Head of Department:** {hod if hod else '____________________'}")
        lines.append(f"- **Principal / Dean:** {dean if dean else '____________________'}")
        lines.append("- **Internal / External Examiner:** ____________________")
        if dept or univ:
            lines.append(f"\n*{', '.join(filter(None, [dept, univ]))}*")
        return "\n".join(lines).strip()

    if "acknowledgement" in norm:
        lines = [
            "## Acknowledgements\n\n"
            "We take immense pride and pleasure in presenting this project report. "
            "First and foremost, we express our profound gratitude to our project guide"
            + (f", **{guide}**" if guide else "")
            + ", whose relentless encouragement, constructive criticism, and expert technical mentorship guided us through every stage of this work.\n\n"
            "We convey our sincere thanks to the Project Coordinator"
            + (f", **{coord}**" if coord else "")
            + ", and to the Head of Department"
            + (f", **{hod}**" if hod else "")
            + (f", Department of {dept}" if dept else "")
            + ", for providing excellent laboratory infrastructure, technical facilities, and continuous administrative support.\n\n"
            "We are equally indebted to the Principal / Dean"
            + (f", **{dean}**" if dean else "")
            + (f", {univ}" if univ else "")
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
        return (
            "## List of Figures\n\n"
            "| Figure No. | Figure Caption |\n"
            "| :--- | :--- |\n"
            "| Fig. 4.1 | System Architecture Overview Diagram |\n"
            "| Fig. 4.2 | High-Level Design (HLD) Modular Architecture |\n"
            "| Fig. 4.3 | Low-Level Design (LLD) Component Flow |\n"
            "| Fig. 4.4 | System Use Case & Execution Sequence Diagram |\n"
            "| Fig. 4.5 | Entity-Relationship (ER) Schema Diagram |\n"
            "| Fig. 6.1 | Work Breakdown Structure (WBS) Diagram |\n"
            "| Fig. 6.2 | Project Timeline and Milestones Gantt Chart |\n"
            "| Fig. 7.1 | Multi-Agent Execution Pipeline Flowchart |\n"
            "| Fig. 7.2 | Database Schema & Data Dictionary Flow |"
        )

    if "list of tables" in norm:
        return (
            "## List of Tables\n\n"
            "| Table No. | Table Caption |\n"
            "| :--- | :--- |\n"
            "| Table 3.1 | Functional Requirements Specification Matrix |\n"
            "| Table 3.2 | External Interface & API Requirements |\n"
            "| Table 3.3 | Non-Functional Requirements (Performance & Security) |\n"
            "| Table 5.1 | Comprehensive Technology Stack Matrix |\n"
            "| Table 5.2 | Comparison of Frontend, Backend & Database Choices |\n"
            "| Table 6.1 | Team Roles, Allocation & Effort Estimation |\n"
            "| Table 6.2 | Project Risk Management & Mitigation Matrix |\n"
            "| Table 7.1 | Database Design & Data Dictionary |\n"
            "| Table 8.1 | Master Test Suite, Execution Plan & Test Cases |\n"
            "| Table 9.1 | System Comparison with Existing Solutions |"
        )

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
        return (
            "## Appendix B: Glossary\n\n"
            "| Term | Definition |\n"
            "| :--- | :--- |\n"
            "| **LLM** | Large Language Model (e.g. Llama-3.3-70b-versatile via Groq). |\n"
            "| **Agent** | Autonomous software entity that reasons, invokes tools, and collaborates across workflows. |\n"
            "| **LangGraph** | Multi-agent state orchestration framework based on state machines and directed cycles. |\n"
            "| **FastAPI** | High-performance Python web framework for asynchronous REST endpoints and Server-Sent Events. |\n"
            "| **Tavily** | Search engine API optimized for factual AI retrieval and web source extraction. |\n"
            "| **SRS** | Software Requirements Specification defining system functionality and constraints. |\n"
            "| **HLD / LLD** | High-Level Design and Low-Level Design architectural specifications. |\n"
            "| **SSE** | Server-Sent Events protocol for real-time progress streaming. |"
        )

    if "references" in norm:
        return None  # Compiled automatically from cited sources

    return None


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

    # Sanitize outline section titles to replace [Domain] and [Project]
    for s in sections:
        t = str(s.get("title", ""))
        if "[Domain]" in t or "[Project]" in t:
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
- End strictly with a final line: "Keywords: keyword1, keyword2, keyword3, keyword4, keyword5"

Project Facts (Ground Truth):
{project_fact_sheet}

Output format:
## Abstract

[Your ~250-word plain text abstract body]

Keywords: [5-7 comma-separated domain keywords]"""
            try:
                abs_text, abs_usage = robust_generate_text(
                    abs_prompt,
                    is_easy=False,
                    temperature=0.2,
                    max_tokens=600,
                    on_rate_limit=notify_rate_limit,
                )
                add_tokens(abs_usage.get("input_tokens", 0), abs_usage.get("output_tokens", 0))
                fm_text = abs_text.strip()
            except DailyTokenLimitError as dt_err:
                raise dt_err
            except Exception as exc:
                logger.warning("Abstract generation failed: %s", exc)
                fm_text = f"## Abstract\n\nThis project presents the design, analysis, and implementation of {proj_name}.\n\nKeywords: {proj_name}, software architecture, system analysis, implementation"

            # Clean and sanitize abstract
            fm_text = sanitize_section_markdown(fm_text, domain_name, proj_name)
            if not fm_text.strip().startswith("#"):
                fm_text = f"## Abstract\n\n{fm_text.strip()}"
            if "Keywords:" not in fm_text:
                fm_text += f"\n\nKeywords: {proj_name}, software architecture, engineering implementation, analysis, system evaluation"

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
            search_query = f"{topic} domain overview industry architecture" if actual_ch_num == 1 else f"{topic} research papers literature survey methodology"
            try:
                with tavily_lock:
                    tavily_call_count[0] += 1
                    logger.info("Tavily search executed for Chapter %d: query='%s', run total=%d", actual_ch_num, search_query, tavily_call_count[0])
                raw = _collect_sources(search_query)
                # Filter out other people's personal github repos
                for s in raw:
                    u = s.get("url", "").lower()
                    if "github.com/" in u and not any(k in u for k in ["langchain-ai", "fastapi", "tiangolo", "facebookresearch"]):
                        if not ("github" in topic.lower()):
                            continue
                    chapter_sources.append(s)
                chapter_sources = chapter_sources[:4]
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
                ch_facts, usage = robust_generate_text(
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
                ch_facts = f"- Domain foundations and background context of {topic}."
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

            # If container H1 heading, format with introductory roadmap paragraph
            if sec_lvl == 1:
                intro_text = (
                    f"# {sec_title}\n\n"
                    f"This chapter presents a comprehensive overview of {sec_title.replace('Chapter ', '')} "
                    f"for the {proj_name} platform, establishing key principles, methodologies, and engineering specifications."
                )
                intro_text = sanitize_section_markdown(intro_text, domain_name, proj_name, sources=chapter_sources)
                rendered_subsections.append((s_idx, intro_text))
                persist_section_to_db(s_idx, intro_text)
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
                f"- Numbering: format figure captions strictly as 'Fig. {actual_ch_num}.N: [Description]' and table captions as 'Table {actual_ch_num}.N: [Description]'. Refer to them as 'Fig. {actual_ch_num}.N' and 'Table {actual_ch_num}.N' in text.",
                f"- Diagrams: Where a diagram is needed (architecture, ERD, sequence, flowchart, Gantt), insert a clean placeholder without ASCII boxes or backtick fences: '> [Insert diagram here: Fig. {actual_ch_num}.N - Description]'.",
                "- Citations: Do NOT invent author-year citations like (Smith, 2024). Use numeric IEEE citations like [1], [2] where referencing domain concepts, or plain technical description.",
                "- Do NOT generate a Sources or References section; that will be compiled at the end.",
            ]

            if actual_ch_num >= 3:
                rules.append(
                    "- GROUND TRUTH CONSTRAINT (CRITICAL):\n"
                    "  * The Project Facts below are the ONLY allowed source for how the system works.\n"
                    "  * NEVER name agents, tools, libraries, versions, servers, CI/CD, backups, endpoints or test IDs that are not in the project facts.\n"
                    "  * If any specific detail, metric, test case, or configuration is not provided, explicitly write '[Add your ...]'. Never invent fake benchmarks or test figures."
                )

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

            # Set max_tokens per section from its word target (words * 1.6 + 100)
            sec_max_tokens = max(250, int(sec_target * 1.6 + 100))

            sec_md = ""
            for attempt in range(1, 3):
                try:
                    sec_md, u = robust_generate_text(
                        writer_prompt,
                        is_easy=is_easy_section,
                        temperature=0.25,
                        max_tokens=sec_max_tokens,
                        on_rate_limit=notify_rate_limit,
                    )
                    add_tokens(u.get("input_tokens", 0), u.get("output_tokens", 0))

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
                                max_tokens=max(200, int(sec_target * 0.8 + 60)),
                                on_rate_limit=notify_rate_limit,
                            )
                            add_tokens(cont_u.get("input_tokens", 0), cont_u.get("output_tokens", 0))
                            cont_clean = cont_text.strip()
                            if cont_clean:
                                sec_md = sec_md.rstrip() + " " + cont_clean.lstrip()
                        except Exception as cont_err:
                            logger.warning("Continuation for '%s' failed: %s", sec_title, cont_err)

                    # Reject canned boilerplate or severe truncation (regenerate once)
                    if is_canned_boilerplate(sec_md, sec_target) and attempt == 1:
                        logger.warning("Section '%s' matched boilerplate or was too short (%d words). Regenerating...", sec_title, len(sec_md.split()))
                        writer_prompt += "\n\nREWRITE NOTE: Avoid generic boilerplate like 'leverages a modular multi-agent architecture'. Provide specific engineering depth or use '[Add your ...]'."
                        continue

                    break
                except DailyTokenLimitError as dt_err:
                    raise dt_err
                except Exception as exc:
                    logger.warning("Writing section '%s' attempt %d failed: %s", sec_title, attempt, exc)
                    time.sleep(1.5 * attempt)

            if not sec_md:
                sec_md = f"{heading_prefix} {sec_title}\n\n[Add your technical details and implementation specifications for {sec_title} here.]"

            # Post-process: sanitize markdown, remove fences, remove ASCII boxes, fill tokens
            sec_md = sanitize_section_markdown(sec_md, domain_name, proj_name, sources=chapter_sources)

            # Ensure section ends with a full stop
            if sec_md and sec_md[-1] not in ".!?\":\n":
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
    raw_markdown = sanitize_section_markdown(raw_markdown, domain_name, proj_name, sources=all_sources)

    # Clean and renumber citations gaplessly
    renumbered_markdown, final_sources = filter_and_renumber_sources(raw_markdown, all_sources)

    # Filter out external GitHub repos from final_sources unless topic is about GitHub
    if not ("github" in topic.lower()):
        final_sources = [
            s for s in final_sources
            if not ("github.com/" in s.get("url", "").lower() and not any(k in s.get("url", "").lower() for k in ["langchain-ai", "fastapi", "tiangolo", "facebookresearch"]))
        ]

    # Replace References section with formatted IEEE bibliography
    ieee_refs = ["## References\n"]
    if final_sources:
        for i, s in enumerate(final_sources, start=1):
            s_title = s.get("title", "Reference Source").strip()
            s_url = s.get("url", "").strip()
            if s_url:
                ieee_refs.append(f"[{i}] {s_title}, Available: {s_url}")
            else:
                ieee_refs.append(f"[{i}] {s_title}")
    else:
        ieee_refs.append(f"[1] {proj_name} Technical Specification and System Documentation, 2026.")
        ieee_refs.append("[2] Multi-Agent Workflow and Graph Orchestration Reference, 2026.")
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
    )
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
