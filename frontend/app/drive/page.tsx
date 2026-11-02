"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API_URL, api, authHeaders } from "@/lib/api";

type Folder = { id: number; drive_folder_id: string; name: string };

export default function DrivePage() {
  const [status, setStatus] = useState("");
  const [folders, setFolders] = useState<Folder[]>([]);
  const [message, setMessage] = useState("");

  async function load() {
    try {
      const conn = await api<{ status: string }>("/api/drive/connection");
      setStatus(conn.status);
      const list = await api<Folder[]>("/api/drive/folders");
      setFolders(list);
    } catch {
      setMessage("Could not load Drive status. Log in first.");
    }
  }

  useEffect(() => { load(); }, []);

  async function connect() {
    try {
      const data = await api<{ auth_url: string }>("/api/drive/oauth/start");
      window.location.href = data.auth_url;
    } catch (e) {
      setMessage("Connect failed: Google OAuth is not configured yet. See docs/GOOGLE_DRIVE_SETUP.md (GOOGLE_CLIENT_ID / SECRET in backend .env).");
    }
  }

  async function sync() {
    try {
      const res = await fetch(`${API_URL}/api/drive/sync`, { method: "POST", headers: authHeaders() });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Sync failed");
      setMessage(`Sync done: ${data.created} new, ${data.updated} updated, ${data.total} folders found in Drive.`);
      await load();
    } catch (e: any) {
      setMessage(`Sync failed: ${e.message}`);
    }
  }

  return (
    <main className="mx-auto max-w-3xl p-6">
      <Link href="/" className="text-sm text-slate-500">← Dashboard</Link>
      <h1 className="mt-2 text-2xl font-bold">Google Drive Integration</h1>
      <p className="mt-1 text-sm text-slate-500">One central Drive account. Expected layout: Instagram-Automation / XYZ / … — mapping stores the permanent folder ID, never just the name.</p>
      <p className="mt-4">Status: <b>{status || "…"}</b></p>
      <div className="mt-3 flex gap-2">
        <button className="rounded bg-slate-900 px-4 py-2 text-white" onClick={connect}>Connect Google Drive</button>
        <button className="rounded border bg-white px-4 py-2" onClick={sync}>Sync folders from Drive</button>
        <Link href="/mappings" className="rounded border bg-white px-4 py-2">Account-Folder Mapping →</Link>
      </div>
      {message && <p className="mt-4 rounded bg-white p-3 shadow">{message}</p>}
      <h2 className="mt-6 text-lg font-semibold">Synced folders ({folders.length})</h2>
      <ul className="mt-2 space-y-1">
        {folders.map((f) => (
          <li key={f.id} className="rounded bg-white p-2 shadow">{f.name} <span className="text-xs text-slate-400">{f.drive_folder_id}</span></li>
        ))}
      </ul>
      {folders.length === 0 && <p className="mt-2 text-slate-500">No folders synced yet.</p>}
    </main>
  );
}
