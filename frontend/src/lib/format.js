// Inbox-style dates: the time for today, "Mon 3" style for this year, the full date otherwise.
export function listDate(iso, now = new Date()) {
  const date = new Date(iso);
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }
  if (date.getFullYear() === now.getFullYear()) {
    return date.toLocaleDateString([], { month: "short", day: "numeric" });
  }
  return date.toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" });
}

export function fullDate(iso) {
  return new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

export function initials(name) {
  const words = (name || "?").replace(/[^\p{L}\p{N} ]/gu, " ").trim().split(/\s+/);
  return ((words[0]?.[0] || "?") + (words.length > 1 ? words[words.length - 1][0] : "")).toUpperCase();
}

// A stable colour per sender, so the same person always gets the same avatar.
export function avatarColor(seed) {
  let hash = 0;
  for (const ch of seed || "") hash = (hash * 31 + ch.codePointAt(0)) >>> 0;
  return `hsl(${hash % 360} 55% 45%)`;
}

// Split plain text into strings and {url} parts, so links can be rendered as anchors safely.
export function linkify(text) {
  const parts = [];
  const pattern = /https?:\/\/[^\s<>"')]+/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    parts.push({ url: match[0] });
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}
