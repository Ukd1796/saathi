"use client";

import Link from "next/link";
import {
  Activity, AlertTriangle, ArrowRight, ClipboardList, HandHeart, PackageX, PhoneCall, PhoneIncoming, PhoneOutgoing,
  Inbox, Rocket, TrendingUp, Trophy, Pill,
} from "lucide-react";
import { ago, useApi } from "@/lib/api";
import { useMe, useSetupProgress } from "@/components/shell";
import { Avatar, Badge, BarChart, Button, Card, EmptyState, HBarList, PageHeader, Skeleton, Stat } from "@/components/ui";

type Overview = {
  visits_today: number; calls_today: number; open_promises: number; overdue_promises: number;
  stock_outs_week: number; needs_review: number;
  reps_today: { id: number; name: string; visits: number }[]; silent_reps: string[];
  recent_calls: { id: string; status: string; rep: string | null; direction: string | null; call_type: string | null;
    duration_s: number | null; note: string | null; visit_id: number | null; created_at: string }[];
  trend: { date: string; visits: number }[];
  leaderboard: { id: number; name: string; visits: number; overdue: number }[];
  open_actions: number;
  top_products: { name: string; count: number }[];
  top_stockouts: { name: string; count: number }[];
};

function callTone(status: string, note: string | null) {
  if (status !== "completed") return "brand" as const;
  if (note === "ok" || note === "briefing") return "good" as const;
  return "warn" as const;
}

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
}

function SetupBanner({ done }: { done: number }) {
  return (
    <div className="mb-6 flex flex-wrap items-center gap-4 rounded-2xl bg-gradient-to-r from-brand to-[#7c3aed] p-5 text-white shadow-lg">
      <span className="flex size-11 items-center justify-center rounded-xl bg-white/15"><Rocket size={22} /></span>
      <div className="min-w-48 flex-1">
        <div className="font-semibold">Finish setting up Saathi: {done} of 3 steps done</div>
        <div className="mt-2 h-1.5 max-w-sm rounded-full bg-white/20"><div className="h-1.5 rounded-full bg-coral" style={{ width: `${(done / 3) * 100}%` }} /></div>
      </div>
      <Link href="/setup"><Button variant="coral" icon={ArrowRight}>Continue setup</Button></Link>
    </div>
  );
}

export default function OverviewPage() {
  const { me } = useMe();
  const { done } = useSetupProgress(me);
  const { data: o } = useApi<Overview>("/overview", 5000);

  const attention = o ? [
    o.open_actions > 0 && { href: "/actions", icon: Inbox, text: `${o.open_actions} action${o.open_actions > 1 ? "s" : ""} waiting: approvals and alerts from calls`, tone: "coral" as const },
    o.overdue_promises > 0 && { href: "/doctors?view=overdue", icon: HandHeart, text: `${o.overdue_promises} promise${o.overdue_promises > 1 ? "s are" : " is"} overdue (7+ days)`, tone: "bad" as const },
    o.silent_reps.length > 0 && { href: "/reps", icon: AlertTriangle, text: `${o.silent_reps.length} rep${o.silent_reps.length > 1 ? "s haven't" : " hasn't"} reported today: ${o.silent_reps.slice(0, 3).join(", ")}${o.silent_reps.length > 3 ? "…" : ""}`, tone: "warn" as const },
  ].filter((x) => !!x) : [];

  return (
    <div>
      <PageHeader title={`${greeting()}, ${me.name.split(" ")[0]}`}
        sub={<>{me.role === "manager" ? "Here's what your team reported today." : "Here's what your field team reported today."} Updates live every 5 seconds.</>} />
      {me.role === "admin" && done < 3 && <SetupBanner done={done} />}

      {!o ? (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-5">{Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-20" />)}</div>
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-5">
            <Stat label="Visits today" value={o.visits_today} icon={ClipboardList} href="/visits" />
            <Stat label="Calls today" value={o.calls_today} icon={PhoneCall} tone="good" />
            <Stat label="Open promises" value={o.open_promises} icon={HandHeart} href="/doctors?view=promises" />
            <Stat label="Overdue promises" value={o.overdue_promises} icon={AlertTriangle} tone={o.overdue_promises ? "bad" : "default"} href="/doctors?view=overdue" />
            <Stat label="Stock-outs, 7 days" value={o.stock_outs_week} icon={PackageX} tone={o.stock_outs_week ? "warn" : "default"} href="/stock-outs" />
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <Card title="Visits, last 14 days" icon={TrendingUp} className="lg:col-span-2"
              action={<span className="text-xs text-muted">{o.trend.reduce((a, d) => a + d.visits, 0)} total</span>}>
              <BarChart data={o.trend.map((d) => {
                const day = new Date(d.date + "T00:00:00");
                return { label: day.toLocaleDateString("en-IN", { day: "numeric" }), hint: day.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" }), value: d.visits };
              })} />
            </Card>
            <Card title="Needs attention" icon={AlertTriangle}>
              {attention.length === 0 ? (
                <div className="py-6 text-center text-sm text-muted"><div className="mb-1 text-2xl">🎉</div>All clear. Nothing needs you right now.</div>
              ) : (
                <ul className="space-y-2">
                  {attention.map((a) => (
                    <li key={a.href}>
                      <Link href={a.href} className="flex items-start gap-3 rounded-xl border border-line p-3 text-sm transition hover:border-brand/40 hover:bg-brand-soft/40">
                        <span className={`mt-0.5 rounded-lg p-1.5 ${a.tone === "coral" ? "bg-coral-soft text-coral" : a.tone === "bad" ? "bg-bad/12 text-bad" : "bg-warn/12 text-warn"}`}><a.icon size={14} /></span>
                        <span className="flex-1 text-ink">{a.text}</span>
                        <ArrowRight size={14} className="mt-1 text-muted" />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>

          <div className="grid gap-6 lg:grid-cols-3">
            <Card title="Live calls" icon={Activity} className="lg:col-span-2" pad={false}
              action={<span className="flex items-center gap-1.5 text-xs text-good"><span className="size-1.5 animate-pulse rounded-full bg-good" />live</span>}>
              {o.recent_calls.length === 0 ? (
                <EmptyState icon={PhoneCall} title="No calls yet">
                  {me.company.phone_number ? <>Call <b>{me.company.phone_number}</b> from a rep&apos;s phone.</> : <>Use <Link href="/reps" className="text-brand underline">Reps → Call now</Link> to have Saathi call you.</>}
                </EmptyState>
              ) : (
                <ul className="divide-y divide-line">
                  {o.recent_calls.map((c) => {
                    const Dir = c.direction === "outbound" ? PhoneOutgoing : PhoneIncoming;
                    const row = (
                      <div className="flex items-center gap-3 px-5 py-3 transition hover:bg-brand-soft/40">
                        <Avatar name={c.rep ?? "?"} size="sm" />
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-semibold text-ink">{c.rep ?? "Unknown caller"}</div>
                          <div className="flex items-center gap-1 text-xs text-muted">
                            <Dir size={12} />{c.direction === "outbound" ? "Saathi called" : "Called in"} · {c.call_type ?? "call"}{c.duration_s ? ` · ${Math.round(c.duration_s)}s` : ""} · {ago(c.created_at)}
                          </div>
                        </div>
                        <Badge tone={callTone(c.status, c.note)}>{c.status === "completed" ? c.note ?? "done" : c.status}</Badge>
                      </div>
                    );
                    return <li key={c.id}>{c.visit_id ? <Link href={`/visits/${c.visit_id}`}>{row}</Link> : row}</li>;
                  })}
                </ul>
              )}
            </Card>
            <Card title="Team this week" icon={Trophy} action={<span className="text-[11px] text-muted">visits · overdue</span>}>
              {o.leaderboard.length === 0 ? <div className="py-6 text-center text-sm text-muted">No reps yet.</div> : (
                <ol className="space-y-2.5">
                  {o.leaderboard.slice(0, 8).map((r, i) => (
                    <li key={r.id} className="flex items-center gap-3 text-sm">
                      <span className={`w-5 text-center text-xs font-bold ${i < 3 && r.visits ? "text-coral" : "text-muted"}`}>{i + 1}</span>
                      <Avatar name={r.name} size="sm" />
                      <span className="flex-1 truncate text-ink">{r.name}</span>
                      <span className="w-8 text-right font-semibold tabular-nums text-ink">{r.visits}</span>
                      <span className={`w-8 text-right tabular-nums ${r.overdue ? "font-semibold text-bad" : "text-muted"}`}>{r.overdue || "–"}</span>
                    </li>
                  ))}
                </ol>
              )}
            </Card>
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            <Card title="Top products discussed, 30 days" icon={Pill}>
              <HBarList items={o.top_products} empty="No products mentioned yet." />
            </Card>
            <Card title="Top stock-outs, 30 days" icon={PackageX} action={<Link href="/stock-outs" className="text-xs font-semibold text-brand">View all</Link>}>
              <HBarList items={o.top_stockouts} tone="coral" empty="No stock-outs reported. Shelves look good." />
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
