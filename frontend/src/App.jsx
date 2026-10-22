import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import AccountFinder from "./components/AccountFinder.jsx";
import AccountsDialog from "./components/AccountsDialog.jsx";
import AuthScreen from "./components/AuthScreen.jsx";
import ComposeDialog from "./components/ComposeDialog.jsx";
import Icon from "./components/Icon.jsx";
import Sidebar, { FOLDERS } from "./components/Sidebar.jsx";
import Subscriptions from "./components/Subscriptions.jsx";
import ThreadList from "./components/ThreadList.jsx";
import ThreadView from "./components/ThreadView.jsx";
import { useAuth } from "./hooks/useAuth.js";
import { api } from "./lib/api.js";

const SYNC_EVERY_MS = 60_000;

const TABS = [
  [null, "All"],
  ["primary", "Primary"],
  ["updates", "Updates"],
  ["promotions", "Promotions"],
  ["newsletters", "Newsletters"],
];

const SEARCH_TIPS = [
  ["from:priya", "sent by someone"],
  ["to:northwind", "sent to an address"],
  ["is:unread  is:read  is:starred", "by status"],
  ["after:2026-09-01  before:2026-10-01", "by date"],
  ['"exact words"', "words together"],
];

// The app is opened at /?connected=... or /?connect_error=... after signing in with Google or
// Microsoft. Read the result once, then clean the address bar.
function takeConnectResult() {
  const params = new URLSearchParams(window.location.search);
  const result = { connected: params.get("connected"), error: params.get("connect_error") };
  if (result.connected || result.error) window.history.replaceState(null, "", window.location.pathname);
  return result;
}

function since(date) {
  if (!date) return "";
  const seconds = Math.round((Date.now() - date) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  return minutes < 60 ? `${minutes} min ago` : `${Math.round(minutes / 60)} h ago`;
}

// Does a thread still belong in the current folder after a change?
function fitsFolder(thread, folder) {
  if (folder === "inbox") return !thread.is_archived;
  if (folder === "unread") return !thread.is_archived && thread.unread_count > 0;
  if (folder === "starred") return thread.is_starred;
  if (folder === "archive") return thread.is_archived;
  return true; // "sent" and "all"
}

function Mailbox({ token, user, onLogout }) {
  const [accounts, setAccounts] = useState([]);
  const [accountsLoaded, setAccountsLoaded] = useState(false);
  const [view, setView] = useState({ folder: "inbox", accountId: null, category: null });
  const [tool, setTool] = useState(null); // "finder" | "subscriptions" | null
  const [aiProvider, setAiProvider] = useState("offline");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [threads, setThreads] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [lastSync, setLastSync] = useState(null);
  const [toast, setToast] = useState("");
  const [dialog, setDialog] = useState(null); // "accounts" | "compose" | null
  const [replying, setReplying] = useState(false);
  const [showTips, setShowTips] = useState(false);
  const [, tick] = useState(0);
  const searchBox = useRef(null);
  const listRequest = useRef(0);
  const toastTimer = useRef(0);
  // The open thread stays in the list until the view changes, even if it no longer fits the
  // folder (e.g. opening it in Unread marks it read). A ref keeps async callbacks current.
  const selectedRef = useRef(null);
  selectedRef.current = selectedId;

  const call = useCallback((path, opts = {}) => api(path, { token, ...opts }), [token]);
  const notify = useCallback((message) => {
    setToast(message);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(""), 3500);
  }, []);

  const accountsById = useMemo(() => Object.fromEntries(accounts.map((a) => [a.id, a])), [accounts]);

  const loadAccounts = useCallback(async () => {
    setAccounts(await call("/api/accounts"));
    setAccountsLoaded(true);
  }, [call]);

  const listPath = useCallback(
    (after) => {
      const params = new URLSearchParams({ folder: view.folder });
      if (view.accountId !== null) params.set("account_id", view.accountId);
      if (view.category) params.set("category", view.category);
      if (query) params.set("q", query);
      if (after) params.set("cursor", after);
      return `/api/threads?${params}`;
    },
    [view, query],
  );

  // First page of the current folder/account/search. Older responses are ignored if the
  // user has already moved on to another view.
  const loadThreads = useCallback(async () => {
    const request = ++listRequest.current;
    setLoading(true);
    try {
      const page = await call(listPath());
      if (request !== listRequest.current) return;
      setThreads(page.threads);
      setCursor(page.next_cursor);
    } catch (err) {
      if (request === listRequest.current) notify(err.message);
    } finally {
      if (request === listRequest.current) setLoading(false);
    }
  }, [call, listPath, notify]);

  const loadMore = useCallback(async () => {
    if (!cursor || loading) return;
    const request = listRequest.current;
    setLoading(true);
    try {
      const page = await call(listPath(cursor));
      if (request !== listRequest.current) return;
      setThreads((prev) => [...prev, ...page.threads.filter((t) => !prev.some((p) => p.id === t.id))]);
      setCursor(page.next_cursor);
    } finally {
      if (request === listRequest.current) setLoading(false);
    }
  }, [call, cursor, listPath, loading]);

  const sync = useCallback(
    async ({ quiet = false } = {}) => {
      setSyncing(true);
      try {
        const results = await call("/api/sync", { method: "POST" });
        const fresh = results.reduce((n, r) => n + r.new_messages, 0);
        const failed = results.filter((r) => r.error);
        setLastSync(Date.now());
        if (fresh > 0) {
          await Promise.all([loadAccounts(), loadThreads()]);
          notify(`${fresh} new message${fresh > 1 ? "s" : ""}`);
        } else if (failed.length) {
          await loadAccounts();
          notify(`Couldn't sync ${failed.length} account${failed.length > 1 ? "s" : ""}`);
        } else if (!quiet) {
          notify("You're up to date");
        }
      } catch (err) {
        if (!quiet) notify(err.message);
      } finally {
        setSyncing(false);
      }
    },
    [call, loadAccounts, loadThreads, notify],
  );

  useEffect(() => {
    loadAccounts().catch((err) => notify(err.message));
  }, [loadAccounts, notify]);

  useEffect(() => {
    call("/api/insights/ai")
      .then((status) => setAiProvider(status.provider))
      .catch(() => {});
  }, [call]);

  useEffect(() => {
    const { connected, error } = takeConnectResult();
    if (connected) notify(`Connected ${connected}. Your mail is syncing…`);
    if (error) {
      notify(`Couldn't connect: ${error}`);
      setDialog("accounts");
    }
  }, [notify]);

  // A freshly connected account fills up during its first sync: refresh while that runs.
  const syncingFirstTime = accounts.some((a) => !a.last_synced_at && !a.needs_reauth);
  useEffect(() => {
    if (!syncingFirstTime) return;
    const timer = window.setTimeout(() => Promise.all([loadAccounts(), loadThreads()]).catch(() => {}), 4000);
    return () => window.clearTimeout(timer);
  }, [syncingFirstTime, accounts, loadAccounts, loadThreads]);

  useEffect(() => {
    loadThreads();
  }, [loadThreads]);

  // Background sync while the app is open, plus a clock tick for "synced 2 min ago".
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") sync({ quiet: true });
      tick((n) => n + 1);
    }, SYNC_EVERY_MS);
    return () => window.clearInterval(timer);
  }, [sync]);

  // Debounce the search box.
  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  const applyLocal = useCallback(
    (updated) => {
      setThreads((prev) => prev.map((t) => (t.id === updated.id ? { ...t, ...updated } : t)).filter((t) => t.id === selectedRef.current || fitsFolder(t, view.folder)));
      setDetail((d) => (d && d.id === updated.id ? { ...d, ...updated } : d));
    },
    [view.folder],
  );

  // Optimistic update: the change shows at once and is rolled back if the server refuses it.
  const updateThread = useCallback(
    async (thread, change) => {
      const before = threads.find((t) => t.id === thread.id) || thread;
      const guess = { ...before, ...change };
      if ("is_read" in change) guess.unread_count = change.is_read ? 0 : before.message_count;
      applyLocal(guess);
      const isOpen = thread.id === selectedRef.current;
      if (change.is_archived !== undefined && isOpen && view.folder !== "all") {
        setSelectedId(null);
        setDetail(null);
        setThreads((prev) => prev.filter((t) => t.id !== thread.id));
        notify(change.is_archived ? "Archived" : "Moved to inbox");
      }
      if (change.is_read === false && isOpen) {
        setSelectedId(null);
        setDetail(null);
      }
      try {
        const saved = await call(`/api/threads/${thread.id}`, { method: "PATCH", body: change });
        applyLocal(saved);
        if ("is_read" in change || "is_archived" in change) loadAccounts();
      } catch (err) {
        applyLocal(before);
        notify(err.message);
      }
    },
    [threads, applyLocal, view.folder, call, loadAccounts, notify],
  );

  const openThread = useCallback(
    async (id) => {
      setSelectedId(id);
      setReplying(false);
      setDetailLoading(true);
      setDetail(null);
      try {
        const data = await call(`/api/threads/${id}`);
        setDetail(data);
        if (data.unread_count > 0) updateThread(data, { is_read: true });
      } catch (err) {
        notify(err.message);
      } finally {
        setDetailLoading(false);
      }
    },
    [call, updateThread, notify],
  );

  const changeView = useCallback((next) => {
    setView(next);
    setTool(null);
    setSelectedId(null);
    setDetail(null);
  }, []);

  // From the Account Finder: leave the tool and open the email that proves the account.
  const openFromTool = useCallback(
    (threadId) => {
      setTool(null);
      setView((v) => ({ ...v, folder: "all", category: null }));
      openThread(threadId);
    },
    [openThread],
  );

  const showSender = useCallback((domain) => {
    setTool(null);
    setView((v) => ({ ...v, folder: "all", category: null }));
    setSearch(`from:${domain}`);
    setSelectedId(null);
    setDetail(null);
  }, []);

  // Keyboard shortcuts, as in Gmail.
  useEffect(() => {
    const onKey = (e) => {
      if (dialog) return;
      if (e.target.closest("input, textarea, select") || e.metaKey || e.ctrlKey || e.altKey) {
        if (e.key === "Escape") e.target.blur();
        return;
      }
      const index = threads.findIndex((t) => t.id === selectedId);
      const current = threads[index];
      if (e.key === "j" || e.key === "k") {
        const next = threads[e.key === "j" ? index + 1 : Math.max(index - 1, 0)];
        if (next) {
          openThread(next.id);
          document.querySelector(`[data-thread-id="${next.id}"]`)?.scrollIntoView({ block: "nearest" });
        }
      } else if (e.key === "/") {
        e.preventDefault();
        searchBox.current?.focus();
      } else if (e.key === "c" && accounts.length) {
        e.preventDefault();
        setDialog("compose");
      } else if (e.key === "r" && detail) {
        e.preventDefault();
        setReplying(true);
      } else if (current && e.key === "e") {
        updateThread(current, { is_archived: !current.is_archived });
      } else if (current && e.key === "s") {
        updateThread(current, { is_starred: !current.is_starred });
      } else if (current && e.key === "u") {
        updateThread(current, { is_read: false });
      } else if (e.key === "Escape") {
        setSelectedId(null);
        setDetail(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [threads, selectedId, openThread, updateThread, dialog, accounts.length, detail]);

  const refreshAll = useCallback(() => Promise.all([loadAccounts(), loadThreads()]).catch((err) => notify(err.message)), [loadAccounts, loadThreads, notify]);

  const onReplied = useCallback(async () => {
    setReplying(false);
    notify(accountsById[detail?.account_id]?.provider === "demo" ? "Reply saved (demo mailboxes never really send)" : "Reply sent");
    if (detail) await openThread(detail.id);
    refreshAll();
  }, [accountsById, detail, notify, openThread, refreshAll]);

  const onComposed = useCallback(
    (thread) => {
      setDialog(null);
      notify("Message sent");
      refreshAll();
      if (thread) openThread(thread.id);
    },
    [notify, openThread, refreshAll],
  );

  const addSamples = async () => {
    try {
      setAccounts(await call("/api/accounts/demo", { method: "POST" }));
      await loadThreads();
    } catch (err) {
      notify(err.message);
    }
  };

  const folderLabel = FOLDERS.find(([key]) => key === view.folder)[1];
  const scopeLabel = view.accountId === null ? "All accounts" : accountsById[view.accountId]?.display_name || "";
  const emptyText = query ? `No conversations match "${query}".` : view.folder === "inbox" ? "Inbox zero. Nice work! 🎉" : `Nothing in ${folderLabel.toLowerCase()}.`;

  return (
    <div className={`app ${selectedId ? "reading" : ""}`}>
      <Sidebar
        accounts={accounts}
        view={view}
        onView={changeView}
        user={user}
        onLogout={onLogout}
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        syncing={syncing}
        lastSync={since(lastSync)}
        onSync={() => sync()}
        onCompose={() => setDialog("compose")}
        onManage={() => setDialog("accounts")}
        tool={tool}
        onTool={(next) => {
          setTool(next);
          setSelectedId(null);
          setDetail(null);
        }}
      />
      {menuOpen && <div className="scrim" onClick={() => setMenuOpen(false)} />}

      {tool === "finder" && <AccountFinder call={call} accounts={accounts} onOpenThread={openFromTool} onBack={() => setTool(null)} />}
      {tool === "subscriptions" && (
        <Subscriptions call={call} notify={notify} onShowSender={showSender} onChanged={refreshAll} onBack={() => setTool(null)} />
      )}

      <section className="list-pane" hidden={Boolean(tool)}>
        <header className="list-header">
          <button className="icon-btn only-mobile" onClick={() => setMenuOpen(true)} aria-label="Open menu">
            <Icon name="menu" />
          </button>
          <label className="search">
            <Icon name="search" size={16} />
            <input
              ref={searchBox}
              type="search"
              placeholder="Search all mail"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onFocus={() => setShowTips(true)}
              onBlur={() => setShowTips(false)}
              aria-label="Search all mail"
            />
          </label>
          {showTips && !search && (
            <div className="search-tips" role="note">
              <strong>Search tips</strong>
              {SEARCH_TIPS.map(([example, meaning]) => (
                <div key={example}>
                  <code>{example}</code> <span className="muted">{meaning}</span>
                </div>
              ))}
            </div>
          )}
        </header>
        <div className="list-title">
          <h1>{folderLabel}</h1>
          <span className="muted small">{scopeLabel}</span>
        </div>
        {view.folder === "inbox" && (
          <div className="tabs" role="tablist" aria-label="Categories">
            {TABS.map(([key, label]) => (
              <button
                key={label}
                role="tab"
                aria-selected={view.category === key}
                className={`tab ${view.category === key ? "active" : ""}`}
                onClick={() => changeView({ ...view, category: key })}
              >
                {label}
              </button>
            ))}
          </div>
        )}

        {accountsLoaded && accounts.length === 0 ? (
          <div className="connect">
            <h2>Connect your email accounts</h2>
            <p className="muted">Bring in Gmail, Outlook, Yahoo, iCloud or any IMAP mailbox. Or explore first with three sample mailboxes.</p>
            <div className="connect-options">
              <button className="btn primary" onClick={() => setDialog("accounts")}>
                <Icon name="plus" size={16} /> Connect an account
              </button>
              <button className="btn" onClick={addSamples}>
                Add sample mailboxes
              </button>
            </div>
          </div>
        ) : (
          <ThreadList
            threads={threads}
            accountsById={accountsById}
            selectedId={selectedId}
            onOpen={openThread}
            onToggleStar={(t) => updateThread(t, { is_starred: !t.is_starred })}
            hasMore={Boolean(cursor)}
            loading={loading}
            onLoadMore={loadMore}
            emptyText={emptyText}
          />
        )}
      </section>

      <ThreadView
        hidden={Boolean(tool)}
        aiProvider={aiProvider}
        thread={detail}
        account={detail ? accountsById[detail.account_id] : null}
        loading={detailLoading}
        onBack={() => {
          setSelectedId(null);
          setDetail(null);
        }}
        onUpdate={updateThread}
        call={call}
        replying={replying}
        onReplying={setReplying}
        onReplied={onReplied}
      />

      {dialog === "accounts" && (
        <AccountsDialog call={call} user={user} accounts={accounts} onClose={() => setDialog(null)} onChanged={refreshAll} notify={notify} />
      )}
      {dialog === "compose" && (
        <ComposeDialog call={call} accounts={accounts} defaultAccountId={view.accountId} onClose={() => setDialog(null)} onSent={onComposed} />
      )}

      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}
    </div>
  );
}

export default function App() {
  const { token, user, checking, authenticate, startDemo, logout } = useAuth();
  if (checking) return <div className="splash">Loading…</div>;
  if (!token || !user) return <AuthScreen onAuthenticate={authenticate} onDemo={startDemo} />;
  return <Mailbox token={token} user={user} onLogout={logout} />;
}
