import { describe, expect, it } from "vitest";
import { fileKind, formatSize } from "./files.js";

describe("formatSize", () => {
  it("uses friendly units", () => {
    expect(formatSize(512)).toBe("512 B");
    expect(formatSize(2048)).toBe("2 KB");
    expect(formatSize(5 * 1024 * 1024)).toBe("5.0 MB");
  });
});

describe("fileKind", () => {
  it("groups common types", () => {
    expect(fileKind("image/png")).toBe("image");
    expect(fileKind("application/octet-stream", "Invoice.PDF")).toBe("pdf");
    expect(fileKind("application/vnd.ms-excel")).toBe("sheet");
    expect(fileKind("application/zip")).toBe("archive");
    expect(fileKind("text/plain")).toBe("file");
  });
});
