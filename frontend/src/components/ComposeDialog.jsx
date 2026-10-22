import { useState } from "react";
import { FilePicker, forUpload } from "./Attachments.jsx";
import Dialog from "./Dialog.jsx";

// "a@x.com, B <b@y.com>; c@z.com" -> ["a@x.com", "b@y.com", "c@z.com"]
export function parseRecipients(text) {
  return text
    .split(/[,;\n]/)
    .map((part) => {
      const angle = part.match(/<([^>]+)>/);
      return (angle ? angle[1] : part).trim();
    })
    .filter(Boolean);
}

export default function ComposeDialog({ call, accounts, defaultAccountId, onClose, onSent }) {
  const [files, setFiles] = useState([]);
  const usable = accounts.filter((a) => !a.needs_reauth);
  const [accountId, setAccountId] = useState(defaultAccountId && usable.some((a) => a.id === defaultAccountId) ? defaultAccountId : usable[0]?.id);
  const [to, setTo] = useState("");
  const [cc, setCc] = useState("");
  const [showCc, setShowCc] = useState(false);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const account = usable.find((a) => a.id === accountId);

  const send = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const thread = await call("/api/messages", {
        method: "POST",
        body: { account_id: accountId, to: parseRecipients(to), cc: parseRecipients(cc), subject, body, attachments: forUpload(files) },
      });
      onSent(thread);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  if (usable.length === 0) {
    return (
      <Dialog title="New message" onClose={onClose}>
        <p className="muted">Connect an account first.</p>
      </Dialog>
    );
  }

  return (
    <Dialog title="New message" onClose={onClose} wide>
      <form className="compose" onSubmit={send}>
        <label className="row">
          <span>From</span>
          <select value={accountId} onChange={(e) => setAccountId(Number(e.target.value))}>
            {usable.map((a) => (
              <option key={a.id} value={a.id}>
                {a.display_name ? `${a.display_name} <${a.email}>` : a.email}
              </option>
            ))}
          </select>
        </label>
        <label className="row">
          <span>To</span>
          <input value={to} onChange={(e) => setTo(e.target.value)} required placeholder="name@example.com, …" autoComplete="off" />
          {!showCc && (
            <button type="button" className="link" onClick={() => setShowCc(true)}>
              Cc
            </button>
          )}
        </label>
        {showCc && (
          <label className="row">
            <span>Cc</span>
            <input value={cc} onChange={(e) => setCc(e.target.value)} autoComplete="off" />
          </label>
        )}
        <label className="row">
          <span>Subject</span>
          <input value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={500} />
        </label>
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          onKeyDown={(e) => (e.ctrlKey || e.metaKey) && e.key === "Enter" && e.currentTarget.form.requestSubmit()}
          rows={12}
          required
          aria-label="Message"
          placeholder="Write your message…"
        />
        <FilePicker files={files} onChange={setFiles} onError={setError} />
        {account?.provider === "demo" && <p className="muted small">Demo mailbox: the message is saved in the hub but never actually sent.</p>}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="compose-actions">
          <button className="btn primary" disabled={busy}>
            {busy ? "Sending…" : "Send"}
          </button>
          <span className="muted small">Ctrl+Enter to send</span>
        </div>
      </form>
    </Dialog>
  );
}
