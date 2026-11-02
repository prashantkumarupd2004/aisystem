"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API_URL, api, authHeaders } from "@/lib/api";

type N = { id: number; kind: string; title: string; body: string | null; is_read: boolean; created_at: string };

export default function NotificationsPage() {
  const [items, setItems] = useState<N[]>([]);
  async function load() {
    try { setItems(await api<N[]>("/api/notifications")); } catch {}
  }
  useEffect(() => { load(); }, []);
  async function markAll() {
    await fetch(`${API_URL}/api/notifications/mark-all-read`, { method: "POST", headers: authHeaders() });
    await load();
  }
  return (
    <main className="mx-auto max-w-3xl p-6">
      <Link href="/" className="text-sm text-slate-500">← Dashboard</Link>
      <h1 className="mt-2 text-2xl font-bold">Notifications</h1>
      <button className="mt-4 rounded border bg-white px-4 py-2" onClick={markAll}>Mark all read</button>
      <ul className="mt-4 space-y-2">
        {items.map((n) => (
          <li key={n.id} className="rounded bg-white p-3 shadow">
            <p className="font-semibold">{n.title} {!n.is_read && <span className="text-xs text-red-600">UNREAD</span>}</p>
            <p className="text-sm text-slate-500">{n.body}</p>
            <p className="text-xs text-slate-400">{n.kind} · {n.created_at}</p>
          </li>
        ))}
      </ul>
      {items.length === 0 && <p className="mt-4 text-slate-500">No notifications.</p>}
    </main>
  );
}
