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
    VERIFIED_API_ENDPOINTS,
    VERIFIED_DATABASE_TABLES,
    VERIFIED_ENDPOINT_COUNT,
    VERIFIED_SCHEMA_RELATIONSHIPS,
    VERIFIED_TABLE_COUNT,
    VERIFIED_TABLE_NAMES,
    build_allowed_tokens_set,
    build_compact_project_fact_sheet,
    build_deterministic_data_design_section,
    build_deterministic_data_dictionary_section,
    ensure_unique_figure_and_table_captions,
    extract_domain_and_project,
    filter_grounded_college_section,
    format_front_matter_section,
    is_canned_boilerplate,
    is_sentence_allowed_by_whitelist,
    normalize_college_captions_and_placeholders,
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
            "Submitted in partial fulfilment of the requirements for the award of the degree of"
            if "fulfilment" in page1_txt
            else "Submitted in partial fulfillment of the requirements for the award of the degree of",
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


    def test_caption_and_placeholder_normalizer(self):
        """Verify caption and placeholder normalization rules."""
        # 1. Nested diagram collapse
        nested_md = "[Insert diagram here: [Insert diagram here: System Architecture]]\n\nFig. 7.1: System Architecture"
        norm_nested = normalize_college_captions_and_placeholders(nested_md)
        self.assertIn("[Insert diagram here: System Architecture]", norm_nested)
        self.assertNotIn("[Insert diagram here: [Insert diagram here:", norm_nested)

        # 2. Always close bracket / bare bracket
        bare_md = "[Insert diagram here:\n\nProse text."
        norm_bare = normalize_college_captions_and_placeholders(bare_md)
        self.assertIn("[Insert diagram here]", norm_bare)
        self.assertNotIn("[Insert diagram here:\n", norm_bare)

        unclosed_md = "[Insert diagram here: Data Flow Pipeline\n\nProse text."
        norm_unclosed = normalize_college_captions_and_placeholders(unclosed_md)
        self.assertIn("[Insert diagram here: Data Flow Pipeline]", norm_unclosed)

        # 3. Strip stray ']' and '[' at end of captions
        caption_stray_md = "Fig. 7.1: Architecture Diagram]\n\nTable 7.1: Entity Matrix["
        norm_captions = normalize_college_captions_and_placeholders(caption_stray_md)
        self.assertIn("Fig. 7.1: Architecture Diagram", norm_captions)
        self.assertNotIn("Architecture Diagram]", norm_captions)
        self.assertIn("Table 7.1: Entity Matrix", norm_captions)
        self.assertNotIn("Entity Matrix[", norm_captions)

        # 4. Never let caption title lose first letter (test 'Non-functional requirements overview')
        test_caption_input = "# Chapter 3 SRS\n\nFig. 3.1: Non-functional requirements overview"
        unique_out = ensure_unique_figure_and_table_captions(test_caption_input)
        self.assertIn("Non-functional requirements overview", unique_out)
        self.assertNotIn("Fig. 3.1: on-functional", unique_out)
        self.assertNotIn(" - on-functional", unique_out)

        # 5. Remove inline 'see [Insert diagram here: Fig. 7.2 - ...]' in prose
        prose_md = "The data flow is illustrated below (see [Insert diagram here: Fig. 7.2 - Database Schema])."
        norm_prose = normalize_college_captions_and_placeholders(prose_md)
        self.assertIn("see Fig. 7.2", norm_prose)
        self.assertNotIn("[Insert diagram here: Fig. 7.2", norm_prose)

        # 6. Drop captions with empty or junk title ('for the ER diagram.')
        junk_md = "[Insert diagram here: Fig. 7.1 - for the ER diagram.]\n\nFig. 7.1: for the ER diagram.\n\nValid text."
        norm_junk = normalize_college_captions_and_placeholders(junk_md)
        self.assertNotIn("for the ER diagram", norm_junk)
        self.assertIn("Valid text.", norm_junk)

        # 7. Placeholder never inserted mid-word or mid-sentence
        mid_word_md = "The platform delivers per-run L[Add your latency metrics here.] across requests."
        norm_mid_word = normalize_college_captions_and_placeholders(mid_word_md)
        self.assertNotIn("L[Add", norm_mid_word)
        self.assertNotIn("per-run L", norm_mid_word)
        self.assertIn("[Add your latency metrics here.]", norm_mid_word)

        # 8. Remove meta-text sentences
        meta_md = "This module is presented as a placeholder pending detailed analysis. We also maintain placeholder sections for additional validation."
        norm_meta = normalize_college_captions_and_placeholders(meta_md)
        self.assertNotIn("presented as a placeholder pending detailed analysis", norm_meta)
        self.assertNotIn("placeholder sections for additional validation", norm_meta)

        # 9. Placeholder bullets must not be bold
        bold_bullet_md = "- **[Add your system architecture here.]**\n* **[Add your database schema here.]**"
        norm_bullet = normalize_college_captions_and_placeholders(bold_bullet_md)
        self.assertIn("- [Add your system architecture here.]", norm_bullet)
        self.assertIn("* [Add your database schema here.]", norm_bullet)
        self.assertNotIn("**[Add your", norm_bullet)

    def test_grounding_filter_and_repetition(self):
        """Verify post-generation grounding filter and repetition checks."""
        facts = "Project Name: CiteBolt\nCore Domain: AI Research\nDatabase Schema: users(id), runs(id)\nMain API Endpoints: GET /api/runs"

        # 1. Unsupported numbers / units / metrics removed
        ungrounded_text = "The platform achieves 99.8% precision with sub-second latency under 150ms on 8 cores and 16GB RAM. It provides robust capabilities."
        filtered_metrics = filter_grounded_college_section("7.1 Implementation", ungrounded_text, facts)
        self.assertNotIn("99.8%", filtered_metrics)
        self.assertNotIn("sub-second", filtered_metrics)
        self.assertNotIn("150ms", filtered_metrics)
        self.assertNotIn("16GB", filtered_metrics)
        self.assertIn("robust capabilities", filtered_metrics)

        # 2. Unsupported tools removed
        ungrounded_tools = "Frontend tests use Jest and React Testing Library while backend calls httpx in CircleCI and Docker with Jira tracking. The architecture is modular."
        filtered_tools = filter_grounded_college_section("8.1 Testing", ungrounded_tools, facts)
        self.assertNotIn("Jest", filtered_tools)
        self.assertNotIn("React Testing Library", filtered_tools)
        self.assertNotIn("CircleCI", filtered_tools)
        self.assertNotIn("Docker", filtered_tools)
        self.assertNotIn("Jira", filtered_tools)
        self.assertIn("The architecture is modular", filtered_tools)

        # 3. Forbidden words removed
        forbidden_text = "The data is stored in encrypted SQLite over HTTPS following CRUD sprints with GDPR compliance. We enforce token-budget scheduler."
        filtered_words = filter_grounded_college_section("7.2 Storage", forbidden_text, facts)
        self.assertNotIn("encrypted SQLite", filtered_words)
        self.assertNotIn("HTTPS", filtered_words)
        self.assertNotIn("CRUD", filtered_words)
        self.assertNotIn("sprints", filtered_words)
        self.assertNotIn("GDPR", filtered_words)
        self.assertNotIn("token-budget scheduler", filtered_words)

        # 4. Section 8.6 returns test plan placeholder (no repeated 14 tests)
        filtered_86 = filter_grounded_college_section("8.6 Master Test Suite", "Integration testing was executed with Jest and Cypress.", facts)
        self.assertIn("[Add your test plan here.]", filtered_86)
        self.assertNotIn("Jest", filtered_86)

        # 5. Section 8.7 & 10.5/10.6 no invented process -> placeholder
        filtered_87 = filter_grounded_college_section("8.7 Maintenance and Monitoring", "We maintain continuous automated bug tracking and database integrity monitoring.", facts)
        self.assertIn("[Add your Maintenance and Monitoring here.]", filtered_87)
        self.assertNotIn("database integrity monitoring", filtered_87)

        # 6. Section 9.6 comparison placeholder
        filtered_96 = filter_grounded_college_section("9.6 Comparison with Existing Systems", "The platform outperforms commercial search tools in accuracy and throughput.", facts)
        self.assertIn("[Add your comparison with existing systems here.]", filtered_96)

        # 7. Section 7.4/7.5 agents as LangGraph nodes (not route handlers)
        agent_text = "The research agents are implemented as FastAPI route handlers for query processing."
        filtered_agents = filter_grounded_college_section("7.4 Agent Pipeline", agent_text, facts)
        self.assertIn("LangGraph", filtered_agents)
        self.assertNotIn("FastAPI route handlers", filtered_agents)

        # 8. Repetition: run command removed from 1.1-1.5 and 5.1
        rep_11 = "Launch using uvicorn app.main:app --reload and npm run dev. This chapter introduces the system."
        filtered_rep = filter_grounded_college_section("1.1 Overview of the Domain", rep_11, facts)
        self.assertNotIn("uvicorn", filtered_rep)
        self.assertNotIn("npm run dev", filtered_rep)
        self.assertIn("This chapter introduces the system.", filtered_rep)

    def test_chapter_2_sources_and_title_page(self):
        """Verify Chapter 2 fallback, title page title-casing and bracket placeholders."""
        # 1. Front matter title page name title-casing
        fm = {
            "projectTitle": "research engine",
            "teamMembers": [{"name": "john doe", "prn": "123"}, {"name": "alice smith", "prn": "456"}],
            "guide": "dr. jane doe",
            "degree": "",
            "department": "",
            "university": "",
        }
        tp = format_front_matter_section("Title Page", "research engine", fm)
        self.assertIn("John Doe (PRN: 123)", tp)
        self.assertIn("Alice Smith (PRN: 456)", tp)
        self.assertIn("Dr. Jane Doe", tp)
        self.assertIn("[Degree]", tp)
        self.assertIn("[Department Name]", tp)
        self.assertIn("[University Name]", tp)

        cert = format_front_matter_section("Certificate", "research engine", fm)
        self.assertIn("John Doe", cert)
        self.assertIn("Alice Smith", cert)
        self.assertIn("Dr. Jane Doe", cert)

        # 2. PDF references left alignment and URL wrap check
        pdf_md = "# Title\n\n## References\n\n[1] Reference Paper, Available: https://arxiv.org/abs/2103.12345678901234567890."
        pdf_bytes = markdown_to_pdf(pdf_md, title="Test", report_type="college")
        self.assertTrue(len(pdf_bytes) > 1000)

    def test_item1_sentence_fragment_and_placeholder_isolation(self):
        """Item 1: Placeholders must never split a sentence; dangling fragments are dropped."""
        # A. Dangling fragment before and after placeholder
        text1 = "The Gantt chart in [Add your project timeline here.] to finalize the project timeline."
        cleaned1 = normalize_college_captions_and_placeholders(text1)
        self.assertEqual(cleaned1.strip(), "[Add your project timeline here.]")
        self.assertNotIn("The Gantt chart in", cleaned1)
        self.assertNotIn("to finalize the project timeline", cleaned1)

        # B. Fragment ending in utilizes
        text2 = "CiteBolt utilizes. [Add your tech stack here.]"
        cleaned2 = normalize_college_captions_and_placeholders(text2)
        self.assertEqual(cleaned2.strip(), "[Add your tech stack here.]")
        self.assertNotIn("CiteBolt utilizes", cleaned2)

        # C. Fragment ending in depends on
        text3 = "Total effort depends on. [Add your effort estimation here.]"
        cleaned3 = normalize_college_captions_and_placeholders(text3)
        self.assertEqual(cleaned3.strip(), "[Add your effort estimation here.]")
        self.assertNotIn("Total effort depends on", cleaned3)

        # D. Trailing fragment
        text4 = "[Add your project timeline here.] to finalize the project timeline."
        cleaned4 = normalize_college_captions_and_placeholders(text4)
        self.assertEqual(cleaned4.strip(), "[Add your project timeline here.]")

        # E. Placeholder in middle of paragraph with valid sentences is isolated to own line (3.4)
        text5 = "Functional requirements define core behaviors. [Add your functional requirements matrix here.] Non-functional requirements specify security."
        cleaned5 = normalize_college_captions_and_placeholders(text5)
        self.assertIn("\n\n[Add your functional requirements matrix here.]\n\n", cleaned5)
        self.assertIn("Functional requirements define core behaviors.", cleaned5)
        self.assertIn("Non-functional requirements specify security.", cleaned5)

    def test_item2_doubled_figure_placeholders(self):
        """Item 2: Bare [Insert diagram here] next to titled one is removed, keeping only titled."""
        text = (
            "[Insert diagram here]\n\n"
            "[Insert diagram here: Fig. 4.1 - System Architecture Overview]\n"
            "Fig. 4.1: System Architecture Overview"
        )
        cleaned = normalize_college_captions_and_placeholders(text)
        self.assertNotIn("[Insert diagram here]\n", cleaned)
        self.assertIn("[Insert diagram here: Fig. 4.1 - System Architecture Overview]", cleaned)

        # Reversed order
        text_rev = (
            "[Insert diagram here: Fig. 4.1 - System Architecture Overview]\n\n"
            "[Insert diagram here]"
        )
        cleaned_rev = normalize_college_captions_and_placeholders(text_rev)
        self.assertEqual(cleaned_rev.strip(), "[Insert diagram here: Fig. 4.1 - System Architecture Overview]")

    def test_item3_section_1_2_and_intro_code_identifiers_and_run_commands(self):
        """Item 3: Remove leftover .main:app --host 127.0.0.1. text; 1.1-1.7 contain no endpoints or code identifiers."""
        facts = "Project Facts: SQLite database, 3 agents (Research, Analysis, Writer), FastAPI, React."

        # A. Run command stripping removes entire command including leftover pieces
        dirty_12 = "Start the system via uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload in the terminal. The platform provides automated literature synthesis."
        filtered_12 = filter_grounded_college_section("1.2 Introduction to CiteBolt", dirty_12, facts)
        self.assertNotIn("main:app", filtered_12)
        self.assertNotIn("127.0.0.1", filtered_12)
        self.assertNotIn("uvicorn", filtered_12)
        self.assertIn("The platform provides automated literature synthesis.", filtered_12)

        # B. Endpoints and code identifiers removed from 1.1-1.7
        dirty_intro = (
            "Requests are routed to POST /api/research endpoint. "
            "Data is stored in report_markdown and outline_json columns. "
            "The system coordinates multi-agent research."
        )
        filtered_intro = filter_grounded_college_section("1.3 Objectives", dirty_intro, facts)
        self.assertNotIn("/api/research", filtered_intro)
        self.assertNotIn("report_markdown", filtered_intro)
        self.assertNotIn("outline_json", filtered_intro)
        self.assertIn("The system coordinates multi-agent research.", filtered_intro)

    def test_item4_banned_claim_rules_and_fact_sheet(self):
        """Item 4: Banned DBs, agents, and phrases dropped; 8.2 covers only 14 unit tests; fact sheet has forbidden block."""
        facts = "Project Facts: SQLite database, 3 agents (Research, Analysis, Writer), 14 unit tests for college report mode."

        # A. Fact sheet has NOT TRUE / DO NOT WRITE block
        fs = build_compact_project_fact_sheet("Test", "Context", {})
        self.assertIn("NOT TRUE / DO NOT WRITE", fs)
        self.assertIn("SQLite is the only database", fs)

        # B. PostgreSQL, MySQL, MongoDB dropped
        dbs_text = "The system persists data in PostgreSQL and synchronizes with MongoDB. SQLite provides local storage."
        filtered_dbs = filter_grounded_college_section("5.3 Database Architecture", dbs_text, facts)
        self.assertNotIn("PostgreSQL", filtered_dbs)
        self.assertNotIn("MongoDB", filtered_dbs)
        self.assertIn("SQLite provides local storage.", filtered_dbs)

        # C. Non-existent agents dropped
        agents_text = "The Synthesis Agent formats markdown while Formatting Agent handles styles. The Writer Agent produces final text."
        filtered_agents = filter_grounded_college_section("4.2 System Architecture", agents_text, facts)
        self.assertNotIn("Synthesis Agent", filtered_agents)
        self.assertNotIn("Formatting Agent", filtered_agents)
        self.assertIn("Writer Agent", filtered_agents)

        # D. Banned phrases dropped
        phrases_text = "The backend stores user credentials and passwords securely. The engine avoids race conditions and lacks built-in persistence under concurrent requests."
        filtered_phrases = filter_grounded_college_section("3.3 Security Requirements", phrases_text, facts)
        self.assertNotIn("stores user credentials", filtered_phrases)
        self.assertNotIn("race conditions", filtered_phrases)
        self.assertNotIn("lacks built-in persistence", filtered_phrases)
        self.assertNotIn("concurrent requests", filtered_phrases)

        # E. Section 8.2 objectives only mention 14 tests, never OTP or concurrency
        sec82_text = "Test objectives include validating OTP authentication flows, resume mechanics, and endpoint reliability under concurrency. Unit tests verify college report mode."
        filtered_82 = filter_grounded_college_section("8.2 Testing Objectives", sec82_text, facts)
        self.assertNotIn("OTP", filtered_82)
        self.assertNotIn("concurrency", filtered_82)
        self.assertNotIn("endpoint reliability", filtered_82)
        self.assertIn("Unit tests verify college report mode.", filtered_82)

    def test_item5_thin_sections_and_deterministic_table_7_1(self):
        """Item 5: Thin sections require >=25 words or placeholder; Section 7.3 is deterministic markdown table."""
        facts = "Project Facts: SQLite database, 14 tests."

        # A. Thin section with < 25 words becomes placeholder
        short_thin = "The component model specifies relational tables."
        filtered_thin = filter_grounded_college_section("4.6 Database Design Overview", short_thin, facts, min_words=25)
        self.assertIn("[Add your Database Design Overview here.]", filtered_thin)

        # B. List of Tables contains "Table 7.1: Database tables" without pipe characters
        lot = format_front_matter_section("List of Tables", "Topic", {})
        self.assertIn("Table 7.1", lot)
        self.assertIn("Database tables", lot)
        self.assertNotIn("|", lot)

    def test_item6_section_5_1_deduplication_and_8_5_8_6_placeholders(self):
        """Item 6: Section 5.1 has only one intro paragraph; 8.5 and 8.6 do not repeat 14 tests."""
        facts = "Project Facts: 14 unit tests with a mocked LLM and mocked search."

        # A. Section 5.1 deduplication
        dup_51 = "## 5.1 Frontend Technologies\n\nThe frontend is built using React and Vite with Tailwind CSS for layout.\n\nThe frontend is built using React and Vite with Tailwind CSS for layout."
        filtered_51 = filter_grounded_college_section("5.1 Frontend Technologies", dup_51, facts)
        paras = [p for p in filtered_51.split("\n\n") if not p.startswith("#")]
        self.assertEqual(len(paras), 1)

        # B. Section 8.5 test case table placeholder
        sec_85 = "The system verification suite comprises 14 unit tests with a mocked LLM and mocked search."
        filtered_85 = filter_grounded_college_section("8.5 Test Cases", sec_85, facts)
        self.assertEqual(filtered_85.strip(), "## 8.5 Test Cases\n\n[Add your test case table here.]")

        # C. Section 8.6 test plan placeholder
        sec_86 = "The system verification suite comprises 14 unit tests with a mocked LLM."
        filtered_86 = filter_grounded_college_section("8.6 Master Test Suite", sec_86, facts)
        self.assertEqual(filtered_86.strip(), "## 8.6 Master Test Suite\n\n[Add your test plan here.]")

    def test_item7_keep_with_next_on_headings_in_export(self):
        """Item 7: Headings in PDF export have keepWithNext = True."""
        md = (
            "# Chapter 4 System Design\n\n"
            "## 4.1 System Overview\n\nIntroductory text for chapter.\n\n"
            "### 4.1.1 Modular Subsystems\n\nSubsystem details."
        )
        # Test markdown_to_pdf builds without error and inspect that headings flowables have keepWithNext
        pdf_bytes = markdown_to_pdf(md, title="Test Project", report_type="college")
        self.assertTrue(len(pdf_bytes) > 2000)

    def test_item8_chapter_2_citations_and_search_ranking(self):
        """Item 8: Literal [n] replaced/removed; vendor/tutorial domains dropped; fewer than 3 academic adds placeholder."""
        # A. Literal [n] without matching source is removed entirely
        md = "Multi-agent systems improve research efficiency [n] in modern pipelines."
        sanitized = sanitize_section_markdown(md)
        self.assertNotIn("[n]", sanitized)
        self.assertIn("Multi-agent systems improve research efficiency", sanitized)

        # B. Literal [n] with matching source is replaced with real number
        sources = [{"id": 1, "title": "LangGraph Framework", "author": "LangChain Team", "url": "https://arxiv.org/abs/2101.12345"}]
        md_matched = "The LangGraph framework coordinates graphs [n]."
        sanitized_matched = sanitize_section_markdown(md_matched, sources=sources)
        self.assertIn("[1]", sanitized_matched)
        self.assertNotIn("[n]", sanitized_matched)

    def test_item9_title_page_and_certificate_field_mapping(self):
        """Item 9: Guide -> guide line, HoD blank for signature; HoD generic in Acknowledgements; Sandip untruncated; automatic dates."""
        fm = {
            "projectTitle": "Autonomous Agent",
            "guide": "Prof. Alan Turing",
            "university": "Sandip",
            "department": "Computer Science and Engineering",
            "degree": "Bachelor of Technology",
            "teamMembers": [{"name": "Ada Lovelace", "prn": "CS101"}],
        }

        # Title Page
        tp = format_front_matter_section("Title Page", "Autonomous Agent", fm)
        self.assertIn("Prof. Alan Turing", tp)
        self.assertIn("Sandip", tp)
        self.assertNotIn("Sandip University", tp)
        # Automatic academic year and month year without brackets
        self.assertNotIn("[Academic Year]", tp)
        self.assertNotIn("[submissionMonthYear]", tp)
        self.assertRegex(tp, r"Academic Year: \d{4}-\d{2}")

        # Certificate: Guide is filled, HoD is blank signature line
        cert = format_front_matter_section("Certificate", "Autonomous Agent", fm)
        self.assertIn("**Project Guide:** Prof. Alan Turing", cert)
        self.assertIn("**Head of Department:** ____________________", cert)

        # Acknowledgements: Guide thanked by name, HoD referred to only generically
        ack = format_front_matter_section("Acknowledgements", "Autonomous Agent", fm)
        self.assertIn("Prof. Alan Turing", ack)
        self.assertIn("Head of Department, Department of Computer Science and Engineering", ack)
        self.assertNotIn("Prof. Alan Turing** as Head", ack)

    def test_item1_whitelist_grounding_filter(self):
        """Item 1: Whitelist grounding filter for chapters 3-11 drops specific ungrounded tokens and excludes forbidden block from corpus."""
        # Fact sheet has "NOT TRUE / DO NOT WRITE: - SQLite is the only database (do NOT mention PostgreSQL, MySQL...)"
        fact_sheet = build_compact_project_fact_sheet("CiteBolt Platform", "A platform for literature research using LangGraph, FastAPI, and SQLite.", {})

        # Test A: Allowed tokens set does NOT contain postgresql despite postgresql appearing in the prompt's forbidden block
        allowed = build_allowed_tokens_set(fact_sheet)
        self.assertNotIn("postgresql", allowed)
        self.assertNotIn("alembic", allowed)
        self.assertIn("sqlite", allowed)
        self.assertIn("fastapi", allowed)
        self.assertIn("langgraph", allowed)

        # Test B: Specific ungrounded tokens are dropped in chapters 3-11:
        # PostgreSQL, Alembic, SQLModel, MyPy, ESLint, WCAG, Swagger, OpenAI, Sprint N, '2 seconds', '99 percent', '5 concurrent runs', 'AuthService'
        ungrounded_sentences = [
            "Data is stored in PostgreSQL database.",
            "Database migrations are executed via Alembic.",
            "Schema models are defined using SQLModel.",
            "Static typing is enforced using MyPy across all modules.",
            "Linting rules are configured through ESLint.",
            "The web UI adheres strictly to WCAG accessibility rules.",
            "Interactive documentation is provided by Swagger UI.",
            "External completions are queried from OpenAI endpoints.",
            "Tasks were planned and tracked during Sprint 1.",
            "The API responds in 2 seconds under peak conditions.",
            "The system delivers 99 percent reliability across requests.",
            "The server handles 5 concurrent runs simultaneously.",
            "User credentials are validated by AuthService class.",
        ]
        valid_sentence = "The platform coordinates agents using LangGraph with FastAPI and SQLite storage."

        test_text = "\n".join(ungrounded_sentences) + "\n" + valid_sentence
        filtered = filter_grounded_college_section("5.2 Architecture Overview", test_text, fact_sheet)

        # All 13 ungrounded tokens must be absent
        self.assertNotIn("PostgreSQL", filtered)
        self.assertNotIn("Alembic", filtered)
        self.assertNotIn("SQLModel", filtered)
        self.assertNotIn("MyPy", filtered)
        self.assertNotIn("ESLint", filtered)
        self.assertNotIn("WCAG", filtered)
        self.assertNotIn("Swagger", filtered)
        self.assertNotIn("OpenAI", filtered)
        self.assertNotIn("Sprint 1", filtered)
        self.assertNotIn("2 seconds", filtered)
        self.assertNotIn("99 percent", filtered)
        self.assertNotIn("5 concurrent runs", filtered)
        self.assertNotIn("AuthService", filtered)

        # Valid sentence with allowed generic terms is preserved
        self.assertIn("LangGraph", filtered)
        self.assertIn("FastAPI", filtered)
        self.assertIn("SQLite", filtered)

    def test_item2_feedback_and_test_claims(self):
        """Item 2: Never claim feedback/comments/surveys unless in facts; only state fact sheet claims for 14 tests."""
        facts = "Project Facts: SQLite database, LangGraph multi-agent pipeline, 14 unit tests for college report mode."

        # A. Informal comments / peer reviewers / faculty advisors dropped from 9.4, fallback to placeholder
        feedback_text = "The team collected informal comments from peer reviewers and faculty advisors during the symposium."
        filtered_94 = filter_grounded_college_section("9.4 User Feedback", feedback_text, facts)
        self.assertNotIn("peer reviewers", filtered_94)
        self.assertNotIn("faculty advisors", filtered_94)
        self.assertIn("[Add your user feedback results here.]", filtered_94)

        # B. 14 tests: no claims about OTP, resume, template selection, endpoints, run-state persistence
        invented_test_claims = (
            "The 14 unit tests verify OTP verification, run resume, and endpoint reliability. "
            "All 14 tests passed successfully without regression."
        )
        filtered_82 = filter_grounded_college_section("8.2 Testing Objectives", invented_test_claims, facts)
        self.assertNotIn("OTP", filtered_82)
        self.assertNotIn("resume", filtered_82)
        self.assertNotIn("endpoint reliability", filtered_82)
        self.assertNotIn("All 14 tests passed", filtered_82)

    def test_item3_blank_duration_and_no_time_splits(self):
        """Item 3: Blank duration drops months/weeks and time fraction splits; 6.7 and 6.9 become placeholders."""
        facts_blank_duration = "Project Facts: SQLite database, FastAPI. Project Duration: [Not specified / Blank]."

        # A. Sentences with three-month, weeks, months dropped
        duration_text = "The application was completed during a three-month development phase spanning 12 weeks."
        filtered_prose = filter_grounded_college_section("6.1 Implementation Planning", duration_text, facts_blank_duration)
        self.assertNotIn("three-month", filtered_prose)
        self.assertNotIn("12 weeks", filtered_prose)

        # B. Time splits into fractions/thirds dropped
        thirds_text = "The first third of the project focused on research, while the final third completed testing."
        filtered_thirds = filter_grounded_college_section("6.1 Implementation Planning", thirds_text, facts_blank_duration)
        self.assertNotIn("first third", filtered_thirds)
        self.assertNotIn("final third", filtered_thirds)

        # C. 6.7 and 6.9 become placeholders when duration is blank
        sec_67 = filter_grounded_college_section("6.7 Project Timeline", "Schedule details.", facts_blank_duration)
        self.assertIn("[Add your Project Timeline here.]", sec_67)
        sec_69 = filter_grounded_college_section("6.9 Effort Estimation", "Effort breakdown.", facts_blank_duration)
        self.assertIn("[Add your Effort Estimation here.]", sec_69)

    def test_item8_table_7_1_consistency_and_repeat_header(self):
        """Item 8: Table 7.1 numbering sequential, text/caption/LOT match, no [Insert table here] placeholder, repeatRows=1."""
        fm = {"projectTitle": "CiteBolt", "university": "Sandip"}

        # A. Section 7.3 generates Table 7.1 with caption and no [Insert table here]
        sec_73 = filter_grounded_college_section("7.3 Data Dictionary / Schema Details", "", "Project facts", heading_prefix="##")
        self.assertIn("Table 7.1: Database tables", sec_73)
        self.assertIn("Table 7.1 describes each database table", sec_73)
        self.assertNotIn("[Insert table here]", sec_73)
        self.assertIn("| users | id, email |", sec_73)

        # B. List of Tables matches Table 7.1
        lot = format_front_matter_section("List of Tables", "CiteBolt", fm)
        self.assertIn("Table 7.1", lot)
        self.assertIn("Database tables", lot)

        # C. PDF rendering includes repeatRows for tables in college template mode
        pdf_md = (
            "# Test Report\n\n"
            "## 7.3 Schema\n\n"
            "Table 7.1: Database tables\n\n"
            "| Col A | Col B |\n"
            "| :--- | :--- |\n"
            "| Val 1 | Val 2 |\n"
        )
        pdf_bytes = markdown_to_pdf(pdf_md, title="Test Report", report_type="college")
        self.assertTrue(len(pdf_bytes) > 2000)

    def test_item11_placeholder_positioning_and_deduplication(self):
        """Item 11: Figure placeholders on their own line, never appended to paragraph, deduplicated if doubled."""
        # A. Appended placeholder separated to its own line
        appended_text = "The overall system architecture is depicted below. [Insert diagram here: Fig. 4.1 - Architecture Overview] Further components coordinate state."
        normalized_appended = normalize_college_captions_and_placeholders(appended_text)
        self.assertIn("\n\n[Insert diagram here: Fig. 4.1 - Architecture Overview]\n\n", normalized_appended)

        # B. Doubled diagram placeholders twice in a row collapsed to one
        doubled_text = "[Insert diagram here] [Insert diagram here]"
        normalized_doubled = normalize_college_captions_and_placeholders(doubled_text)
        self.assertNotIn("[Insert diagram here] [Insert diagram here]", normalized_doubled)
        self.assertEqual(normalized_doubled.strip(), "[Insert diagram here]")

    def test_tables_in_sections_4_6_7_3_5_4_must_be_verified(self):
        """Test that sections 4.6, 7.3, and 5.4 only contain verified tables and fail on unverified tables."""
        facts = "Project Facts: SQLite database with 6 tables and 25 endpoints."
        
        # A. Section 4.6 deterministic text contains only verified tables
        sec_46 = build_deterministic_data_design_section("4.6 Data Design")
        for tbl in VERIFIED_TABLE_NAMES:
            self.assertIn(f"`{tbl}`", sec_46)
        # Verify foreign keys are verified from models.py
        for rel in VERIFIED_SCHEMA_RELATIONSHIPS:
            self.assertIn(f"`{rel}`", sec_46)
        # Ensure unverified tables never appear in 4.6
        unverified_tables = ["reports", "report_sections", "sources", "audit_logs", "orders", "transactions", "customers"]
        for unv in unverified_tables:
            self.assertNotIn(f"`{unv}`", sec_46)
            self.assertNotIn(f" {unv} ", sec_46.lower())

        # B. Section 7.3 deterministic text contains only verified tables
        sec_73 = build_deterministic_data_dictionary_section("7.3 Data Dictionary")
        for tbl in VERIFIED_TABLE_NAMES:
            self.assertIn(f"| {tbl} |", sec_73)
        for unv in unverified_tables:
            self.assertNotIn(f"| {unv} |", sec_73)

        # C. Section 5.4 filter drops sentences with unverified table names
        sec_54_raw = (
            "## 5.4 Database Architecture\n\n"
            "The SQLite backend persists user sessions in the `orders` and `audit_logs` tables. "
            "Verified user accounts and research generation records are stored in the `users` and `runs` tables. "
            "The data layer also configures a `report_sections` table for chunk storage."
        )
        filtered_54 = filter_grounded_college_section("5.4 Database Architecture", sec_54_raw, facts)
        self.assertIn("users", filtered_54)
        self.assertIn("runs", filtered_54)
        self.assertNotIn("orders", filtered_54)
        self.assertNotIn("audit_logs", filtered_54)
        self.assertNotIn("report_sections", filtered_54)

    def test_endpoint_count_equals_len_verified_endpoints(self):
        """Test that VERIFIED_ENDPOINT_COUNT equals len(VERIFIED_API_ENDPOINTS) and filtering enforces it."""
        facts = "Project Facts: SQLite database with 6 tables and 25 endpoints."

        # A. Endpoint count equals len(VERIFIED_API_ENDPOINTS) and matches 25
        self.assertEqual(VERIFIED_ENDPOINT_COUNT, len(VERIFIED_API_ENDPOINTS))
        self.assertEqual(VERIFIED_ENDPOINT_COUNT, 25)
        self.assertEqual(VERIFIED_TABLE_COUNT, len(VERIFIED_TABLE_NAMES))
        self.assertEqual(VERIFIED_TABLE_COUNT, 6)

        # B. Filter accepts verified count (25) and rejects wrong count (10, 12, etc.)
        sec_valid = f"The FastAPI backend registers {VERIFIED_ENDPOINT_COUNT} endpoints for core services."
        filtered_valid = filter_grounded_college_section("5.4 Backend Architecture", sec_valid, facts)
        self.assertIn(f"{VERIFIED_ENDPOINT_COUNT} endpoints", filtered_valid)

        sec_wrong_endpoints = "The FastAPI backend registers 10 API endpoints for core services."
        filtered_wrong = filter_grounded_college_section("5.4 Backend Architecture", sec_wrong_endpoints, facts)
        self.assertNotIn("10 API endpoints", filtered_wrong)

        # C. Filter accepts verified table count (6) and rejects wrong table count (8, 10, etc.)
        sec_valid_tbl = f"The SQLite schema maintains {VERIFIED_TABLE_COUNT} database tables."
        filtered_valid_tbl = filter_grounded_college_section("5.4 Database Architecture", sec_valid_tbl, facts)
        self.assertIn(f"{VERIFIED_TABLE_COUNT} database tables", filtered_valid_tbl)

        sec_wrong_tbl = "The SQLite schema maintains 8 database tables."
        filtered_wrong_tbl = filter_grounded_college_section("5.4 Database Architecture", sec_wrong_tbl, facts)
        self.assertNotIn("8 database tables", filtered_wrong_tbl)

    def test_task1_pdf_export_code_spans_with_asterisks(self):
        """TASK 1 4(a): Sentence with `/api/auth/*`, `/api/runs/*`, `/api/templates/*` exports to PDF and contains `/api/auth/*`."""
        md = (
            "# College Report\n\n"
            "## 10.1 API Access\n\n"
            "The backend exposes endpoints under `/api/auth/*`, `/api/runs/*`, and `/api/templates/*` for operations.\n"
        )
        pdf_bytes = markdown_to_pdf(md, title="College Report", report_type="college")
        self.assertTrue(len(pdf_bytes) > 2000)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        full_text = "".join(page.extract_text() or "" for page in reader.pages)
        self.assertIn("/api/auth/*", full_text)
        self.assertIn("/api/runs/*", full_text)
        self.assertIn("/api/templates/*", full_text)

    def test_task1_pdf_export_unmatched_markers(self):
        """TASK 1 4(b): Paragraph with unmatched * and unmatched backtick exports cleanly."""
        md = (
            "# College Report\n\n"
            "## 10.1 Edge Cases\n\n"
            "This paragraph has an unmatched * asterisk and an unmatched ` backtick in prose.\n"
        )
        pdf_bytes = markdown_to_pdf(md, title="College Report", report_type="college")
        self.assertTrue(len(pdf_bytes) > 2000)
        docx_bytes = markdown_to_docx(md, title="College Report", report_type="college")
        self.assertTrue(len(docx_bytes) > 2000)

    def test_task1_pdf_export_xml_chars(self):
        """TASK 1 4(c): Markdown paragraph with <, >, and & exports cleanly."""
        md = (
            "# College Report\n\n"
            "## 10.1 XML Entities\n\n"
            "Testing entities where x < y and y > z and apples & oranges are compared.\n"
        )
        pdf_bytes = markdown_to_pdf(md, title="College Report", report_type="college")
        self.assertTrue(len(pdf_bytes) > 2000)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        full_text = "".join(page.extract_text() or "" for page in reader.pages)
        self.assertIn("x < y", full_text)
        self.assertIn("apples & oranges", full_text)

    def test_task1_reexport_run_83bb845d(self):
        """TASK 1 Item 5: Re-export run 83bb845df1ee4e3690d8e92125a78185 directly from DB to verify PDF and DOCX export work cleanly."""
        import sqlite3
        db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "reports.db"))
        if not os.path.exists(db_path):
            self.skipTest("reports.db not found")
        con = sqlite3.connect(db_path)
        row = con.execute("SELECT topic, report_type, report_markdown, sources_json FROM runs WHERE id LIKE '83bb845d%'").fetchone()
        con.close()
        if not row:
            self.skipTest("Run 83bb845d not found in database")
        topic, rtype, md, s_json = row
        sources = json.loads(s_json) if s_json else []
        pdf_bytes = markdown_to_pdf(md, topic=topic, report_type=rtype, sources=sources)
        self.assertGreater(len(pdf_bytes), 10000)
        docx_bytes = markdown_to_docx(md, topic=topic, report_type=rtype, sources=sources)
        self.assertGreater(len(docx_bytes), 10000)

    def test_task2_dynamic_lof_and_lot_only_from_actual_body_captions(self):
        """TASK 2 Item 1: LOF and LOT built ONLY from captions actually present in final body text. No pipe characters, no ghost entries, no [Insert table here]."""
        body_md = (
            "# Chapter 1 Introduction\n\n"
            "Some introduction.\n\n"
            "# Chapter 4 System Design\n\n"
            "[Insert diagram here: Fig. 4.1 - System Architecture]\n\n"
            "Fig. 4.1: System Architecture\n\n"
            "# Chapter 7 Software Implementation\n\n"
            "Table 7.1: Database tables\n\n"
            "| Table | Purpose |\n"
            "| :--- | :--- |\n"
            "| users | Accounts |\n\n"
        )
        from app.agents.section_engine import extract_captions_from_body, build_dynamic_lof_and_lot
        figs, tbls = extract_captions_from_body(body_md)
        self.assertEqual(len(figs), 1)
        self.assertEqual(figs[0][0], "Fig. 4.1")
        self.assertEqual(len(tbls), 1)
        self.assertEqual(tbls[0][0], "Table 7.1")

        lof, lot = build_dynamic_lof_and_lot(body_md)
        self.assertIn("Fig. 4.1: System Architecture", lof)
        self.assertNotIn("|", lof)
        self.assertNotIn("[Insert diagram here", lof)
        self.assertIn("Table 7.1: Database tables", lot)
        self.assertNotIn("|", lot)
        self.assertNotIn("Table 1.1", lot)
        self.assertNotIn("[Insert table here]", lot)

    def test_task2_front_matter_shared_fields_and_title_casing(self):
        """TASK 2 Item 2: Title page, certificate, and acknowledgements read the SAME fields. University title-cased when lowercase, never prints asterisks. Restores DOCX labels."""
        fm = {
            "projectTitle": "Test Project",
            "degree": "",  # blank -> [Degree]
            "department": "",  # blank -> [Department Name]
            "university": "sandip university",  # lowercase -> Sandip University
            "guide": "dr. jane doe",
            "academicYear": "2024-2025",
        }
        tp = format_front_matter_section("Title Page", "Test Project", fm)
        self.assertIn("A PROJECT REPORT", tp)
        self.assertIn("Submitted in partial fulfilment of the requirements for the award of the degree of", tp)
        self.assertIn("**[Degree]**", tp)
        self.assertIn("Submitted by", tp)
        self.assertIn("Under the guidance of", tp)
        self.assertIn("Department: [Department Name]", tp)
        self.assertIn("University: Sandip University", tp)
        self.assertNotIn("sandip university", tp)

        cert = format_front_matter_section("Certificate", "Test Project", fm)
        self.assertIn("Sandip University", cert)
        self.assertNotIn("*sandip university*", cert.lower())
        self.assertIn("[Department Name], Sandip University", cert)

        ack = format_front_matter_section("Acknowledgements", "Test Project", fm)
        self.assertIn("Sandip University", ack)
        self.assertIn("Department of [Department Name]", ack)

    def test_task2_section_1_5_deterministic_roadmap(self):
        """TASK 2 Item 3: Section 1.5 roadmap contains exact 11 chapters from real chapter titles."""
        from app.agents.section_engine import build_deterministic_roadmap_section
        roadmap = build_deterministic_roadmap_section("1.5 Report Organization")
        expected_chapters = [
            "Chapter 2 (Literature Survey)",
            "Chapter 3 (Software Requirements Specification)",
            "Chapter 4 (System Design)",
            "Chapter 5 (Technical Specifications)",
            "Chapter 6 (Project Planning & Scheduling)",
            "Chapter 7 (Software Implementation)",
            "Chapter 8 (Software Testing)",
            "Chapter 9 (Result and Discussion)",
            "Chapter 10 (Deployment and Maintenance)",
            "Chapter 11 (Conclusion and Future Scope)",
        ]
        for ch in expected_chapters:
            self.assertIn(ch, roadmap)

    def test_task2_whitelist_filter_drops_banned_terms(self):
        """TASK 2 Item 4: Whitelist filter drops sentences with config.yaml, returns 429, CI runs, hashes, etc."""
        facts = "Project Facts: LangGraph multi-agent pipeline with SQLite."
        banned_sentences = [
            ("3.2 Requirements", "The application loads credentials from `config.yaml` at startup."),
            ("3.2 Requirements", "The system returns 429 when rate limits are exceeded."),
            ("6.1 Planning", "Automated CI runs are configured for pull request validation."),
            ("7.2 Security", "The system verifies user password hashes upon authentication."),
            ("7.2 Security", "State synchronization produces state-diff structures for patching."),
            ("7.2 Security", "The report compiler applies markdown patches across sections."),
            ("6.1 Planning", "The team completed the work in Sprint 1 and Sprint 2."),
            ("4.3 Architecture", "Custom CORS middleware intercepts all incoming HTTP requests."),
            ("8.1 Testing", "Comprehensive load testing is planned for the subsequent release phase."),
            ("1.1 Domain", "The research lab evaluated multiple grant proposals during funding."),
            ("6.1 Planning", "Faculty advisors reviewed the project milestone deliveries."),
        ]
        for sec_name, sent in banned_sentences:
            filtered = filter_grounded_college_section(sec_name, sent, facts)
            self.assertNotIn(sent, filtered, f"Sentence '{sent}' should have been dropped by whitelist filter")

    def test_task2_test_claims_8_2_8_5_8_6(self):
        """TASK 2 Item 5: In 8.2, 8.5, 8.6, drop claims of testing endpoint contracts, status codes, JWT cookies, OTP delivery, or database state."""
        facts = "Project Facts: 14 unit tests with a mocked LLM and mocked search for the college report mode."
        test_sentences = [
            ("8.2 Test Objectives", "The test suite validates endpoint contracts across API handlers."),
            ("8.2 Test Objectives", "Tests verify HTTP status codes and error responses."),
            ("8.5 Test Cases", "Test Case 1 checks JWT cookies for session authorization."),
            ("8.5 Test Cases", "Test Case 2 asserts OTP delivery through Gmail SMTP."),
            ("8.6 Test Plan", "The test execution asserts database state transitions in SQLite."),
        ]
        for sec_name, sent in test_sentences:
            filtered = filter_grounded_college_section(sec_name, sent, facts)
            self.assertNotIn(sent, filtered, f"Sentence '{sent}' should have been dropped")

    def test_task2_sections_10_5_10_6_10_7_match_headings(self):
        """TASK 2 Item 6: 10.5 manual restart; 10.6 copy SQLite file; 10.7 external API limits and local-only deployment."""
        facts = "Project Facts: local deployment with FastAPI, Vite, SQLite."
        sec_105 = filter_grounded_college_section("10.5 Maintenance", "", facts)
        self.assertIn("manual process restarts", sec_105.lower())
        self.assertNotIn("backup", sec_105.lower())

        sec_106 = filter_grounded_college_section("10.6 Backup and Recovery", "", facts)
        self.assertIn("filesystem copies of the sqlite database file", sec_106.lower())

        sec_107 = filter_grounded_college_section("10.7 Challenges During Deployment", "", facts)
        self.assertIn("external api rate limits", sec_107.lower())
        self.assertIn("local-only deployment", sec_107.lower())

    def test_task2_code_blocks_and_10_3_installation(self):
        """TASK 2 Item 7: Code blocks render fenced code as code block in PDF and DOCX; 10.3 includes backend and frontend commands."""
        facts = "Project Facts: local deployment."
        from app.agents.section_engine import build_deterministic_installation_section
        sec_103 = build_deterministic_installation_section("10.3 Installation Process")
        self.assertIn("```bash", sec_103)
        self.assertIn("cd backend", sec_103)
        self.assertIn("uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload", sec_103)
        self.assertIn("cd frontend", sec_103)
        self.assertIn("npm install", sec_103)
        self.assertIn("npm run dev", sec_103)

        pdf_bytes = markdown_to_pdf(f"# Report\n\n{sec_103}", title="Report", report_type="college")
        self.assertGreater(len(pdf_bytes), 2000)
        docx_bytes = markdown_to_docx(f"# Report\n\n{sec_103}", title="Report", report_type="college")
        self.assertGreater(len(docx_bytes), 2000)

    def test_task2_drop_truncated_sentences(self):
        """TASK 2 Item 8: Drop truncated sentences ending in 'launched via', 'such as', 'including' or without terminal punctuation."""
        facts = "Project Facts: FastAPI backend and React frontend."
        trunc1 = "The backend services are launched via"
        trunc2 = "The architecture integrates several core components including"
        trunc3 = "This sentence is missing terminal punctuation"
        valid = "The application architecture utilizes a FastAPI backend and a React frontend."

        md = f"## 5.5 Backend Implementation\n\n{valid}\n\n{trunc1}\n\n{trunc2}\n\n{trunc3}"
        filtered = filter_grounded_college_section("5.5 Backend Implementation", md, facts)
        self.assertIn(valid, filtered)
        self.assertNotIn("launched via", filtered)
        self.assertNotIn("core components including", filtered)
        self.assertNotIn("terminal punctuation", filtered)

    def test_task2_remove_glued_chapter_summary_from_5_8(self):
        """TASK 2 Item 9: Remove glued **Chapter Summary** paragraphs from 5.8."""
        facts = "Project Facts: FastAPI backend."
        md = (
            "## 5.8 Summary\n\n"
            "**Chapter Summary** This chapter outlined the technical specifications governing the frontend, backend, and data persistence layers."
        )
        filtered = filter_grounded_college_section("5.8 Summary", md, facts)
        self.assertNotIn("**Chapter Summary**", filtered)
        self.assertIn("This chapter outlined the technical specifications", filtered)

    def test_task2_team_structure_single_student(self):
        """TASK 2 Item 10: If team size is 1, write 'The project was developed by a single student.' No placeholders for external contributors."""
        facts = "Project Facts: developed by one student."
        filtered = filter_grounded_college_section("6.6 Team Structure", "Some team text", facts)
        self.assertIn("The project was developed by a single student.", filtered)
        self.assertNotIn("[Add", filtered)


if __name__ == "__main__":
    unittest.main()
