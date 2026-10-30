"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { AlertTriangle, ListOrdered, Volume2 } from "lucide-react";
import { type CallTrace, useApi, when } from "@/lib/api";
import { OUTCOMES, STAGES } from "@/lib/call-stages";
import { Badge, Card, ErrorNote, PageHeader, Skeleton } from "@/components/ui";

const TURN_TONE: Record<string, "good" | "brand" | "warn" | "bad" | "default"> = {
  recorded: "good", found: "good", complete: "brand", missing: "default", unclear: "warn", asking: "warn",
  flagged: "warn", repeat: "warn", not_found: "bad", error: "bad",
};

export default function CallTracePage() {
  const { id } = useParams<{ id: string }>();
  const { data, error } = useApi<CallTrace>(`/health/calls/${id}`);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <div className="space-y-4"><Skeleton className="h-16 w-80" /><Skeleton className="h-96" /></div>;

  const { call: c, turns, draft } = data;
  const lines = (c.transcript ?? "").split("\n").filter(Boolean);
  const outcome = OUTCOMES[c.outcome];
  return (
    <div>
      <PageHeader crumbs={[{ href: "/call-health", label: "Call health" }]}
        title={<span className="flex flex-wrap items-center gap-3">{c.rep ?? c.rep_phone ?? "Unknown rep"}
          <Badge tone={outcome?.tone ?? "default"}>{outcome?.label ?? c.outcome}</Badge></span>}
        sub={`${when(c.at)} · ${c.direction ?? "call"}${c.duration_s ? ` · ${Math.round(c.duration_s)} s` : ""}${c.ended_by ? ` · ended: ${c.ended_by}` : ""}`}
        action={c.visit_id ? <Link href={`/visits/${c.visit_id}`} className="inline-flex h-9 items-center rounded-xl border border-line bg-card px-3.5 text-sm font-semibold text-ink hover:text-brand">Open visit</Link> : undefined} />

      {(c.failure_stage || c.warnings.length > 0) && (
        <div className="mb-6 space-y-1 rounded-2xl border border-bad/30 bg-bad/5 px-4 py-3 text-sm">
          {c.failure_stage && <div className="flex items-start gap-2 text-ink"><AlertTriangle size={16} className="mt-0.5 shrink-0 text-bad" />
            <span><span className="font-semibold">Failed at {STAGES[c.failure_stage]?.label ?? c.failure_stage}:</span> {c.failure_reason}</span></div>}
          {c.warnings.map((w) => <div key={w} className="pl-6 text-xs text-warn">{w}</div>)}
          {c.process_note && <div className="pl-6 text-xs text-muted">Pipeline: {c.process_note}</div>}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-5">
        <Card title={`Tool turns · ${turns.length}`} icon={ListOrdered} className="lg:col-span-3">
          {turns.length === 0 ? <p className="text-sm text-muted">No tool ran on this call.</p> : (
            <ol className="space-y-3">
              {turns.map((t, i) => (
                <li key={i} className="rounded-xl border border-line p-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="font-semibold text-muted">#{i + 1}</span>
                    <code className="text-ink">{t.tool}</code>
                    <Badge tone={TURN_TONE[t.status] ?? "default"}>{t.status}</Badge>
                    {t.asked && <span className="text-muted">asked: <code>{t.asked}</code></span>}
                    <span className="ml-auto tabular-nums text-muted">{t.ms != null ? `${t.ms} ms` : ""}</span>
                  </div>
                  {t.mr_said && <div className="mt-2 text-xs text-muted">Rep: &ldquo;{t.mr_said}&rdquo;</div>}
                  {t.say && <div className="mt-1 text-ink">Saathi: {t.say}</div>}
                  {t.error && <div className="mt-1 font-mono text-xs text-bad">{t.error}</div>}
                  <details className="mt-1">
                    <summary className="cursor-pointer text-[11px] text-muted">what the agent sent</summary>
                    <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-soft p-2 font-mono text-[11px]">{JSON.stringify(t.params, null, 2)}</pre>
                  </details>
                </li>
              ))}
            </ol>
          )}
          {draft && (
            <details className="mt-4">
              <summary className="cursor-pointer text-xs font-semibold text-muted">Draft: {draft.confirmed ? "confirmed by the rep" : "not confirmed"}</summary>
              <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-soft p-2 font-mono text-[11px]">{JSON.stringify(draft, null, 2)}</pre>
            </details>
          )}
        </Card>

        <Card title="Transcript" icon={Volume2} className="lg:col-span-2">
          {c.recording_url && <audio controls src={c.recording_url} className="mb-4 w-full" />}
          <div className="max-h-[40rem] space-y-2.5 overflow-auto pr-1">
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
  );
}
