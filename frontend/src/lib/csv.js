// Spreadsheet-safe CSV: quotes every cell, and neutralises cells that a spreadsheet would run
// as a formula (=, +, -, @), since service names come from emails anyone can send.
export function toCsv(rows) {
  return rows
    .map((row) =>
      row
        .map((cell) => {
          let text = String(cell ?? "");
          if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
          return `"${text.replace(/"/g, '""')}"`;
        })
        .join(","),
    )
    .join("\r\n");
}

export function downloadCsv(filename, rows) {
  const blob = new Blob(["﻿" + toCsv(rows)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
