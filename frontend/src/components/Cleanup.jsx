import { useCallback, useEffect, useMemo, useState } from "react";
import { formatSize } from "../lib/files.js";
import { listDate } from "../lib/format.js";
import Icon from "./Icon.jsx";

const AGES = [
  ["", "All of it"],
  ["30", "Older than a month"],
  ["90", "Older than 3 months"],
  ["365", "Older than a year"],
];

const keyOf = (s) => `${s.account_id}:${s.email}`;

export default function Cleanup({ call, accounts, notify, onShowSender, onChanged, onBack }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [unopenedOnly, setUnopenedOnly] = useState(false);
  const [age, setAge] = useState("");
  const [chosen, setChosen] = useState(() => new Set());
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => call("/api/cleanup").then(setData, (err) => setError(err.message)), [call]);
  useEffect(() => {
    load();
  }, [load]);

  const accountById = useMemo(() => Object.fromEntries(accounts.map((a) => [a.id, a])), [accounts]);
  const senders = useMemo(() => (data?.senders || []).filter((s) => !unopenedOnly || s.read === 0), [data, unopenedOnly]);
  const picked = senders.filter((s) => chosen.has(keyOf(s)));
  const pickedCount = picked.reduce((n, s) => n + s.count - s.starred, 0);
  const pickedSize = picked.reduce((n, s) => n + s.size, 0);

  const toggle = (s) =>
    setChosen((prev) => {
      const next = new Set(prev);
      next.has(keyOf(s)) ? next.delete(keyOf(s)) : next.add(keyOf(s));
      return next;
    });
  const allPicked = senders.length > 0 && picked.length === senders.length;
  const toggleAll = () => setChosen(allPicked ? new Set() : new Set(senders.map(keyOf)));

  const trash = async () => {
    const when = age ? ` ${AGES.find(([v]) => v === age)[1].toLowerCase()}` : "";
    const question =
      `Move ${age ? "up to " : ""}${pickedCount} email${pickedCount === 1 ? "" : "s"}${when} from ${picked.length} sender${picked.length === 1 ? "" : "s"} ` +
      `to the Trash of your real mailbox?\n\nStarred emails are kept. Gmail and Outlook empty the Trash after 30 days; until then you can restore them there.`;
    if (!window.confirm(question)) return;
    setBusy(true);
    try {
      const res = await call("/api/cleanup/trash", {
        method: "POST",
        body: { senders: picked.map((s) => ({ account_id: s.account_id, email: s.email })), older_than_days: age ? Number(age) : null },
      });
      notify(`Moved ${res.trashed} email${res.trashed === 1 ? "" : "s"} to Trash${res.failed.length ? `. Couldn't reach ${res.failed.join(", ")}` : ""}`);
      setChosen(new Set());
      onChanged();
      load();
    } catch (err) {
      notify(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="tool-pane" aria-label="Clean up">
      <header className="tool-head">
        <button className="icon-btn only-mobile" onClick={onBack} aria-label="Back">
          <Icon name="back" />
        </button>
        <div>
          <h1>Clean up</h1>
          <p className="muted">
            Who fills your mailbox, biggest first, and how much of it you ever opened. Pick senders to move their mail to the Trash.
            {data && ` ${data.total_count} emails, about ${formatSize(data.total_size)} in total.`}
          </p>
        </div>
      </header>

      <p className="notice small">
        Mailbox full? Gmail's 15 GB is shared with Google Drive and Google Photos, and text emails are small. Check{" "}
        <a href="https://one.google.com/storage" target="_blank" rel="noopener noreferrer">
          what uses your storage ↗
        </a>{" "}
        first; emails only free space once they leave the Trash.
      </p>

      <div className="cleanup-filters">
        <label className="check">
          <input type="checkbox" checked={unopenedOnly} onChange={(e) => setUnopenedOnly(e.target.checked)} /> Only senders I never open
        </label>
        <label>
          Delete{" "}
          <select value={age} onChange={(e) => setAge(e.target.value)}>
            {AGES.map(([value, label]) => (
              <option key={value} value={value}>
                {label.toLowerCase()}
              </option>
            ))}
          </select>
        </label>
        {senders.length > 0 && (
          <label className="check">
            <input type="checkbox" checked={allPicked} onChange={toggleAll} /> Select all {senders.length}
          </label>
        )}
      </div>

      {error && <p className="error">{error}</p>}
      {!data && !error && <p className="muted">Loading…</p>}
      {data && senders.length === 0 && <p className="empty">{unopenedOnly ? "You've opened something from every sender." : "No mail yet."}</p>}
      {senders.length > 0 && (
        <ul className="sub-list">
          {senders.map((s) => {
            const account = accountById[s.account_id];
            const readRate = Math.round((s.read / s.count) * 100);
            return (
              <li key={keyOf(s)} className={`sub cleanup-row ${chosen.has(keyOf(s)) ? "picked" : ""}`}>
                <input type="checkbox" checked={chosen.has(keyOf(s))} onChange={() => toggle(s)} aria-label={`Select ${s.name || s.email}`} />
                <div className="sub-info">
                  <strong>{s.name || s.email}</strong>
                  <span className="muted small">
                    {account && <span className="dot" style={{ background: account.color }} title={account.email} aria-hidden="true" />} {s.email}
                  </span>
                  <span className="muted small">
                    {s.count} email{s.count === 1 ? "" : "s"} · <strong>{formatSize(s.size)}</strong> · {readRate}% opened · {listDate(s.first_seen)} – {listDate(s.last_seen)}
                    {s.starred > 0 && ` · ${s.starred} starred (kept)`}
                  </span>
                </div>
                <button className="btn ghost small" onClick={() => onShowSender(s.email)}>
                  Show emails
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {picked.length > 0 && (
        <div className="cleanup-bar">
          <span>
            {picked.length} sender{picked.length === 1 ? "" : "s"} · {pickedCount} emails · {formatSize(pickedSize)}
          </span>
          <button className="btn danger" onClick={trash} disabled={busy || pickedCount === 0}>
            {busy ? "Moving to Trash…" : "Move to Trash"}
          </button>
        </div>
      )}
    </section>
  );
}
