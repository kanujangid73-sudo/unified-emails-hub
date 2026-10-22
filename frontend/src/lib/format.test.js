import { describe, expect, it } from "vitest";
import { avatarColor, initials, linkify, listDate } from "./format.js";

describe("listDate", () => {
  const now = new Date(2026, 9, 22, 18, 0);

  it("shows the time for today, month and day this year, and the year otherwise", () => {
    expect(listDate(new Date(2026, 9, 22, 9, 30).toISOString(), now)).toMatch(/9:30/);
    expect(listDate(new Date(2026, 2, 3).toISOString(), now)).toMatch(/3/);
    expect(listDate(new Date(2026, 2, 3).toISOString(), now)).not.toMatch(/2026/);
    expect(listDate(new Date(2024, 2, 3).toISOString(), now)).toMatch(/2024/);
  });
});

describe("initials", () => {
  it("uses the first and last word", () => {
    expect(initials("Priya Sharma")).toBe("PS");
    expect(initials("Mom")).toBe("M");
    expect(initials("Northwind CI")).toBe("NC");
    expect(initials("")).toBe("?");
  });
});

describe("avatarColor", () => {
  it("is stable for the same name", () => {
    expect(avatarColor("Sam Lee")).toBe(avatarColor("Sam Lee"));
    expect(avatarColor("Sam Lee")).not.toBe(avatarColor("Rohan Mehta"));
  });
});

describe("linkify", () => {
  it("splits text around URLs", () => {
    expect(linkify("See https://a.example/x, then reply.")).toEqual(["See ", { url: "https://a.example/x," }, " then reply."]);
    expect(linkify("no links")).toEqual(["no links"]);
  });
});
