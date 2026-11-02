"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

type Schedule = { id: number; instagram_account_id: number; drive_video_id: number; scheduled_at_utc: string; status: string };
type Attempt = { attempt_number: number; status: string; instagram_media_id: string | null; error_detail: string | null };

export default function HistoryPage() {
  const [rows, setRows] = useState<(Schedule & { attempts: Attempt[] })[]>([]);
  const [filter, setFilter] = useState("PUBLISHED");

  useEffect(() => {
    (async () => {
      const list = await api<Schedule[]>(`/api/schedules?status=${filter}&limit=100`);
      const withAttempts = await Promise.all(list.map(async (s) => ({
        ...s, attempts: await api<Attempt[]>(`/api/schedules/${s.id}/attempts`).catch(() => []),
      })));
      setRows(withAttempts);
    })().catch(() => {});
  }, [filter]);

  return (
    <main className="mx-auto max-w-4xl p-6">
      <Link href="/" className="text-sm text-slate-500">← Dashboard</Link>
      <h1 className="mt-2 text-2xl font-bold">Publishing History</h1>
      <select className="mt-4 rounded border bg-white p-2" value={filter} onChange={(e) => setFilter(e.target.value)}>
        <option value="PUBLISHED">Published</option>
        <option value="FAILED">Failed</option>
        <option value="SCHEDULED">Scheduled</option>
      </select>
      <ul className="mt-4 space-y-2">
        {rows.map((r) => (
          <li key={r.id} className="rounded bg-white p-3 shadow">
            <p>Schedule #{r.id} · account {r.instagram_account_id} · video {r.drive_video_id} · {r.scheduled_at_utc} · {r.status}</p>
            {r.attempts.map((a) => (
              <p key={a.attempt_number} className="text-sm text-slate-500">
                Attempt {a.attempt_number}: {a.status}
                {a.instagram_media_id ? ` · Media ID: ${a.instagram_media_id}` : ""}
                {a.error_detail ? ` · ${a.error_detail}` : ""}
              </p>
            ))}
          </li>
        ))}
      </ul>
      {rows.length === 0 && <p className="mt-4 text-slate-500">No rows for this filter yet.</p>}
    </main>
  );
}
