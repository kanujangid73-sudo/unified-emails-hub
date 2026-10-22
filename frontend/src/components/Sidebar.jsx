import { MailIcon } from "./AuthScreen.jsx";
import Icon from "./Icon.jsx";

export const FOLDERS = [
  ["inbox", "Inbox", "inbox"],
  ["unread", "Unread", "unread"],
  ["starred", "Starred", "star"],
  ["sent", "Sent", "sent"],
  ["archive", "Archive", "archive"],
  ["all", "All mail", "all"],
];

const BRAND_LABEL = { gmail: "Gmail", outlook: "Outlook", imap: "IMAP" };

export default function Sidebar({ accounts, view, onView, user, onLogout, open, onClose, syncing, lastSync, onSync, onCompose, onManage, tool, onTool }) {
  const totalUnread = accounts.reduce((sum, a) => sum + a.unread_count, 0);
  const pick = (next) => {
    onView({ ...view, ...next });
    onClose();
  };

  return (
    <aside className={`sidebar ${open ? "open" : ""}`} aria-label="Mailboxes">
      <div className="sidebar-head">
        <div className="brand-mark" aria-hidden="true">
          <MailIcon />
        </div>
        <span className="brand-name">Emails Hub</span>
        <button className="icon-btn only-mobile" onClick={onClose} aria-label="Close menu">
          <Icon name="close" />
        </button>
      </div>

      <div className="sidebar-actions">
        <button className="btn primary block" onClick={onCompose} disabled={accounts.length === 0}>
          <Icon name="compose" size={16} /> Compose
        </button>
      </div>

      <nav>
        <h2 className="nav-title">Folders</h2>
        {FOLDERS.map(([key, label, icon]) => (
          <button key={key} className={`nav-item ${!tool && view.folder === key ? "active" : ""}`} onClick={() => pick({ folder: key })}>
            <Icon name={icon} />
            <span>{label}</span>
            {key === "inbox" && totalUnread > 0 && <span className="count">{totalUnread}</span>}
          </button>
        ))}

        <h2 className="nav-title">Insights</h2>
        {[
          ["finder", "Account Finder", "finder"],
          ["subscriptions", "Subscriptions", "subs"],
        ].map(([key, label, icon]) => (
          <button
            key={key}
            className={`nav-item ${tool === key ? "active" : ""}`}
            onClick={() => {
              onTool(key);
              onClose();
            }}
          >
            <Icon name={icon} />
            <span>{label}</span>
          </button>
        ))}

        <h2 className="nav-title">Accounts</h2>
        <button className={`nav-item ${view.accountId === null ? "active" : ""}`} onClick={() => pick({ accountId: null })}>
          <span className="dot all" aria-hidden="true" />
          <span>All accounts</span>
        </button>
        {accounts.map((account) => (
          <button
            key={account.id}
            className={`nav-item account ${view.accountId === account.id ? "active" : ""}`}
            onClick={() => pick({ accountId: account.id })}
            title={account.needs_reauth ? `Reconnect needed: ${account.sync_error}` : account.sync_error ? `Sync problem: ${account.sync_error}` : account.email}
          >
            <span className="dot" style={{ background: account.color }} aria-hidden="true" />
            <span className="account-text">
              <span>{account.display_name || account.email}</span>
              <small>
                {BRAND_LABEL[account.brand] || account.brand} · {account.email}
              </small>
            </span>
            {account.needs_reauth || account.sync_error ? (
              <span className="count warn" aria-label="Sync problem">
                <Icon name="warn" size={14} />
              </span>
            ) : (
              account.unread_count > 0 && <span className="count">{account.unread_count}</span>
            )}
          </button>
        ))}
        <button
          className="nav-item"
          onClick={() => {
            onManage();
            onClose();
          }}
        >
          <Icon name="plus" />
          <span>Add or manage accounts</span>
        </button>
      </nav>

      <div className="sidebar-foot">
        <button className="btn ghost small block" onClick={onSync} disabled={syncing}>
          <span className={syncing ? "spin" : ""}>
            <Icon name="sync" size={16} />
          </span>
          {syncing ? "Syncing…" : lastSync ? `Synced ${lastSync}` : "Sync now"}
        </button>
        <div className="user-row">
          <span className="user-name">
            {user.username}
            {user.is_guest && <small>Demo account</small>}
          </span>
          <button className="icon-btn" onClick={onLogout} aria-label="Sign out" title="Sign out">
            <Icon name="logout" />
          </button>
        </div>
      </div>
    </aside>
  );
}
