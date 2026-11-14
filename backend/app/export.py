"""Report exports.

PDF is rendered with WeasyPrint from the HTML/CSS in app/templates, using the
bundled Inter font. Word is built with python-docx using real heading styles,
a shaded Executive Summary table, list styles, hyperlinks and a page-number
footer. Both read the same normalised markdown, title and structured sources.
"""

from __future__ import annotations

import datetime as dt
import html
import io
import json
import re
from pathlib import Path
from typing import Any

from jinja2 import Template
from markdown_it import MarkdownIt
from pypdf import PdfReader, PdfWriter

from app.text import (
    domain_of,
    normalize_text,
    source_description,
    strip_leading_title,
    strip_sources_section,
)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = BASE_DIR / "templates"
FONTS = BASE_DIR / "assets" / "fonts"

REPORT_TYPE_LABELS = {
    "auto": "Research report",
    "briefing": "Briefing",
    "deepdive": "Deep dive",
    "architectureblueprint": "Architecture blueprint",
    "researchpaper": "Research paper",
}

_CITATION = re.compile(r"\[(\d{1,3})\]")


# --- shared helpers ---------------------------------------------------
def _markdown() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": True, "linkify": False})
    md.enable(["table", "strikethrough"])
    return md


def _as_html(markdown: str, source_count: int) -> str:
    """Markdown → HTML with citation markers turned into footnote links."""
    md = _markdown()

    def cite(match: re.Match[str]) -> str:
        number = int(match.group(1))
        if not 1 <= number <= source_count:
            return ""
        return f'<sup class="cite"><a href="#source-{number}">{number}</a></sup>'

    with_cites = _CITATION.sub(cite, markdown or "")
    return md.render(with_cites)


def _split_summary(markdown: str) -> tuple[str, str]:
    """Pull the Executive Summary out of the body so it can be a callout."""
    lines = (markdown or "").splitlines()
    start = None
    for index, line in enumerate(lines):
        if re.match(r"^#{2,3}\s*executive summary\s*$", line.strip(), re.IGNORECASE):
            start = index
            break
    if start is None:
        return "", (markdown or "").strip()

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.match(r"^#{1,3}\s+\S", lines[index].strip()):
            end = index
            break

    summary = "\n".join(lines[start + 1 : end]).strip()
    body = "\n".join(lines[:start] + lines[end:]).strip()
    return summary, body


def _structured_sources(sources: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    items = []
    for index, source in enumerate(sources or [], start=1):
        url = str(source.get("url") or "")
        items.append(
            {
                "number": index,
                "title": normalize_text(str(source.get("title") or f"Source {index}")),
                "url": url,
                "domain": domain_of(url),
                "description": source_description(source),
            }
        )
    return items


def _meta_values(
    title: str,
    topic: str,
    report_type: str | None,
    sources: list[dict[str, Any]],
) -> dict[str, str]:
    today = dt.date.today().strftime("%d %B %Y")
    return {
        "title": normalize_text(title) or "Research report",
        "topic": normalize_text(topic or ""),
        "date": today,
        "report_type": REPORT_TYPE_LABELS.get((report_type or "auto").lower(), "Research report"),
        "sources_count": str(len(sources)),
        "sources_label": f"{len(sources)} source" + ("" if len(sources) == 1 else "s"),
    }


# --- PDF --------------------------------------------------------------
def _md_inline_to_reportlab(text: str) -> str:
    escaped = html.escape(text or "")
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"\*(.+?)\*", r"<i>\1</i>", escaped)
    escaped = re.sub(r"`([^`]+)`", r'<font face="Courier">\1</font>', escaped)
    escaped = re.sub(
        r"\[(\d{1,3})\]",
        r'<super><font color="#0d9488"><b>[\1]</b></font></super>',
        escaped,
    )
    escaped = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        r'<a href="\2" color="#0d9488"><u>\1</u></a>',
        escaped,
    )
    return escaped


def _render_pdf_reportlab(
    title: str,
    topic: str,
    report_type: str,
    summary_md: str,
    body_md: str,
    structured: list[dict[str, Any]],
    meta: dict[str, str],
) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    from reportlab.platypus import (
        HRFlowable,
        KeepTogether,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    font_regular = "Helvetica"
    font_bold = "Helvetica-Bold"
    try:
        regular_path = FONTS / "Inter-Regular.ttf"
        bold_path = FONTS / "Inter-Bold.ttf"
        if regular_path.is_file() and bold_path.is_file():
            pdfmetrics.registerFont(TTFont("Inter", str(regular_path)))
            pdfmetrics.registerFont(TTFont("Inter-Bold", str(bold_path)))
            font_regular = "Inter"
            font_bold = "Inter-Bold"
    except Exception:
        pass

    buffer = io.BytesIO()
    margin = 44
    printable_width = A4[0] - (margin * 2)

    class NumberedCanvas(canvas.Canvas):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._saved_page_states: list[dict[str, Any]] = []

        def showPage(self) -> None:
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            num_pages = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self.saveState()
                self.setFont(font_regular, 8)
                self.setFillColor(colors.HexColor("#9ca3af"))
                self.drawString(margin, 26, "Citebolt — research, distilled")
                self.drawRightString(A4[0] - margin, 26, f"Page {self._pageNumber} of {num_pages}")
                self.setStrokeColor(colors.HexColor("#e5e7eb"))
                self.setLineWidth(0.5)
                self.line(margin, 36, A4[0] - margin, 36)
                self.restoreState()
                super().showPage()
            super().save()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
    )

    eyebrow_style = ParagraphStyle(
        "Eyebrow",
        fontName=font_bold,
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#0d9488"),
        spaceAfter=4,
    )
    title_style = ParagraphStyle(
        "Title",
        fontName=font_bold,
        fontSize=22,
        leading=26,
        textColor=colors.HexColor("#111827"),
        spaceAfter=6,
    )
    meta_style = ParagraphStyle(
        "Meta",
        fontName=font_regular,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#6b7280"),
        spaceAfter=14,
    )
    summary_title_style = ParagraphStyle(
        "SummaryTitle",
        fontName=font_bold,
        fontSize=12,
        leading=16,
        textColor=colors.HexColor("#0f766e"),
        spaceAfter=6,
    )
    summary_p_style = ParagraphStyle(
        "SummaryBody",
        fontName=font_regular,
        fontSize=9.5,
        leading=14,
        textColor=colors.HexColor("#1f2937"),
        spaceAfter=6,
    )
    h1_style = ParagraphStyle(
        "Heading1",
        fontName=font_bold,
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#111827"),
        spaceBefore=14,
        spaceAfter=6,
        keepWithNext=True,
    )
    h2_style = ParagraphStyle(
        "Heading2",
        fontName=font_bold,
        fontSize=13,
        leading=17,
        textColor=colors.HexColor("#111827"),
        spaceBefore=12,
        spaceAfter=5,
        keepWithNext=True,
    )
    h3_style = ParagraphStyle(
        "Heading3",
        fontName=font_bold,
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#374151"),
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True,
    )
    body_style = ParagraphStyle(
        "Body",
        fontName=font_regular,
        fontSize=10,
        leading=14.5,
        textColor=colors.HexColor("#1f2937"),
        spaceAfter=7,
    )
    bullet_style = ParagraphStyle(
        "Bullet",
        fontName=font_regular,
        fontSize=10,
        leading=14.5,
        textColor=colors.HexColor("#1f2937"),
        leftIndent=14,
        firstLineIndent=-10,
        spaceAfter=4,
    )
    source_title_style = ParagraphStyle(
        "SourceTitle",
        fontName=font_bold,
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor("#111827"),
        spaceAfter=1,
    )
    source_url_style = ParagraphStyle(
        "SourceUrl",
        fontName=font_regular,
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#0d9488"),
        spaceAfter=2,
    )
    source_desc_style = ParagraphStyle(
        "SourceDesc",
        fontName=font_regular,
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#4b5563"),
        spaceAfter=6,
    )
    table_cell_style = ParagraphStyle(
        "TableCell",
        fontName=font_regular,
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor("#1f2937"),
    )
    table_cell_bold = ParagraphStyle(
        "TableCellBold",
        fontName=font_bold,
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor("#111827"),
    )

    story: list[Any] = []

    # Header block
    story.append(Paragraph('<font color="#0f766e"><b>CITE</b></font><font color="#171717"><b>BOLT</b></font> <font color="#8a8a8a"><b>RESEARCH REPORT</b></font>', eyebrow_style))
    story.append(Paragraph(_md_inline_to_reportlab(title), title_style))
    meta_line = " &middot; ".join(
        filter(None, [meta.get("date"), meta.get("report_type"), meta.get("sources_label"), meta.get("topic")])
    )
    story.append(Paragraph(meta_line, meta_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e5e7eb"), spaceAfter=14))

    # Executive summary
    if summary_md:
        summary_elements: list[Any] = [Paragraph("Executive Summary", summary_title_style)]
        for p_text in _plain_blocks(summary_md):
            summary_elements.append(Paragraph(_md_inline_to_reportlab(p_text), summary_p_style))
        summary_table = Table([[summary_elements]], colWidths=[printable_width])
        summary_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0fdfa")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#99f6e4")),
                ("ROUNDEDCORNERS", [4, 4, 4, 4]),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ])
        )
        story.append(summary_table)
        story.append(Spacer(1, 14))

    # Body elements
    for block in _body_blocks(body_md):
        kind = block["kind"]
        text = block.get("text", "")
        if kind == "table":
            raw_rows = block.get("rows", [])
            if raw_rows:
                num_cols = max(len(r) for r in raw_rows)
                col_width = printable_width / num_cols if num_cols else printable_width
                table_data = []
                for row_idx, r in enumerate(raw_rows):
                    row_cells = []
                    style_to_use = table_cell_bold if row_idx == 0 else table_cell_style
                    for cell in r:
                        row_cells.append(Paragraph(_md_inline_to_reportlab(cell), style_to_use))
                    while len(row_cells) < num_cols:
                        row_cells.append(Paragraph("", style_to_use))
                    table_data.append(row_cells)
                t = Table(table_data, colWidths=[col_width] * num_cols)
                t.setStyle(
                    TableStyle([
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f8fafc")),
                        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#cbd5e1")),
                        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ])
                )
                story.append(Spacer(1, 6))
                story.append(t)
                story.append(Spacer(1, 8))
        elif kind == "h1":
            story.append(Paragraph(_md_inline_to_reportlab(text), h1_style))
        elif kind == "h2":
            story.append(Paragraph(_md_inline_to_reportlab(text), h2_style))
        elif kind == "h3":
            story.append(Paragraph(_md_inline_to_reportlab(text), h3_style))
        elif kind == "bullet":
            story.append(Paragraph("&bull; " + _md_inline_to_reportlab(text), bullet_style))
        elif kind == "number":
            story.append(Paragraph(_md_inline_to_reportlab(text), bullet_style))
        else:
            story.append(Paragraph(_md_inline_to_reportlab(text), body_style))

    # Sources section
    if structured:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Sources", h2_style))
        for s in structured:
            s_title = _md_inline_to_reportlab(s["title"])
            s_num = s["number"]
            s_url = s["url"]
            s_domain = s.get("domain", "")
            s_desc = _md_inline_to_reportlab(s.get("description", ""))

            src_header = f"<b>[{s_num}]</b> {s_title}"
            if s_domain:
                src_header += f' <font color="#9ca3af">&mdash; {html.escape(s_domain)}</font>'
            story.append(Paragraph(src_header, source_title_style))
            if s_url:
                story.append(Paragraph(f'<a href="{s_url}" color="#0d9488">{html.escape(s_url)}</a>', source_url_style))
            if s_desc:
                story.append(Paragraph(s_desc, source_desc_style))

    doc.build(story, canvasmaker=NumberedCanvas)
    return buffer.getvalue()


def markdown_to_pdf(
    markdown: str,
    topic: str = "",
    sources: list[dict[str, Any]] | None = None,
    *,
    title: str = "",
    report_type: str = "auto",
) -> bytes:
    """Render the report to a styled A4 PDF."""
    structured = _structured_sources(sources)
    # The stored markdown ends with a Sources list for the app/markdown export;
    # PDF and Word build their own from structured data.
    clean = strip_sources_section(strip_leading_title(normalize_text(markdown)))
    summary_md, body_md = _split_summary(clean)
    meta = _meta_values(title or topic, topic, report_type, structured)

    use_weasyprint = False
    try:
        from weasyprint import HTML  # imported lazily so the app starts without it
        use_weasyprint = True
    except (ImportError, OSError):
        use_weasyprint = False

    if use_weasyprint:
        try:
            template = Template((TEMPLATES / "report.html").read_text(encoding="utf-8"))
            document = template.render(
                **meta,
                description=f"{meta['title']} — a Citebolt research report.",
                stylesheet=(TEMPLATES / "report.css").as_uri(),
                summary=_as_html(summary_md, len(structured)) if summary_md else "",
                body=_as_html(body_md, len(structured)),
                sources=structured,
            )

            buffer = io.BytesIO()
            HTML(string=document, base_url=str(BASE_DIR)).write_pdf(
                buffer,
                presentational_hints=False,
                metadata_title=meta["title"],
            )

            # WeasyPrint does not write document dates, so set the full metadata here.
            buffer.seek(0)
            reader = PdfReader(buffer)
            writer = PdfWriter()
            writer.append(reader)
            writer.add_metadata(
                {
                    "/Title": meta["title"],
                    "/Author": "Citebolt",
                    "/Creator": "Citebolt",
                    "/Producer": "Citebolt",
                    "/CreationDate": dt.datetime.now().strftime("D:%Y%m%d%H%M%S"),
                    "/ModDate": dt.datetime.now().strftime("D:%Y%m%d%H%M%S"),
                }
            )
            output = io.BytesIO()
            writer.write(output)
            return output.getvalue()
        except Exception:
            pass

    # Fallback to pure-Python ReportLab
    return _render_pdf_reportlab(
        title=meta["title"],
        topic=meta["topic"],
        report_type=meta["report_type"],
        summary_md=summary_md,
        body_md=body_md,
        structured=structured,
        meta=meta,
    )


# --- Word -------------------------------------------------------------
def _add_hyperlink(paragraph, url: str, text: str, color: str = "4F46E5") -> None:
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    part = paragraph.part
    relationship_id = part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )

    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), relationship_id)

    run = OxmlElement("w:r")
    properties = OxmlElement("w:rPr")
    run_color = OxmlElement("w:color")
    run_color.set(qn("w:val"), color)
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    properties.append(run_color)
    properties.append(underline)
    run.append(properties)

    text_element = OxmlElement("w:t")
    text_element.text = text
    run.append(text_element)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def _shade_cell(cell, fill: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:color"), "auto")
    shading.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shading)


def _add_page_header(section) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    header = section.header
    paragraph = header.paragraphs[0]
    paragraph.text = ""
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    run1 = paragraph.add_run("CITE")
    run1.bold = True
    run1.font.size = Pt(8.5)
    run1.font.color.rgb = RGBColor(0x0F, 0x76, 0x6E)

    run2 = paragraph.add_run("BOLT")
    run2.bold = True
    run2.font.size = Pt(8.5)
    run2.font.color.rgb = RGBColor(0x17, 0x17, 0x17)


def _add_page_footer(section, title: str) -> None:
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor

    footer = section.footer
    paragraph = footer.paragraphs[0]
    paragraph.text = ""
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    run1 = paragraph.add_run("CITE")
    run1.bold = True
    run1.font.size = Pt(8.5)
    run1.font.color.rgb = RGBColor(0x0F, 0x76, 0x6E)

    run2 = paragraph.add_run("BOLT  ·  ")
    run2.bold = True
    run2.font.size = Pt(8.5)
    run2.font.color.rgb = RGBColor(0x17, 0x17, 0x17)

    field_run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = "PAGE"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    field_run._r.append(begin)
    field_run._r.append(instruction)
    field_run._r.append(end)

    paragraph.add_run(f"  ·  {title}")


def markdown_to_docx(
    markdown: str,
    title: str = "",
    sources: list[dict[str, Any]] | None = None,
    *,
    topic: str = "",
    report_type: str = "auto",
) -> bytes:
    """Render the report to a styled .docx document."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor, Cm

    structured = _structured_sources(sources)
    clean = strip_sources_section(strip_leading_title(normalize_text(markdown)))
    summary_md, body_md = _split_summary(clean)
    meta = _meta_values(title or topic, topic, report_type, structured)

    document = Document()
    section = document.sections[0]
    section.top_margin = Cm(2.2)
    section.bottom_margin = Cm(2.2)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)

    styles = document.styles
    normal = styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    normal.paragraph_format.line_spacing = 1.15
    normal.paragraph_format.space_after = Pt(6)

    for name, size in (("Heading 1", 16), ("Heading 2", 13), ("Heading 3", 11.5)):
        style = styles[name]
        style.font.name = "Calibri"
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor(0x11, 0x11, 0x13)
        style.paragraph_format.space_before = Pt(12)
        style.paragraph_format.space_after = Pt(4)

    # --- title block ---
    eyebrow = document.add_paragraph()
    eyebrow_cite = eyebrow.add_run("CITE")
    eyebrow_cite.font.size = Pt(8)
    eyebrow_cite.font.bold = True
    eyebrow_cite.font.color.rgb = RGBColor(0x0F, 0x76, 0x6E)
    eyebrow_bolt = eyebrow.add_run("BOLT ")
    eyebrow_bolt.font.size = Pt(8)
    eyebrow_bolt.font.bold = True
    eyebrow_bolt.font.color.rgb = RGBColor(0x17, 0x17, 0x17)
    eyebrow_rest = eyebrow.add_run("RESEARCH REPORT")
    eyebrow_rest.font.size = Pt(8)
    eyebrow_rest.font.bold = True
    eyebrow_rest.font.color.rgb = RGBColor(0x8A, 0x8A, 0x8A)
    eyebrow.paragraph_format.space_after = Pt(2)

    heading = document.add_paragraph(style="Heading 1")
    heading.paragraph_format.space_before = Pt(0)
    title_run = heading.add_run(meta["title"])
    title_run.font.size = Pt(24)
    title_run.font.bold = True
    title_run.font.color.rgb = RGBColor(0x11, 0x11, 0x13)
    heading.paragraph_format.space_after = Pt(4)

    meta_paragraph = document.add_paragraph()
    meta_text = "  ·  ".join(
        [meta["date"], meta["report_type"], meta["sources_label"], meta["topic"]]
    )
    meta_run = meta_paragraph.add_run(meta_text)
    meta_run.font.size = Pt(8.5)
    meta_run.font.color.rgb = RGBColor(0x6B, 0x6B, 0x72)
    meta_paragraph.paragraph_format.space_after = Pt(14)

    # --- executive summary callout (shaded single-cell table) ---
    if summary_md:
        table = document.add_table(rows=1, cols=1)
        table.autofit = True
        cell = table.cell(0, 0)
        _shade_cell(cell, "F5F5FF")
        cell.paragraphs[0].text = ""
        summary_heading = cell.paragraphs[0]
        summary_run = summary_heading.add_run("Executive Summary")
        summary_run.font.bold = True
        summary_run.font.size = Pt(12)
        summary_run.font.color.rgb = RGBColor(0x31, 0x2E, 0x81)

        for block in _plain_blocks(summary_md):
            paragraph = cell.add_paragraph(block)
            paragraph.paragraph_format.space_after = Pt(4)

        document.add_paragraph()

    # --- body ---
    for block in _body_blocks(body_md):
        kind = block["kind"]
        payload = block.get("text", "")
        if kind == "table":
            _add_table(document, block["rows"])
        elif kind == "h1":
            document.add_heading(payload, level=1)
        elif kind == "h2":
            document.add_heading(payload, level=2)
        elif kind == "h3":
            document.add_heading(payload, level=3)
        elif kind == "bullet":
            paragraph = document.add_paragraph(style="List Bullet")
            _add_inline(paragraph, payload)
        elif kind == "number":
            paragraph = document.add_paragraph(style="List Number")
            _add_inline(paragraph, payload)
        else:
            paragraph = document.add_paragraph()
            _add_inline(paragraph, payload)

    # --- sources ---
    if structured:
        document.add_heading("Sources", level=2)
        for source in structured:
            paragraph = document.add_paragraph(style="List Number")
            if source["url"]:
                _add_hyperlink(paragraph, source["url"], source["title"])
            else:
                paragraph.add_run(source["title"]).bold = True
            if source["domain"]:
                domain_run = paragraph.add_run(f" — {source['domain']}")
                domain_run.font.color.rgb = RGBColor(0x8A, 0x8A, 0x8A)
            if source["url"]:
                url_paragraph = document.add_paragraph()
                url_run = url_paragraph.add_run(source["url"])
                url_run.font.size = Pt(8)
                url_run.font.color.rgb = RGBColor(0x6B, 0x6B, 0x72)
                url_paragraph.paragraph_format.space_after = Pt(2)
            if source["description"]:
                description_paragraph = document.add_paragraph()
                description_run = description_paragraph.add_run(source["description"])
                description_run.font.size = Pt(9)
                description_run.font.color.rgb = RGBColor(0x4B, 0x4B, 0x52)
                description_paragraph.paragraph_format.space_after = Pt(8)

    _add_page_header(section)
    _add_page_footer(section, meta["title"])
    document.core_properties.author = "Citebolt"

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CITE = re.compile(r"\[(\d{1,3})\]")


def _add_inline(paragraph, text: str) -> None:
    """Add text, keeping **bold** runs and rendering [n] as a superscript."""
    from docx.shared import Pt, RGBColor

    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", text)
    position = 0

    def emit(chunk: str, bold: bool = False) -> None:
        cursor = 0
        for cite in _CITE.finditer(chunk):
            if cite.start() > cursor:
                run = paragraph.add_run(chunk[cursor : cite.start()])
                run.bold = bold
            run = paragraph.add_run(cite.group(1))
            run.bold = bold
            run.font.superscript = True
            run.font.size = Pt(8)
            run.font.color.rgb = RGBColor(0x4F, 0x46, 0xE5)
            cursor = cite.end()
        if cursor < len(chunk):
            run = paragraph.add_run(chunk[cursor:])
            run.bold = bold

    for match in _BOLD.finditer(text):
        if match.start() > position:
            emit(text[position : match.start()])
        emit(match.group(1), bold=True)
        position = match.end()
    if position < len(text):
        emit(text[position:])


def _add_table(document, rows: list[list[str]]) -> None:
    """Add a Markdown table as a real Word table with a shaded header."""
    from docx.shared import Pt, RGBColor

    if not rows:
        return
    columns = max(len(row) for row in rows)
    table = document.add_table(rows=len(rows), cols=columns)
    table.style = "Table Grid"
    table.autofit = True

    for row_index, row in enumerate(rows):
        for column in range(columns):
            cell = table.cell(row_index, column)
            cell.text = ""
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(2)
            value = row[column] if column < len(row) else ""
            run = paragraph.add_run(value)
            run.font.size = Pt(9)
            if row_index == 0:
                run.bold = True
                _shade_cell(cell, "F4F4F6")
            elif row_index % 2 == 0:
                _shade_cell(cell, "FAFAFC")
    document.add_paragraph().paragraph_format.space_after = Pt(2)
    _ = RGBColor  # keep the import used for type checkers


def _plain_blocks(markdown: str) -> list[str]:
    blocks = []
    for block in re.split(r"\n\s*\n", markdown or ""):
        text = block.strip()
        if not text:
            continue
        text = re.sub(r"^[-*]\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", text)
        text = text.replace("**", "")
        blocks.append(text)
    return blocks


def _body_blocks(markdown: str) -> list[dict[str, str]]:
    """Split markdown into headings, bullets and paragraphs for python-docx."""
    blocks: list[dict[str, str]] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            blocks.append({"kind": "p", "text": " ".join(paragraph).strip()})
            paragraph.clear()

    for raw_line in (markdown or "").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped:
            flush()
            continue

        if stripped.startswith("### "):
            flush()
            blocks.append({"kind": "h3", "text": stripped[4:]})
        elif stripped.startswith("## "):
            flush()
            blocks.append({"kind": "h2", "text": stripped[3:]})
        elif stripped.startswith("# "):
            flush()
            blocks.append({"kind": "h1", "text": stripped[2:]})
        elif re.match(r"^[-*]\s+", stripped):
            flush()
            blocks.append({"kind": "bullet", "text": re.sub(r"^[-*]\s+", "", stripped)})
        elif re.match(r"^\d+[.)]\s+", stripped):
            flush()
            blocks.append({"kind": "number", "text": re.sub(r"^\d+[.)]\s+", "", stripped)})
        elif stripped.startswith("|"):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if all(set(cell) <= set("-: ") for cell in cells):
                continue
            if blocks and blocks[-1]["kind"] == "table":
                blocks[-1]["rows"].append(cells)  # type: ignore[union-attr]
            else:
                flush()
                blocks.append({"kind": "table", "rows": [cells]})  # type: ignore[dict-item]
        else:
            paragraph.append(stripped)

    flush()
    return [block for block in blocks if block.get("text") or block.get("rows")]


# Backwards-compatible aliases for older imports.
md_to_docx = markdown_to_docx


def sources_json(sources: list[dict[str, Any]] | None) -> str:
    return json.dumps(sources or [], ensure_ascii=False)
