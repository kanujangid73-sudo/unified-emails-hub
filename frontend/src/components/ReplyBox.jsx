import { useEffect, useRef, useState } from "react";
import Icon from "./Icon.jsx";

// Who a reply goes to: the last person who wrote to you, or whoever you last wrote to.
export function replyRecipient(messages) {
  const received = [...messages].reverse().find((m) => !m.is_sent);
  if (received) return received.from_email;
  return (messages[messages.length - 1]?.to || "").split(",")[0].trim();
}

export default function ReplyBox({ call, thread, account, aiProvider, onSent, onCancel }) {
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [instruction, setInstruction] = useState("");
  const [drafting, setDrafting] = useState(false);
  const [draftNote, setDraftNote] = useState("");
  const box = useRef(null);
  const to = replyRecipient(thread.messages);

  useEffect(() => {
    box.current?.focus();
  }, []);

  const draft = async () => {
    if (body.trim() && !window.confirm("Replace what you've written with a new draft?")) return;
    setDrafting(true);
    setError("");
    try {
      const res = await call(`/api/threads/${thread.id}/draft`, { method: "POST", body: { instruction } });
      setBody(res.draft);
      setDraftNote(
        res.notice ||
          (res.source === "gemini" ? "Drafted by Google Gemini (the conversation was sent to Google). Check it before sending." : "A simple template: edit it before sending."),
      );
      box.current?.focus();
    } catch (err) {
      setError(err.message);
    } finally {
      setDrafting(false);
    }
  };

  const send = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await call("/api/messages", {
        method: "POST",
        body: { account_id: thread.account_id, to: [to], body, reply_to_thread_id: thread.id },
      });
      onSent();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  };

  return (
    <form className="reply-box" onSubmit={send}>
      <div className="muted small">
        Reply to <strong>{to}</strong> from {account?.email}
      </div>
      <div className="draft-row">
        <input
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              draft();
            }
          }}
          maxLength={300}
          placeholder={aiProvider === "gemini" ? 'Tell the AI what to say (optional), e.g. "yes, I\'ll be there"' : "Instruction (needs Gemini on the server)"}
          aria-label="What the draft should say"
          disabled={aiProvider !== "gemini"}
        />
        <button type="button" className="btn small" onClick={draft} disabled={drafting}>
          <Icon name="sparkle" size={14} /> {drafting ? "Drafting…" : "Draft reply"}
        </button>
      </div>
      <textarea
        ref={box}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        onKeyDown={(e) => {
          if ((e.ctrlKey || e.metaKey) && e.key === "Enter") e.currentTarget.form.requestSubmit();
          if (e.key === "Escape") onCancel();
        }}
        rows={5}
        required
        aria-label="Reply"
        placeholder="Write your reply…"
      />
      {draftNote && <p className="muted small">{draftNote}</p>}
      {account?.provider === "demo" && <p className="muted small">Demo mailbox: the reply is saved in the hub but never actually sent.</p>}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="compose-actions">
        <button className="btn primary" disabled={busy || !to}>
          {busy ? "Sending…" : "Send"}
        </button>
        <button type="button" className="btn ghost" onClick={onCancel}>
          Discard
        </button>
        <span className="muted small">Ctrl+Enter to send</span>
      </div>
    </form>
  );
}
