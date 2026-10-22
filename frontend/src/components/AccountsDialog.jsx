import { useEffect, useState } from "react";
import { PRESETS, presetForEmail } from "../lib/imapPresets.js";
import Dialog from "./Dialog.jsx";
import Icon from "./Icon.jsx";

const BRAND_LABEL = { gmail: "Gmail", outlook: "Outlook", imap: "IMAP" };

function ago(iso) {
  if (!iso) return "never";
  const minutes = Math.round((Date.now() - new Date(iso)) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  return `${Math.round(minutes / 60)} h ago`;
}

function ImapForm({ call, onConnected, notify }) {
  const [form, setForm] = useState({ email: "", password: "", display_name: "", preset: "", imap_host: "", smtp_host: "", smtp_port: 465 });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const set = (key, value) => setForm((f) => ({ ...f, [key]: value }));
  const applyPreset = (preset) =>
    setForm((f) => ({ ...f, preset: preset?.id || "custom", imap_host: preset?.imap || f.imap_host, smtp_host: preset?.smtp || f.smtp_host, smtp_port: preset?.smtpPort || f.smtp_port }));

  const onEmail = (email) => {
    set("email", email);
    const preset = presetForEmail(email);
    if (preset && (!form.preset || form.preset !== "custom")) applyPreset(preset);
  };

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const account = await call("/api/accounts/imap", {
        method: "POST",
        body: {
          email: form.email.trim(),
          password: form.password,
          display_name: form.display_name.trim(),
          imap_host: form.imap_host.trim(),
          smtp_host: form.smtp_host.trim(),
          smtp_port: Number(form.smtp_port),
        },
      });
      notify(`Connected ${account.email}. Your mail is syncing.`);
      onConnected();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="imap-form" onSubmit={submit}>
      <div className="form-grid">
        <label>
          Email address
          <input type="email" value={form.email} onChange={(e) => onEmail(e.target.value)} required autoComplete="email" />
        </label>
        <label>
          <span>
            Name in the sidebar <small className="muted">(optional)</small>
          </span>
          <input value={form.display_name} onChange={(e) => set("display_name", e.target.value)} placeholder="Personal, Work…" maxLength={80} />
        </label>
        <label className="span-2">
          App password
          <input type="password" value={form.password} onChange={(e) => set("password", e.target.value)} required autoComplete="new-password" />
          <small className="muted">Most providers need an app password (made in your account's security settings), not your normal password.</small>
        </label>
        <label>
          Provider
          <select value={form.preset} onChange={(e) => applyPreset(PRESETS.find((p) => p.id === e.target.value))}>
            <option value="">Choose…</option>
            {PRESETS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
            <option value="custom">Other (enter servers)</option>
          </select>
        </label>
        <label>
          Incoming server (IMAP, port 993)
          <input value={form.imap_host} onChange={(e) => set("imap_host", e.target.value)} required placeholder="imap.example.com" />
        </label>
        <label>
          Outgoing server (SMTP)
          <input value={form.smtp_host} onChange={(e) => set("smtp_host", e.target.value)} required placeholder="smtp.example.com" />
        </label>
        <label>
          SMTP port
          <select value={form.smtp_port} onChange={(e) => set("smtp_port", e.target.value)}>
            <option value={465}>465 (SSL)</option>
            <option value={587}>587 (STARTTLS)</option>
          </select>
        </label>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button className="btn primary" disabled={busy}>
        {busy ? "Checking the login…" : "Connect"}
      </button>
    </form>
  );
}

export default function AccountsDialog({ call, user, accounts, onClose, onChanged, notify }) {
  const [providers, setProviders] = useState({ gmail: false, outlook: false, imap: true });
  const [showImap, setShowImap] = useState(false);
  const [busy, setBusy] = useState("");

  useEffect(() => {
    call("/api/oauth/providers").then(setProviders).catch(() => {});
  }, [call]);

  const connectOAuth = async (provider) => {
    setBusy(provider);
    try {
      const { url } = await call(`/api/oauth/${provider}/start`, { method: "POST" });
      window.location.assign(url); // the provider sends the browser back to the app when done
    } catch (err) {
      notify(err.message);
      setBusy("");
    }
  };

  const remove = async (account) => {
    if (!window.confirm(`Remove ${account.email} from the hub? Mail stays in your real mailbox.`)) return;
    try {
      await call(`/api/accounts/${account.id}`, { method: "DELETE" });
      notify(`Removed ${account.email}`);
      onChanged();
    } catch (err) {
      notify(err.message);
    }
  };

  const reconnect = (account) => (account.provider === "imap" ? setShowImap(true) : connectOAuth(account.provider));
  const oauthHint = (name) => `This server isn't set up for ${name} sign-in yet. See docs/CONNECT_ACCOUNTS.md.`;

  return (
    <Dialog title="Accounts" onClose={onClose} wide>
      {accounts.length > 0 && (
        <ul className="account-list">
          {accounts.map((a) => (
            <li key={a.id}>
              <span className="dot" style={{ background: a.color }} aria-hidden="true" />
              <div className="account-info">
                <strong>{a.display_name || a.email}</strong>
                <span className="muted small">
                  {a.provider === "demo" ? "Sample mailbox" : BRAND_LABEL[a.brand]} · {a.email}
                </span>
                {a.needs_reauth ? (
                  <span className="status warn">
                    <Icon name="warn" size={14} /> Needs reconnecting: {a.sync_error}
                  </span>
                ) : a.sync_error ? (
                  <span className="status warn">Last sync failed: {a.sync_error} (retrying automatically)</span>
                ) : (
                  <span className="status muted small">Synced {ago(a.last_synced_at)}</span>
                )}
              </div>
              {a.needs_reauth && (
                <button className="btn small" onClick={() => reconnect(a)}>
                  Reconnect
                </button>
              )}
              <button className="btn ghost small" onClick={() => remove(a)}>
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}

      <h3 className="section-title">Add an account</h3>
      {user.is_guest ? (
        <p className="notice">
          You're using a demo account. <strong>Create a free account</strong> (sign out, then "Create an account") to connect your own mailboxes.
        </p>
      ) : (
        <>
          <div className="connect-options">
            <button className="btn" onClick={() => connectOAuth("gmail")} disabled={!providers.gmail || busy} title={providers.gmail ? "" : oauthHint("Google")}>
              <span className="dot" style={{ background: "#ea4335" }} /> {busy === "gmail" ? "Opening Google…" : "Sign in with Google"}
            </button>
            <button
              className="btn"
              onClick={() => connectOAuth("outlook")}
              disabled={!providers.outlook || busy}
              title={providers.outlook ? "" : oauthHint("Microsoft")}
            >
              <span className="dot" style={{ background: "#0078d4" }} /> {busy === "outlook" ? "Opening Microsoft…" : "Sign in with Microsoft"}
            </button>
            <button className={`btn ${showImap ? "active" : ""}`} onClick={() => setShowImap((v) => !v)} aria-expanded={showImap}>
              <span className="dot" style={{ background: "#7c3aed" }} /> Other (IMAP)
            </button>
          </div>
          {(!providers.gmail || !providers.outlook) && (
            <p className="muted small">Google and Microsoft sign-in appear here once the server has OAuth credentials. IMAP works with Yahoo, iCloud, Zoho and most others.</p>
          )}
          {showImap && (
            <ImapForm
              call={call}
              notify={notify}
              onConnected={() => {
                setShowImap(false);
                onChanged();
              }}
            />
          )}
        </>
      )}
    </Dialog>
  );
}
