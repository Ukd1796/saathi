"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { AlertTriangle, CalendarClock, Check, CircleHelp, Gauge, RotateCcw, HandHeart, MessageSquareQuote, MessagesSquare, Package, PackageX, Pill, ShoppingCart, Store, Volume2 } from "lucide-react";
import type { ReactNode } from "react";
import { useApi, when, type Visit } from "@/lib/api";
import { DoctorCell, Items } from "@/components/visit-bits";
import { Avatar, Badge, Card, ErrorNote, PageHeader, Skeleton } from "@/components/ui";
import type { LucideIcon } from "lucide-react";

function Row({ icon: Icon, label, children }: { icon: LucideIcon; label: string; children: ReactNode }) {
  return (
    <div className="flex gap-3 py-3">
      <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand"><Icon size={15} /></span>
      <div className="min-w-0 flex-1">
        <div className="text-xs font-semibold uppercase tracking-wide text-muted">{label}</div>
        <div className="mt-1 text-sm text-ink">{children}</div>
      </div>
    </div>
  );
}

function Chip({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className={`rounded-xl px-4 py-2.5 ${tone}`}>
      <div className="text-lg font-bold tabular-nums">{value}</div>
      <div className="text-xs font-medium opacity-80">{label}</div>
    </div>
  );
}

const OUTCOME = {
  high: { icon: Check, label: "understood", tone: "text-good" },
  medium: { icon: CircleHelp, label: "confirmed with rep", tone: "text-warn" },
  low: { icon: RotateCcw, label: "asked again", tone: "text-coral" },
} as const;

/** How hard the call was: the names Saathi checked and how sure it was, plus re-asks and length. */
function CallQuality({ q }: { q: NonNullable<Visit["quality"]> }) {
  const names = q.names.filter((n) => n.heard);
  return (
    <Card title="Call quality" icon={Gauge}>
      <div className="grid grid-cols-3 gap-2 text-center">
        {[["Length", q.duration_s ? `${Math.round(q.duration_s)}s` : "–"], ["Rep turns", q.rep_turns], ["Asked again", q.reasks]].map(([k, val]) => (
          <div key={k} className="rounded-xl bg-soft py-2"><div className="text-lg font-bold tabular-nums text-ink">{val}</div><div className="text-[11px] text-muted">{k}</div></div>
        ))}
      </div>
      {names.length > 0 && (
        <ul className="mt-4 space-y-1.5 text-sm">
          {names.map((n, i) => {
            const o = OUTCOME[(n.confidence as keyof typeof OUTCOME) ?? "low"] ?? OUTCOME.low;
            return (
              <li key={i} className="flex items-center gap-2">
                <o.icon size={14} className={`shrink-0 ${o.tone}`} />
                <span className="truncate text-muted">&ldquo;{n.heard}&rdquo;</span>
                <span className="text-muted">→</span>
                <span className="truncate font-medium text-ink">{n.best ?? "?"}</span>
                <span className={`ml-auto whitespace-nowrap text-[11px] ${o.tone}`}>{o.label}</span>
              </li>
            );
          })}
        </ul>
      )}
      {names.length === 0 && <p className="mt-3 text-xs text-muted">No names needed checking on this call.</p>}
    </Card>
  );
}

export default function VisitPage() {
  const { id } = useParams<{ id: string }>();
  const { data: v, error } = useApi<Visit>(`/visits/${id}`);
  if (error) return <ErrorNote error={error} />;
  if (!v) return <div className="space-y-4"><Skeleton className="h-16 w-80" /><Skeleton className="h-96" /></div>;

  const lines = (v.call?.transcript ?? "").split("\n").filter(Boolean);
  const sampleQty = v.samples.reduce((a, i) => a + (i.qty ?? 0), 0);
  return (
    <div>
      <PageHeader crumbs={[{ href: "/visits", label: "Visits" }]}
        title={<span className="flex items-center gap-3"><Avatar name={v.doctor ?? v.doctor_heard ?? "?"} size="lg" />{v.doctor ?? `? ${v.doctor_heard}`}</span>}
        sub={`${when(v.visited_at)} · reported by ${v.rep ?? "unknown rep"}${v.area ? ` · ${v.area}` : ""}`}
        action={<>
          {v.doctor_id && <Link href={`/doctors/${v.doctor_id}`} className="inline-flex h-9 items-center rounded-xl border border-line bg-card px-3.5 text-sm font-semibold text-ink hover:text-brand">Doctor history</Link>}
        </>} />

      <div className="mb-6 flex flex-wrap gap-3">
        <Chip label="samples given" value={sampleQty} tone="bg-brand-soft text-brand" />
        <Chip label="products ordered" value={v.orders.length} tone="bg-good/12 text-good" />
        <Chip label="stock-outs" value={v.stock_outs.length} tone="bg-coral-soft text-coral" />
        <Chip label="promises" value={v.promises.length} tone="bg-warn/12 text-warn" />
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        <Card title="Visit report" icon={Package} className="lg:col-span-3">
          <div className="divide-y divide-line">
            <Row icon={Pill} label="Doctor"><DoctorCell v={v} /></Row>
            <Row icon={MessagesSquare} label="Products discussed">
              {v.products_discussed.length ? <span className="flex flex-wrap gap-1">{v.products_discussed.map((p) => <Badge key={p} tone="brand">{p}</Badge>)}</span> : <span className="text-muted">–</span>}
            </Row>
            <Row icon={Package} label="Samples"><Items items={v.samples} /></Row>
            <Row icon={ShoppingCart} label="Orders"><Items items={v.orders} /></Row>
            <Row icon={Store} label="Chemist">{v.chemist ?? <span className="text-muted">–</span>} {v.chemist && !v.chemist_matched && <Badge tone="warn">not matched</Badge>}</Row>
            <Row icon={PackageX} label="Stock-outs">
              {v.stock_outs.length ? <span className="flex flex-wrap gap-1">{v.stock_outs.map((s) => <Badge key={s} tone="coral">{s}</Badge>)}</span> : <span className="text-muted">–</span>}
            </Row>
            <Row icon={MessageSquareQuote} label="Doctor's feedback">{v.feedback ? <span className="italic">&ldquo;{v.feedback}&rdquo;</span> : <span className="text-muted">–</span>}</Row>
            <Row icon={HandHeart} label="Promises">
              {v.promises.length ? <ul className="space-y-1">{v.promises.map((p) => <li key={p.id} className="flex items-start gap-2">{p.text} <Badge tone={p.status === "done" ? "good" : "warn"}>{p.status}</Badge></li>)}</ul> : <span className="text-muted">–</span>}
            </Row>
            <Row icon={CalendarClock} label="Next visit">{v.next_visit ?? <span className="text-muted">–</span>}</Row>
            {v.unmatched.length > 0 && (
              <Row icon={AlertTriangle} label="Not on your lists">
                <ul className="space-y-1">{v.unmatched.map((u) => <li key={u.kind + u.heard}><Badge tone="coral">{u.kind}</Badge> &ldquo;{u.heard}&rdquo;{u.suggestion && <span className="text-muted">: maybe {u.suggestion}</span>}</li>)}</ul>
              </Row>
            )}
          </div>
        </Card>

        <div className="space-y-6 lg:col-span-2">
        {v.quality && <CallQuality q={v.quality} />}
        <Card title={`Call${v.call?.duration_s ? ` · ${Math.round(v.call.duration_s)} s` : ""}`} icon={Volume2}>
          {v.call?.recording_url && <audio controls src={v.call.recording_url} className="mb-4 w-full" />}
          <div className="max-h-[36rem] space-y-2.5 overflow-auto pr-1">
            {lines.length === 0 ? <div className="text-sm text-muted">No transcript.</div> : lines.map((line, i) => {
              const agent = line.startsWith("assistant:");
              return (
                <div key={i} className={`flex ${agent ? "justify-start" : "justify-end"}`}>
                  <div className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-sm ${agent ? "rounded-tl-sm bg-brand-soft text-ink" : "rounded-tr-sm bg-brand text-white"}`}>
                    <div className={`mb-0.5 text-[10px] font-bold uppercase tracking-wide ${agent ? "text-brand" : "text-white/70"}`}>{agent ? "Saathi" : "Rep"}</div>
                    {line.replace(/^(assistant|user):\s*/, "")}
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
        </div>
      </div>
    </div>
  );
}
