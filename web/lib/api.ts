"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const res = await fetch(`/api${path}`, {
    credentials: "same-origin",
    ...rest,
    headers: json !== undefined ? { "Content-Type": "application/json", ...headers } : headers,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const data = await res.json();
      message = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data);
    } catch {}
    throw new ApiError(res.status, message);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

/** Fetch a GET endpoint, optionally re-polling every `pollMs`. `reload()` refetches now. */
export function useApi<T>(path: string | null, pollMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const alive = useRef(true);

  const reload = useCallback(async () => {
    if (!path) return;
    try {
      const d = await api<T>(path);
      if (alive.current) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (alive.current) setError(e as ApiError);
    } finally {
      if (alive.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    alive.current = true;
    // Subscribing to the backend: reload() only sets state after its fetch resolves.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    reload();
    if (!pollMs) return () => void (alive.current = false);
    const id = setInterval(reload, pollMs);
    return () => {
      alive.current = false;
      clearInterval(id);
    };
  }, [reload, pollMs]);

  return { data, error, loading, reload, setData };
}

export function ago(iso: string | null | undefined) {
  if (!iso) return "–";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  const d = Math.floor(s / 86400);
  return d === 1 ? "yesterday" : `${d} days ago`;
}

export function when(iso: string | null | undefined) {
  if (!iso) return "–";
  return new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export type Me = {
  id: number;
  name: string;
  email: string;
  role: "admin" | "manager";
  phone: string | null;
  team_size: number | null;
  company: { id: number; name: string; agent_id: string | null; phone_number: string | null; sweep_time: string | null;
    auto_followup: boolean; followup_time: string };
};

export type ActionItem = { id: string; action_id?: number; promise_id?: number; kind: "stockout" | "material" | "overdue";
  status: string; title: string; detail: string | null; rep: string | null; doctor: string | null; doctor_id: number | null;
  visit_id: number | null; created_at: string; resolved_at: string | null };

export type UserRow = { id: number; name: string; email: string; role: "admin" | "manager"; rep_ids: number[] };

export type Item = { product: string; qty: number | null; matched: boolean };
export type Visit = {
  id: number;
  call_id: string;
  visited_at: string;
  rep: string | null;
  rep_id: number | null;
  doctor: string | null;
  doctor_id: number | null;
  doctor_heard: string | null;
  area: string | null;
  products_discussed: string[];
  samples: Item[];
  orders: Item[];
  chemist: string | null;
  chemist_matched: boolean;
  stock_outs: string[];
  promises: { id: number; text: string; status: string; due_on?: string | null }[];
  followup?: { run_on: string; time: string; active: boolean; result: string | null } | null;
  feedback: string | null;
  next_visit: string | null;
  unmatched: { kind: string; heard: string; suggestion: string | null }[];
  call?: { duration_s: number | null; transcript: string | null; direction: string | null; extracted: unknown;
    cost: number | null; recording_url: string | null };
  quality?: { duration_s: number | null; rep_turns: number; reasks: number; ended_by: string | null;
    names: { kind: string | null; heard: string | null; best: string | null; confidence: string | null }[] };
};

/** Download rows as a CSV file (opens in Excel). */
export function downloadCsv(filename: string, rows: (string | number | null | undefined)[][]) {
  const esc = (v: string | number | null | undefined) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const blob = new Blob(["\ufeff" + rows.map((r) => r.map(esc).join(",")).join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}

/** Local YYYY-MM-DD, `daysAgo` days before today. */
export function isoDay(daysAgo = 0) {
  const d = new Date();
  d.setDate(d.getDate() - daysAgo);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function mask(phone: string | null | undefined) {
  if (!phone) return "–";
  return phone.length > 6 ? `${phone.slice(0, 3)} ••••• ${phone.slice(-4)}` : phone;
}

export type Agent = {
  agent_id: string | null; synced_at: string | null; phone_number: string | null; sweep_time: string | null;
  public_base_url: string; localhost_warning: boolean; prompt: string; keywords: string; welcome: string; extractions: string[];
};
