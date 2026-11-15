import { useEffect, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  Bookmark,
  Check,
  ChevronDown,
  FileCheck,
  Plus,
  Trash2,
  Upload,
  Loader2,
  AlertCircle,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

export interface OutlineSection {
  level: 1 | 2 | 3;
  title: string;
  suggested_words?: number;
  target_words?: number;
}

export interface SavedTemplate {
  id: string;
  name: string;
  outline: OutlineSection[];
  created_at: string;
}

interface OutlineEditorProps {
  initialOutline?: OutlineSection[];
  initialTitle?: string;
  onConfirm: (outline: OutlineSection[], title: string) => void;
  targetTotalWords: number;
}

export default function OutlineEditor({
  initialOutline = [],
  initialTitle = "",
  onConfirm,
  targetTotalWords,
}: OutlineEditorProps) {
  const [outline, setOutline] = useState<OutlineSection[]>(initialOutline);
  const [docTitle, setDocTitle] = useState(initialTitle);
  const [savedTemplates, setSavedTemplates] = useState<SavedTemplate[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [savingTemplate, setSavingTemplate] = useState(false);
  const [templateName, setTemplateName] = useState("");
  const [showSaveInput, setShowSaveInput] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Load saved templates
  useEffect(() => {
    void api<SavedTemplate[]>("/api/templates")
      .then((data) => setSavedTemplates(data || []))
      .catch(() => setSavedTemplates([]));
  }, []);

  const totalWords = outline.reduce(
    (sum, s) => sum + (s.target_words ?? s.suggested_words ?? 0),
    0,
  );

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
        if (data.detail === "scan_no_text" || (typeof data.detail === "string" && data.detail.includes("scanned"))) {
          throw new Error("This document appears to be a scanned image without a text layer. Please upload a document with selectable text.");
        }
        throw new Error(data.detail || "Could not extract outline.");
      }

      setDocTitle(data.title || file.name.replace(/\.[^/.]+$/, ""));
      setOutline(
        (data.outline || []).map((s: OutlineSection) => ({
          level: s.level || 1,
          title: s.title || "Section",
          target_words: s.suggested_words || 350,
        })),
      );
      setConfirmed(false);
      toast.success("Outline extracted successfully!");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Upload failed.";
      setErrorMsg(msg);
      toast.error(msg);
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  const handleSelectTemplate = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const id = e.target.value;
    setSelectedTemplateId(id);
    if (!id) return;
    const tmpl = savedTemplates.find((t) => t.id === id);
    if (tmpl) {
      setDocTitle(tmpl.name);
      setOutline(tmpl.outline);
      setConfirmed(false);
      toast.info(`Loaded template "${tmpl.name}"`);
    }
  };

  const saveCurrentAsTemplate = async () => {
    const name = templateName.trim() || docTitle.trim();
    if (!name) {
      toast.error("Please enter a template name.");
      return;
    }
    if (outline.length === 0) {
      toast.error("Outline cannot be empty.");
      return;
    }

    setSavingTemplate(true);
    try {
      const created = await api<SavedTemplate>("/api/templates", {
        method: "POST",
        body: JSON.stringify({ name, outline }),
      });
      setSavedTemplates((prev) => [created, ...prev]);
      setSelectedTemplateId(created.id);
      setShowSaveInput(false);
      setTemplateName("");
      toast.success(`Template "${name}" saved!`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save template.");
    } finally {
      setSavingTemplate(false);
    }
  };

  const updateSection = (idx: number, patch: Partial<OutlineSection>) => {
    setOutline((prev) => prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)));
    setConfirmed(false);
  };

  const removeSection = (idx: number) => {
    setOutline((prev) => prev.filter((_, i) => i !== idx));
    setConfirmed(false);
  };

  const moveSection = (idx: number, dir: -1 | 1) => {
    const targetIdx = idx + dir;
    if (targetIdx < 0 || targetIdx >= outline.length) return;
    setOutline((prev) => {
      const copy = [...prev];
      const temp = copy[idx];
      copy[idx] = copy[targetIdx];
      copy[targetIdx] = temp;
      return copy;
    });
    setConfirmed(false);
  };

  const addSection = () => {
    setOutline((prev) => [
      ...prev,
      {
        level: 1,
        title: `New Section ${prev.length + 1}`,
        target_words: Math.max(150, Math.round(targetTotalWords / (prev.length + 1))),
      },
    ]);
    setConfirmed(false);
  };

  const handleConfirm = () => {
    if (outline.length === 0) {
      toast.error("Please add at least one section to the outline.");
      return;
    }
    setConfirmed(true);
    onConfirm(outline, docTitle || "Reference Outline");
    toast.success("Outline confirmed for this run!");
  };

  return (
    <div className="mt-4 rounded-xl border border-line bg-surface p-5">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line pb-4">
        <div>
          <h3 className="text-sm font-semibold text-fg">Reference Document & Outline</h3>
          <p className="text-xs text-muted">
            Upload a .pdf, .docx, or .md reference (max 10 MB) to extract its section structure.
          </p>
        </div>

        {/* Saved Templates Dropdown */}
        {savedTemplates.length > 0 && (
          <div className="flex items-center gap-2">
            <Bookmark className="h-3.5 w-3.5 text-accent" />
            <select
              value={selectedTemplateId}
              onChange={handleSelectTemplate}
              className="rounded-lg border border-line bg-bg px-2.5 py-1 text-xs text-fg focus:outline-none"
            >
              <option value="">Reuse a saved template...</option>
              {savedTemplates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} ({t.outline.length} sections)
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {/* File Upload Box */}
      <div className="mt-4">
        <label className="flex cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-line bg-bg/50 p-5 transition-colors hover:border-accent hover:bg-accent-soft/30">
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
              Extracting outline structure from document...
            </div>
          ) : (
            <div className="flex flex-col items-center gap-1.5 text-center">
              <Upload className="h-5 w-5 text-accent" />
              <span className="text-xs font-medium text-fg">
                Upload reference document (.pdf, .docx, .md)
              </span>
              <span className="text-[11px] text-muted">
                Extracts headings only. Body text is never stored or transmitted.
              </span>
            </div>
          )}
        </label>
      </div>

      {/* Error Banner */}
      {errorMsg && (
        <div className="mt-3 flex items-start gap-2 rounded-lg border border-red-300 bg-red-50 p-3 text-xs text-red-700 dark:border-red-900/50 dark:bg-red-950/20 dark:text-red-300">
          <AlertCircle className="h-4 w-4 shrink-0 text-red-500" />
          <span>{errorMsg}</span>
        </div>
      )}

      {/* Editable Outline List */}
      {outline.length > 0 && (
        <div className="mt-5 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex-1 min-w-[200px]">
              <label className="block text-xs font-medium text-muted">Document / Outline Title</label>
              <input
                type="text"
                value={docTitle}
                onChange={(e) => {
                  setDocTitle(e.target.value);
                  setConfirmed(false);
                }}
                className="mt-1 w-full rounded-lg border border-line bg-bg px-3 py-1.5 text-sm font-semibold text-fg focus:outline-none"
                placeholder="Template Title"
              />
            </div>

            <div className="text-right">
              <span className="text-xs text-muted">Total Target</span>
              <p className="text-sm font-bold tabular-nums text-fg">
                {totalWords.toLocaleString()} words ({outline.length} sections)
              </p>
            </div>
          </div>

          <div className="max-h-[360px] space-y-2 overflow-y-auto pr-1">
            {outline.map((sec, idx) => (
              <div
                key={idx}
                className="flex items-center gap-2 rounded-lg border border-line bg-bg p-2 transition-colors hover:border-line-strong"
              >
                {/* Level Toggle */}
                <select
                  value={sec.level}
                  onChange={(e) =>
                    updateSection(idx, { level: Number(e.target.value) as 1 | 2 | 3 })
                  }
                  className="rounded border border-line bg-surface px-1.5 py-1 text-xs font-semibold text-muted"
                  title="Heading level"
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
                  className="flex-1 min-w-0 rounded border border-transparent bg-transparent px-2 py-1 text-xs text-fg hover:border-line focus:border-line-strong focus:bg-surface focus:outline-none"
                  placeholder="Section title"
                />

                {/* Section Word Target */}
                <div className="flex items-center gap-1">
                  <input
                    type="number"
                    min={50}
                    step={25}
                    value={sec.target_words ?? sec.suggested_words ?? 300}
                    onChange={(e) =>
                      updateSection(idx, { target_words: Math.max(50, Number(e.target.value)) })
                    }
                    className="w-16 rounded border border-line bg-surface px-1.5 py-1 text-right text-xs tabular-nums text-fg focus:outline-none"
                    title="Target word count"
                  />
                  <span className="text-[11px] text-muted">w</span>
                </div>

                {/* Reorder Buttons */}
                <div className="flex items-center gap-0.5">
                  <button
                    type="button"
                    disabled={idx === 0}
                    onClick={() => moveSection(idx, -1)}
                    className="rounded p-1 text-muted hover:bg-surface hover:text-fg disabled:opacity-30"
                    title="Move up"
                  >
                    <ArrowUp className="h-3 w-3" />
                  </button>
                  <button
                    type="button"
                    disabled={idx === outline.length - 1}
                    onClick={() => moveSection(idx, 1)}
                    className="rounded p-1 text-muted hover:bg-surface hover:text-fg disabled:opacity-30"
                    title="Move down"
                  >
                    <ArrowDown className="h-3 w-3" />
                  </button>
                </div>

                {/* Delete Button */}
                <button
                  type="button"
                  onClick={() => removeSection(idx)}
                  className="rounded p-1 text-muted hover:bg-surface hover:text-red-500"
                  title="Remove section"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>

          {/* Add Section & Save Template Controls */}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
            <button
              type="button"
              onClick={addSection}
              className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-1.5 text-xs font-medium text-fg hover:bg-accent-soft"
            >
              <Plus className="h-3.5 w-3.5" />
              Add section
            </button>

            <div className="flex items-center gap-2">
              {!showSaveInput ? (
                <button
                  type="button"
                  onClick={() => setShowSaveInput(true)}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-1.5 text-xs font-medium text-muted hover:text-fg"
                >
                  <Bookmark className="h-3.5 w-3.5" />
                  Save as template
                </button>
              ) : (
                <div className="flex items-center gap-1.5">
                  <input
                    type="text"
                    value={templateName}
                    onChange={(e) => setTemplateName(e.target.value)}
                    placeholder="Template name..."
                    className="rounded-lg border border-line bg-bg px-2.5 py-1 text-xs text-fg focus:outline-none"
                  />
                  <button
                    type="button"
                    disabled={savingTemplate}
                    onClick={saveCurrentAsTemplate}
                    className="rounded-lg bg-accent px-2.5 py-1 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50"
                  >
                    {savingTemplate ? "Saving..." : "Save"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowSaveInput(false)}
                    className="text-xs text-muted hover:text-fg"
                  >
                    Cancel
                  </button>
                </div>
              )}

              {/* Confirm / Use Outline Button */}
              <button
                type="button"
                onClick={handleConfirm}
                className={`inline-flex items-center gap-1.5 rounded-lg px-4 py-1.5 text-xs font-semibold transition-all ${
                  confirmed
                    ? "border border-emerald-600 bg-emerald-600/10 text-emerald-600 dark:text-emerald-400"
                    : "bg-accent text-white shadow hover:opacity-90"
                }`}
              >
                {confirmed ? (
                  <>
                    <Check className="h-3.5 w-3.5" />
                    Outline confirmed
                  </>
                ) : (
                  <>
                    <FileCheck className="h-3.5 w-3.5" />
                    Use this outline
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
