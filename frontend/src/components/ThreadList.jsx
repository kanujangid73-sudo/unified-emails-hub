import { useEffect, useRef } from "react";
import { avatarColor, initials, listDate } from "../lib/format.js";
import Icon from "./Icon.jsx";

export default function ThreadList({ threads, accountsById, selectedId, onOpen, onToggleStar, hasMore, loading, onLoadMore, emptyText }) {
  const sentinel = useRef(null);

  // Load the next page when the end of the list scrolls into view.
  useEffect(() => {
    if (!hasMore || !sentinel.current) return;
    const observer = new IntersectionObserver((entries) => entries[0].isIntersecting && onLoadMore(), { rootMargin: "300px" });
    observer.observe(sentinel.current);
    return () => observer.disconnect();
  }, [hasMore, onLoadMore, threads.length]);

  if (!loading && threads.length === 0) {
    return <p className="empty">{emptyText}</p>;
  }

  return (
    <ul className="thread-list" role="listbox" aria-label="Conversations">
      {threads.map((t) => {
        const account = accountsById[t.account_id];
        const unread = t.unread_count > 0;
        const lead = t.participants.split(", ")[0] || "";
        return (
          <li
            key={t.id}
            role="option"
            aria-selected={t.id === selectedId}
            className={`thread-row ${unread ? "unread" : ""} ${t.id === selectedId ? "selected" : ""}`}
            onClick={() => onOpen(t.id)}
            data-thread-id={t.id}
          >
            <span className="account-bar" style={{ background: account?.color }} title={account?.email} />
            <span className="avatar" style={{ background: avatarColor(lead) }} aria-hidden="true">
              {initials(lead)}
            </span>
            <div className="thread-main">
              <div className="thread-top">
                <span className="participants">
                  {t.participants}
                  {t.message_count > 1 && <span className="msg-count">{t.message_count}</span>}
                </span>
                <span className="row-meta">
                  {t.attachment_count > 0 && (
                    <span className="clip" title={`${t.attachment_count} attachment${t.attachment_count > 1 ? "s" : ""}`}>
                      <Icon name="attach" size={14} />
                    </span>
                  )}
                  <time dateTime={t.last_message_at}>{listDate(t.last_message_at)}</time>
                </span>
              </div>
              <div className="subject">
                {t.suspicious_reasons.length > 0 && (
                  <span className="badge danger" title={t.suspicious_reasons.join("\n")}>
                    Suspicious
                  </span>
                )}
                {t.subject}
              </div>
              <div className="snippet">{t.snippet}</div>
            </div>
            <button
              className={`star ${t.is_starred ? "on" : ""}`}
              onClick={(e) => {
                e.stopPropagation();
                onToggleStar(t);
              }}
              aria-label={t.is_starred ? "Unstar" : "Star"}
              aria-pressed={t.is_starred}
            >
              <Icon name="star" size={16} filled={t.is_starred} />
            </button>
          </li>
        );
      })}
      {hasMore && <li ref={sentinel} className="loading-row">Loading more…</li>}
      {loading && threads.length === 0 && <li className="loading-row">Loading…</li>}
    </ul>
  );
}
