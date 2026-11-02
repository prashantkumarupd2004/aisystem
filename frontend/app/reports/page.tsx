"use client";

import { useState } from "react";
import Link from "next/link";
import { API_URL, api, authHeaders } from "@/lib/api";

type Report = {
  start_date: string; end_date: string;
  totals: { total_detected: number; total_scheduled: number; total_published: number; total_failed: number; total_pending: number };
  per_account: { id: number; username: string; total_detected: number; total_scheduled: number; total_published: number; total_failed: number; total_pending: number }[];
  published_history: { schedule_id: number; account: string | null; scheduled_at_utc: string; published_at_utc: string; instagram_media_id: string | null }[];
};

export default function ReportsPage() {
  const today = new Date().toISOString().slice(0, 10);
  const [start, setStart] = useState(today);
  const [end, setEnd] = useState(today);
  const [report, setReport] = useState<Report | null>(null);
  const [message, setMessage] = useState("");

  async function load() {
    try { setReport(await api<Report>(`/api/reports?start=${start}&end=${end}`)); }
    catch { setMessage("Could not load report. Log in first."); }
  }

  async function downloadCsv() {
    const res = await fetch(`${API_URL}/api/reports/export.csv?start=${start}&end=${end}`, { headers: authHeaders() });
    if (!res.ok) { setMessage("CSV download failed."); return; }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `report-${start}-to-${end}.csv`; a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <main className="mx-auto max-w-5xl p-6">
      <Link href="/" className="text-sm text-slate-500">← Dashboard</Link>
      <h1 className="mt-2 text-2xl font-bold">Daily Reports</h1>
      <p className="mt-1 text-sm text-slate-500">Counts are computed from real rows. Pending is a current snapshot, not a historical count.</p>
      <div className="mt-4 flex flex-wrap gap-2">
        <input className="rounded border bg-white p-2" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        <input className="rounded border bg-white p-2" type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
        <button className="rounded bg-slate-900 px-4 py-2 text-white" onClick={load}>Show report</button>
        <button className="rounded border bg-white px-4 py-2" onClick={downloadCsv}>Download CSV</button>
      </div>
      {message && <p className="mt-4 rounded bg-white p-3 shadow">{message}</p>}
      {report && (
        <>
          <p className="mt-6 font-semibold">Totals: detected {report.totals.total_detected} · scheduled {report.totals.total_scheduled} · published {report.totals.total_published} · failed attempts {report.totals.total_failed} · pending {report.totals.total_pending}</p>
          <table className="mt-3 w-full rounded bg-white shadow">
            <thead><tr className="text-left text-sm text-slate-500">
              <th className="p-3">Account</th><th className="p-3">Detected</th><th className="p-3">Scheduled</th><th className="p-3">Published</th><th className="p-3">Failed</th><th className="p-3">Pending</th>
            </tr></thead>
            <tbody>{report.per_account.map((a) => (
              <tr key={a.id} className="border-t">
                <td className="p-3">@{a.username}</td><td className="p-3">{a.total_detected}</td><td className="p-3">{a.total_scheduled}</td><td className="p-3">{a.total_published}</td><td className="p-3">{a.total_failed}</td><td className="p-3">{a.total_pending}</td>
              </tr>
            ))}</tbody>
          </table>
          <h2 className="mt-6 text-lg font-semibold">Published history</h2>
          <ul className="mt-2 space-y-1">
            {report.published_history.map((h) => (
              <li key={h.schedule_id} className="rounded bg-white p-2 shadow">@{h.account} · scheduled {h.scheduled_at_utc} · published {h.published_at_utc} · Media ID: {h.instagram_media_id || "—"}</li>
            ))}
          </ul>
        </>
      )}
    </main>
  );
}
