"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API_URL, api, authHeaders } from "@/lib/api";

type Job = { id: number; instagram_account_id: number; drive_video_id: number; scheduled_at_utc: string; last_error: string | null; last_attempt_number: number; instagram_media_id: string | null };

export default function FailedPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [message, setMessage] = useState("");

  async function load() {
    try { setJobs(await api<Job[]>("/api/failed-jobs")); } catch { setMessage("Could not load failed jobs. Log in first."); }
  }
  useEffect(() => { load(); }, []);

  async function act(id: number, action: string) {
    const res = await fetch(`${API_URL}/api/schedules/${id}/${action}`, { method: "POST", headers: authHeaders() });
    const data = await res.json();
    if (!res.ok) { setMessage(`${action} failed: ${data.detail || "error"}`); return; }
    if (action === "reconcile") {
      setMessage(data.found ? `Reconciled: found on Instagram, Media ID ${data.instagram_media_id}.` : `Not found on Instagram: ${data.reason}. Check Instagram manually before retrying.`);
    } else {
      setMessage(`Job #${id} set back to SCHEDULED for immediate retry.`);
    }
    await load();
  }

  return (
    <main className="mx-auto max-w-4xl p-6">
      <Link href="/" className="text-sm text-slate-500">← Dashboard</Link>
      <h1 className="mt-2 text-2xl font-bold">Failed Jobs (Dead-Letter Queue)</h1>
      <p className="mt-1 text-sm text-slate-500">These jobs stopped after max retries, a permanent error, or an uncertain publish. Retry is manual and deliberate — for UNCERTAIN jobs, reconcile first to check whether the Reel is already live, otherwise you may duplicate it.</p>
      {message && <p className="mt-4 rounded bg-white p-3 shadow">{message}</p>}
      <ul className="mt-4 space-y-2">
        {jobs.map((j) => (
          <li key={j.id} className="rounded bg-white p-3 shadow">
            <p>Schedule #{j.id} · account {j.instagram_account_id} · video {j.drive_video_id} · was due {j.scheduled_at_utc}</p>
            <p className="text-sm text-red-700">Attempt {j.last_attempt_number}: {j.last_error || "no error recorded"}</p>
            <div className="mt-2 flex gap-2">
              <button className="rounded border px-2 py-1 text-sm" onClick={() => act(j.id, "reconcile")}>Reconcile (check Instagram)</button>
              <button className="rounded border px-2 py-1 text-sm" onClick={() => act(j.id, "retry")}>Manual retry</button>
            </div>
          </li>
        ))}
      </ul>
      {jobs.length === 0 && <p className="mt-4 text-slate-500">No failed jobs. Good.</p>}
    </main>
  );
}
