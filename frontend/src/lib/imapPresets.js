// IMAP/SMTP settings of common providers, so most people only type their address and password.
// Outlook.com and Hotmail are missing on purpose: Microsoft turned off password sign-in for
// IMAP, so those accounts connect with "Sign in with Microsoft" instead.
// appPasswords: the provider's page for making an app password, linked from the form;
// twoStep: the page that turns on 2-step verification, which app passwords require.
export const PRESETS = [
  { id: "yahoo", label: "Yahoo Mail", domains: ["yahoo.com", "yahoo.co.in", "ymail.com"], imap: "imap.mail.yahoo.com", smtp: "smtp.mail.yahoo.com", smtpPort: 465, appPasswords: "https://login.yahoo.com/account/security/app-passwords" },
  { id: "icloud", label: "iCloud Mail", domains: ["icloud.com", "me.com", "mac.com"], imap: "imap.mail.me.com", smtp: "smtp.mail.me.com", smtpPort: 587, appPasswords: "https://account.apple.com/account/manage" },
  { id: "zoho", label: "Zoho Mail", domains: ["zoho.com", "zohomail.com", "zohomail.in"], imap: "imap.zoho.com", smtp: "smtp.zoho.com", smtpPort: 465 },
  { id: "fastmail", label: "Fastmail", domains: ["fastmail.com", "fastmail.fm"], imap: "imap.fastmail.com", smtp: "smtp.fastmail.com", smtpPort: 465 },
  { id: "aol", label: "AOL Mail", domains: ["aol.com"], imap: "imap.aol.com", smtp: "smtp.aol.com", smtpPort: 465 },
  { id: "gmail", label: "Gmail (app password)", domains: ["gmail.com", "googlemail.com"], imap: "imap.gmail.com", smtp: "smtp.gmail.com", smtpPort: 465, appPasswords: "https://myaccount.google.com/apppasswords", twoStep: "https://myaccount.google.com/signinoptions/two-step-verification" },
];

export function presetForEmail(email) {
  const domain = (email.split("@")[1] || "").trim().toLowerCase();
  return PRESETS.find((p) => p.domains.includes(domain)) || null;
}

// Links to the provider's 2-step verification and app password pages, or null when it has none.
// For Google, authuser opens them for the address being connected, even when the browser is
// signed in to another Google account first.
export function setupLinks(presetId, email) {
  const preset = PRESETS.find((p) => p.id === presetId);
  if (!preset?.appPasswords) return null;
  const address = email.trim();
  const forAddress = (url) => (url && preset.id === "gmail" && address.includes("@") ? `${url}?authuser=${encodeURIComponent(address)}` : url || null);
  return { twoStep: forAddress(preset.twoStep), appPassword: forAddress(preset.appPasswords) };
}
