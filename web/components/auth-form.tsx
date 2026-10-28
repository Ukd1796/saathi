"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { AudioLines, CheckCircle2 } from "lucide-react";
import { useState } from "react";
import { api, type ApiError } from "@/lib/api";
import { Button, ErrorNote, Input, Label } from "@/components/ui";

const POINTS = [
  "Reps report visits by phone, in Hinglish",
  "Names checked against your own lists",
  "Promises, samples and stock-outs per doctor",
];

export function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const router = useRouter();
  const next = useSearchParams().get("next");
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = Object.fromEntries(new FormData(e.currentTarget));
    setBusy(true);
    setError(null);
    try {
      await api(`/auth/${mode}`, { method: "POST", json: form });
      router.replace(mode === "signup" ? "/setup" : next || "/overview");
    } catch (err) {
      setError(err as ApiError);
      setBusy(false);
    }
  }

  return (
    <main className="grid min-h-screen lg:grid-cols-2">
      <div className="relative hidden overflow-hidden bg-gradient-to-br from-[#1e1b4b] via-brand to-[#7c3aed] p-12 text-white lg:flex lg:flex-col">
        <div className="pointer-events-none absolute -right-24 -top-24 size-96 rounded-full bg-coral/40 blur-3xl" />
        <Link href="/" className="relative flex items-center gap-2 text-lg font-bold">
          <span className="flex size-8 items-center justify-center rounded-xl bg-white/15"><AudioLines size={17} /></span>Saathi
        </Link>
        <div className="relative mt-auto">
          <h2 className="text-3xl font-extrabold leading-tight">The medical rep&apos;s memory,<br /><span className="text-coral">on any phone.</span></h2>
          <ul className="mt-6 space-y-3">
            {POINTS.map((p) => <li key={p} className="flex items-center gap-2 text-white/85"><CheckCircle2 size={18} className="text-coral" />{p}</li>)}
          </ul>
        </div>
      </div>

      <div className="flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-sm">
          <Link href="/" className="mb-8 flex items-center gap-2 text-lg font-bold text-brand lg:hidden"><AudioLines size={20} />Saathi</Link>
          <h1 className="text-2xl font-bold tracking-tight text-ink">{mode === "signup" ? "Set up your company" : "Welcome back"}</h1>
          <p className="mt-1 text-sm text-muted">{mode === "signup" ? "Free to try. Your voice agent is ready in minutes." : "Log in to your Saathi dashboard."}</p>
          <form onSubmit={submit} className="mt-8 space-y-4">
            <ErrorNote error={error} />
            {mode === "signup" && (
              <>
                <Label text="Company name"><Input name="company_name" placeholder="Sahyadri Pharma" required /></Label>
                <Label text="Your name"><Input name="name" placeholder="Asha Patil" required /></Label>
                <Label text="Your mobile (optional)"><Input name="phone" placeholder="For test calls from your phone" inputMode="tel" /></Label>
              </>
            )}
            <Label text="Work email"><Input name="email" type="email" placeholder="you@company.com" required autoComplete="email" /></Label>
            <Label text="Password"><Input name="password" type="password" placeholder={mode === "signup" ? "8+ characters" : "••••••••"} required
              autoComplete={mode === "signup" ? "new-password" : "current-password"} /></Label>
            <Button disabled={busy} className="h-11 w-full">{busy ? "Please wait…" : mode === "signup" ? "Create account" : "Log in"}</Button>
          </form>
          <p className="mt-6 text-center text-sm text-muted">
            {mode === "signup" ? <>Already have an account? <Link href="/login" className="font-semibold text-brand">Log in</Link></>
              : <>New to Saathi? <Link href="/signup" className="font-semibold text-brand">Set up your company</Link></>}
          </p>
        </div>
      </div>
    </main>
  );
}
