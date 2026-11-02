"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  Clapperboard,
  Instagram,
  Users,
  Video,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { api, type AccountSummary, type DashboardStats } from "@/lib/api";

const NAV: [string, string][] = [
  ["Dashboard", "/"], ["Instagram Accounts", "/accounts"],
  ["Google Drive Integration", "/drive"], ["Account-Folder Mapping", "/mappings"],
  ["Video Library", "/videos"], ["Bulk Upload / Video Detection", "/videos"],
  ["Reel Scheduler", "/scheduler"], ["Publishing Calendar", "/scheduler"],
  ["Publishing History", "/history"], ["Failed Jobs", "/failed"], ["Account Health", "/health"],
  ["Daily Reports", "/reports"], ["Notifications", "/notifications"], ["Settings", "#"],
  ["System Logs", "#"],
];

export default function Dashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [accounts, setAccounts] = useState<AccountSummary[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!localStorage.getItem("aisystem_token")) {
      window.location.href = "/login";
      return;
    }
    api<DashboardStats>("/api/dashboard/stats")
      .then(setStats)
      .catch(() => setError("Could not load dashboard. Is the backend running on port 8000, and are you logged in?"));
    api<AccountSummary[]>("/api/dashboard/accounts-summary")
      .then(setAccounts)
      .catch(() => {});
  }, []);

  const cards = stats
    ? [
        { label: "Connected Accounts", value: stats.connected_accounts, icon: Users },
        { label: "Active Accounts", value: stats.active_accounts, icon: CheckCircle2 },
        { label: "Needing Attention", value: stats.accounts_needing_attention, icon: AlertTriangle },
        { label: "Total Videos", value: stats.total_videos, icon: Video },
        { label: "Scheduled Reels", value: stats.scheduled_reels, icon: CalendarClock },
        { label: "Published Reels", value: stats.published_reels, icon: Clapperboard },
        { label: "Failed Jobs", value: stats.failed_jobs, icon: XCircle },
      ]
    : [];

  return (
    <div className="flex min-h-screen">
      <aside className="w-64 shrink-0 bg-slate-900 p-4 text-white">
        <p className="flex items-center gap-2 text-lg font-bold"><Instagram /> Reels Automation</p>
        <p className="mt-1 text-xs text-slate-400">Phase 1 — real backend data</p>
        <nav className="mt-6 space-y-1">
          {NAV.map(([item, href], i) => (
            <Link key={item} href={href}
              className={`block rounded px-3 py-2 text-sm ${i === 0 ? "bg-slate-700" : "text-slate-300 hover:bg-slate-800"}`}>
              {item}
            </Link>
          ))}
        </nav>
      </aside>
      <main className="flex-1 p-6">
        <h1 className="text-2xl font-bold">Dashboard</h1>
        {error && <p className="mt-4 rounded bg-red-100 p-3 text-red-800">{error}</p>}
        {!stats && !error && <p className="mt-4">Loading…</p>}
        <div className="mt-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
          {cards.map((c) => (
            <div key={c.label} className="rounded bg-white p-4 shadow">
              <c.icon className="text-slate-500" />
              <p className="mt-2 text-3xl font-bold">{c.value}</p>
              <p className="text-sm text-slate-500">{c.label}</p>
            </div>
          ))}
        </div>
        <h2 className="mt-8 text-lg font-semibold">Accounts</h2>
        {accounts.length === 0 ? (
          <p className="mt-2 text-slate-500">No accounts connected yet. Add one via the API, then connect it with Meta OAuth in Phase 3.</p>
        ) : (
          <table className="mt-3 w-full rounded bg-white shadow">
            <thead><tr className="text-left text-sm text-slate-500">
              <th className="p-3">Username</th><th className="p-3">Status</th>
              <th className="p-3">Videos</th><th className="p-3">Scheduled</th><th className="p-3">Published</th>
            </tr></thead>
            <tbody>{accounts.map((a) => (
              <tr key={a.id} className="border-t">
                <td className="p-3">@{a.username}</td><td className="p-3">{a.connection_status}</td>
                <td className="p-3">{a.videos}</td><td className="p-3">{a.scheduled}</td><td className="p-3">{a.published}</td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </main>
    </div>
  );
}
