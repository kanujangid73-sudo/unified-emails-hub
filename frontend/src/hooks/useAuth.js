import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api.js";

const STORAGE_KEY = "mailhub.token";

function readToken() {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeToken(token) {
  try {
    if (token) localStorage.setItem(STORAGE_KEY, token);
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage unavailable (private mode): the session just won't survive a reload.
  }
}

export function useAuth() {
  const [token, setToken] = useState(readToken);
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(Boolean(readToken()));

  useEffect(() => {
    if (!token || user) return;
    let cancelled = false;
    api("/api/auth/me", { token })
      .then((me) => !cancelled && setUser(me))
      .catch((err) => {
        if (!cancelled && err.status === 401) {
          writeToken(null);
          setToken(null);
        }
      })
      .finally(() => !cancelled && setChecking(false));
    return () => {
      cancelled = true;
    };
  }, [token, user]);

  const signIn = useCallback((data) => {
    writeToken(data.access_token);
    setToken(data.access_token);
    setUser(data.user);
  }, []);

  const authenticate = useCallback(
    async (mode, username, password) => {
      signIn(await api(`/api/auth/${mode}`, { method: "POST", body: { username, password } }));
    },
    [signIn],
  );

  // One-click demo: a temporary guest account with three sample mailboxes.
  const startDemo = useCallback(async () => {
    signIn(await api("/api/auth/demo", { method: "POST" }));
  }, [signIn]);

  const logout = useCallback(() => {
    writeToken(null);
    setToken(null);
    setUser(null);
  }, []);

  return { token, user, checking, authenticate, startDemo, logout };
}
