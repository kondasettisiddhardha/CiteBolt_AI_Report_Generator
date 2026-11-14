import { useState } from "react";
import { Moon, Sun } from "lucide-react";

export type ThemeMode = "light" | "dark" | "system";

export default function ThemeToggle({
  mode,
  onChange,
  className,
}: {
  mode: ThemeMode;
  onChange: (next: ThemeMode) => void;
  className?: string;
}) {
  const [current, setCurrent] = useState<ThemeMode>(mode);

  const toggle = () => {
    const next = current === "dark" ? "light" : "dark";
    setCurrent(next);
    onChange(next);
  };

  return (
    <button
      type="button"
      onClick={toggle}
      className={`inline-flex h-8 w-8 items-center justify-center rounded-lg border border-line text-muted transition-colors hover:bg-accent-soft hover:text-fg ${className ?? ""}`}
      aria-label={current === "dark" ? "Switch to light mode" : "Switch to dark mode"}
    >
      {current === "dark" ? (
        <Sun className="h-4 w-4" aria-hidden="true" />
      ) : (
        <Moon className="h-4 w-4" aria-hidden="true" />
      )}
    </button>
  );
}
