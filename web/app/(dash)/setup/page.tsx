"use client";

import Link from "next/link";
import { ArrowRight, Bot, Check, Database, Phone, PhoneCall, Sparkles, TriangleAlert } from "lucide-react";
import { useState, type ReactNode } from "react";
import { type Agent, api, type ApiError, useApi } from "@/lib/api";
import { useMe, useSetupProgress } from "@/components/shell";
import { useToast } from "@/components/toast";
import { Badge, Button, PageHeader } from "@/components/ui";
import { NumberPicker } from "../settings/number-picker";

function Step({ n, done, active, title, sub, children }: { n: number; done: boolean; active: boolean; title: string; sub: string; children: ReactNode }) {
  return (
    <div className={`relative rounded-2xl border bg-card p-5 transition md:p-6 ${active ? "border-brand shadow-lg shadow-brand/10" : "border-line"}`}>
      <div className="flex items-start gap-4">
        <span className={`flex size-10 shrink-0 items-center justify-center rounded-full text-sm font-bold ${done ? "bg-good text-white" : active ? "bg-brand text-white" : "bg-soft text-muted"}`}>
          {done ? <Check size={18} /> : n}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-semibold text-ink">{title}</h2>
            {done ? <Badge tone="good">done</Badge> : active ? <Badge tone="brand">next</Badge> : null}
          </div>
          <p className="mt-0.5 text-sm text-muted">{sub}</p>
          <div className="mt-4">{children}</div>
        </div>
      </div>
    </div>
  );
}

export default function SetupPage() {
  const toast = useToast();
  const { me, reload: reloadMe } = useMe();
  const { counts: c, steps, done, reload: reloadCounts } = useSetupProgress(me);
  const agent = useApi<Agent>("/agent");
  const [busy, setBusy] = useState<string | null>(null);
  const next = steps.indexOf(false);

  async function run(label: string, fn: () => Promise<unknown>, ok: string) {
    setBusy(label);
    try {
      await fn();
      toast(ok);
      reloadCounts();
      agent.reload();
      reloadMe();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    } finally {
      setBusy(null);
    }
  }
  const a = agent.data;

  return (
    <div className="max-w-3xl">
      <PageHeader title="Set up Saathi" sub="Three steps and your reps can start reporting visits by phone." />
      <div className="mb-6 rounded-2xl bg-card p-4">
        <div className="mb-2 flex justify-between text-xs font-semibold"><span className="text-ink">{done} of 3 complete</span><span className="text-muted">{Math.round((done / 3) * 100)}%</span></div>
        <div className="h-2 rounded-full bg-soft"><div className="h-2 rounded-full bg-gradient-to-r from-brand to-coral transition-all" style={{ width: `${(done / 3) * 100}%` }} /></div>
      </div>

      <div className="space-y-4">
        <Step n={1} done={steps[0]} active={next === 0} title="Add your field data"
          sub="Reps, products, doctors and chemists. Saathi checks every name a rep says against these lists.">
          {c && (
            <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {(["reps", "products", "doctors", "chemists"] as const).map((k) => (
                <div key={k} className="rounded-xl bg-soft px-3 py-2"><div className="text-lg font-bold tabular-nums text-ink">{c[k]}</div><div className="text-xs capitalize text-muted">{k}</div></div>
              ))}
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <Link href="/data"><Button icon={Database}>Upload your CSVs</Button></Link>
            <Button variant="secondary" icon={Sparkles} disabled={!!busy}
              onClick={() => run("demo", () => api("/data/demo", { method: "POST" }), "Demo data loaded: 20 products, 10 doctors and 6 chemists in Pune.")}>
              {busy === "demo" ? "Loading…" : "Use Pune demo data"}
            </Button>
          </div>
          {me.phone && <p className="mt-2 text-xs text-muted">The demo makes you the first rep, so you can test calls from your own phone.</p>}
        </Step>

        <Step n={2} done={steps[1]} active={next === 1} title="Create your voice agent"
          sub={`A Bolna agent just for ${me.company.name}, in Hinglish or English. It takes the call step by step, checks every doctor, chemist and product name against your lists while the rep talks, reads the whole visit back, and saves only what the rep confirmed. It also gives doctor briefings.`}>
          {a?.localhost_warning && (
            <div className="mb-3 flex gap-2 rounded-xl bg-warn/10 px-3 py-2 text-sm text-warn">
              <TriangleAlert size={16} className="mt-0.5 shrink-0" />
              <span>The backend address is {a.public_base_url}, which Bolna can&apos;t reach. Start a tunnel or deploy, set PUBLIC_BASE_URL, then create or re-sync.</span>
            </div>
          )}
          {a?.agent_id ? (
            <div className="flex flex-wrap items-center gap-3">
              <Badge tone="good"><Bot size={12} />Agent live</Badge>
              <Link href="/settings" className="text-sm font-semibold text-brand">Manage in Settings <ArrowRight size={13} className="inline" /></Link>
            </div>
          ) : (
            <>
              <Button icon={Bot} disabled={!steps[0] || !!busy}
                onClick={() => run("create", () => api("/agent/create", { method: "POST" }), "Your voice agent is live.")}>
                {busy === "create" ? "Creating…" : "Create voice agent"}
              </Button>
              {!steps[0] && <p className="mt-2 text-xs text-muted">Add reps and products first.</p>}
            </>
          )}
        </Step>

        <Step n={3} done={steps[2]} active={next === 2} title="Connect a number and make a test call"
          sub="Link a Bolna phone number so reps can call in. No number yet? Have Saathi call you instead.">
          {!a?.agent_id ? <p className="text-sm text-muted">Create the agent first.</p> : (
            <div className="space-y-4">
              <NumberPicker linked={a.phone_number} onLinked={() => { agent.reload(); reloadMe(); }} />
              <div className="rounded-xl bg-brand-soft p-4 text-sm">
                <div className="flex items-center gap-2 font-semibold text-ink"><PhoneCall size={15} className="text-brand" />Try it now</div>
                <p className="mt-1 text-muted">
                  {a.phone_number ? <>Call <b className="text-ink">{a.phone_number}</b> from your phone</> : <>Open <b className="text-ink">Reps</b> and press <b className="text-ink">Call now</b> on yourself</>}, then say:
                  <i className="mt-1 block text-ink">&ldquo;Dr Patil se mil ke aaya, Hadapsar mein. Telma 40 ke 4 strip diye…&rdquo;</i>
                  <span className="mt-0.5 block text-xs">(&ldquo;Just met Dr Patil in Hadapsar. Gave 4 strips of Telma 40…&rdquo;)</span>
                </p>
                <Link href="/reps" className="mt-3 inline-block"><Button size="sm" icon={Phone}>Go to Reps</Button></Link>
              </div>
            </div>
          )}
        </Step>
      </div>
    </div>
  );
}
