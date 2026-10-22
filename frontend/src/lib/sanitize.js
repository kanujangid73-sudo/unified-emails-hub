import DOMPurify from "dompurify";

// Email HTML is untrusted: anyone can send anything. It is shown in layers of defence:
// 1. DOMPurify removes scripts, event handlers, forms and other active content.
// 2. The result goes into a sandboxed iframe without allow-scripts, so even something that
//    slipped through cannot run, and it can't reach the app's page or its login token.
// 3. A Content-Security-Policy inside that frame blocks every network request except the
//    images the reader chose to load. Remote images are blocked by default because senders
//    use them as tracking pixels to learn when, where and on what device mail was opened.

const REMOTE = /^(https?:)?\/\//i;

function isRemote(url) {
  return REMOTE.test((url || "").trim());
}

export function sanitizeEmail(html, { allowImages = false } = {}) {
  let blockedImages = 0;
  let trackingPixels = 0;

  const hook = (node) => {
    if (node.tagName === "A") {
      // Open links outside the app and don't tell the target page where the click came from.
      node.setAttribute("target", "_blank");
      node.setAttribute("rel", "noopener noreferrer nofollow");
    }
    if (node.tagName === "IMG" && isRemote(node.getAttribute("src"))) {
      const width = parseInt(node.getAttribute("width") || "0", 10);
      const height = parseInt(node.getAttribute("height") || "0", 10);
      const pixel = width <= 2 && height <= 2 && (width > 0 || height > 0);
      if (pixel) trackingPixels += 1;
      if (pixel || !allowImages) {
        if (!pixel) blockedImages += 1;
        node.setAttribute("data-blocked-src", node.getAttribute("src"));
        node.removeAttribute("src");
        node.removeAttribute("srcset");
        if (!pixel) node.setAttribute("alt", node.getAttribute("alt") || "Image blocked");
      }
    }
  };

  DOMPurify.addHook("afterSanitizeAttributes", hook);
  let clean;
  try {
    clean = DOMPurify.sanitize(html, {
      FORBID_TAGS: ["form", "input", "button", "textarea", "select", "iframe", "object", "embed", "base", "meta", "link"],
      FORBID_ATTR: ["ping"],
    });
  } finally {
    DOMPurify.removeHook("afterSanitizeAttributes");
  }
  return { html: clean, blockedImages, trackingPixels };
}

export function emailDocument(cleanHtml, { allowImages = false } = {}) {
  const img = allowImages ? "data: cid: https:" : "data: cid:";
  const csp = `default-src 'none'; img-src ${img}; style-src 'unsafe-inline'; font-src data:`;
  // Most email is designed for a white page, so keep it white even in dark mode.
  return `<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<base target="_blank">
<style>
  html,body{margin:0;padding:0;background:#fff;color:#1f2937;font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;overflow-wrap:anywhere}
  body{padding:16px}
  img{max-width:100%;height:auto}
  img[data-blocked-src]:not([width="1"]){display:inline-block;min-height:24px;background:#f3f4f6;border:1px dashed #d1d5db;color:#6b7280;font-size:12px}
  table{max-width:100%}
  a{color:#4f46e5}
</style></head><body>${cleanHtml}</body></html>`;
}
