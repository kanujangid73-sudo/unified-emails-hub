import { describe, expect, it } from "vitest";
import { emailDocument, sanitizeEmail } from "./sanitize.js";

describe("sanitizeEmail", () => {
  it("removes scripts, event handlers and javascript: links", () => {
    const { html } = sanitizeEmail(
      `<p onclick="steal()">Hi</p><script>steal()</script><a href="javascript:steal()">x</a><img src=x onerror="steal()">`,
    );
    expect(html).not.toMatch(/script|onclick|onerror|javascript:/i);
    expect(html).toContain("<p>Hi</p>");
  });

  it("removes forms that could phish for passwords", () => {
    const { html } = sanitizeEmail(`<form action="https://evil.example"><input name="password"><button>Log in</button></form>`);
    expect(html).not.toMatch(/<form|<input|<button/i);
  });

  it("blocks remote images by default and counts them", () => {
    const result = sanitizeEmail(`<img src="https://cdn.example/banner.png" alt="Banner"><img src="data:image/png;base64,AAAA">`);
    expect(result.blockedImages).toBe(1);
    expect(result.html).toContain('data-blocked-src="https://cdn.example/banner.png"');
    expect(result.html).not.toMatch(/\ssrc="https:/);
    expect(result.html).toContain('src="data:image/png;base64,AAAA"');
  });

  it("always blocks tracking pixels, even when images are allowed", () => {
    const html = `<img src="https://cdn.example/a.png" width="600"><img src="https://track.example/open.gif" width="1" height="1">`;
    const shown = sanitizeEmail(html, { allowImages: true });
    expect(shown.trackingPixels).toBe(1);
    expect(shown.blockedImages).toBe(0);
    expect(shown.html).toContain('src="https://cdn.example/a.png"');
    expect(shown.html).not.toMatch(/\ssrc="https:\/\/track/);
  });

  it("opens links in a new tab without leaking the referrer", () => {
    const { html } = sanitizeEmail(`<a href="https://shop.example">Shop</a>`);
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer nofollow"');
  });
});

describe("emailDocument", () => {
  it("adds a Content-Security-Policy that only allows remote images when asked", () => {
    expect(emailDocument("<p>x</p>")).toContain("img-src data: cid:;");
    expect(emailDocument("<p>x</p>", { allowImages: true })).toContain("img-src data: cid: https:;");
    expect(emailDocument("<p>x</p>")).toContain("default-src 'none'");
  });
});
