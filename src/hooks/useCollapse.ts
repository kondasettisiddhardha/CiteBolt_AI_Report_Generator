import { useState } from "react";

const STORAGE_KEY = "citebolt-sidebar-collapsed";
const LEGACY_STORAGE_KEY = "dossier-sidebar-collapsed";

function getStoredCollapsed(): boolean {
  if (typeof window === "undefined") return false;
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY) ?? window.localStorage.getItem(LEGACY_STORAGE_KEY);
    return stored === "1" || stored === "true";
  } catch {
    return false;
  }
}

function setStoredCollapsed(value: boolean) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, value ? "1" : "0");
  } catch {
    // Ignore storage errors.
  }
}

export function useCollapse() {
  const [collapsed, setCollapsedState] = useState<boolean>(() => getStoredCollapsed());

  const setCollapsed = (value: boolean | ((prev: boolean) => boolean)) => {
    setCollapsedState((prev) => {
      const next = typeof value === "function" ? value(prev) : value;
      setStoredCollapsed(next);
      return next;
    });
  };

  const toggle = () => {
    setCollapsed((prev) => !prev);
  };

  return { collapsed, setCollapsed, toggle };
}
