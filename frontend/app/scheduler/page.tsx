"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API_URL, api, authHeaders } from "@/lib/api";

type Account = { id: number; username: string };
type Video = { id: number; filename: string; status: string };
type Schedule = { id: number; instagram_account_id: number; drive_video_id: number; scheduled_at_utc: string; scheduled_at_local: string | null; timezone: string; recurrence_rule: string | null; status: string; is_paused: boolean };

export default function SchedulerPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [videos, setVideos] = useState<Video[]>([]);
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [accountId, setAccountId] = useState("");
  const [videoId, setVideoId] = useState("");
  const [local, setLocal] = useState("");
  const [tz, setTz] = useState("Asia/Kolkata");
  const [recurrence, setRecurrence] = useState("");
  const [message, setMessage] = useState("");

  async function loadSchedules() {
    try { setSchedules(await api<Schedule[]>("/api/schedules?limit=100")); } catch { setMessage("Could not load schedules. Log in first."); }
  }
  useEffect(() => { api<Account[]>("/api/accounts?limit=200").then(setAccounts).catch(() => {}); loadSchedules(); }, []);
  useEffect(() => {
    if (accountId) api<Video[]>(`/api/videos?account_id=${accountId}&status=READY&limit=200`).then(setVideos).catch(() => {});
    else setVideos([]);
  }, [accountId]);

  async function create() {
    if (!local) { setMessage("Pick a date and time."); return; }
    const res = await fetch(`${API_URL}/api/schedules`, {
      method: "POST", headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ instagram_account_id: Number(accountId), drive_video_id: Number(videoId), scheduled_at_local: local, timezone: tz, recurrence_rule: recurrence || null }),
    });
    const data = await res.json();
    if (!res.ok) { setMessage(`Schedule failed: ${data.detail || "error"}`); return; }
    setMessage(`Scheduled for ${data.scheduled_at_local} (${tz}) = ${data.scheduled_at_utc} UTC.`);
    await loadSchedules();
  }

  async function action(id: number, act: string) {
    await fetch(`${API_URL}/api/schedules/${id}/${act}`, { method: "POST", headers: authHeaders() });
    await loadSchedules();
  }

  return (
    <main className="mx-auto max-w-4xl p-6">
      <Link href="/" className="text-sm text-slate-500">← Dashboard</Link>
      <h1 className="mt-2 text-2xl font-bold">Reel Scheduler</h1>
      <p className="mt-1 text-sm text-slate-500">Times are stored in UTC and shown in your timezone. A video can only be scheduled for its own mapped account, and only when it is READY. The worker (Phase 5, separate process) picks up due jobs; actual Meta publishing arrives in Phase 6.</p>
      <div className="mt-4 space-y-3 rounded bg-white p-4 shadow">
        <select className="w-full rounded border p-2" value={accountId} onChange={(e) => setAccountId(e.target.value)}>
          <option value="">Select account…</option>
          {accounts.map((a) => <option key={a.id} value={a.id}>@{a.username}</option>)}
        </select>
        <select className="w-full rounded border p-2" value={videoId} onChange={(e) => setVideoId(e.target.value)}>
          <option value="">Select READY video…</option>
          {videos.map((v) => <option key={v.id} value={v.id}>{v.filename}</option>)}
        </select>
        <input className="w-full rounded border p-2" type="datetime-local" value={local} onChange={(e) => setLocal(e.target.value)} />
        <select className="w-full rounded border p-2" value={tz} onChange={(e) => setTz(e.target.value)}>
          {["Asia/Kolkata", "UTC", "America/New_York", "America/Los_Angeles", "Europe/London"].map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <select className="w-full rounded border p-2" value={recurrence} onChange={(e) => setRecurrence(e.target.value)}>
          <option value="">No recurrence</option>
          <option value="daily">Daily (same video)</option>
          <option value="weekly">Weekly (same video)</option>
          <option value="monthly">Monthly (same video)</option>
        </select>
        <button className="rounded bg-slate-900 px-4 py-2 text-white" onClick={create} disabled={!accountId || !videoId}>Schedule Reel</button>
      </div>
      {message && <p className="mt-4 rounded bg-white p-3 shadow">{message}</p>}
      <h2 className="mt-6 text-lg font-semibold">Schedules</h2>
      <ul className="mt-2 space-y-2">
        {schedules.map((s) => (
          <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 rounded bg-white p-3 shadow">
            <span>#{s.id} · account {s.instagram_account_id} · video {s.drive_video_id} · {s.scheduled_at_local || s.scheduled_at_utc} ({s.timezone}){s.recurrence_rule ? ` · ${s.recurrence_rule}` : ""}{s.is_paused ? " · PAUSED" : ""}</span>
            <span className="flex gap-2">
              <span>{s.status}</span>
              {s.is_paused
                ? <button className="rounded border px-2 py-1 text-sm" onClick={() => action(s.id, "resume")}>Resume</button>
                : <button className="rounded border px-2 py-1 text-sm" onClick={() => action(s.id, "pause")}>Pause</button>}
              <button className="rounded border px-2 py-1 text-sm" onClick={() => action(s.id, "cancel")}>Cancel</button>
            </span>
          </li>
        ))}
      </ul>
    </main>
  );
}
