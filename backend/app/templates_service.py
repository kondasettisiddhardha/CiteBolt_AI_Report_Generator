"""Template extraction and outline parsing service.

Extracts heading structures from PDF, DOCX, and Markdown reference files.
Never persists reference document body text; temp files are cleaned up immediately.
"""

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile
import pypdf
import docx

from app.llm import generate_text

logger = logging.getLogger("citebolt.templates")

MAX_TEMPLATE_FILE_BYTES = 10 * 1024 * 1024  # 10 MB


def clean_title(text: str) -> str:
    cleaned = re.sub(r"^[\d\.\-\)\s]+", "", text.strip())
    return cleaned.strip()


def distribute_words(sections: list[dict[str, Any]], target_total: int = 4000) -> list[dict[str, Any]]:
    """Distribute target word count across outline sections."""
    if not sections:
        return []
    n = len(sections)
    # Weight level 1 slightly more than level 2 or 3
    weights = [3 if s.get("level", 1) == 1 else 2 for s in sections]
    total_weight = sum(weights) or 1
    
    result = []
    allocated = 0
    for i, s in enumerate(sections):
        weight = weights[i]
        words = max(150, round((weight / total_weight) * target_total / 25) * 25)
        allocated += words
        result.append({
            "level": s.get("level", 1),
            "title": clean_title(s.get("title", f"Section {i + 1}")),
            "suggested_words": words,
        })
    return result


def extract_outline_from_md(content: str) -> tuple[str, list[dict[str, Any]]]:
    lines = content.splitlines()
    doc_title = ""
    sections: list[dict[str, Any]] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# ") and not doc_title:
            doc_title = clean_title(stripped[2:])
            sections.append({"level": 1, "title": doc_title})
        elif stripped.startswith("# "):
            sections.append({"level": 1, "title": clean_title(stripped[2:])})
        elif stripped.startswith("## "):
            sections.append({"level": 2, "title": clean_title(stripped[3:])})
        elif stripped.startswith("### "):
            sections.append({"level": 3, "title": clean_title(stripped[4:])})

    if not sections:
        # Fallback to lines that look like headings
        for line in lines[:50]:
            stripped = line.strip()
            if stripped and len(stripped) < 80 and not stripped.endswith("."):
                sections.append({"level": 1, "title": clean_title(stripped)})
                if len(sections) >= 6:
                    break

    return doc_title or "Untitled Document", sections


def extract_outline_from_docx(file_path: Path) -> tuple[str, list[dict[str, Any]]]:
    doc = docx.Document(file_path)
    doc_title = (doc.core_properties.title or "").strip()
    sections: list[dict[str, Any]] = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style_name = para.style.name.lower()
        if "heading 1" in style_name or style_name == "title":
            if not doc_title and style_name == "title":
                doc_title = clean_title(text)
            sections.append({"level": 1, "title": clean_title(text)})
        elif "heading 2" in style_name:
            sections.append({"level": 2, "title": clean_title(text)})
        elif "heading 3" in style_name:
            sections.append({"level": 3, "title": clean_title(text)})

    # Fallback to bold paragraphs if no styled headings found
    if not sections:
        for para in doc.paragraphs:
            text = para.text.strip()
            if not text or len(text) > 90:
                continue
            is_bold = any(run.bold for run in para.runs if run.text.strip())
            if is_bold:
                sections.append({"level": 1, "title": clean_title(text)})

    return doc_title or "Untitled Document", sections


def _traverse_pdf_outline(outline_items: list[Any], level: int = 1) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for item in outline_items:
        if isinstance(item, list):
            sections.extend(_traverse_pdf_outline(item, level=min(3, level + 1)))
        elif hasattr(item, "title") and item.title:
            sections.append({"level": min(3, level), "title": clean_title(str(item.title))})
    return sections


def extract_outline_from_pdf(file_path: Path) -> tuple[str, list[dict[str, Any]]]:
    reader = pypdf.PdfReader(file_path)
    num_pages = len(reader.pages)
    if num_pages == 0:
        raise HTTPException(
            status_code=400,
            detail="The uploaded PDF file has no pages.",
        )

    # 1. Check for text layer to catch scanned PDFs immediately
    total_chars = 0
    extracted_sample_texts: list[str] = []
    for i in range(min(num_pages, 5)):
        txt = reader.pages[i].extract_text() or ""
        total_chars += len(txt.strip())
        extracted_sample_texts.append(txt)

    if total_chars < 15:
        # Check all remaining pages if short
        for i in range(5, min(num_pages, 15)):
            txt = reader.pages[i].extract_text() or ""
            total_chars += len(txt.strip())

    if total_chars < 15:
        raise HTTPException(
            status_code=400,
            detail="This document appears to be a scanned image without a text layer. Please upload a document with selectable text.",
        )

    meta = reader.metadata or {}
    doc_title = clean_title(str(meta.get("/Title", "") or ""))

    # 2. Try native PDF bookmarks / outline
    try:
        pdf_outline = reader.outline
        if pdf_outline:
            sections = _traverse_pdf_outline(pdf_outline)
            if sections:
                return doc_title or sections[0]["title"], sections
    except Exception as exc:
        logger.warning("Could not read PDF outline bookmarks: %s", exc)

    # 3. Detect headings by font heuristics from first pages
    headings: list[dict[str, Any]] = []
    try:
        for page_idx in range(min(num_pages, 10)):
            page = reader.pages[page_idx]
            font_sizes: list[tuple[float, str]] = []

            def visitor_body(text: str, cm: Any, tm: Any, font_dict: Any, font_size: float) -> None:
                stripped = text.strip()
                if stripped and len(stripped) < 90:
                    font_sizes.append((font_size, stripped))

            page.extract_text(visitor_text=visitor_body)
            if font_sizes:
                # Group consecutive text fragments of large font sizes
                avg_size = sum(fs[0] for fs in font_sizes) / len(font_sizes)
                for size, txt in font_sizes:
                    if size > avg_size * 1.25 and len(txt) > 3 and not txt.isdigit():
                        lvl = 1 if size > avg_size * 1.5 else 2
                        cleaned = clean_title(txt)
                        if cleaned and not any(h["title"] == cleaned for h in headings):
                            headings.append({"level": lvl, "title": cleaned})
    except Exception as exc:
        logger.warning("Font heuristic extraction failed: %s", exc)

    if len(headings) >= 3:
        return doc_title or headings[0]["title"], headings

    # 4. LLM fallback on extracted text sample from the first few pages
    sample_text = "\n\n".join(extracted_sample_texts)[:4000]
    prompt = (
        "You are an outline extraction expert. Extract ONLY the hierarchical sections/headings "
        "of the following document text as an ordered JSON list. Do not include body text or explanations.\n\n"
        "Document excerpt:\n"
        f"\"\"\"\n{sample_text}\n\"\"\"\n\n"
        "Return ONLY a valid JSON array of objects with keys 'level' (integer 1, 2, or 3) and 'title' (string), like:\n"
        "[{\"level\": 1, \"title\": \"Introduction\"}, {\"level\": 2, \"title\": \"Background\"}]"
    )
    try:
        raw_json, _ = generate_text(prompt, temperature=0.1)
        # Parse JSON array from response
        match = re.search(r"\[.*\]", raw_json, re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list) and len(parsed) > 0:
                parsed_sections = [
                    {"level": int(item.get("level", 1)), "title": clean_title(str(item.get("title", "")))}
                    for item in parsed
                    if item.get("title")
                ]
                if parsed_sections:
                    return doc_title or parsed_sections[0]["title"], parsed_sections
    except Exception as exc:
        logger.warning("LLM outline inference failed: %s", exc)

    # 5. Final fallback: split sample by common structural headings or lines
    lines = [clean_title(l) for l in sample_text.splitlines() if 3 < len(l.strip()) < 70]
    fallback_sections = [{"level": 1, "title": l} for l in lines[:8]]
    return doc_title or "Custom Document Template", fallback_sections


async def extract_outline_from_upload(file: UploadFile) -> dict[str, Any]:
    """Process an uploaded reference document, extract heading structure only, and immediately remove temp file."""
    filename = file.filename or "reference"
    ext = Path(filename).suffix.lower()

    if ext not in {".pdf", ".docx", ".md"}:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file format. Please upload a .pdf, .docx, or .md file.",
        )

    # Read bytes safely with size check
    content = await file.read()
    if len(content) > MAX_TEMPLATE_FILE_BYTES:
        raise HTTPException(
            status_code=400,
            detail="The uploaded file exceeds the 10 MB limit.",
        )
    if len(content) == 0:
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is empty.",
        )

    # Create temporary file for parsing
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        if ext == ".md":
            text_str = content.decode("utf-8", errors="replace")
            doc_title, sections = extract_outline_from_md(text_str)
        elif ext == ".docx":
            doc_title, sections = extract_outline_from_docx(tmp_path)
        else:  # .pdf
            doc_title, sections = extract_outline_from_pdf(tmp_path)
    finally:
        # ALWAYS delete the reference document file immediately! Never store body text!
        try:
            if tmp_path.exists():
                os.remove(tmp_path)
        except Exception as exc:
            logger.warning("Failed to remove temp file %s: %s", tmp_path, exc)

    if not doc_title or doc_title == "Untitled Document":
        doc_title = clean_title(Path(filename).stem.replace("_", " ").replace("-", " "))

    if not sections:
        # Default standard sections if none could be extracted
        sections = [
            {"level": 1, "title": "Executive Summary"},
            {"level": 1, "title": "Background and Objectives"},
            {"level": 1, "title": "Core Analysis"},
            {"level": 1, "title": "Findings and Trade-offs"},
            {"level": 1, "title": "Recommendations and Next Steps"},
        ]

    outline_with_words = distribute_words(sections, target_total=4000)
    return {
        "title": doc_title,
        "outline": outline_with_words,
    }
