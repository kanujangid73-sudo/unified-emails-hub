import { describe, expect, it } from "vitest";
import { presetForEmail, setupLinks } from "./imapPresets.js";

describe("presets", () => {
  it("finds the provider from the address", () => {
    expect(presetForEmail("me@Gmail.com").id).toBe("gmail");
    expect(presetForEmail("me@example.org")).toBeNull();
  });

  it("links the setup pages for the address being connected", () => {
    expect(setupLinks("gmail", " a.b+x@gmail.com ")).toEqual({
      twoStep: "https://myaccount.google.com/signinoptions/two-step-verification?authuser=a.b%2Bx%40gmail.com",
      appPassword: "https://myaccount.google.com/apppasswords?authuser=a.b%2Bx%40gmail.com",
    });
    expect(setupLinks("gmail", "").appPassword).toBe("https://myaccount.google.com/apppasswords");
    expect(setupLinks("yahoo", "me@yahoo.com")).toEqual({ twoStep: null, appPassword: "https://login.yahoo.com/account/security/app-passwords" });
    expect(setupLinks("zoho", "me@zoho.com")).toBeNull();
    expect(setupLinks("custom", "me@example.org")).toBeNull();
  });
});
