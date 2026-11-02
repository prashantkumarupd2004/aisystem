"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API_URL, api, authHeaders } from "@/lib/api";

type Account = { id: number; username: string; connection_status: string; account_type: string };

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const connected = params.get("instagram_connected");
    if (connected !== null) setMessage(`${connected} Instagram account(s) connected/updated via Meta OAuth.`);
    api<Account[]>(`/api/accounts?search=${encodeURIComponent(search)}`)
      .then(setAccounts)
      .catch(() => setError("Could not load accounts. Log in first."));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  async function connect() {
    try {
      const data = await api<{ auth_url: string }>("/api/instagram/oauth/start");
      window.location.href = data.auth_url;
    } catch {
      setMessage("Connect failed: Meta OAuth is not configured yet. See docs/META_SETUP.md (META_APP_ID / SECRET in backend .env).");
    }
  }

  async function check(id: number) {
    const res = await fetch(`${API_URL}/api/instagram/accounts/${id}/check`, { method: "POST", headers: authHeaders() });
    const data = await res.json();
    setMessage(res.ok ? `@${data.username}: ${data.status}` : `Check failed: ${data.detail || "error"}`);
    const list = await api<Account[]>("/api/accounts");
    setAccounts(list);
  }

  async function disconnect(id: number) {
    if (!confirm("Disconnect this account? Its stored token will be cleared and it must be reconnected via Meta OAuth.")) return;
    await fetch(`${API_URL}/api/accounts/${id}/disconnect`, { method: "POST", headers: authHeaders() });
    const list = await api<Account[]>("/api/accounts");
    setAccounts(list);
  }

  return (
    <main className="mx-auto max-w-4xl p-6">
      <Link href="/" className="text-sm text-slate-500">← Dashboard</Link>
      <h1 className="mt-2 text-2xl font-bold">Instagram Accounts</h1>
      <p className="mt-1 text-sm text-slate-500">Official Meta OAuth only — no Instagram passwords are ever requested or stored. Only Business/Creator accounts linked to a Facebook Page are eligible.</p>
      <button className="mt-4 rounded bg-slate-900 px-4 py-2 text-white" onClick={connect}>Connect Instagram via Meta</button>
      {message && <p className="mt-4 rounded bg-white p-3 shadow">{message}</p>}
      <input className="mt-4 w-full rounded border bg-white p-2" placeholder="Search username…" value={search} onChange={(e) => setSearch(e.target.value)} />
      {error && <p className="mt-4 text-red-700">{error}</p>}
      <ul className="mt-4 space-y-2">
        {accounts.map((a) => (
          <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 rounded bg-white p-3 shadow">
            <span>@{a.username} <span className="text-slate-400">({a.account_type})</span></span>
            <span className="flex items-center gap-2">
              <span>{a.connection_status}</span>
              <button className="rounded border px-2 py-1 text-sm" onClick={() => check(a.id)}>Check</button>
              <button className="rounded border px-2 py-1 text-sm" onClick={() => disconnect(a.id)}>Disconnect</button>
            </span>
          </li>
        ))}
      </ul>
      {accounts.length === 0 && !error && <p className="mt-4 text-slate-500">No accounts yet.</p>}
    </main>
  );
}
