import { useEffect, useState } from "react";
import { avatarColor, fullDate, initials, linkify, listDate } from "../lib/format.js";
import { AttachmentList } from "./Attachments.jsx";
import EmailFrame from "./EmailFrame.jsx";
import Icon from "./Icon.jsx";
import ReplyBox from "./ReplyBox.jsx";

function PlainBody({ text }) {
  return (
    <div className="plain-body">
      {linkify(text).map((part, i) =>
        typeof part === "string" ? (
          part
        ) : (
          <a key={i} href={part.url} target="_blank" rel="noopener noreferrer nofollow">
            {part.url}
          </a>
        ),
      )}
    </div>
  );
}

function MessageCard({ message, expanded, onToggle, token, onError }) {
  const name = message.is_sent ? "me" : message.from_name || message.from_email;
  return (
    <article className={`message ${expanded ? "expanded" : ""}`}>
      <header onClick={onToggle} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onToggle()} aria-expanded={expanded}>
        <span className="avatar" style={{ background: avatarColor(message.from_name || message.from_email) }} aria-hidden="true">
          {initials(message.from_name || message.from_email)}
        </span>
        <div className="message-meta">
          <div>
            <strong>{name}</strong> {!message.is_sent && <span className="muted">&lt;{message.from_email}&gt;</span>}
          </div>
          {expanded ? (
            <div className="muted small">
              to {message.to}
              {message.cc && `, cc ${message.cc}`}
            </div>
          ) : <div className="muted small one-line">{message.body_text.slice(0, 140)}</div>}
        </div>
        <time className="muted small" dateTime={message.sent_at} title={fullDate(message.sent_at)}>
          {expanded ? fullDate(message.sent_at) : listDate(message.sent_at)}
        </time>
      </header>
      {expanded && (message.body_html ? <EmailFrame html={message.body_html} /> : <PlainBody text={message.body_text} />)}
      {expanded && <AttachmentList attachments={message.attachments || []} token={token} onError={onError} />}
    </article>
  );
}

function SummaryCard({ state, aiProvider, onRefresh }) {
  if (state.loading) return <div className="summary-card muted">Summarizing…</div>;
  if (state.error) return <div className="summary-card error">{state.error}</div>;
  const s = state.data;
  return (
    <div className="summary-card">
      <div className="summary-head">
        <Icon name="sparkle" size={16} />
        <strong>Summary</strong>
        <button className="link small" onClick={onRefresh}>
          Refresh
        </button>
      </div>
      <p>{s.summary}</p>
      {s.action_items.length > 0 && (
        <ul className="action-items">
          {s.action_items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )}
      <p className="muted small">
        {s.notice ||
          (s.source === "gemini"
            ? "Written by Google Gemini. This conversation was sent to Google to make it."
            : aiProvider === "gemini"
              ? "Built-in summary."
              : "Built-in summary (no AI is configured on this server, so nothing left it).")}
      </p>
    </div>
  );
}

export default function ThreadView({ thread, account, loading, onBack, onUpdate, call, replying, onReplying, onReplied, aiProvider, hidden, token, onError }) {
  // The latest message and any unread ones start open; older read ones are folded, as in Gmail.
  const [open, setOpen] = useState(new Set());
  const [summary, setSummary] = useState(null);
  useEffect(() => {
    if (!thread) return;
    const msgs = thread.messages;
    setOpen(new Set(msgs.filter((m, i) => i === msgs.length - 1 || !m.is_read).map((m) => m.id)));
    setSummary(null);
  }, [thread?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const summarize = async (refresh = false) => {
    const id = thread.id;
    setSummary({ loading: true });
    try {
      const data = await call(`/api/threads/${id}/summary${refresh ? "?refresh=true" : ""}`, { method: "POST" });
      setSummary((current) => (current && thread.id === id ? { data } : current));
    } catch (err) {
      setSummary({ error: err.message });
    }
  };

  if (!thread) {
    return (
      <section className="reader empty-reader" hidden={hidden}>
        {loading ? <p className="muted">Loading…</p> : <p className="muted">Select a conversation to read it.</p>}
        <p className="muted small shortcuts">
          Shortcuts: <kbd>j</kbd>/<kbd>k</kbd> move · <kbd>r</kbd> reply · <kbd>c</kbd> compose · <kbd>e</kbd> archive · <kbd>s</kbd> star · <kbd>u</kbd> mark unread ·{" "}
          <kbd>/</kbd> search
        </p>
      </section>
    );
  }

  const toggle = (id) =>
    setOpen((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  return (
    <section className="reader" aria-label="Conversation" hidden={hidden}>
      <div className="reader-toolbar">
        <button className="icon-btn only-mobile" onClick={onBack} aria-label="Back to list">
          <Icon name="back" />
        </button>
        <button className="icon-btn" onClick={() => onReplying(true)} aria-label="Reply" title="Reply (r)" disabled={account?.needs_reauth}>
          <Icon name="reply" />
        </button>
        <button
          className="icon-btn"
          onClick={() => onUpdate(thread, { is_archived: !thread.is_archived })}
          aria-label={thread.is_archived ? "Move to inbox" : "Archive"}
          title={thread.is_archived ? "Move to inbox" : "Archive (e)"}
        >
          <Icon name={thread.is_archived ? "unarchive" : "archive"} />
        </button>
        <button className="icon-btn" onClick={() => onUpdate(thread, { is_read: false })} aria-label="Mark as unread" title="Mark as unread (u)">
          <Icon name="unread" />
        </button>
        <button
          className={`icon-btn star ${thread.is_starred ? "on" : ""}`}
          onClick={() => onUpdate(thread, { is_starred: !thread.is_starred })}
          aria-label={thread.is_starred ? "Unstar" : "Star"}
          title="Star (s)"
        >
          <Icon name="star" filled={thread.is_starred} />
        </button>
        <span className="toolbar-gap" />
        <button className="btn ghost small" onClick={() => summarize()} disabled={summary?.loading}>
          <Icon name="sparkle" size={16} /> Summarize
        </button>
      </div>

      <div className="reader-scroll">
        <h1 className="reader-subject">{thread.subject}</h1>
        {account && (
          <span className="account-chip" style={{ "--chip": account.color }}>
            {account.display_name} · {account.email}
          </span>
        )}
        {thread.suspicious_reasons.length > 0 && (
          <div className="phishing-banner" role="alert">
            <Icon name="warn" size={18} />
            <div>
              <strong>This looks like a phishing email.</strong> Don't click its links or reply with personal details.
              <ul>
                {thread.suspicious_reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </div>
          </div>
        )}
        {summary && <SummaryCard state={summary} aiProvider={aiProvider} onRefresh={() => summarize(true)} />}
        {thread.messages.map((m) => (
          <MessageCard key={m.id} message={m} expanded={open.has(m.id)} onToggle={() => toggle(m.id)} token={token} onError={onError} />
        ))}
        {replying ? (
          <ReplyBox call={call} thread={thread} account={account} aiProvider={aiProvider} onCancel={() => onReplying(false)} onSent={onReplied} onError={onError} />
        ) : (
          <button className="btn reply-button" onClick={() => onReplying(true)} disabled={account?.needs_reauth}>
            <Icon name="reply" size={16} /> Reply
          </button>
        )}
      </div>
    </section>
  );
}
