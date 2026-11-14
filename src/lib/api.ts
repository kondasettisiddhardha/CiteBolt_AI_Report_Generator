const RAW_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "";

/** API origin. Empty string means "same origin" (the Vite dev proxy). */
export const API_BASE = RAW_BASE.replace(/\/$/, "");

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type") && !(init.body instanceof Blob)) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? String((payload as { detail: unknown }).detail)
        : typeof payload === "string" && payload
          ? payload
          : `Request failed (${response.status})`;
    throw new ApiError(detail, response.status);
  }

  return payload as T;
}

export function exportUrl(runId: string, format: "md" | "pdf" | "docx"): string {
  return `${API_BASE}/api/runs/${runId}/export?format=${format}`;
}
