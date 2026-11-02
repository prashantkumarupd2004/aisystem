"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API_URL, api, authHeaders } from "@/lib/api";

type Account = { id: number; username: string };
type Folder = { id: number; name: string };
type Mapping = { id: number; instagram_account_id: number; drive_folder_id: number };

export default function MappingsPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [mappings, setMappings] = useState<Mapping[]>([]);
  const [accountId, setAccountId] = useState("");
  const [folderId, setFolderId] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [message, setMessage] = useState("");

  async function load() {
    try {
      setAccounts(await api<Account[]>("/api/accounts?limit=200"));
      setFolders(await api<Folder[]>("/api/drive/account-folders"));
      setMappings(await api<Mapping[]>("/api/mappings"));
    } catch {
      setMessage("Could not load data. Log in first.");
    }
  }
  useEffect(() => { load(); }, []);

  async function save() {
    if (!confirmed) { setMessage("Please confirm the mapping change first."); return; }
    const res = await fetch(`${API_URL}/api/mappings`, {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ instagram_account_id: Number(accountId), drive_folder_id: Number(folderId), shared_folder_mode: false, confirmed_by_admin: true }),
    });
    const data = await res.json();
    if (!res.ok) { setMessage(`Mapping failed: ${data.detail || "error"}`); return; }
    setMessage("Mapping saved. That account will only ever publish from this folder.");
    await load();
  }

  const nameOfAccount = (id: number) => accounts.find((a) => a.id === id)?.username || String(id);
  const nameOfFolder = (id: number) => folders.find((f) => f.id === id)?.name || `folder #${id}`;

  return (
    <main className="mx-auto max-w-3xl p-6">
      <Link href="/" className="text-sm text-slate-500">← Dashboard</Link>
      <h1 className="mt-2 text-2xl font-bold">Account-Folder Mapping</h1>
      <p className="mt-1 text-sm text-slate-500">One folder per account. A folder already mapped to another account is rejected unless shared-folder mode is explicitly enabled (API only).</p>
      <div className="mt-4 space-y-3 rounded bg-white p-4 shadow">
        <select className="w-full rounded border p-2" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
          <option value="">Select Instagram account…</option>
          {accounts.map((a) => <option key={a.id} value={a.id}>@{a.username}</option>)}
        </select>
        <select className="w-full rounded border p-2" value={folderId} onChange={(e) => setFolderId(e.target.value)}>
          <option value="">Select Drive folder…</option>
          {folders.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
        </select>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
          I confirm this mapping change
        </label>
        <button className="rounded bg-slate-900 px-4 py-2 text-white" onClick={save} disabled={!accountId || !folderId}>Save mapping</button>
      </div>
      {message && <p className="mt-4 rounded bg-white p-3 shadow">{message}</p>}
      <h2 className="mt-6 text-lg font-semibold">Current mappings</h2>
      <ul className="mt-2 space-y-1">
        {mappings.map((m) => (
          <li key={m.id} className="rounded bg-white p-2 shadow">@{nameOfAccount(m.instagram_account_id)} → {nameOfFolder(m.drive_folder_id)}</li>
        ))}
      </ul>
    </main>
  );
}
