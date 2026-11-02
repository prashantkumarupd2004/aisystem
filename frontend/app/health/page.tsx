"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API_URL, api, authHeaders } from "@/lib/api";

type Summary = {
  total_connected: number; api_accessible: number; disconnected: number;
  expired_tokens: number; revoked_permissions: number; needing_reconnection: number;
  needing_manual_review: number; accounts_with_publishing_errors: number;
  accounts: { id: number; username: string; health_status: string; connection_status: string; detail: string | null; last_api_check_at: string | null; last_published_at: string | null; has_publishing_errors: boolean }[];
};

export default function HealthPage() {
  const [data, setData] = useState<Summary | null>(null);
  const [message, setMessage] = useState("");

  async function load() {
    try { setData(await api<Summary>("/api/health/accounts")); } catch { setMessage("Could not load health. Log in first."); }
  }
  useEffect(() => { load(); }, []);

  async function checkAll() {
    const res = await fetch(`${API_URL}/api/health/check-all`, { method: "POST", headers: authHeaders() });
    const d = await res.json();
    if (!res.ok) { setMessage(`Check failed: ${d.detail || "error"}`); return; }
    setMessage("Live check done for all accounts.");
    await load();
  }

  return (
    <main className="mx-auto max-w-5xl p-6">
      <Link href="/" className="text-sm text-slate-500">← Dashboard</Link>
      <h1 className="mt-2 text-2xl font-bold">Account Health</h1>
      <p className="mt-1 text-sm text-slate-500">API accessible means the last API check succeeded. It is NOT proof an account has no suspension or policy restriction — unconfirmable cases stay UNKNOWN / NEEDS_MANUAL_REVIEW.</p>
      <button className="mt-4 rounded bg-slate-900 px-4 py-2 text-white" onClick={checkAll}>Run live check for all accounts</button>
      {message && <p className="mt-4 rounded bg-white p-3 shadow">{message}</p>}
      {data && (
        <>
          <div className="mt-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
            {[
              ["Connected", data.total_connected], ["API accessible", data.api_accessible],
              ["Disconnected", data.disconnected], ["Expired tokens", data.expired_tokens],
              ["Revoked", data.revoked_permissions], ["Needing reconnection", data.needing_reconnection],
              ["Needing manual review", data.needing_manual_review], ["With publishing errors", data.accounts_with_publishing_errors],
            ].map(([label, value]) => (
              <div key={label as string} className="rounded bg-white p-4 shadow">
                <p className="text-3xl font-bold">{value}</p><p className="text-sm text-slate-500">{label}</p>
              </div>
            ))}
          </div>
          <table className="mt-6 w-full rounded bg-white shadow">
            <thead><tr className="text-left text-sm text-slate-500">
              <th className="p-3">Account</th><th className="p-3">Health</th><th className="p-3">Last API check</th><th className="p-3">Last published</th><th className="p-3">Errors?</th>
            </tr></thead>
            <tbody>{data.accounts.map((a) => (
              <tr key={a.id} className="border-t">
                <td className="p-3">@{a.username}</td><td className="p-3">{a.health_status}</td>
                <td className="p-3">{a.last_api_check_at || "—"}</td><td className="p-3">{a.last_published_at || "—"}</td>
                <td className="p-3">{a.has_publishing_errors ? "Yes" : "No"}</td>
              </tr>
            ))}</tbody>
          </table>
        </>
      )}
    </main>
  );
}
