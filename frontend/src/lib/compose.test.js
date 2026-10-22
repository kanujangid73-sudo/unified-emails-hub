import { describe, expect, it } from "vitest";
import { parseRecipients } from "../components/ComposeDialog.jsx";
import { replyRecipient } from "../components/ReplyBox.jsx";
import { presetForEmail } from "./imapPresets.js";

describe("parseRecipients", () => {
  it("accepts commas, semicolons, new lines and display names", () => {
    expect(parseRecipients("a@x.com, Bob <b@y.com>; c@z.com\n")).toEqual(["a@x.com", "b@y.com", "c@z.com"]);
    expect(parseRecipients("  ")).toEqual([]);
  });
});

describe("replyRecipient", () => {
  it("answers the last person who wrote to you", () => {
    const messages = [
      { is_sent: false, from_email: "priya@example.net", to: "me@example.com" },
      { is_sent: true, from_email: "me@example.com", to: "priya@example.net" },
    ];
    expect(replyRecipient(messages)).toBe("priya@example.net");
  });

  it("follows up with whoever you wrote to when nobody has answered", () => {
    expect(replyRecipient([{ is_sent: true, from_email: "me@example.com", to: "sam@example.org, x@example.org" }])).toBe("sam@example.org");
  });
});

describe("presetForEmail", () => {
  it("recognises common providers by domain", () => {
    expect(presetForEmail("someone@yahoo.co.in").imap).toBe("imap.mail.yahoo.com");
    expect(presetForEmail("me@icloud.com").smtpPort).toBe(587);
    expect(presetForEmail("me@company.example")).toBeNull();
  });
});
