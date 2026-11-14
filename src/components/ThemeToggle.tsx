import { Moon, Sun } from "lucide-react";
import type { ThemePreference } from "@/lib/theme";

export type ThemeMode = ThemePreference;

export default function ThemeToggle({
  mode,
  onChange,
  className,
}: {
  mode: ThemeMode;
  onChange: (next: ThemeMode) => void;
  className?: string;
}) {
  const isDark =
    mode === "dark" ||
    (mode === "system" &&
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches);

  const toggle = () => {
    const next: ThemeMode = isDark ? "light" : "dark";
    onChange(next);
  };

  return (
    <button
      type="button"
      onClick={toggle}
      className={`inline-flex h-8 w-8 items-center justify-center rounded-lg border border-line text-muted transition-colors hover:bg-accent-soft hover:text-fg ${className ?? ""}`}
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      title={isDark ? "Switch to light mode" : "Switch to dark mode"}
    >
      {isDark ? (
        <Sun className="h-4 w-4" aria-hidden="true" />
      ) : (
        <Moon className="h-4 w-4" aria-hidden="true" />
      )}
    </button>
  );
}
