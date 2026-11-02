export const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function authHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const token = localStorage.getItem("aisystem_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function api<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  return res.json() as Promise<T>;
}

export type DashboardStats = {
  connected_accounts: number;
  active_accounts: number;
  accounts_needing_attention: number;
  total_videos: number;
  scheduled_reels: number;
  published_reels: number;
  failed_jobs: number;
};

export type AccountSummary = {
  id: number;
  username: string;
  connection_status: string;
  videos: number;
  scheduled: number;
  published: number;
};
