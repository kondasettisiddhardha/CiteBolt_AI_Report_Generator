import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { Check, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/hooks/useAuth";
import { getStoredTheme, setStoredTheme, watchSystemTheme, type ThemePreference } from "@/lib/theme";
import { REPORT_TYPES, type ReportType } from "@/components/RunComposer";

const THEMES: Array<{ value: ThemePreference; label: string; hint: string }> = [
  { value: "light", label: "Light", hint: "Off-white background, white cards." },
  { value: "dark", label: "Dark", hint: "Near-black, the default look." },
  { value: "system", label: "System", hint: "Follow your OS setting." },
];

const EXPORTS = [
  { value: "md", label: "Markdown" },
  { value: "pdf", label: "PDF" },
  { value: "docx", label: "Word" },
] as const;

export default function Settings() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [theme, setTheme] = useState<ThemePreference>(getStoredTheme);
  const [reportType, setReportType] = useState<ReportType>("auto");
  const [exportFormat, setExportFormat] = useState<"md" | "pdf" | "docx">("md");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api<{ default_report_type: ReportType; default_export_format: "md" | "pdf" | "docx"; theme: ThemePreference }>(
      "/api/settings",
    )
      .then((data) => {
        setReportType(data.default_report_type);
        setExportFormat(data.default_export_format);
      })
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (theme !== "system") return;
    return watchSystemTheme(() => setStoredTheme("system"));
  }, [theme]);

  async function persist(next: Partial<{ theme: ThemePreference; reportType: ReportType; exportFormat: string }>) {
    setSaving(true);
    try {
      await api("/api/settings", {
        method: "PUT",
        body: JSON.stringify({
          theme: next.theme ?? theme,
          default_report_type: next.reportType ?? reportType,
          default_export_format: next.exportFormat ?? exportFormat,
        }),
      });
    } catch {
      // Preferences still apply locally when the API is unavailable.
    } finally {
      setSaving(false);
    }
  }

  function chooseTheme(value: ThemePreference) {
    setTheme(value);
    setStoredTheme(value);
    void persist({ theme: value });
    toast.success(`Theme set to ${value}`);
  }

  async function deleteAll() {
    if (!window.confirm("Delete every run in this account? This cannot be undone.")) return;
    try {
      const data = await api<{ deleted: number }>("/api/runs", { method: "DELETE" });
      toast.success(`Deleted ${data.deleted} run${data.deleted === 1 ? "" : "s"}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not delete your runs.");
    }
  }

  async function signOut() {
    await logout();
    navigate("/login");
  }

  return (
    <div className="px-5 py-8 sm:px-10">
      <div className="mx-auto max-w-[820px]">
        <h1 className="text-2xl font-bold tracking-tight text-fg sm:text-[32px]">Settings</h1>
        <p className="mt-2 text-sm text-muted">
          Appearance, account and the defaults each new run starts with.
        </p>

        <section className="mt-6 rounded-2xl border border-line bg-surface p-6">
          <h2 className="text-base font-semibold text-fg">Appearance</h2>
          <p className="mt-1 text-sm text-muted">Saved in this browser and on your account.</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            {THEMES.map((option) => {
              const selected = option.value === theme;
              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => chooseTheme(option.value)}
                  aria-pressed={selected}
                  className={`rounded-xl border p-4 text-left transition-colors ${
                    selected ? "border-accent bg-accent-soft" : "border-line bg-bg hover:border-line-strong"
                  }`}
                >
                  <span className="flex items-center justify-between text-sm font-semibold text-fg">
                    {option.label}
                    {selected && <Check className="h-4 w-4 text-accent" aria-hidden="true" />}
                  </span>
                  <span className="mt-1 block text-xs text-muted">{option.hint}</span>
                </button>
              );
            })}
          </div>
        </section>

        <section className="mt-4 rounded-2xl border border-line bg-surface p-6">
          <h2 className="text-base font-semibold text-fg">Account</h2>
          <p className="mt-1 text-sm text-muted">Signed in as {user?.email}</p>
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={signOut}
              className="rounded-lg border border-line px-3 py-1.5 text-xs font-medium text-fg transition-colors hover:bg-accent-soft"
            >
              Log out
            </button>
            <button
              type="button"
              onClick={deleteAll}
              className="rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-700 transition-colors hover:bg-red-50 dark:border-red-500/30 dark:text-red-300 dark:hover:bg-red-500/10"
            >
              Delete all my runs
            </button>
          </div>
        </section>

        <section className="mt-4 rounded-2xl border border-line bg-surface p-6">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-fg">Defaults</h2>
            {saving && <Loader2 className="h-4 w-4 animate-spin text-muted" />}
          </div>
          {loading ? (
            <p className="mt-2 text-sm text-muted">Loading…</p>
          ) : (
            <>
              <p className="mt-1 text-sm text-muted">Applied to new runs and exports.</p>
              <div className="mt-4">
                <p className="text-xs font-medium uppercase tracking-wide text-muted">Report type</p>
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  {REPORT_TYPES.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => {
                        setReportType(option.value);
                        void persist({ reportType: option.value });
                      }}
                      className={`rounded-lg border px-3 py-2 text-left text-sm transition-colors ${
                        reportType === option.value
                          ? "border-accent bg-accent-soft text-fg"
                          : "border-line bg-bg text-muted hover:text-fg"
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="mt-4">
                <p className="text-xs font-medium uppercase tracking-wide text-muted">Export format</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {EXPORTS.map((option) => (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => {
                        setExportFormat(option.value);
                        void persist({ exportFormat: option.value });
                      }}
                      className={`rounded-lg border px-3 py-1.5 text-sm transition-colors ${
                        exportFormat === option.value
                          ? "border-accent bg-accent-soft text-fg"
                          : "border-line bg-bg text-muted hover:text-fg"
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
