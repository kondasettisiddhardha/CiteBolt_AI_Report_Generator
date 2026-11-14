export type ThemePreference = "light" | "dark" | "system";

const STORAGE_KEY = "dossier-theme";

export function getStoredTheme(): ThemePreference {
  if (typeof window === "undefined") return "system";
  const value = window.localStorage.getItem(STORAGE_KEY);
  return value === "light" || value === "dark" || value === "system" ? value : "system";
}

export function resolvedTheme(preference: ThemePreference): "light" | "dark" {
  if (preference !== "system") return preference;
  if (typeof window === "undefined") return "dark";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(preference: ThemePreference): void {
  if (typeof document === "undefined") return;
  const theme = resolvedTheme(preference);
  document.documentElement.classList.toggle("dark", theme === "dark");
  document.documentElement.dataset.theme = theme;
}

export function setStoredTheme(preference: ThemePreference): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, preference);
  applyTheme(preference);
}

export function watchSystemTheme(onChange: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const listener = () => onChange();
  media.addEventListener("change", listener);
  return () => media.removeEventListener("change", listener);
}
