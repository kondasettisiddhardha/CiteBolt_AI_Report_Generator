"""Text normalization and report helpers for Dossier."""

from __future__ import annotations

import re
from typing import Any

_CONTROL_OR_ZERO_WIDTH = re.compile(
    r"[\u200b\u200c\u200d\u200e\u200f\u202a-\u202e\u2060-\u2069\ufeff\u00ad]"
    r"|\x00-\x1f"
    r"|\x7f",
)

_NORMALIZE_SUBSTITUTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\u2010|\u2011|\u2012"), "-"),
]


def normalize_text(markdown: str) -> str:
    if not markdown:
        return ""
    lines: list[str] = []
    for line in markdown.splitlines(keepends=True):
        for pattern in (
            _LINETABLE_START,
            _LINETABLE_END,
        ):
            line = pattern.sub("", line)
        lines.append(line)
    text = "".join(lines)

    text = _CONTROL_OR_ZERO_WIDTH.sub("", text)
    text = text.replace("\u00a0", " ")
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')

    for pattern, replacement in _NORMALIZE_SUBSTITUTIONS:
        text = pattern.sub(replacement, text)

    text = text.replace("\u2010", "-").replace("\u2011", "-").replace("\u2012", "-")

    _EM_START = re.compile(r"^(\u2014|\u2013|\u2012)")
    _EM_END = re.compile(r"(\u2014|\u2013|\u2012)$")
    text = _EM_START.sub("-", text, count=1)
    text = _EM_END.sub("-", text, count=1)

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def clean_title(raw: str, fallback_topic: str = "") -> str:
    value = normalize_text(raw or "")
    value = value.strip().strip("#").strip().strip('"').strip("'").strip()
    value = value.rstrip(".")

    stripped = _IMPERATIVE_PREFIXES.sub("", value).strip(" :.-\t")
    if stripped and stripped.lower() != value.lower():
        value = stripped

    if len(value.split()) > 16:
        value = " ".join(value.split()[:16]).rstrip(",;:")

    lowered = value.lower()
    if not value or lowered.startswith(("here is", "here's", "report:", "title:")):
        value = normalize_text(fallback_topic).strip().rstrip(".")
        stripped = _IMPERATIVE_PREFIXES.sub("", value).strip(" :.-\t")
        if stripped:
            value = stripped

    if not value:
        value = "Report"

    if value.isupper() or value.islower():
        value = " ".join(
            word.capitalize() if word.islower() else word for word in value.split()
        )
    return value


def prepare_report(
    report_markdown: str,
    sources: list[dict[str, Any]] | None = None,
    topic: str = "",
) -> tuple[str, str]:
    normalized = normalize_text(report_markdown or "")
    if not normalized:
        title = clean_title("", fallback_topic=topic)
        return title, ""

    lines = normalized.splitlines()
    raw_title = ""
    title_idx = -1

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# ") or re.match(r"^#\s+", stripped):
            raw_title = re.sub(r"^#\s+", "", stripped)
            title_idx = idx
            break
        break

    if title_idx != -1:
        remaining = lines[:title_idx] + lines[title_idx + 1 :]
        cleaned_markdown = "\n".join(remaining).strip()
    else:
        cleaned_markdown = normalized.strip()

    title = clean_title(raw_title, fallback_topic=topic)
    return title, cleaned_markdown


def _normalise_sources_list(
    sources: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    for position, src in enumerate(sources or [], start=1):
        if not isinstance(src, dict):
            continue
        url = str(src.get("url") or "").strip()
        title = str(src.get("title") or url or "Untitled source").strip()
        try:
            orig_id = int(src.get("id") or src.get("index") or position)
        except (TypeError, ValueError):
            orig_id = position
        key = url.lower().rstrip("/") or title.lower()
        if key in seen:
            seen[key]["orig_ids"].append(orig_id)
            continue
        entry = {**src, "title": title, "url": url, "orig_ids": [orig_id]}
        seen[key] = entry
        cleaned.append(entry)
    for new_id, entry in enumerate(cleaned, start=1):
        entry["id"] = new_id
    return cleaned


_HEADING_LINE = re.compile(r"^(#{2,3})\s+(.+?)(?:\s*\{#([\w-]+)\})?\s*$")
_WORD_TOKENS = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’-]*")


def word_count(text: str) -> int:
    if not text:
        return 0
    body = strip_sources_section(text or "")
    return len(_WORD_TOKENS.findall(body))


def heading_tree(markdown: str) -> list[dict[str, Any]]:
    headings: list[dict[str, Any]] = []
    anchor_crawler: dict[str, int] = {}
    for line in (markdown or "").splitlines():
        match = _HEADING_LINE.match(line)
        if not match:
            continue
        level = match.group(1)
        if level not in ("##", "###"):
            continue
        level = 2 if level == "##" else 3
        text = normalize_text(match.group(2).strip())
        raw_id = match.group(3)
        anchor = raw_id.lower() if raw_id else slug(text)
        if anchor in anchor_crawler:
            anchor_crawler[anchor] += 1
            anchor = f"{anchor}-{anchor_crawler[anchor]}"
        else:
            anchor_crawler[anchor] = 0
        headings.append({"level": level, "text": text, "id": anchor})
    return headings


_CITATION_PATTERN = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)*)\]")


def renumber_citations(markdown: str, sources: list[dict[str, Any]] | None) -> str:
    if not markdown:
        return ""
    if not sources:
        return _CITATION_PATTERN.sub("", markdown)

    mapping: dict[int, int] = {}
    has_orig_ids = False
    for entry in sources:
        if isinstance(entry, dict):
            new_id = entry.get("id") or entry.get("number") or entry.get("n")
            if new_id is not None:
                try:
                    new_id_int = int(new_id)
                except (ValueError, TypeError):
                    continue
                orig_ids = entry.get("orig_ids")
                if orig_ids and isinstance(orig_ids, list):
                    has_orig_ids = True
                    for old in orig_ids:
                        try:
                            mapping[int(old)] = new_id_int
                        except (ValueError, TypeError):
                            pass
                else:
                    mapping[new_id_int] = new_id_int

    if has_orig_ids and mapping:
        def replace_mapped(match: re.Match[str]) -> str:
            olds = [int(x) for x in re.split(r"[,;]\s*", match.group(1)) if x.strip().isdigit()]
            news = sorted({mapping[o] for o in olds if o in mapping})
            return "".join(f"[{n}]" for n in news)

        return _CITATION_PATTERN.sub(replace_mapped, markdown)

    valid: set[int] = set(mapping.keys()) if mapping else set(range(1, len(sources) + 1))
    citation_order: list[int] = []
    found: set[int] = set()
    for match in re.finditer(r"\[(\d{1,3})\]", markdown):
        n = int(match.group(1))
        if n in valid and n not in found:
            citation_order.append(n)
            found.add(n)

    if not citation_order:
        return _CITATION_PATTERN.sub("", markdown)

    renumber_map: dict[int, int] = {old: i + 1 for i, old in enumerate(citation_order)}

    def replace_order(match: re.Match[str]) -> str:
        raw = match.group(1)
        if raw.isdigit():
            n = int(raw)
            return f"[{renumber_map[n]}]" if n in renumber_map else ""
        return ""

    return re.sub(r"\[\d{1,3}\]", replace_order, markdown)


def is_formal_table(block: str) -> bool:
    if not block.strip():
        return False
    rows = [r.strip() for r in block.strip().splitlines() if r.strip().startswith("|")]
    if len(rows) < 3:
        return False
    if not _SEP_MATCH.match(rows[1].strip()):
        return False
    width = len(rows[0].strip("|").split("|"))
    return all(len(r.strip("|").split("|")) == width for r in rows)


def guarantees_table(block: str, min_columns: int = 2) -> str:
    rows = [r.strip() for r in block.strip().splitlines() if r.strip().startswith("|")]
    if not rows or len(rows) < 3:
        return ""
    if not _SEP_MATCH.match(rows[1].strip()):
        return ""
    columns = len(rows[0].strip("|").split("|"))
    if columns < min_columns:
        return ""
    for row in rows[2:]:
        if len(row.strip("|").split("|")) != columns:
            return ""
    return block


def strip_sources_section(markdown: str) -> str:
    if not markdown:
        return ""
    lines = markdown.splitlines()
    kept: list[str] = []
    dropping = False
    for line in lines:
        stripped = line.strip().lower()
        if re.match(r"^#{1,3}\s*(sources|references|bibliography|citations)\b", stripped):
            dropping = True
            continue
        if dropping and re.match(r"^#{1,3}\s+\S", line.strip()):
            dropping = False
        if not dropping:
            kept.append(line)
    return "\n".join(kept).strip()


def strip_leading_title(markdown: str) -> str:
    if not markdown:
        return ""
    lines = markdown.splitlines()
    if lines and re.match(r"^#\s+", lines[0].strip()):
        return "\n".join(lines[1:]).strip()
    return "\n".join(lines).strip()


def source_description(source: dict[str, Any]) -> str:
    text = normalize_text(str(source.get("content") or source.get("snippet") or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    sentence = re.split(r"(?<=[.!?])\s", text, 1)[0]
    if len(sentence) > 160:
        sentence = sentence[:157].rstrip() + "..."
    return sentence


def domain_of(url: str) -> str:
    m = re.match(r"^https?://([^/]+)", url or "")
    return m.group(1).removeprefix("www.") if m else ""


def build_sources_markdown(sources: list[dict[str, Any]]) -> str:
    lines: list[str] = ["## Sources", ""]
    for i, s in enumerate(sources, start=1):
        title = normalize_text(str(s.get("title") or f"Source {i}"))
        url = str(s.get("url") or "")
        desc = source_description(s)
        entry = f"{i}. [{title}]({url})"
        if url:
            entry += f" — {domain_of(url)}"
        if desc:
            entry += f": {desc}"
        lines.append(entry)
    return "\n".join(lines) + "\n"


def slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", normalize_text(s).lower())
    s = re.sub(r"^-|-$", "", s)
    return s or "section"


def slide_in(
    sources: list[dict[str, Any]], heading_id: str, word_count: int
) -> dict[str, Any]:
    return {
        "n": 1,
        "title": heading_id,
        "word_count": word_count,
        "source_count": len(sources),
    }


def build_source_entries(sources: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for idx, raw in enumerate(sources or [], start=1):
        item: dict[str, Any] = {
            "n": idx,
            "title": normalize_text(str(raw.get("title") or f"Source {idx}")),
            "url": str(raw.get("url") or ""),
            "domain": domain_of(str(raw.get("url") or "")),
        }
        item["year"] = _year_of(str(raw.get("pub_date") or raw.get("published") or ""))
        items.append(item)
    return items


def _year_of(text: str) -> str:
    m = re.search(r"\b(1\d{3}|20\d{2})\b", text)
    return m.group(1) if m else ""


_IMPERATIVE_PREFIXES = re.compile(
    r"^(?:(?:write|generate|create|produce|build|make|draft|summarize|research|give)\s+"
    r"(?:me\s+)?(?:a|an|the)?\s*)?"
    r"(?:(?:report|brief|article|overview|summary|analysis)\s*(?:about|on|for|:)?\s*)?",
    re.IGNORECASE,
)

_HEADING_START = re.compile(r"^#{2,3}\s+")
_HEADING_END = re.compile(r"[\u2014\u2013\u2012]$")
_LINETABLE_START = re.compile(r"^(\u2014|\u2013|\u2012)")
_LINETABLE_END = re.compile(r"^(\u2014|\u2013|\u2012)")

_SEP_MATCH = re.compile(r"^\s*\|[\s:\-|]+\|\s*$")
