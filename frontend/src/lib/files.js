import { API_URL } from "../config.js";
import { ApiError } from "./api.js";

export const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024; // in total, as the server allows

export function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function fileKind(mimeType, filename = "") {
  if (mimeType.startsWith("image/")) return "image";
  if (mimeType === "application/pdf" || filename.toLowerCase().endsWith(".pdf")) return "pdf";
  if (/sheet|excel|csv/.test(mimeType)) return "sheet";
  if (/zip|compressed|tar/.test(mimeType)) return "archive";
  return "file";
}

// File -> {filename, mime_type, data (base64)} for the send API.
export function toUpload(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const data = String(reader.result).split(",", 2)[1] || "";
      resolve({ filename: file.name, mime_type: file.type || "application/octet-stream", data });
    };
    reader.onerror = () => reject(new Error(`Couldn't read ${file.name}`));
    reader.readAsDataURL(file);
  });
}

// Download with the login token (a plain link can't send it), then hand the file to the browser.
export async function downloadAttachment(token, attachment) {
  let res;
  try {
    res = await fetch(`${API_URL}/api/attachments/${attachment.id}`, { headers: { Authorization: `Bearer ${token}` } });
  } catch {
    throw new ApiError(`Cannot reach the server at ${API_URL}.`, 0);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(body?.detail || `Download failed (HTTP ${res.status})`, res.status);
  }
  const url = URL.createObjectURL(await res.blob());
  const link = Object.assign(document.createElement("a"), { href: url, download: attachment.filename });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
