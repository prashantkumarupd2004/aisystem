"use client";

import { useState } from "react";
import { API_URL } from "@/lib/api";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    const form = new URLSearchParams({ username: email, password });
    const res = await fetch(`${API_URL}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form,
    });
    if (!res.ok) {
      setError("Invalid credentials. Check ADMIN_EMAIL / ADMIN_PASSWORD in the backend .env.");
      return;
    }
    const data = await res.json();
    localStorage.setItem("aisystem_token", data.access_token);
    window.location.href = "/";
  }

  return (
    <main className="mx-auto mt-24 max-w-sm rounded bg-white p-6 shadow">
      <h1 className="text-xl font-bold">Admin login</h1>
      <p className="mt-1 text-sm text-slate-500">First admin is created from ADMIN_EMAIL / ADMIN_PASSWORD on backend startup.</p>
      <form onSubmit={submit} className="mt-4 space-y-3">
        <input className="w-full rounded border p-2" placeholder="Admin email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <input className="w-full rounded border p-2" placeholder="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        {error && <p className="text-sm text-red-700">{error}</p>}
        <button className="w-full rounded bg-slate-900 p-2 text-white" type="submit">Log in</button>
      </form>
    </main>
  );
}
