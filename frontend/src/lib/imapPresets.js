// IMAP/SMTP settings of common providers, so most people only type their address and password.
// Outlook.com and Hotmail are missing on purpose: Microsoft turned off password sign-in for
// IMAP, so those accounts connect with "Sign in with Microsoft" instead.
export const PRESETS = [
  { id: "yahoo", label: "Yahoo Mail", domains: ["yahoo.com", "yahoo.co.in", "ymail.com"], imap: "imap.mail.yahoo.com", smtp: "smtp.mail.yahoo.com", smtpPort: 465 },
  { id: "icloud", label: "iCloud Mail", domains: ["icloud.com", "me.com", "mac.com"], imap: "imap.mail.me.com", smtp: "smtp.mail.me.com", smtpPort: 587 },
  { id: "zoho", label: "Zoho Mail", domains: ["zoho.com", "zohomail.com", "zohomail.in"], imap: "imap.zoho.com", smtp: "smtp.zoho.com", smtpPort: 465 },
  { id: "fastmail", label: "Fastmail", domains: ["fastmail.com", "fastmail.fm"], imap: "imap.fastmail.com", smtp: "smtp.fastmail.com", smtpPort: 465 },
  { id: "aol", label: "AOL Mail", domains: ["aol.com"], imap: "imap.aol.com", smtp: "smtp.aol.com", smtpPort: 465 },
  { id: "gmail", label: "Gmail (app password)", domains: ["gmail.com", "googlemail.com"], imap: "imap.gmail.com", smtp: "smtp.gmail.com", smtpPort: 465 },
];

export function presetForEmail(email) {
  const domain = (email.split("@")[1] || "").trim().toLowerCase();
  return PRESETS.find((p) => p.domains.includes(domain)) || null;
}
