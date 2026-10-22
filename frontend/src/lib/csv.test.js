import { describe, expect, it } from "vitest";
import { toCsv } from "./csv.js";

describe("toCsv", () => {
  it("quotes cells and escapes quotes", () => {
    expect(toCsv([["a", 'say "hi"'], [1, null]])).toBe('"a","say ""hi"""\r\n"1",""');
  });

  it("stops spreadsheet formulas from running", () => {
    expect(toCsv([["=HYPERLINK(\"x\")", "+1", "-2", "@cmd", "safe"]])).toBe(`"'=HYPERLINK(""x"")","'+1","'-2","'@cmd","safe"`);
  });
});
