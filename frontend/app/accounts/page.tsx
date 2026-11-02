"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

type Account = { id: number; username: string; connection_status: string; account_type: string };

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api<Account[]>(`/api/accounts?search=${encodeURIComponent(search)}`)
      .then(setAccounts)
      .catch(() => setError("Could not load accounts. Log in first."));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  return (
    <main className="mx-auto max-w-4xl p-6">
      <Link href="/" className="text-sm text-slate-500">← Dashboard</Link>
      <h1 className="mt-2 text-2xl font-bold">Instagram Accounts</h1>
      <input className="mt-4 w-full rounded border bg-white p-2" placeholder="Search username…" value={search} onChange={(e) => setSearch(e.target.value)} />
      {error && <p className="mt-4 text-red-700">{error}</p>}
      <ul className="mt-4 space-y-2">
        {accounts.map((a) => (
          <li key={a.id} className="flex justify-between rounded bg-white p-3 shadow">
            <span>@{a.username} <span className="text-slate-400">({a.account_type})</span></span>
            <span>{a.connection_status}</span>
          </li>
        ))}
      </ul>
      {accounts.length === 0 && !error && <p className="mt-4 text-slate-500">No accounts yet.</p>}
    </main>
  );
}
