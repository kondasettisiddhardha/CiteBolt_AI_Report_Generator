import { useState } from "react";

function getStoredCollapsed(): boolean {
  try {
    const stored = window.localStorage.getItem("dossier-sidebar-collapsed");
    if (stored === "1" || stored === "true") return true;
    if (stored === "0" || stored === "false") return false;
    return false;
  } catch {
    return false;
  }
}

function setStoredCollapsed(value: boolean) {
  try {
    window.localStorage.setItem("dossier-sidebar-collapsed", value ? "1" : "0");
  } catch {
    // Ignore storage errors.
  }
}

export function useCollapse() {
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
    return window.matchMedia("(min-width: 1024px)").matches ? false : getStoredCollapsed();
  });

  const toggle = () => {
    setCollapsed((prev) => !prev);
  };

  return { collapsed, setCollapsed, toggle };
}
