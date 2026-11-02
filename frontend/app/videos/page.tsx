"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API_URL, api, authHeaders } from "@/lib/api";

type Video = {
  id: number; filename: string; drive_file_id: string; mime_type: string | null;
  size_bytes: number | null; duration_seconds: number | null; status: string;
  caption: string | null; hashtags: string | null; thumbnail_url: string | null;
  validation_notes: string | null; instagram_account_id: number;
};
type Account = { id: number; username: string };

export default function VideosPage() {
  const [videos, setVideos] = useState<Video[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountId, setAccountId] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [message, setMessage] = useState("");
  const [editing, setEditing] = useState<Video | null>(null);
  const [caption, setCaption] = useState("");
  const [hashtags, setHashtags] = useState("");

  async function load() {
    try {
      const params = new URLSearchParams();
      if (accountId) params.set("account_id", accountId);
      if (status) params.set("status", status);
      if (search) params.set("search", search);
      setVideos(await api<Video[]>(`/api/videos?${params.toString()}`));
    } catch {
      setMessage("Could not load videos. Log in first.");
    }
  }
  useEffect(() => { api<Account[]>("/api/accounts?limit=200").then(setAccounts).catch(() => {}); }, []);
  useEffect(() => { load(); }, [accountId, status, search]);

  async function scan() {
    const res = await fetch(`${API_URL}/api/videos/scan`, { method: "POST", headers: authHeaders() });
    const data = await res.json();
    if (!res.ok) { setMessage(`Scan failed: ${data.detail || "error"}`); return; }
    const summary = data.results.map((r: any) => r.error ? `account ${r.account_id}: error ${r.error}` : `${r.username || r.account_id}: ${r.created} new, ${r.needs_review} needs review, ${r.missing_marked} missing`).join(" | ");
    setMessage(`Scan done. ${summary}`);
    await load();
  }

  async function saveEdit() {
    if (!editing) return;
    const res = await fetch(`${API_URL}/api/videos/${editing.id}`, {
      method: "PATCH", headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ caption, hashtags }),
    });
    if (!res.ok) { setMessage("Save failed."); return; }
    setEditing(null);
    setMessage("Caption/hashtags saved (in our DB only; the Drive file is untouched).");
    await load();
  }

  return (
    <main className="mx-auto max-w-5xl p-6">
      <Link href="/" className="text-sm text-slate-500">← Dashboard</Link>
      <h1 className="mt-2 text-2xl font-bold">Video Library</h1>
      <p className="mt-1 text-sm text-slate-500">One row per Drive file, per account. Scanning never deletes, renames or moves Drive originals. Preview here is the Drive-generated thumbnail; full authenticated playback arrives with the Phase 6 media endpoint.</p>
      <button className="mt-4 rounded bg-slate-900 px-4 py-2 text-white" onClick={scan}>Scan mapped Drive folders</button>
      {message && <p className="mt-4 rounded bg-white p-3 shadow">{message}</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        <select className="rounded border bg-white p-2" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
          <option value="">All accounts</option>
          {accounts.map((a) => <option key={a.id} value={a.id}>@{a.username}</option>)}
        </select>
        <select className="rounded border bg-white p-2" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          {["NEW", "READY", "SCHEDULED", "PROCESSING", "PUBLISHED", "FAILED", "NEEDS_REVIEW"].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <input className="rounded border bg-white p-2" placeholder="Search filename…" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>
      <div className="mt-4 space-y-2">
        {videos.map((v) => (
          <div key={v.id} className="flex flex-wrap items-start gap-3 rounded bg-white p-3 shadow">
            {v.thumbnail_url
              ? <img src={v.thumbnail_url} alt="" className="h-20 w-14 object-cover rounded" />
              : <div className="flex h-20 w-14 items-center justify-center rounded bg-slate-200 text-xs text-slate-500">No thumb</div>}
            <div className="flex-1">
              <p className="font-semibold">{v.filename}</p>
              <p className="text-sm text-slate-500">
                {v.duration_seconds ? `${v.duration_seconds}s` : "duration unknown"} · {v.size_bytes ? `${(v.size_bytes / 1048576).toFixed(1)} MB` : "size unknown"} · {v.mime_type || "mime unknown"}
              </p>
              <p className="text-xs text-slate-400">Drive: {v.drive_file_id}</p>
              {v.validation_notes && <p className="text-sm text-amber-700">{v.validation_notes}</p>}
              {v.caption && <p className="text-sm">{v.caption}</p>}
            </div>
            <div className="text-right">
              <p className="text-sm font-semibold">{v.status}</p>
              <button className="mt-1 rounded border px-2 py-1 text-sm" onClick={() => { setEditing(v); setCaption(v.caption || ""); setHashtags(v.hashtags || ""); }}>Edit caption</button>
            </div>
          </div>
        ))}
      </div>
      {videos.length === 0 && <p className="mt-4 text-slate-500">No videos yet. Map a folder, then scan.</p>}
      {editing && (
        <div className="fixed inset-0 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded bg-white p-4 shadow">
            <h2 className="font-bold">Edit: {editing.filename}</h2>
            <textarea className="mt-3 w-full rounded border p-2" rows={3} placeholder="Caption" value={caption} onChange={(e) => setCaption(e.target.value)} />
            <input className="mt-2 w-full rounded border p-2" placeholder="Hashtags, e.g. #reels #fitness" value={hashtags} onChange={(e) => setHashtags(e.target.value)} />
            <div className="mt-3 flex gap-2">
              <button className="rounded bg-slate-900 px-4 py-2 text-white" onClick={saveEdit}>Save</button>
              <button className="rounded border px-4 py-2" onClick={() => setEditing(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
