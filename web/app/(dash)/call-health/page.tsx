"use client";

import Link from "next/link";
import { Activity } from "lucide-react";
import { useMemo, useState } from "react";
import { type CallHealth, useApi, when } from "@/lib/api";
import { OUTCOMES, STAGES } from "@/lib/call-stages";
import { Avatar, Badge, Card, EmptyState, LoadingRows, PageHeader, Table, Tabs, Td, Tr } from "@/components/ui";

type Range = "1" | "7" | "30";
const RANGES: { value: Range; label: string }[] = [{ value: "1", label: "Today" }, { value: "7", label: "7 days" }, { value: "30", label: "30 days" }];

export default function CallHealthPage() {
  const [days, setDays] = useState<Range>("7");
  const [stage, setStage] = useState<string>("");
  const [all, setAll] = useState(false);
  const { data } = useApi<CallHealth>(`/health/calls?days=${days}`, 15000);

  const rows = useMemo(() => (data?.calls ?? []).filter((c) =>
    stage ? c.failure_stage === stage : all || c.outcome === "failed"), [data, stage, all]);
  const total = data?.calls.length ?? 0;
  const failed = data?.outcomes.failed ?? 0;

  return (
    <div>
      <PageHeader title="Call health" sub="Where Saathi's calls go wrong: every failed call, the step it failed at, and why."
        action={<Tabs value={days} onChange={setDays} options={RANGES} />} />

      <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-2xl border border-line bg-card p-4">
          <div className="text-2xl font-bold tabular-nums text-ink">{total ? Math.round(((total - failed) / total) * 100) : 0}%</div>
          <div className="text-xs text-muted">calls that worked ({total - failed} of {total})</div>
        </div>
        {(["recorded", "briefing", "stopped"] as const).map((k) => (
          <div key={k} className="rounded-2xl border border-line bg-card p-4">
            <div className="text-2xl font-bold tabular-nums text-ink">{data?.outcomes[k] ?? 0}</div>
            <div className="text-xs text-muted">{OUTCOMES[k].label.toLowerCase()}</div>
          </div>
        ))}
      </div>

      <Card title={`Failures by step${failed ? ` · ${failed}` : ""}`} icon={Activity} className="mb-6">
        {!data ? <LoadingRows rows={2} /> : failed === 0 ? <p className="text-sm text-muted">No failed calls in this period.</p> : (
          <div className="flex flex-wrap gap-2">
            {Object.entries(STAGES).filter(([k]) => data.stages[k]).sort(([a], [b]) => data.stages[b] - data.stages[a]).map(([k, s]) => (
              <button key={k} onClick={() => setStage(stage === k ? "" : k)} title={s.hint}
                className={`rounded-xl border px-3 py-2 text-left transition ${stage === k ? "border-brand bg-brand-soft" : "border-line bg-card hover:border-brand"}`}>
                <div className="text-lg font-bold tabular-nums text-ink">{data.stages[k]}</div>
                <div className="text-xs font-semibold text-ink">{s.label}</div>
                <div className="max-w-48 text-[11px] text-muted">{s.hint}</div>
              </button>
            ))}
          </div>
        )}
      </Card>

      <Card pad={false}>
        <div className="flex flex-wrap items-center gap-3 border-b border-line p-4">
          <Tabs value={all ? "all" : "failed"} onChange={(v) => { setAll(v === "all"); setStage(""); }}
            options={[{ value: "failed", label: "Failed", count: failed }, { value: "all", label: "All calls", count: total }]} />
          {stage && <Badge tone="brand">{STAGES[stage]?.label ?? stage} <button onClick={() => setStage("")} className="ml-1">×</button></Badge>}
        </div>
        {!data ? <LoadingRows /> : rows.length === 0 ? (
          <EmptyState icon={Activity} title={all ? "No calls yet" : "No failed calls"}>
            Each call is checked when it ends. A failed one shows here with the step it broke at.
          </EmptyState>
        ) : (
          <>
            <div className="hidden md:block">
              <Table head={["When", "Rep", "Outcome", "Step", "Why", "Length"]}>
                {rows.map((c) => (
                  <Tr key={c.id} href={`/call-health/${c.id}`}>
                    <Td className="whitespace-nowrap text-muted">{when(c.at)}</Td>
                    <Td><span className="flex items-center gap-2 whitespace-nowrap"><Avatar name={c.rep ?? "?"} size="sm" />{c.rep ?? c.rep_phone ?? "–"}</span></Td>
                    <Td><Badge tone={OUTCOMES[c.outcome]?.tone ?? "default"}>{OUTCOMES[c.outcome]?.label ?? c.outcome}</Badge></Td>
                    <Td className="whitespace-nowrap">{c.failure_stage ? STAGES[c.failure_stage]?.label ?? c.failure_stage : <span className="text-muted">–</span>}</Td>
                    <Td className="max-w-md text-xs text-muted">
                      {c.failure_reason ?? "–"}
                      {c.warnings.length > 0 && <div className="mt-0.5 text-warn">{c.warnings.join(" · ")}</div>}
                    </Td>
                    <Td className="whitespace-nowrap text-muted tabular-nums">{c.duration_s ? `${Math.round(c.duration_s)} s` : "–"}</Td>
                  </Tr>
                ))}
              </Table>
            </div>
            <ul className="divide-y divide-line md:hidden">
              {rows.map((c) => (
                <li key={c.id}>
                  <Link href={`/call-health/${c.id}`} className="block space-y-1 px-4 py-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold text-ink">{c.rep ?? c.rep_phone ?? "Unknown rep"}</span>
                      <Badge tone={OUTCOMES[c.outcome]?.tone ?? "default"}>{c.failure_stage ? STAGES[c.failure_stage]?.label : OUTCOMES[c.outcome]?.label}</Badge>
                    </div>
                    <div className="text-xs text-muted">{when(c.at)}{c.failure_reason ? ` · ${c.failure_reason}` : ""}</div>
                  </Link>
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>
    </div>
  );
}
