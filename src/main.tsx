import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Toaster } from "sonner";
import "./index.css";
import App from "./App";
import ErrorBoundary from "./components/ErrorBoundary";
import { applyTheme, getStoredTheme } from "./lib/theme";

// Initialize saved theme immediately to prevent flashing
applyTheme(getStoredTheme());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
      <Toaster position="bottom-right" richColors closeButton />
    </ErrorBoundary>
  </StrictMode>,
);
