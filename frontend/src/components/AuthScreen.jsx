import { useEffect, useState } from "react";
import { API_URL } from "../config.js";

// Free hosting puts the API to sleep when idle; the first request then takes up to a minute.
// Ping it as soon as the page opens, and say so if it's slow, so nobody thinks the site is broken.
function useServerStatus() {
  const [status, setStatus] = useState("checking"); // checking | waking | ready | down
  useEffect(() => {
    let done = false;
    const slow = setTimeout(() => !done && setStatus("waking"), 2500);
    fetch(`${API_URL}/api/health`)
      .then((res) => setStatus(res.ok ? "ready" : "down"))
      .catch(() => setStatus("down"))
      .finally(() => {
        done = true;
        clearTimeout(slow);
      });
    return () => clearTimeout(slow);
  }, []);
  return status;
}

const FEATURES = [
  ["One inbox", "Gmail, Outlook and any IMAP mailbox, newest first, with a colour per account."],
  ["Incremental sync", "Only new changes are fetched. Safe to retry, and resumes after a failure."],
  ["Private by default", "Email HTML is sanitized and sandboxed; tracking pixels are blocked."],
];

export default function AuthScreen({ onAuthenticate, onDemo }) {
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState("");
  const server = useServerStatus();

  const run = async (kind, action) => {
    setBusy(kind);
    setError("");
    try {
      await action();
    } catch (err) {
      setError(err.message);
      setBusy(null);
    }
  };

  const submit = (e) => {
    e.preventDefault();
    run("form", () => onAuthenticate(mode, username.trim(), password));
  };

  return (
    <main className="auth">
      <section className="auth-pitch">
        <div className="brand-mark large" aria-hidden="true">
          <MailIcon />
        </div>
        <h1>Unified Emails Hub</h1>
        <p className="lead">All your email accounts in one fast, private inbox.</p>
        <ul className="feature-list">
          {FEATURES.map(([title, text]) => (
            <li key={title}>
              <strong>{title}</strong>
              <span>{text}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="auth-card" aria-label="Sign in">
        <button className="btn primary block" onClick={() => run("demo", onDemo)} disabled={busy !== null}>
          {busy === "demo" ? "Setting up your demo inbox…" : "Try the demo, no sign-up"}
        </button>
        <p className="hint">You get three sample mailboxes (personal, work and an old account) for 24 hours.</p>
        {server === "waking" && (
          <p className="notice small" role="status">
            The server is waking up (it sleeps when nobody uses it, on free hosting). This can take up to a minute.
          </p>
        )}
        {server === "down" && (
          <p className="error" role="alert">
            Can't reach the server right now. Please try again in a minute.
          </p>
        )}

        <div className="divider">
          <span>or {mode === "login" ? "sign in" : "create an account"}</span>
        </div>

        <form onSubmit={submit}>
          <label>
            Username
            <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required minLength={3} />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              required
              minLength={6}
            />
          </label>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <button className="btn block" disabled={busy !== null}>
            {busy === "form" ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>
        <button className="link" onClick={() => setMode(mode === "login" ? "register" : "login")}>
          {mode === "login" ? "New here? Create an account" : "Have an account? Sign in"}
        </button>
      </section>
    </main>
  );
}

export function MailIcon() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round">
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="m3 7 9 6 9-6" />
    </svg>
  );
}
