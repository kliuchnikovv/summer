"use client";

import { useEffect, useRef, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";
const TOKEN_KEY = "summer_token";

type DocStatus = "queued" | "parsing" | "parsed" | "summarizing" | "done" | "failed";

interface DocResult {
  id: string;
  filename: string;
  parser: string;
  status: DocStatus;
  page_count: number | null;
  error: string | null;
  pages: string[];
  summary: string | null;
  // UI-only:
  loaded?: boolean;   // content (pages+summary) fetched
  loading?: boolean;  // content fetch in flight
  expanded?: boolean; // card is open
}

interface Session {
  token: string;
  principal: string;
  dailyLimit: number;
}

const TERMINAL = new Set<DocStatus>(["done", "failed"]);

function loadToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export default function Home() {
  const [session, setSession] = useState<Session | null>(null);
  const [checking, setChecking] = useState(true);

  // Restore a saved session on load.
  useEffect(() => {
    const token = loadToken();
    if (!token) {
      setChecking(false);
      return;
    }
    fetch(`${API_BASE}/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then(async (r) => {
        if (r.ok) {
          const d = await r.json();
          setSession({ token, principal: d.principal, dailyLimit: d.daily_limit });
        } else {
          try { localStorage.removeItem(TOKEN_KEY); } catch {}
        }
      })
      .catch(() => {})
      .finally(() => setChecking(false));
  }, []);

  function onLoggedIn(s: Session) {
    try { localStorage.setItem(TOKEN_KEY, s.token); } catch {}
    setSession(s);
  }

  function onLogout() {
    const token = session?.token;
    if (token) {
      fetch(`${API_BASE}/auth/logout`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }).catch(() => {});
    }
    try { localStorage.removeItem(TOKEN_KEY); } catch {}
    setSession(null);
  }

  if (checking) {
    return <main className="container"><p className="meta">Loading…</p></main>;
  }

  return (
    <main className="container">
      <h1>Summer</h1>
      <p className="subtitle">Async PDF processing — parse to markdown & summarize.</p>
      {session ? (
        <App session={session} onLogout={onLogout} />
      ) : (
        <LoginForm onLoggedIn={onLoggedIn} />
      )}
    </main>
  );
}

function LoginForm({ onLoggedIn }: { onLoggedIn: (s: Session) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      const r = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!r.ok) {
        setErr(r.status === 401 ? "Invalid username or password." : `Login failed (${r.status}).`);
        return;
      }
      const d = await r.json();
      onLoggedIn({ token: d.token, principal: d.principal, dailyLimit: d.daily_limit });
    } catch (e: any) {
      setErr(`Network error: ${e?.message || e}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" onSubmit={submit} style={{ maxWidth: 420 }}>
      <h3 style={{ marginTop: 0 }}>Sign in</h3>
      <div style={{ marginBottom: 12 }}>
        <label>Username</label>
        <input type="text" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
      </div>
      <div>
        <label>Password</label>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
      </div>
      <button type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      {err && <div className="error">{err}</div>}
    </form>
  );
}

function App({ session, onLogout }: { session: Session; onLogout: () => void }) {
  const [parser, setParser] = useState("pypdf");
  const [docs, setDocs] = useState<Record<string, DocResult>>({});
  const [order, setOrder] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const auth = { "X-API-Key": session.token };

  function upsert(d: Partial<DocResult> & { id: string }) {
    setDocs((prev) => ({ ...prev, [d.id]: { ...prev[d.id], ...d } as DocResult }));
  }

  // On mount: load the user's existing documents (metadata only, no content).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${API_BASE}/documents`, { headers: auth });
        if (r.status === 401) { onLogout(); return; }
        if (!r.ok) return;
        const list: DocResult[] = await r.json();
        if (cancelled) return;
        const map: Record<string, DocResult> = {};
        for (const d of list) {
          map[d.id] = { ...d, pages: [], summary: null, loaded: false, expanded: false };
          // Resume streaming for anything still in flight.
          if (!TERMINAL.has(d.status)) streamDoc(d.id);
        }
        setDocs((prev) => ({ ...map, ...prev }));
        setOrder((prev) => {
          const have = new Set(prev);
          return [...prev, ...list.map((d) => d.id).filter((id) => !have.has(id))];
        });
      } catch { /* offline */ }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Lazily fetch a document's content (pages + summary) and open the card.
  async function loadContent(id: string) {
    upsert({ id, loading: true, expanded: true });
    try {
      const r = await fetch(`${API_BASE}/documents/${id}`, { headers: auth });
      if (r.status === 401) { onLogout(); return; }
      if (r.ok) {
        const d: DocResult = await r.json();
        upsert({ ...d, loaded: true, loading: false, expanded: true });
      } else {
        upsert({ id, loading: false });
      }
    } catch {
      upsert({ id, loading: false });
    }
  }

  function toggle(id: string) {
    const d = docs[id];
    if (!d) return;
    if (d.expanded) { upsert({ id, expanded: false }); return; }
    if (d.loaded) { upsert({ id, expanded: true }); return; }
    loadContent(id);
  }

  async function streamDoc(id: string) {
    try {
      const resp = await fetch(`${API_BASE}/documents/${id}/events`, { headers: auth });
      if (!resp.ok || !resp.body) return pollDoc(id);
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop() || "";
        for (const part of parts) {
          const line = part.split("\n").find((l) => l.startsWith("data:"));
          if (!line) continue;
          try {
            const d: DocResult = JSON.parse(line.slice(5).trim());
            upsert(d);
            if (TERMINAL.has(d.status)) return;
          } catch { /* keep-alive */ }
        }
      }
    } catch {
      return pollDoc(id);
    }
  }

  async function pollDoc(id: string) {
    for (let i = 0; i < 300; i++) {
      try {
        const r = await fetch(`${API_BASE}/documents/${id}`, { headers: auth });
        if (r.ok) {
          const d: DocResult = await r.json();
          upsert(d);
          if (TERMINAL.has(d.status)) return;
        }
      } catch { /* retry */ }
      await new Promise((res) => setTimeout(res, 1500));
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    const files = fileRef.current?.files;
    if (!files || files.length === 0) {
      setErr("Please choose at least one PDF.");
      return;
    }
    const form = new FormData();
    form.append("parser", parser);
    for (const f of Array.from(files)) form.append("files", f);

    setBusy(true);
    try {
      const resp = await fetch(`${API_BASE}/documents`, { method: "POST", headers: auth, body: form });
      if (resp.status === 401) {
        onLogout();
        return;
      }
      if (!resp.ok) {
        const text = await resp.text();
        setErr(`Upload failed (${resp.status}): ${text}`);
        return;
      }
      const data = await resp.json();
      const newIds: string[] = [];
      for (const doc of data.documents) {
        upsert({ id: doc.id, filename: doc.filename, parser, status: doc.status,
                 page_count: null, error: null, pages: [], summary: null,
                 loaded: true, expanded: true });  // freshly uploaded -> show live
        newIds.push(doc.id);
        streamDoc(doc.id);
      }
      setOrder((prev) => [...newIds.filter((id) => !prev.includes(id)), ...prev]);
      if (fileRef.current) fileRef.current.value = "";
    } catch (e: any) {
      setErr(`Network error: ${e?.message || e}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="card" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div className="meta">
          Signed in as <strong>{session.principal}</strong> · limit {session.dailyLimit} uploads/day
        </div>
        <button type="button" onClick={onLogout} style={{ marginTop: 0, background: "var(--panel-2)", color: "var(--text)" }}>
          Log out
        </button>
      </div>

      <form className="card" onSubmit={onSubmit}>
        <div>
          <label>Parser</label>
          <select value={parser} onChange={(e) => setParser(e.target.value)}>
            <option value="pypdf">PyPDF (text)</option>
            <option value="gemini">Gemini Flash (markdown)</option>
            <option value="openai">GPT-5 Mini (OCR)</option>
          </select>
        </div>
        <div style={{ marginTop: 14 }}>
          <label>PDF files (one or more)</label>
          <input ref={fileRef} type="file" accept="application/pdf" multiple />
        </div>
        <button type="submit" disabled={busy}>{busy ? "Uploading…" : "Upload & process"}</button>
        {err && <div className="error">{err}</div>}
      </form>

      {order.length === 0 && <p className="meta">No documents yet — upload a PDF to get started.</p>}

      {order.map((id) => {
        const d = docs[id];
        if (!d) return null;
        const terminal = TERMINAL.has(d.status);
        const hasContent = d.pages.length > 0 || !!d.summary;
        return (
          <div className="card" key={id}>
            <div className="doc-head" onClick={() => toggle(id)} style={{ cursor: "pointer" }}>
              <span className="doc-name">
                <span className="caret">{d.expanded ? "▾" : "▸"}</span> {d.filename}
              </span>
              <span className={`badge ${d.status}`}>{d.status}</span>
            </div>
            <div className="meta">
              parser: {d.parser}{d.page_count != null ? ` · ${d.page_count} pages` : ""} · id: {d.id}
            </div>
            {d.error && <div className="error">Error: {d.error}</div>}

            {!d.expanded && terminal && !d.error && (
              <button type="button" className="link-btn" onClick={() => toggle(id)}>
                View result
              </button>
            )}

            {d.expanded && (
              <div>
                {d.loading && <div className="meta" style={{ marginTop: 10 }}>Loading content…</div>}
                {!d.loading && d.summary && (
                  <div className="summary">
                    <h4>Summary</h4>
                    <div>{d.summary}</div>
                  </div>
                )}
                {!d.loading && d.pages.length > 0 && (
                  <details open>
                    <summary>Per-page content ({d.pages.length} pages)</summary>
                    {d.pages.map((p, i) => (
                      <div key={i}>
                        <div className="meta" style={{ marginTop: 10 }}>Page {i + 1}</div>
                        <pre>{p}</pre>
                      </div>
                    ))}
                  </details>
                )}
                {!d.loading && terminal && !hasContent && !d.error && (
                  <div className="meta" style={{ marginTop: 10 }}>No content available (it may have expired).</div>
                )}
                {!terminal && !hasContent && (
                  <div className="meta" style={{ marginTop: 10 }}>Processing…</div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </>
  );
}
