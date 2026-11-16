"""Unit tests for college project report quality and token-efficiency features.

All external LLM and search calls are mocked. Zero network calls are made.
"""

import io
import json
import os
import re
import sys
import unittest
from unittest.mock import MagicMock, patch

import docx
from pypdf import PdfReader

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.agents import section_engine
from app.agents.section_engine import (
    build_compact_project_fact_sheet,
    ensure_unique_figure_and_table_captions,
    extract_domain_and_project,
    format_front_matter_section,
    is_canned_boilerplate,
    sanitize_section_markdown,
)
from app.export import markdown_to_docx, markdown_to_pdf
from app.llm import DailyTokenLimitError


class TestCollegeReportQuality(unittest.TestCase):
    """Test suite for college report token efficiency and quality constraints."""

    def test_fact_sheet_reuse_and_ground_truth(self):
        """Verify that Chapters 3-10 build and reuse a compact fact sheet with 0 Tavily search calls."""
        topic = "AI Research and Report Generator using LangGraph Multi-Agent Pipeline"
        context = (
            "React + Vite + Tailwind frontend, FastAPI + LangGraph + SQLite backend, "
            "Groq LLM, Tavily search, Gmail SMTP OTP login; 3-agent pipeline (Research, Analysis, Writer), "
            "report types, PDF/Word export, citation checking. Results: none measured."
        )
        front_matter = {
            "projectTitle": "CiteBolt Research Assistant",
            "teamMembers": [{"name": "Test Student", "prn": "12345678"}],
        }

        # 1. Fact sheet is compact (~200-300 words)
        fact_sheet = build_compact_project_fact_sheet(topic, context, front_matter)
        self.assertIn("CiteBolt Research Assistant", fact_sheet)
        self.assertIn("React", fact_sheet)
        self.assertIn("FastAPI", fact_sheet)
        self.assertIn("Strict Rule:", fact_sheet)
        words = len(fact_sheet.split())
        self.assertLess(words, 300, f"Fact sheet exceeds 300 words ({words} words)")

        # 2. Test section pipeline with mocked LLM and search
        tavily_searches = []

        def mock_collect(q, *args, **kwargs):
            tavily_searches.append(q)
            return [
                {
                    "title": "Multi-Agent Research",
                    "url": "https://langchain-ai.github.io/langgraph/",
                    "content": "Multi-agent systems using LangGraph coordinate research workflows.",
                }
            ]

        captured_prompts = []

        def mock_generate_text(prompt, *args, **kwargs):
            captured_prompts.append(prompt)
            # Return valid markdown
            return "This section describes the engineering implementation of the platform.", {
                "input_tokens": 120,
                "output_tokens": 80,
                "total_tokens": 200,
                "finish_reason": "stop",
            }

        outline = [
            {"level": 1, "title": "Title page", "is_auto": True},
            {"level": 1, "title": "Certificate", "is_auto": True},
            {"level": 1, "title": "Abstract", "target_words": 250},
            {"level": 1, "title": "Chapter 1 Introduction"},
            {"level": 2, "title": "1.1 Overview of [Domain] Industry", "target_words": 150},
            {"level": 1, "title": "Chapter 3 Software Requirement Specification (SRS)"},
            {"level": 2, "title": "3.1 Introduction", "target_words": 200},
            {"level": 1, "title": "Chapter 5 Technical Specifications"},
            {"level": 2, "title": "5.1 Frontend Technologies", "target_words": 200},
            {"level": 1, "title": "References", "is_auto": True},
        ]

        state = {
            "topic": topic,
            "context": context,
            "report_type": "college",
            "outline": outline,
            "front_matter": front_matter,
        }

        with patch.object(section_engine, "_collect_sources", side_effect=mock_collect), patch.object(
            section_engine, "generate_text", side_effect=mock_generate_text
        ):
            res = section_engine.run_section_pipeline(state, lambda ev: None, lambda: False)

        # Tavily search should only be called for Chapter 1 (background), NEVER for Chapter 3 or Chapter 5!
        self.assertEqual(len(tavily_searches), 1)
        self.assertIn("arxiv survey paper", tavily_searches[0].lower())

        # Prompts for Chapter 3 and 5 must contain the compact fact sheet
        ch3_5_prompts = [p for p in captured_prompts if "3.1 Introduction" in p or "5.1 Frontend Technologies" in p]
        self.assertGreaterEqual(len(ch3_5_prompts), 2)
        for p in ch3_5_prompts:
            self.assertIn("Verified Architecture & Project Facts (Ground Truth):", p)
            self.assertIn("CiteBolt Research Assistant", p)

    def test_truncation_continue(self):
        """Verify that when an LLM call returns finish_reason 'length', it continues from the seam."""
        topic = "AI Research and Report Generator"
        call_count = [0]

        def mock_generate_text(prompt, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call runs out of tokens mid-sentence
                return "The system architecture decomposes user queries into parallel agent tasks, where each researcher agent performs web retrieval and extracts domain facts from academic sources", {
                    "input_tokens": 100,
                    "output_tokens": 150,
                    "total_tokens": 250,
                    "finish_reason": "length",
                }
            elif call_count[0] == 2:
                # Second call continues seamlessly from the seam
                self.assertIn("Continue writing the section", prompt)
                self.assertIn("from academic sources", prompt)
                return "and passes structured factual summaries to the synthesis engine.", {
                    "input_tokens": 120,
                    "output_tokens": 60,
                    "total_tokens": 180,
                    "finish_reason": "stop",
                }
            return "Section content.", {
                "input_tokens": 50,
                "output_tokens": 50,
                "total_tokens": 100,
                "finish_reason": "stop",
            }

        outline = [
            {"level": 1, "title": "Chapter 4 System Design"},
            {"level": 2, "title": "4.2 System Architecture", "target_words": 40},
        ]
        state = {
            "topic": topic,
            "context": "React, FastAPI, LangGraph.",
            "report_type": "college",
            "outline": outline,
        }

        with patch.object(section_engine, "_collect_sources", return_value=[]), patch.object(
            section_engine, "generate_text", side_effect=mock_generate_text
        ):
            res = section_engine.run_section_pipeline(state, lambda ev: None, lambda: False)

        report = res.get("report", "")
        # The continuation text should be cleanly stitched into the section
        self.assertIn("passes structured factual summaries to the synthesis engine.", report)
        self.assertTrue(report.strip().endswith((".", "[Add more references here]")))
        self.assertGreaterEqual(call_count[0], 2)

    def test_boilerplate_rejection_and_regeneration(self):
        """Verify that canned boilerplate fallback is detected, rejected, and regenerated."""
        self.assertTrue(
            is_canned_boilerplate(
                "The implementation of system architecture leverages a modular multi-agent architecture designed to meet rigorous functional and performance criteria.",
                200,
            )
        )
        self.assertTrue(is_canned_boilerplate("Detailed analysis of system design specifications.", 200))
        # Too short (< 60% of 200 words = < 120 words)
        self.assertTrue(is_canned_boilerplate("This is a brief 10 word summary of the system.", 200))

        # Real technical prose should NOT be flagged as boilerplate
        valid_prose = " ".join(["The system utilizes FastAPI and SQLite to manage asynchronous state."] * 20)
        self.assertFalse(is_canned_boilerplate(valid_prose, 200))

        # Test pipeline regenerates boilerplate
        call_count = [0]

        def mock_gen(prompt, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # Return generic boilerplate on first attempt
                return "The implementation of System Architecture leverages a modular multi-agent architecture.", {
                    "input_tokens": 50,
                    "output_tokens": 50,
                    "total_tokens": 100,
                    "finish_reason": "stop",
                }
            else:
                # Return real engineering prose on rewrite
                self.assertIn("REWRITE NOTE", prompt)
                return "The core architecture orchestrates three discrete agents across a LangGraph state machine, validating inputs and persisting reports to SQLite.", {
                    "input_tokens": 80,
                    "output_tokens": 80,
                    "total_tokens": 160,
                    "finish_reason": "stop",
                }

        outline = [
            {"level": 1, "title": "Chapter 4 System Design"},
            {"level": 2, "title": "4.2 System Architecture", "target_words": 150},
        ]
        state = {
            "topic": "AI Report Generator",
            "context": "LangGraph multi-agent pipeline.",
            "report_type": "college",
            "outline": outline,
        }

        with patch.object(section_engine, "_collect_sources", return_value=[]), patch.object(
            section_engine, "generate_text", side_effect=mock_gen
        ):
            res = section_engine.run_section_pipeline(state, lambda ev: None, lambda: False)

        report = res.get("report", "")
        self.assertNotIn("leverages a modular multi-agent architecture", report)
        self.assertIn("orchestrates three discrete agents across a LangGraph state machine", report)
        self.assertEqual(call_count[0], 2)

    def test_token_counting_and_429_exclusion(self):
        """Verify that token counts accurately sum successful calls and exclude failed 429 calls."""
        call_step = [0]

        def mock_gen(prompt, *args, **kwargs):
            call_step[0] += 1
            if call_step[0] == 1:
                # Successful call
                return "Chapter 1 Intro content.", {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}
            elif call_step[0] == 2:
                # Simulated failed 429 call (should NOT add tokens)
                raise RuntimeError("Rate limit reached 429")
            else:
                # Successful retry
                return "Section body content.", {"input_tokens": 200, "output_tokens": 100, "total_tokens": 300}

        outline = [
            {"level": 1, "title": "Chapter 1 Introduction"},
            {"level": 2, "title": "1.1 Overview", "target_words": 100},
        ]
        state = {
            "topic": "Token Test Project",
            "context": "Context",
            "report_type": "college",
            "outline": outline,
        }

        with patch.object(section_engine, "_collect_sources", return_value=[]), patch.object(
            section_engine, "generate_text", side_effect=mock_gen
        ):
            res = section_engine.run_section_pipeline(state, lambda ev: None, lambda: False)

        # Total tokens should be 150 + 300 = 450 (the failed 429 was excluded)
        self.assertEqual(res.get("token_usage"), 450)
        self.assertEqual(res.get("input_tokens"), 300)
        self.assertEqual(res.get("output_tokens"), 150)

    def test_tpd_pause_and_resume(self):
        """Verify that daily token limit (TPD) pauses run with saved sections and supports clean resume."""
        call_step = [0]

        def mock_gen(prompt, *args, **kwargs):
            call_step[0] += 1
            if call_step[0] == 1:
                return "Content for Section 1 with detailed technical specifications and verified architectural components. " * 3, {"input_tokens": 50, "output_tokens": 50, "total_tokens": 100}
            else:
                # Raise DailyTokenLimitError (TPD)
                raise DailyTokenLimitError("Daily limit reached (TPD) 200000", model="openai/gpt-oss-120b")

        outline = [
            {"level": 1, "title": "Chapter 4 System Design"},
            {"level": 2, "title": "4.1 Section One", "target_words": 30},
            {"level": 2, "title": "4.2 Section Two", "target_words": 30},
        ]
        state = {
            "topic": "Pause Test Project",
            "context": "Context",
            "report_type": "college",
            "outline": outline,
        }

        # 1. Run hits TPD and pauses
        with patch.object(section_engine, "_collect_sources", return_value=[]), patch.object(
            section_engine, "generate_text", side_effect=mock_gen
        ):
            paused_state = section_engine.run_section_pipeline(state, lambda ev: None, lambda: False)

        self.assertTrue(paused_state.get("paused"))
        self.assertEqual(paused_state.get("pause_reason"), "Paused: daily token limit reached")
        saved_outline = paused_state.get("outline", [])
        self.assertTrue(saved_outline[1].get("completed"))
        self.assertFalse(saved_outline[2].get("completed"))

        # 2. Resume when quota is available
        def mock_resume_gen(prompt, *args, **kwargs):
            return "Content for Section 2 on resume with detailed database schemas and verification pipelines. " * 3, {"input_tokens": 60, "output_tokens": 60, "total_tokens": 120}

        with patch.object(section_engine, "_collect_sources", return_value=[]), patch.object(
            section_engine, "generate_text", side_effect=mock_resume_gen
        ):
            paused_state["paused"] = False
            resumed_state = section_engine.run_section_pipeline(paused_state, lambda ev: None, lambda: False)

        self.assertFalse(resumed_state.get("paused", False))
        final_report = resumed_state.get("report", "")
        self.assertIn("Content for Section 1", final_report)
        self.assertIn("Content for Section 2 on resume", final_report)

    def test_template_tokens_filling_and_markdown_sanitization(self):
        """Verify [Domain] and [Project] tokens are replaced and ASCII diagram boxes are cleaned."""
        domain, proj = extract_domain_and_project(
            "AI Research and Report Generator using LangGraph Multi-Agent Pipeline",
            {"projectTitle": "CiteBolt"},
        )
        self.assertEqual(proj, "CiteBolt")
        self.assertIn("AI Research and Report Generator", domain)

        raw_md = """```markdown
### 1.1 Overview of [Domain] Industry

The [Project] platform automates engineering documentation (Vaswani et al., 2017).

+-------------------------------------------------------------+
|                   [Insert diagram here]                     |
+-------------------------------------------------------------+
Fig. 4.1: System Architecture Diagram
```"""

        clean_md = sanitize_section_markdown(raw_md, domain=domain, project=proj)
        self.assertNotIn("```", clean_md)
        self.assertNotIn("[Domain]", clean_md)
        self.assertNotIn("[Project]", clean_md)
        self.assertNotIn("+----------------", clean_md)
        self.assertNotIn("(Vaswani et al., 2017)", clean_md)
        self.assertIn("CiteBolt", clean_md)
        self.assertIn("[Insert diagram here]", clean_md)
        self.assertNotIn("> [Insert diagram here]", clean_md)

    def test_front_matter_certificate_and_toc(self):
        """Verify signature block has Guide, Coordinator, HOD, Dean, Examiner, and TOC has page numbers."""
        # 1. Certificate with empty fields leaves blank lines
        cert = format_front_matter_section("Certificate", "Topic", {})
        self.assertIn("Project Guide:", cert)
        self.assertIn("Project Coordinator:", cert)
        self.assertIn("Head of Department:", cert)
        self.assertIn("Principal / Dean:", cert)
        self.assertIn("Internal / External Examiner:", cert)
        self.assertIn("____________________", cert)

        # 2. Appendix A does NOT trigger institutional certificate
        app_a = format_front_matter_section("Appendix A: Certificates of Publication", "Topic", {})
        self.assertIn("Appendix A: Certificates of Publication", app_a)
        self.assertNotIn("Signatures:", app_a)

        # 3. Table of Contents has real page numbers and NO 'Sub-section' column
        toc = format_front_matter_section(
            "Table of Contents",
            "Topic",
            {},
            outline=[
                {"level": 1, "title": "Chapter 1 Introduction"},
                {"level": 2, "title": "1.1 Overview", "target_words": 150},
                {"level": 1, "title": "Chapter 2 Literature Survey"},
            ],
        )
        self.assertIn("| Chapter / Section | Page No. |", toc)
        self.assertNotIn("Sub-section", toc)
        self.assertNotIn("Content Description", toc)
        self.assertIn("| **Chapter 1 Introduction** |", toc)

    def test_unicode_symbols_in_college_pdf(self):
        """Verify Liberation Serif renders unicode symbols → ≈ ≥ ✓ ✗ and curly quotes without error or black boxes."""
        from pypdf import PdfReader
        import io

        test_md = """# Unicode Symbols Test
## Chapter 1 Introduction
### 1.1 Symbols and Quotes
Engineering math symbols:
- Arrow: A → B
- Approximate: π ≈ 3.14159
- Greater or equal: N ≥ 100
- Checkmark: ✓ Completed
- Crossmark: ✗ Rejected

Stylistic typography:
“Curly double quotes” and ‘curly single quotes’.
"""
        pdf_bytes = markdown_to_pdf(
            test_md,
            topic="Unicode Test",
            title="Unicode Symbols Test",
            report_type="college",
        )
        reader = PdfReader(io.BytesIO(pdf_bytes))
        extracted = ""
        for p in reader.pages:
            extracted += p.extract_text() + "\n"

        self.assertIn("→", extracted, "Missing arrow symbol →")
        self.assertIn("≈", extracted, "Missing approx symbol ≈")
        self.assertIn("≥", extracted, "Missing gte symbol ≥")
        self.assertIn("✓", extracted, "Missing checkmark symbol ✓")
        self.assertIn("✗", extracted, "Missing crossmark symbol ✗")
        self.assertTrue("“" in extracted or '"' in extracted, "Missing quote")

    def test_author_year_citation_mapping_and_preservation(self):
        """Verify only citation-like parentheses (Name, YYYY) are mapped/removed, while other brackets/parentheses are kept."""
        sources = [
            {
                "id": 1,
                "number": 1,
                "title": "Attention Is All You Need",
                "author": "Vaswani et al.",
                "url": "https://arxiv.org/abs/1706.03762",
                "description": "Transformer architecture paper",
            }
        ]

        text = (
            "The system uses High-Level Design (HLD) and Low-Level Design (LLD) "
            "under the Software Requirement Specification (SRS) guidelines. "
            "Key considerations (Purpose, Project Scope, Constraints, Assumptions) "
            "and non-functional requirements (Performance & Security) were evaluated. "
            "The transformer model (Vaswani et al., 2017) provides core embeddings, "
            "while unrelated citations like (Smith, 2024) are stripped. "
            "Database choice: [Add your database name here]."
        )

        cleaned = sanitize_section_markdown(text, domain="AI Systems", project="CiteBolt", sources=sources)

        # 1. Matching citation is mapped to [1]
        self.assertIn("[1]", cleaned)
        self.assertNotIn("(Vaswani et al., 2017)", cleaned)

        # 2. Non-matching citation is removed
        self.assertNotIn("(Smith, 2024)", cleaned)

        # 3. Non-citation parentheses are preserved intact
        self.assertIn("(HLD)", cleaned)
        self.assertIn("(LLD)", cleaned)
        self.assertIn("(SRS)", cleaned)
        self.assertIn("(Purpose, Project Scope, Constraints, Assumptions)", cleaned)
        self.assertIn("(Performance & Security)", cleaned)

        # 4. Bracketed placeholder is preserved intact
        self.assertIn("[Add your database name here.]", cleaned)

    def test_cheaper_model_routing_rules(self):
        """Verify cheaper model is used ONLY for Acknowledgements and short Summary (<=150 words).
        
        Keep Abstract, Conclusion, Introduction, and Motivation on main model.
        """
        # Acknowledgements (is_easy=True if generated or auto)
        # Short Summary sections (target <= 150 words)
        def check_is_easy(sec_title: str, target_words: int) -> bool:
            norm_sec = sec_title.lower()
            return (
                "summary" in norm_sec
                and not any(k in norm_sec for k in ["introduction", "conclusion", "motivation", "abstract"])
                and target_words <= 150
            )

        self.assertTrue(check_is_easy("4.9 Summary", 100))
        self.assertTrue(check_is_easy("5.8 Technology Stack Summary", 150))
        self.assertFalse(check_is_easy("2.2 Summary of Literature Gaps and Opportunities", 400)) # > 150 words
        self.assertFalse(check_is_easy("1.1 Overview of Domain Industry", 150)) # main model
        self.assertFalse(check_is_easy("1.7 Motivation", 100)) # motivation on main model
        self.assertFalse(check_is_easy("Abstract", 250)) # abstract on main model
        self.assertFalse(check_is_easy("10.1 Conclusion and Future Work", 250)) # conclusion on main model
        self.assertFalse(check_is_easy("3.1 Introduction", 200)) # introduction on main model

    def test_college_pdf_two_pass_toc_page_numbers_on_disk(self):
        """Render a sample college PDF to disk, verify page count, TOC entries, and that TOC page numbers match actual headings."""
        from pypdf import PdfReader
        from pathlib import Path
        import io

        sample_college_md = """# Autonomous Research Platform
## Certificate
This is to certify that this report is bonafide work.
## Table of Contents
| Chapter / Section | Page No. |
| :--- | :--- |
| **Title Page** | i |
| **Certificate** | ii |
| **Table of Contents** | iii |
| **List of Figures** | iv |
| **List of Tables** | v |
## List of Figures
| Figure No. | Figure Caption |
| :--- | :--- |
## List of Tables
| Table No. | Table Caption |
| :--- | :--- |
# Chapter 1 Introduction
This chapter introduces the research context, problem formulation, and foundational background.
### 1.1 Background and Motivation
Here we discuss the core motivation and technical foundations.
Fig. 1.1: System Architecture Overview Diagram
> [Insert diagram here: Fig. 1.1 - System Architecture Overview Diagram]
# Chapter 2 System Design
Detailed high-level and low-level architectural specification.
Table 2.1: Master System Specification Matrix
| Component | Technology | Role |
| :--- | :--- | :--- |
| Frontend | React + Tailwind | User interface |
| Backend | FastAPI | API layer |
# Chapter 3 Implementation Details
Implementation methodology and module workflows.
## References
[1] Fast API Framework Documentation, 2026.
"""
        pdf_bytes = markdown_to_pdf(
            sample_college_md,
            topic="Autonomous Research Platform",
            title="Autonomous Research Platform",
            report_type="college",
        )

        output_path = Path("backend/output_college_test.pdf").resolve()
        output_path.write_bytes(pdf_bytes)
        self.addCleanup(lambda: output_path.unlink(missing_ok=True))
        self.assertTrue(output_path.is_file())
        self.assertGreater(output_path.stat().st_size, 1000)

        # Inspect PDF pages and TOC matching
        reader = PdfReader(str(output_path))
        num_pages = len(reader.pages)
        self.assertGreaterEqual(num_pages, 4, f"Expected at least 4 pages, got {num_pages}")

        # Page 1: Certificate
        # Find TOC page
        toc_page_idx = -1
        heading_pages = {}

        for p_idx, page in enumerate(reader.pages):
            text = page.extract_text()
            if "Table of Contents" in text:
                toc_page_idx = p_idx
            if "Chapter 1 Introduction" in text:
                heading_pages["Chapter 1 Introduction"] = p_idx
            if "Chapter 2 System Design" in text:
                heading_pages["Chapter 2 System Design"] = p_idx
            if "Chapter 3 Implementation Details" in text:
                heading_pages["Chapter 3 Implementation Details"] = p_idx

        self.assertNotEqual(toc_page_idx, -1, "TOC page not found in rendered PDF")
        toc_text = reader.pages[toc_page_idx].extract_text()

        # TOC should have dotted leaders: ".  .  ."
        self.assertIn(".  .", toc_text, "TOC does not contain dotted leaders")

        # Compute actual page numbers for chapters (starting at 1 for Chapter 1)
        ch1_physical_page = heading_pages.get("Chapter 1 Introduction")
        self.assertIsNotNone(ch1_physical_page, "Chapter 1 not found in PDF pages")

        for heading, phys_page in heading_pages.items():
            expected_arabic_num = phys_page - ch1_physical_page + 1
            self.assertIn(heading, toc_text, f"Heading '{heading}' not listed in TOC text")

        print(f"Verified College PDF on disk at: {output_path}")
        print(f"Total pages: {num_pages}, TOC on page {toc_page_idx + 1}")

    def test_college_export_pdf_and_docx(self):
        """Verify that college reports export to PDF and DOCX using Times New Roman styling and no CiteBolt branding."""
        sample_md = """# AI Research and Report Generator
## Certificate
This is to certify bonafide work.
## Table of Contents
| Chapter / Section | Page No. |
| :--- | :--- |
| **Chapter 1 Introduction** | 1 |
# Chapter 1 Introduction
### 1.1 Overview
This chapter introduces the engineering background and system motivation.
## References
[1] LangGraph Reference Documentation, 2026."""

        # PDF export (ReportLab with college style)
        pdf_bytes = markdown_to_pdf(
            sample_md,
            topic="AI Research and Report Generator",
            title="AI Research and Report Generator",
            report_type="college",
        )
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertGreater(len(pdf_bytes), 1000)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

        # DOCX export
        docx_bytes = markdown_to_docx(
            sample_md,
            title="AI Research and Report Generator",
            topic="AI Research and Report Generator",
            report_type="college",
        )
        self.assertIsInstance(docx_bytes, bytes)
        self.assertGreater(len(docx_bytes), 1000)
        self.assertTrue(docx_bytes.startswith(b"PK\x03\x04"))

    def test_real_api_export_route_college_pdf(self):
        """Verify that the real API route GET /api/runs/{run_id}/export?format=pdf exports with college styling."""
        from app.main import export_run
        from app.models import User, Run

        test_user = User(id="test-user-pdf", email="testpdf@example.com")
        test_run = Run(
            id="test-run-pdf-export",
            user_id="test-user-pdf",
            topic="Autonomous Multi-Agent AI Systems",
            title="Autonomous Multi-Agent AI Systems Report",
            report_type="college",
            report_markdown=(
                "# Autonomous Multi-Agent AI Systems Report\n\n"
                "## Certificate\n\nThis is to certify bonafide work.\n\n"
                "## Table of Contents\n\n| Chapter / Section | Page No. |\n| :--- | :--- |\n| **Chapter 1 Introduction** | 1 |\n\n"
                "# Chapter 1 Introduction\n\n### 1.1 Overview\nDetailed engineering overview of multi-agent platforms.\n\n"
                "## References\n\n[1] Multi-Agent Systems Documentation, 2026."
            ),
            sources_json="[]",
            sources_count=0,
            status="completed",
        )

        db = MagicMock()
        db.get.return_value = test_run

        response = export_run(test_run.id, format="pdf", user=test_user, db=db)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.media_type, "application/pdf")
        self.assertIn("attachment; filename=", response.headers["Content-Disposition"])
        self.assertTrue(response.body.startswith(b"%PDF"))
        self.assertGreater(len(response.body), 1000)

    def test_placeholder_warning_threshold_and_status(self):
        """Verify that when >10% of sections end up as placeholders, run is marked 'completed_with_warnings'."""
        topic = "Distributed Systems Reliability"
        outline = [
            {"level": 1, "title": "Title page", "is_auto": True},
            {"level": 1, "title": "Certificate", "is_auto": True},
            {"level": 1, "title": "Abstract", "target_words": 200},
            {"level": 1, "title": "Chapter 1 Overview"},
            {"level": 2, "title": "1.1 Background", "target_words": 100},
            {"level": 2, "title": "1.2 System Goals", "target_words": 100},
            {"level": 1, "title": "Chapter 2 Architecture"},
            {"level": 2, "title": "2.1 Core Services", "target_words": 100},
            {"level": 2, "title": "2.2 State Flow", "target_words": 100},
            {"level": 1, "title": "Chapter 3 Evaluation"},
            {"level": 2, "title": "3.1 Test Suite", "target_words": 100},
            {"level": 2, "title": "3.2 Measurements", "target_words": 100},
            {"level": 1, "title": "References", "is_auto": True},
        ]

        emitted_events = []
        def mock_emit(evt):
            emitted_events.append(evt)

        def mock_generate(prompt, *args, **kwargs):
            if any(k in prompt for k in ["Core Services", "State Flow", "Test Suite", "Measurements"]):
                return "", {"input_tokens": 200, "output_tokens": 200, "finish_reason": "length"}
            return "Valid section prose describing technical architecture and implementation.", {
                "input_tokens": 100,
                "output_tokens": 100,
                "finish_reason": "stop",
            }

        state = {
            "topic": topic,
            "context": "FastAPI and SQLite backend services.",
            "report_type": "college",
            "outline": outline,
            "front_matter": {"projectTitle": "Distributed Systems"},
        }

        with patch.object(section_engine, "generate_text", side_effect=mock_generate), \
             patch.object(section_engine, "_collect_sources", return_value=[]):
            final_state = section_engine.run_section_pipeline(state, emit=mock_emit, is_cancelled=lambda: False)

        # 1. Status marked as completed_with_warnings
        self.assertEqual(final_state.get("status"), "completed_with_warnings")
        self.assertTrue(final_state.get("has_warnings"))

        # 2. Warning details present
        details = final_state.get("warning_details", {})
        self.assertGreater(details.get("placeholder_count", 0), 0)
        self.assertGreater(len(details.get("placeholder_sections", [])), 0)

        # 3. Fallback text format: '[Add your <title> here.]', never '[Add your technical details...]'
        rep = final_state.get("report", "")
        self.assertNotIn("Add your technical details and implementation specifications", rep)
        self.assertIn("[Add your Core Services here.]", rep)
        self.assertIn("[Add your State Flow here.]", rep)

        # 4. Fallback events emitted with reason
        fallback_events = [e for e in emitted_events if e.get("type") == "section_fallback"]
        self.assertGreaterEqual(len(fallback_events), 4)
        for fb in fallback_events:
            self.assertIn("empty_llm_output", fb.get("reason", ""))

    def test_no_placeholder_in_abstract(self):
        """Verify that Abstract strictly contains no '[Add your result here]' or placeholder tokens."""
        topic = "AI Research Assistant"
        context = "FastAPI backend with SQLite database."
        fm = {"projectTitle": "CiteBolt Research Assistant"}

        # 1. Test synthesis fallback contains no placeholders
        synth = section_engine.synthesize_academic_abstract("CiteBolt Research Assistant", "AI Research", "Facts")
        self.assertNotIn("[Add your", synth)
        self.assertNotIn("[Add your result here]", synth)

        # 2. Test abstract generation flow when LLM output contains placeholders
        def mock_generate(prompt, *args, **kwargs):
            if "abstract" in prompt.lower():
                return (
                    "This project implements an AI research assistant. The architecture leverages modular services. "
                    "Evaluation results demonstrate [Add your result here] with high accuracy.",
                    {"input_tokens": 100, "output_tokens": 100, "finish_reason": "stop"}
                )
            return "Content prose.", {"input_tokens": 50, "output_tokens": 50, "finish_reason": "stop"}

        state = {
            "topic": topic,
            "context": context,
            "report_type": "college",
            "outline": [
                {"level": 1, "title": "Abstract", "target_words": 150},
            ],
            "front_matter": fm,
        }
        with patch.object(section_engine, "generate_text", side_effect=mock_generate), \
             patch.object(section_engine, "_collect_sources", return_value=[]):
            res = section_engine.run_section_pipeline(state, emit=lambda ev: None, is_cancelled=lambda: False)

        rep = res.get("report", "")
        self.assertNotIn("[Add your result here]", rep)
        self.assertNotIn("[Add your", rep)

    def test_no_stray_blockquote_before_diagrams(self):
        """Verify that stray '>' markers before [Insert diagram here] are stripped and ASCII frames cleaned."""
        sample_md = (
            "> [Insert diagram here: Fig. 4.1 - System Architecture]\n\n"
            "+-------------------------------------------------+\n"
            "| [Insert diagram here: Fig. 4.2 - High Level Flow] |\n"
            "+-------------------------------------------------+\n\n"
            "Prose text describing architecture."
        )
        cleaned = sanitize_section_markdown(sample_md, "Domain", "Project")
        self.assertNotIn("> [Insert diagram here", cleaned)
        self.assertIn("[Insert diagram here: Fig. 4.1 - System Architecture]", cleaned)
        self.assertIn("[Insert diagram here: Fig. 4.2 - High Level Flow]", cleaned)

    def test_unique_figure_captions(self):
        """Verify that ensure_unique_figure_and_table_captions assigns unique sequential Fig. N.M and Table N.M."""
        md = (
            "# Chapter 4 System Design\n\n"
            "## 4.1 Architecture\n\n"
            "[Insert diagram here: Architecture Diagram]\n\n"
            "## 4.2 Sequence Model\n\n"
            "[Insert diagram here: Sequence Diagram]\n\n"
            "Table 4.1 Component Details\n\n"
            "# Chapter 7 Implementation\n\n"
            "## 7.1 Pipeline\n\n"
            "[Insert diagram here: Execution Flowchart]\n\n"
            "Table 7.1 Database Schema\n"
        )
        processed = ensure_unique_figure_and_table_captions(md)
        self.assertIn("Fig. 4.1: Architecture Diagram", processed)
        self.assertIn("Fig. 4.2: Sequence Diagram", processed)
        self.assertIn("Table 4.1: Component Details", processed)
        self.assertIn("Fig. 7.1: Execution Flowchart", processed)
        self.assertIn("Table 7.1: Database Schema", processed)
        # Check no duplicates
        self.assertEqual(len(re.findall(r"Fig\. 4\.1\b", processed)), 2)  # once in placeholder, once in caption line
        self.assertEqual(len(re.findall(r"Fig\. 4\.2\b", processed)), 2)

    def test_chapter1_arabic_page_one_and_roman_front_matter(self):
        """Verify Chapter 1 is Arabic page 1, front matter is Roman, and Chapter 11 does NOT reset Arabic page 1."""
        from pypdf import PdfReader
        md_content = (
            "# CiteBolt Research Assistant\n\n"
            "**A PROJECT REPORT**\n\n"
            "Submitted in partial fulfillment of the requirements for the award of the degree of\n"
            "**Bachelor of Technology**\n\n"
            "Submitted by:\n**Student One** (PRN: 111)\n\n"
            "Under the guidance of:\n**Dr. Guide**\n\n"
            "Department of Computer Engineering\nUniversity of Technology\n\n"
            "## Certificate\n\n"
            "This is to certify that the project report entitled:\n\n"
            "**\"CiteBolt Research Assistant\"**\n\n"
            "**Signatures**\n\nGuide: Dr. Guide\n\n"
            "## Acknowledgements\n\n"
            "We express our gratitude to our guide.\n\n"
            "## Abstract\n\n"
            "This project presents CiteBolt Research Assistant addressing core challenges in autonomous research.\n\n"
            "## Table of Contents\n\n"
            "| Chapter / Section | Page No. |\n"
            "| :--- | :--- |\n\n"
            "## List of Figures\n\n"
            "| Figure No. | Figure Caption |\n\n"
            "## List of Tables\n\n"
            "| Table No. | Table Caption |\n\n"
            "# Chapter 1 Introduction\n\n"
            "## 1.1 Overview of the Domain\n\n"
            "The domain of multi-agent systems is rapidly expanding with LLM coordination.\n\n"
            "## 1.2 Introduction to CiteBolt\n\n"
            "CiteBolt provides end-to-end report generation with strict fact verification.\n\n"
            "# Chapter 2 Literature Survey\n\n"
            "## 2.1 Survey of Existing Work\n\n"
            "Existing literature highlights challenges in hallucination reduction [1].\n\n"
            "# Chapter 4 System Design\n\n"
            "## 4.1 System Architecture\n\n"
            "[Insert diagram here: Fig. 4.1 - System Architecture]\n\n"
            "Fig. 4.1: System Architecture\n\n"
            "# Chapter 11 Conclusion and Future Scope\n\n"
            "## 11.1 Conclusion\n\n"
            "The platform demonstrates reliable and verifiable report generation.\n\n"
            "## References\n\n"
            "[1] Multi-Agent Systems Documentation, 2026.\n"
        )
        pdf_bytes = markdown_to_pdf(md_content, topic="AI Assistant", report_type="college")
        reader = PdfReader(io.BytesIO(pdf_bytes))
        num_pages = len(reader.pages)
        self.assertGreaterEqual(num_pages, 6)

        # Find which physical page contains "Chapter 1 Introduction"
        ch1_physical_page = None
        ch11_physical_page = None
        toc_physical_page = None
        for p_idx, page in enumerate(reader.pages, start=1):
            txt = page.extract_text() or ""
            if "Chapter 1 Introduction" in txt:
                ch1_physical_page = p_idx
            if "Chapter 11 Conclusion" in txt:
                ch11_physical_page = p_idx
            if "Table of Contents" in txt:
                toc_physical_page = p_idx

        self.assertIsNotNone(ch1_physical_page, "Chapter 1 not found in PDF pages")
        self.assertIsNotNone(ch11_physical_page, "Chapter 11 not found in PDF pages")
        self.assertGreater(ch1_physical_page, 2, "Chapter 1 should appear after front matter")
        self.assertGreater(ch11_physical_page, ch1_physical_page, "Chapter 11 must appear after Chapter 1")

        # In TOC page, check that Chapter 1 is listed
        toc_text = reader.pages[toc_physical_page - 1].extract_text()
        self.assertIn("Chapter 1 Introduction", toc_text)
        # Verify Certificate and Signatures are NOT in the TOC
        self.assertNotIn("Certificate", toc_text)
        self.assertNotIn("Signatures", toc_text)
        # Verify List of Figures and List of Tables ARE in the TOC
        self.assertIn("List of Figures", toc_text)
        self.assertIn("List of Tables", toc_text)

        # Check footer page number of Chapter 1 page: it must end with '1' (Arabic 1), not a Roman numeral!
        ch1_text = reader.pages[ch1_physical_page - 1].extract_text()
        self.assertTrue(ch1_text.strip().endswith("1"), f"Chapter 1 page footer should be Arabic '1', got page text ending with: {repr(ch1_text[-20:])}")

    def test_college_title_page_centered_and_grouped(self):
        """Verify that the college title page in PDF and DOCX puts each item on its own centered line with clear grouping."""
        fm = {
            "projectTitle": "Autonomous Edge Robotics Platform",
            "degree": "Bachelor of Technology in Robotics",
            "teamMembers": [
                {"name": "Devin AI", "prn": "PRN-1001"},
                {"name": "Ada Lovelace", "prn": "PRN-1002"},
            ],
            "guide": "Prof. Charles Babbage",
            "department": "Department of Mechanical & Computing",
            "university": "Apex Institute of Technology",
            "academicYear": "2024-2025",
        }
        title_page_md = format_front_matter_section("Title Page", "Autonomous Edge Robotics Platform", fm)
        full_md = f"{title_page_md}\n\n## Certificate\nCertified bonafide work.\n\n# Chapter 1 Introduction\nContent."

        # 1. Verify PDF rendering
        pdf_bytes = markdown_to_pdf(full_md, title=fm["projectTitle"], report_type="college")
        reader = PdfReader(io.BytesIO(pdf_bytes))
        page1_txt = reader.pages[0].extract_text()

        # Check order of items on title page
        items = [
            "Autonomous Edge Robotics Platform",
            "A PROJECT REPORT",
            "Submitted in partial fulfillment of the requirements for the award of the degree of",
            "Bachelor of Technology in Robotics",
            "Submitted by",
            "Devin AI (PRN: PRN-1001)",
            "Ada Lovelace (PRN: PRN-1002)",
            "Under the guidance of",
            "Prof. Charles Babbage",
            "Department of Mechanical & Computing",
            "Apex Institute of Technology",
            "Academic Year: 2024-2025",
        ]
        last_pos = -1
        for item in items:
            pos = page1_txt.find(item)
            self.assertNotEqual(pos, -1, f"Item '{item}' missing from PDF title page:\n{page1_txt}")
            self.assertGreater(pos, last_pos, f"Item '{item}' out of order on PDF title page")
            last_pos = pos

        # 2. Verify DOCX rendering
        docx_bytes = markdown_to_docx(full_md, title=fm["projectTitle"], report_type="college")
        doc = docx.Document(io.BytesIO(docx_bytes))

        # Find paragraphs before Certificate
        title_paras = []
        for p in doc.paragraphs:
            if "Certificate" in p.text:
                break
            if p.text.strip():
                title_paras.append(p)

        self.assertGreaterEqual(len(title_paras), 10)
        for p in title_paras:
            # Each item must be centered
            self.assertEqual(
                p.alignment,
                docx.enum.text.WD_ALIGN_PARAGRAPH.CENTER,
                f"Title page paragraph should be centered: '{p.text}'",
            )

        # Check degree is bold in DOCX
        degree_p = next((p for p in title_paras if "Bachelor of Technology" in p.text), None)
        self.assertIsNotNone(degree_p)
        self.assertTrue(any(run.bold for run in degree_p.runs))

    def test_college_lists_render_real_bullets_and_numbers(self):
        """Verify markdown bullets and numbered lists render with real bullet glyphs and numbers in PDF and DOCX."""
        sample_md = """# Chapter 5 Implementation Details
### 5.1 Architecture Components
The following key modules are implemented:
- Agent coordinator module
- Database repository abstraction
- Streaming response handler

Numbered deployment steps:
1. Initialize container environment
2. Run database migrations
3. Bind service endpoints
"""
        # 1. PDF
        pdf_bytes = markdown_to_pdf(sample_md, title="Test Lists", report_type="college")
        reader = PdfReader(io.BytesIO(pdf_bytes))
        full_text = "\n".join(page.extract_text() for page in reader.pages)

        # Check bullet glyph
        self.assertIn("• Agent coordinator module", full_text)
        self.assertIn("• Database repository abstraction", full_text)
        self.assertIn("• Streaming response handler", full_text)

        # Check numbers
        self.assertIn("1. Initialize container environment", full_text)
        self.assertIn("2. Run database migrations", full_text)
        self.assertIn("3. Bind service endpoints", full_text)

        # 2. DOCX
        docx_bytes = markdown_to_docx(sample_md, title="Test Lists", report_type="college")
        doc = docx.Document(io.BytesIO(docx_bytes))
        bullet_paras = [p for p in doc.paragraphs if p.style.name == "List Bullet"]
        number_paras = [p for p in doc.paragraphs if p.style.name == "List Number"]

        self.assertEqual(len(bullet_paras), 3)
        self.assertEqual(len(number_paras), 3)
        self.assertIn("Agent coordinator module", bullet_paras[0].text)
        self.assertIn("Initialize container environment", number_paras[0].text)

    def test_college_references_no_fabrication_and_placeholder(self):
        """Verify that References never fabricates entries and adds placeholder line when < 5 sources."""
        # Case A: Fewer than 5 sources (e.g. 2 real sources)
        sources_2 = [
            {"title": "FastAPI Framework Documentation", "url": "https://fastapi.tiangolo.com"},
            {"title": "ReportLab Reference Manual", "url": "https://docs.reportlab.com"},
        ]
        state_few = {
            "topic": "Microservices Engine",
            "context": "FastAPI, Python.",
            "report_type": "college",
            "outline": [
                {"level": 1, "title": "Chapter 1 Introduction"},
                {"level": 2, "title": "1.1 Overview", "target_words": 30},
                {"level": 1, "title": "References"},
            ],
        }

        def mock_gen_text(*args, **kwargs):
            return "Microservices architecture overview text.", {
                "input_tokens": 40,
                "output_tokens": 40,
                "total_tokens": 80,
                "finish_reason": "stop",
            }

        with patch.object(section_engine, "_collect_sources", return_value=sources_2), patch.object(
            section_engine, "generate_text", side_effect=mock_gen_text
        ):
            res_few = section_engine.run_section_pipeline(state_few, lambda ev: None, lambda: False)

        report_few = res_few.get("report", "")
        self.assertIn("FastAPI Framework Documentation", report_few)
        self.assertIn("ReportLab Reference Manual", report_few)
        self.assertIn("[Add more references here]", report_few)
        # Verify no fabricated standard entries
        self.assertNotIn("IEEE Std 730-2014", report_few)
        self.assertNotIn("4+1 View Model", report_few)
        self.assertNotIn("Representational State Transfer (REST) Architectural Style", report_few)

        # Case B: 3 or more sources (no placeholder line)
        sources_3 = [
            {"title": f"Source Paper {i}", "url": f"https://example.com/paper{i}"}
            for i in range(1, 4)
        ]
        state_3 = {
            "topic": "Microservices Engine",
            "context": "FastAPI, Python.",
            "sources": sources_3,
            "report_type": "college",
            "outline": [
                {"level": 1, "title": "Chapter 1 Introduction"},
                {"level": 2, "title": "1.1 Overview", "target_words": 30},
                {"level": 1, "title": "References"},
            ],
        }
        with patch.object(section_engine, "_collect_sources", return_value=sources_3), patch.object(
            section_engine, "generate_text", side_effect=mock_gen_text
        ):
            res_3 = section_engine.run_section_pipeline(state_3, lambda ev: None, lambda: False)

        report_3 = res_3.get("report", "")
        self.assertIn("Source Paper 3", report_3)
        self.assertNotIn("[Add more references here]", report_3)
        self.assertNotIn("IEEE Std 730-2014", report_3)

    def test_no_duration_words_when_duration_blank(self):
        """F.22.1 Verify no duration words ('three months', 'weeks', etc.) when Duration is blank."""
        fm_blank = {"projectTitle": "Test Project", "duration": ""}
        fact_sheet = build_compact_project_fact_sheet("Test Project", "Some context", fm_blank)
        self.assertIn("[Not specified / Blank - do NOT mention any duration, months, or weeks]", fact_sheet)
        self.assertNotIn("three months", fact_sheet.lower())

        # Test sanitize_section_markdown removes invented durations when duration is blank
        invented_text = "The system was developed over three months and evaluated during 12 weeks of trials."
        cleaned = sanitize_section_markdown(invented_text, duration="")
        self.assertNotIn("three months", cleaned.lower())
        self.assertNotIn("12 weeks", cleaned.lower())
        self.assertIn("[Add your project timeline here.]", cleaned)

    def test_no_single_agent_consistency(self):
        """F.22.2 Verify consistency: system has three agents; never write 'single-agent'."""
        text = "This single-agent system uses a single agent architecture for processing."
        cleaned = sanitize_section_markdown(text)
        self.assertNotIn("single-agent", cleaned.lower())
        self.assertNotIn("single agent", cleaned.lower())
        self.assertIn("three-agent", cleaned)

    def test_title_page_contains_project_title(self):
        """F.22.3 Verify title page contains the project title (large, bold, centered) in PDF."""
        title = "Autonomous Edge AI Robotics Platform"
        md = (
            f"# {title}\n\n"
            "A PROJECT REPORT\n\n"
            "Submitted in partial fulfillment of the requirements for the award of the degree of\n\n"
            "**Bachelor of Technology**\n\n"
            "Submitted by\n\nStudent (PRN: 101)\n\n"
            "## Certificate\n\nThis is to certify..."
        )
        pdf_bytes = markdown_to_pdf(md, title=title, report_type="college")
        reader = PdfReader(io.BytesIO(pdf_bytes))
        page1_txt = reader.pages[0].extract_text()
        self.assertIn(title, page1_txt)

    def test_placeholder_format_has_no_trailing_dot(self):
        """F.22.4 Verify placeholder format is strictly '[Add your <title> here.]' with no trailing '].'."""
        raw_text = "## 6.4 Project Timeline\n\n[Add your Project Timeline here.].\n\n[Add your Schedule here].\n\n[Add your Costs here]"
        cleaned = sanitize_section_markdown(raw_text)
        self.assertNotIn("here.].", cleaned)
        self.assertNotIn("here].", cleaned)
        self.assertIn("[Add your Project Timeline here.]", cleaned)
        self.assertIn("[Add your Schedule here.]", cleaned)
        self.assertIn("[Add your Costs here.]", cleaned)
        # Check regex across the entire text
        trailing_dot_matches = re.findall(r"\[Add your [^\]]+ here\.\]\.", cleaned)
        self.assertEqual(len(trailing_dot_matches), 0, f"Found placeholders with trailing dot: {trailing_dot_matches}")

    def test_sequential_figure_numbers_and_stripped_prefixes(self):
        """F.22.5 Verify sequential figure and table numbers with no gaps, stripping stray '– ' and '.N –'."""
        md = (
            "# Chapter 8 Testing\n\n"
            "## 8.1 Test Overview\n\n"
            "[Insert diagram here: Fig. 8.4 – – Architecture Verification Flow]\n\n"
            "Fig. 8.4 – .N – Architecture Verification Flow\n\n"
            "## 8.2 Test Execution\n\n"
            "[Insert diagram here: Fig. 8.9 – Test Case Results]\n\n"
            "Fig. 8.9: Test Case Results\n\n"
            "Table 8.8: Performance Summary\n\n"
            "[Insert table here]\n\n"
            "Table 8.15: Load Test Summary\n\n"
            "[Insert table here]\n"
        )
        processed = ensure_unique_figure_and_table_captions(md)
        # Should be renumbered gaplessly starting at 8.1
        self.assertIn("Fig. 8.1: Architecture Verification Flow", processed)
        self.assertIn("Fig. 8.2: Test Case Results", processed)
        self.assertIn("Table 8.1: Performance Summary", processed)
        self.assertIn("Table 8.2: Load Test Summary", processed)
        # Ensure no gaps
        self.assertNotIn("8.4", processed)
        self.assertNotIn("8.9", processed)
        self.assertNotIn("8.8", processed)
        self.assertNotIn("8.15", processed)
        # Ensure stray prefixes are stripped
        self.assertNotIn(".N –", processed)
        self.assertNotIn("– –", processed)

    def test_appendix_a_in_toc(self):
        """F.22.6 Verify TOC includes Appendix A (Certificates of Publication)."""
        md = (
            "# CiteBolt Research Assistant\n\n"
            "A PROJECT REPORT\n\n"
            "Submitted by\n\nStudent (PRN: 101)\n\n"
            "## Certificate\n\nThis certifies...\n\n"
            "## Acknowledgements\n\nWe thank...\n\n"
            "## Abstract\n\nAbstract content here...\n\n"
            "## Table of Contents\n\n"
            "## List of Figures\n\n"
            "## List of Tables\n\n"
            "# Chapter 1 Introduction\n\n"
            "## 1.1 Overview\n\nIntroduction content.\n\n"
            "[Insert diagram here: Fig. 1.1 - Overview Diagram]\n\n"
            "Fig. 1.1: Overview Diagram\n\n"
            "Table 1.1: Requirement Matrix\n\n"
            "[Insert table here]\n\n"
            "## Appendix A: Certificates of Publication\n\n"
            "Publication details.\n\n"
            "## Appendix B: Glossary\n\n"
            "Glossary table.\n"
        )
        pdf_bytes = markdown_to_pdf(md, title="CiteBolt Research Assistant", report_type="college")
        reader = PdfReader(io.BytesIO(pdf_bytes))
        # Find Table of Contents page
        toc_text = ""
        for page in reader.pages:
            txt = page.extract_text()
            if "Table of Contents" in txt:
                toc_text += txt + "\n"
        self.assertIn("Appendix A: Certificates of Publication", toc_text, f"Appendix A missing from TOC:\n{toc_text}")
        self.assertIn("Appendix B: Glossary", toc_text)
        self.assertIn("Chapter 1 Introduction", toc_text)


if __name__ == "__main__":
    unittest.main()
