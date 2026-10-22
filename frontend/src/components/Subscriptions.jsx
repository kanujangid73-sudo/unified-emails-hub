import { useCallback, useEffect, useState } from "react";
import { listDate } from "../lib/format.js";
import Icon from "./Icon.jsx";

export default function Subscriptions({ call, notify, onShowSender, onChanged, onBack }) {
  const [subs, setSubs] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(() => call("/api/insights/subscriptions").then(setSubs, (err) => setError(err.message)), [call]);
  useEffect(() => {
    load();
  }, [load]);

  const archiveAll = async (sub) => {
    setBusy(sub.domain);
    try {
      const res = await call("/api/threads/bulk", { method: "POST", body: { thread_ids: sub.thread_ids, change: { is_archived: true, is_read: true } } });
      notify(`Archived ${res.updated.length} email${res.updated.length === 1 ? "" : "s"} from ${sub.name}${res.failed.length ? ` (${res.failed.length} failed)` : ""}`);
      onChanged();
      load();
    } catch (err) {
      notify(err.message);
    } finally {
      setBusy("");
    }
  };

  return (
    <section className="tool-pane" aria-label="Subscriptions">
      <header className="tool-head">
        <button className="icon-btn only-mobile" onClick={onBack} aria-label="Back">
          <Icon name="back" />
        </button>
        <div>
          <h1>Subscriptions</h1>
          <p className="muted">Newsletters and promotions, busiest first. Unsubscribe from what you don't read, and archive the backlog in one click.</p>
        </div>
      </header>
      {error && <p className="error">{error}</p>}
      {!subs && !error && <p className="muted">Loading…</p>}
      {subs?.length === 0 && <p className="empty">No newsletters or promotions found.</p>}
      {subs?.length > 0 && (
        <ul className="sub-list">
          {subs.map((s) => {
            const readRate = s.count ? Math.round(((s.count - s.unread) / s.count) * 100) : 0;
            return (
              <li key={s.domain} className="sub">
                <div className="sub-info">
                  <strong>{s.name}</strong>
                  <span className="muted small">
                    {s.domain} · {s.count} email{s.count === 1 ? "" : "s"} · last {s.last_seen ? listDate(s.last_seen) : "–"}
                  </span>
                  <div className="read-meter" title={`You opened ${readRate}% of them`}>
                    <span style={{ width: `${readRate}%` }} />
                  </div>
                  <span className="muted small">{readRate}% opened</span>
                </div>
                <div className="sub-actions">
                  <button className="btn ghost small" onClick={() => onShowSender(s.domain)}>
                    Show emails
                  </button>
                  {s.unsubscribe_url ? (
                    <a className="btn small" href={s.unsubscribe_url} target="_blank" rel="noopener noreferrer nofollow">
                      Unsubscribe ↗
                    </a>
                  ) : s.unsubscribe_mailto ? (
                    <a className="btn small" href={s.unsubscribe_mailto}>
                      Unsubscribe by email
                    </a>
                  ) : (
                    <span className="muted small">No unsubscribe link</span>
                  )}
                  <button className="btn small" onClick={() => archiveAll(s)} disabled={busy === s.domain}>
                    {busy === s.domain ? "Archiving…" : `Archive all ${s.count}`}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <p className="muted small">Unsubscribe links open the sender's own page. Only use them for senders you recognise; phishing emails are never listed here.</p>
    </section>
  );
}
