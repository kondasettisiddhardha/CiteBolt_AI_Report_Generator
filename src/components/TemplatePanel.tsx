import React, { useEffect, useState } from "react";
import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  FileCheck,
  Loader2,
  Plus,
  Trash2,
  Upload,
} from "lucide-react";
import { toast } from "sonner";
import {
  type OutlineSection,
  type TeamMember,
  type CollegeFrontMatter,
  COLLEGE_OUTLINE_TEMPLATE,
  scaleOutlineWords,
  DEFAULT_COLLEGE_FRONT_MATTER,
} from "@/lib/collegeTemplate";

export type { OutlineSection, TeamMember, CollegeFrontMatter };
export { COLLEGE_OUTLINE_TEMPLATE, scaleOutlineWords, DEFAULT_COLLEGE_FRONT_MATTER };

export interface SavedTemplateItem {
  id: string;
  name: string;
  outline: OutlineSection[];
}

interface TemplatePanelProps {
  targetTotalWords: number;
  outline?: OutlineSection[];
  frontMatter?: CollegeFrontMatter;
  isCollegeChipActive?: boolean;
  templateName?: string;
  onUpdate: (
    outline: OutlineSection[] | undefined,
    frontMatter: CollegeFrontMatter | undefined,
    isCollege: boolean,
    name?: string,
  ) => void;
}

export default function TemplatePanel({
  targetTotalWords,
  outline,
  frontMatter,
  isCollegeChipActive = false,
  templateName,
  onUpdate,
}: TemplatePanelProps) {
  const [uploading, setUploading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [isExpanded, setIsExpanded] = useState(Boolean(outline && outline.length > 0));
  const [savedTemplates, setSavedTemplates] = useState<SavedTemplateItem[]>([]);

  useEffect(() => {
    fetch("/api/templates", { credentials: "include" })
      .then((res) => (res.ok ? res.json() : []))
      .then((data) => {
        if (Array.isArray(data)) setSavedTemplates(data);
      })
      .catch(() => {});
  }, []);

  const [collegeForm, setCollegeForm] = useState<CollegeFrontMatter>(
    frontMatter ?? {
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
    },
  );

  const hasTemplate = Boolean(outline && outline.length > 0);

  // Rescale outline whenever target total words changes
  useEffect(() => {
    if (outline && outline.length > 0) {
      const rescaled = scaleOutlineWords(outline, targetTotalWords);
      const totalWords = rescaled.reduce((sum, s) => sum + (s.target_words || 0), 0);
      const oldTotal = outline.reduce((sum, s) => sum + (s.target_words || 0), 0);
      if (Math.abs(totalWords - oldTotal) > 100) {
        onUpdate(rescaled, isCollegeChipActive ? collegeForm : undefined, isCollegeChipActive, templateName);
      }
    }
  }, [targetTotalWords]);

  const handleUseSaved = (tmpl: SavedTemplateItem) => {
    setErrorMsg(null);
    const scaled = scaleOutlineWords(tmpl.outline, targetTotalWords);
    onUpdate(scaled, undefined, false, tmpl.name);
    toast.success(`Applied template: ${tmpl.name}`);
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.size > 10 * 1024 * 1024) {
      toast.error("File exceeds 10 MB limit.");
      return;
    }

    setUploading(true);
    setErrorMsg(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("/api/templates/outline", {
        method: "POST",
        body: formData,
        credentials: "include",
      });

      const data = await res.json();
      if (!res.ok) {
        if (
          data.detail === "scan_no_text" ||
          (typeof data.detail === "string" && data.detail.includes("scanned"))
        ) {
          throw new Error(
            "This document appears to be a scanned image without a text layer. Please upload a document with selectable text.",
          );
        }
        throw new Error(data.detail || "Could not extract outline.");
      }

      const extracted: OutlineSection[] = (data.outline || []).map(
        (s: { level?: number; title?: string; suggested_words?: number }) => ({
          level: (s.level as 1 | 2 | 3) || 1,
          title: s.title || "Section",
          target_words: s.suggested_words || 350,
        }),
      );

      const scaled = scaleOutlineWords(extracted, targetTotalWords);
      onUpdate(scaled, undefined, false, file.name);
      toast.success("Reference outline extracted successfully!");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Upload failed.";
      setErrorMsg(msg);
      toast.error(msg);
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  const handleRemoveTemplate = () => {
    onUpdate(undefined, undefined, false, undefined);
    setErrorMsg(null);
    setIsExpanded(false);
    toast.info("Template removed. Reverted to standard report types.");
  };

  const updateSection = (idx: number, patch: Partial<OutlineSection>) => {
    if (!outline) return;
    const next = outline.map((s, i) => (i === idx ? { ...s, ...patch } : s));
    onUpdate(next, isCollegeChipActive ? collegeForm : undefined, isCollegeChipActive, templateName);
  };

  const moveSection = (idx: number, direction: -1 | 1) => {
    if (!outline) return;
    const targetIdx = idx + direction;
    if (targetIdx < 0 || targetIdx >= outline.length) return;
    const next = [...outline];
    const [moved] = next.splice(idx, 1);
    next.splice(targetIdx, 0, moved);
    onUpdate(next, isCollegeChipActive ? collegeForm : undefined, isCollegeChipActive, templateName);
  };

  const removeSection = (idx: number) => {
    if (!outline) return;
    if (outline.length <= 1) {
      toast.error("An outline must have at least one section.");
      return;
    }
    const next = outline.filter((_, i) => i !== idx);
    onUpdate(next, isCollegeChipActive ? collegeForm : undefined, isCollegeChipActive, templateName);
  };

  const addSection = () => {
    if (!outline) return;
    const next: OutlineSection[] = [
      ...outline,
      { level: 1, title: "New Section", target_words: 300 },
    ];
    onUpdate(next, isCollegeChipActive ? collegeForm : undefined, isCollegeChipActive, templateName);
  };

  const handleCollegeFieldChange = (field: keyof CollegeFrontMatter, val: unknown) => {
    const updated = { ...collegeForm, [field]: val };
    setCollegeForm(updated);
    if (outline) {
      onUpdate(outline, updated, true, templateName);
    }
  };

  const handleAddMember = () => {
    const members = [...collegeForm.teamMembers, { name: "", prn: "" }];
    handleCollegeFieldChange("teamMembers", members);
  };

  const handleRemoveMember = (idx: number) => {
    if (collegeForm.teamMembers.length <= 1) return;
    const members = collegeForm.teamMembers.filter((_, i) => i !== idx);
    handleCollegeFieldChange("teamMembers", members);
  };

  const handleMemberChange = (idx: number, field: "name" | "prn", val: string) => {
    const members = collegeForm.teamMembers.map((m, i) =>
      i === idx ? { ...m, [field]: val } : m,
    );
    handleCollegeFieldChange("teamMembers", members);
  };

  const totalWords = (outline || []).reduce(
    (sum, s) => sum + (s.target_words || s.suggested_words || 0),
    0,
  );

  // When collapsed and no template is attached: render single row "+ Use a reference template"
  if (!hasTemplate && !isExpanded) {
    return (
      <div className="w-full pt-1">
        <button
          type="button"
          onClick={() => setIsExpanded(true)}
          className="inline-flex items-center gap-1.5 text-xs font-semibold text-accent hover:underline"
        >
          <Plus className="h-3.5 w-3.5" />
          <span>+ Use a reference template</span>
        </button>
      </div>
    );
  }

  return (
    <div className="w-full rounded-xl border border-line bg-surface p-4 transition-all space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line pb-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-fg">
              {hasTemplate && isCollegeChipActive
                ? "Using: College project report"
                : hasTemplate && templateName
                ? `Using: ${templateName}`
                : "Reference template (optional)"}
            </h3>
            {hasTemplate && (
              <span className="inline-flex items-center gap-1 rounded bg-accent/10 px-2 py-0.5 text-[11px] font-semibold text-accent">
                <FileCheck className="h-3 w-3" />
                Active
              </span>
            )}
          </div>
          <p className="mt-0.5 text-xs text-muted">
            {hasTemplate && isCollegeChipActive
              ? "College project report format (BE Project Stage) active."
              : "Match a required structure from an uploaded reference document. Only headings are copied, never body text."}
          </p>
        </div>

        {hasTemplate ? (
          <button
            type="button"
            onClick={handleRemoveTemplate}
            className="text-xs font-medium text-red-500 hover:underline"
          >
            Remove
          </button>
        ) : (
          <button
            type="button"
            onClick={() => setIsExpanded(false)}
            className="text-xs text-muted hover:text-fg"
          >
            Collapse
          </button>
        )}
      </div>

      {/* When no template is active: show upload box and saved template dropdown (only if saved templates exist) */}
      {!hasTemplate && (
        <div className="space-y-3">
          {savedTemplates.length > 0 && (
            <div className="flex flex-wrap items-center gap-3">
              <select
                aria-label="Use saved template"
                onChange={(e) => {
                  const tmpl = savedTemplates.find((t) => t.id === e.target.value);
                  if (tmpl) handleUseSaved(tmpl);
                }}
                defaultValue=""
                className="rounded-lg border border-line bg-bg px-3 py-1.5 text-xs text-fg focus:outline-none"
              >
                <option value="" disabled>
                  Use saved template...
                </option>
                {savedTemplates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name} ({t.outline.length} sections)
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Upload box labelled Structure reference (headings only) */}
          <label className="flex cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed border-line bg-bg p-4 text-center transition-colors hover:border-accent hover:bg-accent-soft/20">
            <input
              type="file"
              accept=".pdf,.docx,.md"
              onChange={handleFileUpload}
              disabled={uploading}
              className="hidden"
            />
            {uploading ? (
              <div className="flex items-center gap-2 text-xs font-medium text-accent">
                <Loader2 className="h-4 w-4 animate-spin" />
                Extracting headings...
              </div>
            ) : (
              <div className="flex flex-col items-center gap-1">
                <Upload className="h-4 w-4 text-accent" />
                <span className="text-xs font-semibold text-fg">
                  Structure reference (headings only)
                </span>
                <span className="text-[11px] text-muted">
                  Upload .pdf, .docx, or .md (max 10 MB). Only headings are copied.
                </span>
              </div>
            )}
          </label>
        </div>
      )}

      {/* Error message */}
      {errorMsg && (
        <div className="flex items-start gap-2 rounded-lg border border-red-300 bg-red-50 p-2.5 text-xs text-red-700 dark:border-red-900/50 dark:bg-red-950/20 dark:text-red-300">
          <AlertCircle className="h-4 w-4 shrink-0 text-red-500" />
          <span>{errorMsg}</span>
        </div>
      )}

      {/* College Project Report Front-Matter Form */}
      {hasTemplate && isCollegeChipActive && (
        <div className="rounded-lg border border-line bg-bg p-3.5 space-y-3">
          <div className="border-b border-line pb-2">
            <h4 className="text-xs font-bold uppercase tracking-wider text-accent">
              College Front Matter & Certificate Details
            </h4>
            <p className="mt-0.5 text-[11px] text-muted">
              These fill the Title page and Certificate. Leave blank if not applicable (never invented).
            </p>
          </div>

          <div className="grid gap-2.5 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <label className="block text-[11px] font-medium text-muted">Project Title</label>
              <input
                type="text"
                value={collegeForm.projectTitle}
                onChange={(e) => handleCollegeFieldChange("projectTitle", e.target.value)}
                placeholder="e.g. AI-Powered Autonomous Cloud Cost Optimization System"
                className="mt-1 w-full rounded-md border border-line bg-surface px-2.5 py-1 text-xs text-fg focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </div>

            {/* Team Members Rows */}
            <div className="sm:col-span-2 space-y-1.5">
              <div className="flex items-center justify-between">
                <label className="block text-[11px] font-medium text-muted">
                  Team Members (Name & PRN)
                </label>
                <button
                  type="button"
                  onClick={handleAddMember}
                  className="inline-flex items-center gap-1 text-[11px] font-semibold text-accent hover:underline"
                >
                  <Plus className="h-3 w-3" /> Add member
                </button>
              </div>
              {collegeForm.teamMembers.map((m, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <input
                    type="text"
                    value={m.name}
                    onChange={(e) => handleMemberChange(idx, "name", e.target.value)}
                    placeholder={`Member ${idx + 1} Name`}
                    className="flex-1 rounded-md border border-line bg-surface px-2.5 py-1 text-xs text-fg focus:outline-none"
                  />
                  <input
                    type="text"
                    value={m.prn}
                    onChange={(e) => handleMemberChange(idx, "prn", e.target.value)}
                    placeholder="PRN / Roll No"
                    className="w-32 rounded-md border border-line bg-surface px-2.5 py-1 text-xs text-fg focus:outline-none"
                  />
                  {collegeForm.teamMembers.length > 1 && (
                    <button
                      type="button"
                      onClick={() => handleRemoveMember(idx)}
                      className="rounded p-1 text-muted hover:text-red-500"
                      title="Remove member"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              ))}
            </div>

            <div>
              <label className="block text-[11px] font-medium text-muted">Project Guide / Supervisor</label>
              <input
                type="text"
                value={collegeForm.guide}
                onChange={(e) => handleCollegeFieldChange("guide", e.target.value)}
                placeholder="e.g. Dr. Jane Smith"
                className="mt-1 w-full rounded-md border border-line bg-surface px-2.5 py-1 text-xs text-fg focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-[11px] font-medium text-muted">Project Coordinator</label>
              <input
                type="text"
                value={collegeForm.coordinator}
                onChange={(e) => handleCollegeFieldChange("coordinator", e.target.value)}
                placeholder="e.g. Prof. Alan Brown"
                className="mt-1 w-full rounded-md border border-line bg-surface px-2.5 py-1 text-xs text-fg focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-[11px] font-medium text-muted">Head of Department (HOD)</label>
              <input
                type="text"
                value={collegeForm.hod}
                onChange={(e) => handleCollegeFieldChange("hod", e.target.value)}
                placeholder="e.g. Dr. Robert Wilson"
                className="mt-1 w-full rounded-md border border-line bg-surface px-2.5 py-1 text-xs text-fg focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-[11px] font-medium text-muted">Principal / Dean</label>
              <input
                type="text"
                value={collegeForm.dean}
                onChange={(e) => handleCollegeFieldChange("dean", e.target.value)}
                placeholder="e.g. Dr. Maria Garcia"
                className="mt-1 w-full rounded-md border border-line bg-surface px-2.5 py-1 text-xs text-fg focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-[11px] font-medium text-muted">Department</label>
              <input
                type="text"
                value={collegeForm.department}
                onChange={(e) => handleCollegeFieldChange("department", e.target.value)}
                placeholder="e.g. Computer Science & Engineering"
                className="mt-1 w-full rounded-md border border-line bg-surface px-2.5 py-1 text-xs text-fg focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-[11px] font-medium text-muted">College / University</label>
              <input
                type="text"
                value={collegeForm.university}
                onChange={(e) => handleCollegeFieldChange("university", e.target.value)}
                placeholder="e.g. Stanford University"
                className="mt-1 w-full rounded-md border border-line bg-surface px-2.5 py-1 text-xs text-fg focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-[11px] font-medium text-muted">Academic Year</label>
              <input
                type="text"
                value={collegeForm.academicYear}
                onChange={(e) => handleCollegeFieldChange("academicYear", e.target.value)}
                placeholder="e.g. 2026-2027"
                className="mt-1 w-full rounded-md border border-line bg-surface px-2.5 py-1 text-xs text-fg focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-[11px] font-medium text-muted">Submission Month & Year</label>
              <input
                type="text"
                value={collegeForm.submissionMonthYear}
                onChange={(e) => handleCollegeFieldChange("submissionMonthYear", e.target.value)}
                placeholder="e.g. November 2026"
                className="mt-1 w-full rounded-md border border-line bg-surface px-2.5 py-1 text-xs text-fg focus:outline-none"
              />
            </div>
          </div>
        </div>
      )}

      {/* Editable Outline List */}
      {hasTemplate && outline && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-fg">
              Outline ({outline.length} sections · {totalWords.toLocaleString()} words · ~{Math.max(1, Math.round(totalWords / 380))} pages)
            </span>
            <button
              type="button"
              onClick={addSection}
              className="inline-flex items-center gap-1 text-[11px] font-semibold text-accent hover:underline"
            >
              <Plus className="h-3 w-3" />
              Add section
            </button>
          </div>

          <div className="max-h-[300px] space-y-1.5 overflow-y-auto pr-1">
            {outline.map((sec, idx) => (
              <div
                key={idx}
                className="flex items-center gap-2 rounded-md border border-line bg-bg p-1.5 transition-colors hover:border-line-strong"
              >
                {/* Level Selector */}
                <select
                  value={sec.level}
                  onChange={(e) =>
                    updateSection(idx, { level: Number(e.target.value) as 1 | 2 | 3 })
                  }
                  className="rounded border border-line bg-surface px-1 py-0.5 text-[11px] font-semibold text-muted"
                >
                  <option value={1}>H1</option>
                  <option value={2}>H2</option>
                  <option value={3}>H3</option>
                </select>

                {/* Section Title */}
                <input
                  type="text"
                  value={sec.title}
                  onChange={(e) => updateSection(idx, { title: e.target.value })}
                  className="flex-1 min-w-0 rounded border border-transparent bg-transparent px-1.5 py-0.5 text-xs text-fg hover:border-line focus:border-line-strong focus:bg-surface focus:outline-none"
                />

                {/* Word Target or Auto Badge */}
                {sec.is_auto ? (
                  <span className="inline-flex items-center justify-center rounded border border-line bg-surface px-2 py-0.5 text-[10px] font-semibold text-muted">
                    Auto
                  </span>
                ) : sec.target_words !== undefined ? (
                  <div className="flex items-center gap-1">
                    <input
                      type="number"
                      min={25}
                      step={25}
                      value={sec.target_words}
                      onChange={(e) =>
                        updateSection(idx, { target_words: Math.max(25, Number(e.target.value)) })
                      }
                      className="w-14 rounded border border-line bg-surface px-1 py-0.5 text-right text-xs tabular-nums text-fg focus:outline-none"
                    />
                    <span className="text-[10px] text-muted">w</span>
                  </div>
                ) : (
                  <span className="inline-flex items-center justify-center px-2 py-0.5 text-[11px] text-muted">
                    —
                  </span>
                )}

                {/* Reorder Buttons */}
                <div className="flex items-center">
                  <button
                    type="button"
                    disabled={idx === 0}
                    onClick={() => moveSection(idx, -1)}
                    className="rounded p-0.5 text-muted hover:bg-surface hover:text-fg disabled:opacity-20"
                    title="Move up"
                  >
                    <ArrowUp className="h-3 w-3" />
                  </button>
                  <button
                    type="button"
                    disabled={idx === outline.length - 1}
                    onClick={() => moveSection(idx, 1)}
                    className="rounded p-0.5 text-muted hover:bg-surface hover:text-fg disabled:opacity-20"
                    title="Move down"
                  >
                    <ArrowDown className="h-3 w-3" />
                  </button>
                </div>

                {/* Remove Button */}
                <button
                  type="button"
                  onClick={() => removeSection(idx)}
                  className="rounded p-0.5 text-muted hover:bg-surface hover:text-red-500"
                  title="Remove section"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
