import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Toaster } from "sonner";
import "./index.css";
import App from "./App";
import ErrorBoundary from "./components/ErrorBoundary";


createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
      <Toaster position="bottom-right" richColors closeButton />
    </ErrorBoundary>
  </StrictMode>,
);
