import * as pdfjsLib from "pdfjs-dist";
import workerSrc from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { API_BASE } from "./api";

pdfjsLib.GlobalWorkerOptions.workerSrc = workerSrc;

/** Extract text from a PDF in the browser, page by page. */
export async function extractPdfInBrowser(file: File): Promise<string> {
  const data = new Uint8Array(await file.arrayBuffer());
  const document = await pdfjsLib.getDocument({ data }).promise;
  const pages: string[] = [];

  try {
    for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
      const page = await document.getPage(pageNumber);
      const content = await page.getTextContent();
      const text = content.items
        .map((item) => ("str" in item ? item.str : ""))
        .join(" ")
        .replace(/\s+/g, " ")
        .trim();
      if (text) pages.push(text);
    }
  } finally {
    await document.destroy();
  }

  return pages.join("\n\n").trim();
}

/** Server-side fallback using pypdf, for PDFs the browser can't read. */
export async function extractPdfOnServer(file: File): Promise<string> {
  const response = await fetch(`${API_BASE}/api/extract`, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/pdf",
      "X-Filename": encodeURIComponent(file.name),
    },
    body: await file.arrayBuffer(),
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(
      payload && typeof payload === "object" && "detail" in payload
        ? String((payload as { detail: unknown }).detail)
        : "Couldn't read text from that PDF.",
    );
  }

  const data: { text: string } = await response.json();
  if (!data.text?.trim()) throw new Error("That PDF has no readable text.");
  return data.text;
}

/** Browser first, then the server; only fails when both come back empty. */
export async function extractPdfText(file: File): Promise<string> {
  let browserError: unknown = null;

  try {
    const text = await extractPdfInBrowser(file);
    if (text.trim()) return text;
  } catch (error) {
    browserError = error;
  }

  try {
    return await extractPdfOnServer(file);
  } catch (serverError) {
    const reason = serverError instanceof Error ? serverError.message : "";
    if (reason.includes("scan_no_text") || reason.includes("no text layer")) {
      throw new Error("This PDF has no text layer (scanned document). Please run OCR before uploading or paste the text directly.");
    }
    if (browserError instanceof Error && browserError.message) {
      throw new Error(reason || "Couldn't extract text from that PDF.");
    }
    throw new Error("Couldn't read text from that PDF. Scans without text layers cannot be read.");
  }
}
