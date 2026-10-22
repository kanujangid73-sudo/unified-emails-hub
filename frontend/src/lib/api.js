import { API_URL } from "../config.js";

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

function errorMessage(body, status) {
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  // FastAPI validation errors: [{loc, msg}, ...]
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0];
    const field = first.loc?.[first.loc.length - 1];
    return field ? `${field}: ${first.msg}` : first.msg;
  }
  return `Request failed (HTTP ${status})`;
}

export async function api(path, { token, method = "GET", body } = {}) {
  let res;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method,
      headers: {
        ...(body ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(`Cannot reach the server at ${API_URL}. Is the backend running?`, 0);
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(errorMessage(data, res.status), res.status);
  return data;
}
