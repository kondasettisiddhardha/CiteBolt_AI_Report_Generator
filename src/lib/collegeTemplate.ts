export interface OutlineSection {
  level: 1 | 2 | 3;
  title: string;
  suggested_words?: number;
  target_words?: number;
  is_auto?: boolean;
}

export interface TeamMember {
  name: string;
  prn: string;
}

export interface CollegeFrontMatter {
  projectTitle: string;
  teamMembers: TeamMember[];
  guide: string;
  coordinator: string;
  hod: string;
  dean: string;
  department?: string;
  university: string;
  academicYear: string;
  submissionMonthYear: string;
  degree?: string;
  teamSize?: string;
  duration?: string;
  deploymentStatus?: string;
  databaseTables?: string;
  mainEndpoints?: string;
  relatedWork?: string;
  technologies?: string;
  tests?: string;
  features?: string;
  installCommands?: string;
  useCiteboltPreset?: boolean;
}

export const DEFAULT_COLLEGE_FRONT_MATTER: CollegeFrontMatter = {
  projectTitle: "",
  teamMembers: [{ name: "", prn: "" }],
  guide: "",
  coordinator: "",
  hod: "",
  dean: "",
  department: "",
  university: "",
  academicYear: "",
  submissionMonthYear: "",
  degree: "",
  teamSize: "",
  duration: "",
  deploymentStatus: "",
  databaseTables: "",
  mainEndpoints: "",
  relatedWork: "",
  technologies: "",
  tests: "",
  features: "",
  installCommands: "",
  useCiteboltPreset: false,
};

export const CITEBOLT_PRESET_FRONT_MATTER: Partial<CollegeFrontMatter> = {
  projectTitle: "CiteBolt",
  degree: "Bachelor of Technology in Computer Engineering",
  deploymentStatus: "Local development environment",
  technologies: "FastAPI, React, Vite, Tailwind CSS, SQLite, SQLAlchemy, LangGraph, Tavily Search API, Groq LLM API, Gmail SMTP, ReportLab, python-docx, pytest",
  databaseTables: "users, reports, research_sources, audit_logs, otp_codes, run_checkpoints",
  mainEndpoints: "POST /api/runs, GET /api/runs/{id}, POST /api/auth/otp, POST /api/auth/verify-otp, GET /api/runs/{id}/export/pdf, GET /api/runs/{id}/export/docx",
  tests: "automated pytest unit tests with mocked LLM and search responses",
  features: "Autonomous multi-agent research pipeline (Research, Analysis, Writer), academic citation verification, local SQLite persistence, document export in PDF and DOCX",
  installCommands: "cd backend && python -m venv .venv && .venv\\Scripts\\activate && pip install -r requirements.txt && uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload\ncd frontend && npm install && npm run dev",
  useCiteboltPreset: true,
};

export const COLLEGE_OUTLINE_TEMPLATE: OutlineSection[] = [
  // Front matter
  { level: 1, title: "Title page", is_auto: true },
  { level: 1, title: "Certificate", is_auto: true },
  { level: 1, title: "Acknowledgements", target_words: 200 },
  { level: 1, title: "Abstract", target_words: 250 },
  { level: 1, title: "Table of Contents", is_auto: true },
  { level: 1, title: "List of Figures", is_auto: true },
  { level: 1, title: "List of Tables", is_auto: true },
  { level: 1, title: "List of Publications", is_auto: true },

  // Chapter 1 Introduction (Total ~1,000 words)
  { level: 1, title: "Chapter 1 Introduction" },
  { level: 2, title: "1.1 Overview of the Domain", target_words: 150 },
  { level: 2, title: "1.2 Introduction to [Project]", target_words: 150 },
  { level: 2, title: "1.3 Problem Statement", target_words: 150 },
  { level: 2, title: "1.4 Objectives of the Project", target_words: 150 },
  { level: 2, title: "1.5 Scope of the System", target_words: 150 },
  { level: 2, title: "1.6 Need for the System", target_words: 150 },
  { level: 2, title: "1.7 Motivation", target_words: 100 },

  // Chapter 2 Literature Survey (Total ~1,500 words)
  { level: 1, title: "Chapter 2 Literature Survey" },
  { level: 2, title: "2.1 Detailed Review of Literature", target_words: 700 },
  { level: 2, title: "2.2 Summary of Literature Gaps and Opportunities", target_words: 400 },
  { level: 2, title: "2.3 Problem Formulation Based on Literature", target_words: 400 },

  // Chapter 3 SRS (Total ~2,500 words)
  { level: 1, title: "Chapter 3 Software Requirement Specification (SRS)" },
  { level: 2, title: "3.1 Introduction (Purpose, Project Scope, Constraints, Assumptions)", target_words: 500 },
  { level: 2, title: "3.2 System Features (Functional Requirements)", target_words: 500 },
  { level: 2, title: "3.3 External Interface Requirements", target_words: 350 },
  { level: 2, title: "3.4 Non-Functional Requirements", target_words: 350 },
  { level: 2, title: "3.5 Other Requirements", target_words: 200 },
  { level: 2, title: "3.6 Analysis Model", target_words: 300 },
  { level: 2, title: "3.7 System Implementation Plan", target_words: 300 },

  // Chapter 4 System Design (Total ~2,000 words)
  { level: 1, title: "Chapter 4 System Design" },
  { level: 2, title: "4.1 Introduction", target_words: 150 },
  { level: 2, title: "4.2 System Architecture", target_words: 350 },
  { level: 2, title: "4.3 High-Level Design (HLD)", target_words: 300 },
  { level: 2, title: "4.4 Low-Level Design (LLD)", target_words: 300 },
  { level: 2, title: "4.5 UML Diagrams", target_words: 300 },
  { level: 2, title: "4.6 Data Design", target_words: 200 },
  { level: 2, title: "4.7 Component Design", target_words: 200 },
  { level: 2, title: "4.8 Security Design", target_words: 100 },
  { level: 2, title: "4.9 Summary", target_words: 100 },

  // Chapter 5 Technical Specifications (Total ~1,800 words)
  { level: 1, title: "Chapter 5 Technical Specifications" },
  { level: 2, title: "5.1 Introduction", target_words: 100 },
  { level: 2, title: "5.2 Frontend Technologies", target_words: 250 },
  { level: 2, title: "5.3 Backend Technologies", target_words: 250 },
  { level: 2, title: "5.4 Database Technology", target_words: 200 },
  { level: 2, title: "5.5 Third-Party Services", target_words: 150 },
  { level: 2, title: "5.6 Development Tools", target_words: 150 },
  { level: 2, title: "5.7 System Requirements", target_words: 150 },
  { level: 2, title: "5.8 Technology Stack Summary", target_words: 150 },
  { level: 2, title: "5.9 Advantages of Chosen Technologies", target_words: 200 },
  { level: 2, title: "5.10 Limitations", target_words: 100 },
  { level: 2, title: "5.11 Summary", target_words: 100 },

  // Chapter 6 Project Planning & Scheduling (Total ~1,000 words)
  { level: 1, title: "Chapter 6 Project Planning & Scheduling" },
  { level: 2, title: "6.1 Introduction", target_words: 100 },
  { level: 2, title: "6.2 Project Development Methodology", target_words: 150 },
  { level: 2, title: "6.3 Work Breakdown Structure", target_words: 150 },
  { level: 2, title: "6.4 Project Timeline", target_words: 100 },
  { level: 2, title: "6.5 Gantt Chart", target_words: 100 },
  { level: 2, title: "6.6 Team Structure", target_words: 100 },
  { level: 2, title: "6.7 Effort Estimation", target_words: 100 },
  { level: 2, title: "6.8 Risk Management", target_words: 100 },
  { level: 2, title: "6.9 Resource Allocation", target_words: 50 },
  { level: 2, title: "6.10 Summary", target_words: 50 },

  // Chapter 7 Software Implementation (Total ~2,000 words)
  { level: 1, title: "Chapter 7 Software Implementation" },
  { level: 2, title: "7.1 Introduction", target_words: 150 },
  { level: 2, title: "7.2 System Architecture Overview", target_words: 200 },
  { level: 2, title: "7.3 Database Design (Data Dictionary)", target_words: 250 },
  { level: 2, title: "7.4 Modules Implementation", target_words: 400 },
  { level: 2, title: "7.5 Algorithms Used", target_words: 250 },
  { level: 2, title: "7.6 Business Logic", target_words: 250 },
  { level: 2, title: "7.7 Software Architecture Implementation", target_words: 200 },
  { level: 2, title: "7.8 Advantages of Implementation", target_words: 100 },
  { level: 2, title: "7.9 Disadvantages", target_words: 100 },
  { level: 2, title: "7.10 Applications", target_words: 50 },
  { level: 2, title: "7.11 Summary", target_words: 50 },

  // Chapter 8 Software Testing (Total ~1,500 words)
  { level: 1, title: "Chapter 8 Software Testing" },
  { level: 2, title: "8.1 Introduction", target_words: 100 },
  { level: 2, title: "8.2 Testing Objectives", target_words: 150 },
  { level: 2, title: "8.3 Types of Testing", target_words: 250 },
  { level: 2, title: "8.4 Test Environment", target_words: 150 },
  { level: 2, title: "8.5 Test Cases", target_words: 350 },
  { level: 2, title: "8.6 Test Plan", target_words: 150 },
  { level: 2, title: "8.7 Bug Tracking and Reporting", target_words: 100 },
  { level: 2, title: "8.8 Performance Testing", target_words: 100 },
  { level: 2, title: "8.9 Security Testing", target_words: 100 },
  { level: 2, title: "8.10 Summary", target_words: 50 },

  // Chapter 9 Result and Discussion (Total ~1,500 words)
  { level: 1, title: "Chapter 9 Result and Discussion" },
  { level: 2, title: "9.1 Introduction", target_words: 100 },
  { level: 2, title: "9.2 System Outputs", target_words: 300 },
  { level: 2, title: "9.3 Performance Analysis", target_words: 250 },
  { level: 2, title: "9.4 User Feedback", target_words: 200 },
  { level: 2, title: "9.5 Result Evaluation", target_words: 200 },
  { level: 2, title: "9.6 Comparison with Existing Systems", target_words: 200 },
  { level: 2, title: "9.7 Limitations of the System", target_words: 100 },
  { level: 2, title: "9.8 Discussion", target_words: 100 },
  { level: 2, title: "9.9 Summary", target_words: 50 },

  // Chapter 10 Deployment and Maintenance (Total ~1,200 words)
  { level: 1, title: "Chapter 10 Deployment and Maintenance" },
  { level: 2, title: "10.1 Introduction", target_words: 100 },
  { level: 2, title: "10.2 System Deployment", target_words: 200 },
  { level: 2, title: "10.3 Installation Process", target_words: 200 },
  { level: 2, title: "10.4 User Guide", target_words: 250 },
  { level: 2, title: "10.5 Maintenance", target_words: 150 },
  { level: 2, title: "10.6 Backup and Recovery", target_words: 150 },
  { level: 2, title: "10.7 Challenges During Deployment", target_words: 100 },
  { level: 2, title: "10.8 Summary", target_words: 50 },

  // Chapter 11 Conclusion and Future Scope (Total ~600 words)
  { level: 1, title: "Chapter 11 Conclusion and Future Scope" },
  { level: 2, title: "11.1 Introduction", target_words: 100 },
  { level: 2, title: "11.2 Conclusion", target_words: 250 },
  { level: 2, title: "11.3 Future Scope", target_words: 250 },

  // Post-body
  { level: 1, title: "References", is_auto: true },
  { level: 1, title: "Appendix A: Certificates of Publication", is_auto: true },
  { level: 1, title: "Appendix B: Glossary", is_auto: true },
];

export function scaleOutlineWords(
  sections: OutlineSection[],
  targetTotal: number,
): OutlineSection[] {
  // If Long length selected (targetTotal >= 8000), preserve exact default chapter word targets (~17,050 words)
  if (targetTotal >= 8000) {
    const defaultMap = new Map(COLLEGE_OUTLINE_TEMPLATE.map((s) => [s.title, s.target_words]));
    return sections.map((s) => {
      if (defaultMap.has(s.title)) {
        return { ...s, target_words: defaultMap.get(s.title) };
      }
      return s;
    });
  }

  const currentTotal =
    sections
      .filter((s) => !s.is_auto && (s.target_words || 0) > 0)
      .reduce((sum, s) => sum + (s.target_words || 0), 0) || 1;

  return sections.map((s) => {
    if (s.is_auto || !s.target_words) return s;
    if (s.title === "Acknowledgements" || s.title === "Abstract") return s;
    const scaled = Math.max(
      50,
      Math.round(((s.target_words / currentTotal) * targetTotal) / 25) * 25,
    );
    return { ...s, target_words: scaled };
  });
}

export function cleanTopicForTitle(topic?: string | null): string {
  if (!topic) return "";
  return topic.trim().replace(/\.+$/, "").trim();
}

