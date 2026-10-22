// The backend URL, set at build time. A bare host ("api.example.com") is treated as https.
const raw = (import.meta.env.VITE_API_URL || "http://localhost:8000").trim().replace(/\/+$/, "");

export const API_URL = /^https?:\/\//.test(raw) ? raw : `https://${raw}`;

// http -> ws and https -> wss
export const WS_URL = API_URL.replace(/^http/, "ws");
