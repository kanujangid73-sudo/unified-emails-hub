import { useEffect, useMemo, useState } from "react";
import { downloadCsv } from "../lib/csv.js";
import { fullDate } from "../lib/format.js";
import Icon from "./Icon.jsx";

function monthYear(iso) {
  return new Date(iso).toLocaleDateString([], { month: "short", year: "numeric" });
}

export default function AccountFinder({ call, accounts, onOpenThread, onBack }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState(""); // account id, "multiple", or ""
  const [search, setSearch] = useState("");

  useEffect(() => {
    call("/api/insights/accounts").then(setData, (err) => setError(err.message));
  }, [call]);

  const services = useMemo(() => {
    if (!data) return [];
    const term = search.trim().toLowerCase();
    return data.services.filter((s) => {
      if (term && !s.name.toLowerCase().includes(term) && !s.domain.includes(term)) return false;
      if (filter === "multiple") return s.accounts.length > 1;
      if (filter) return s.accounts.some((a) => a.account_id === Number(filter));
      return true;
    });
  }, [data, filter, search]);

  const exportCsv = () =>
    downloadCsv("account-finder.csv", [
      ["Service", "Domain", "Your address", "Evidence", "First email", "Latest email"],
      ...data.services.flatMap((s) =>
        s.accounts.map((a) => [s.name, s.domain, a.email, a.signals.map((x) => data.signal_labels[x]).join("; "), fullDate(a.first_seen), fullDate(a.last_seen)]),
      ),
    ]);

  const multiple = data?.services.filter((s) => s.accounts.length > 1).length ?? 0;

  return (
    <section className="tool-pane" aria-label="Account Finder">
      <header className="tool-head">
        <button className="icon-btn only-mobile" onClick={onBack} aria-label="Back">
          <Icon name="back" />
        </button>
        <div>
          <h1>Account Finder</h1>
          <p className="muted">
            Websites and apps you've signed up to, and which of your addresses each one has. Found from welcome, verification, password and order
            emails, on this server only.
          </p>
        </div>
      </header>

      {error && <p className="error">{error}</p>}
      {!data && !error && <p className="muted">Looking through your mail…</p>}
      {data && (
        <>
          <div className="stat-row">
            <div className="stat">
              <strong>{data.services.length}</strong>
              <span>services found</span>
            </div>
            <div className="stat">
              <strong>{multiple}</strong>
              <span>use more than one of your addresses</span>
            </div>
            <div className="stat">
              <strong>{accounts.length}</strong>
              <span>mailboxes checked</span>
            </div>
          </div>

          <div className="tool-filters">
            <label className="search small-search">
              <Icon name="search" size={14} />
              <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Find a service" aria-label="Find a service" />
            </label>
            <select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter by address">
              <option value="">All addresses</option>
              <option value="multiple">On more than one address</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.email}
                </option>
              ))}
            </select>
            <button className="btn small" onClick={exportCsv} disabled={!data.services.length}>
              Export CSV
            </button>
          </div>

          {services.length === 0 ? (
            <p className="empty">No services match.</p>
          ) : (
            <ul className="service-list">
              {services.map((s) => (
                <li key={s.domain} className="service">
                  <div className="service-name">
                    <span className="service-logo" aria-hidden="true">
                      {s.name[0]}
                    </span>
                    <div>
                      <strong>{s.name}</strong>
                      <span className="muted small">{s.domain}</span>
                    </div>
                    {s.accounts.length > 1 && <span className="pill">{s.accounts.length} addresses</span>}
                  </div>
                  <div className="service-uses">
                    {s.accounts.map((a) => (
                      <div key={a.account_id} className="use">
                        <span className="dot" style={{ background: a.color }} aria-hidden="true" />
                        <span className="use-email">{a.email}</span>
                        <span className="muted small">
                          {a.signals.map((x) => data.signal_labels[x]).join(" · ")} · since {monthYear(a.first_seen)}
                        </span>
                        {a.thread_id && (
                          <button className="link small" onClick={() => onOpenThread(a.thread_id)}>
                            View email
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          )}
          <p className="muted small">
            Tip: an account you no longer use is a security risk. Open the email, sign in to the service and delete the account, or at least change
            its password.
          </p>
        </>
      )}
    </section>
  );
}
