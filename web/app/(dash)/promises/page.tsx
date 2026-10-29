"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Check, HandHeart, RotateCcw, UserRound } from "lucide-react";
import { useMemo, useState } from "react";
import { api, type ApiError, ago, useApi } from "@/lib/api";
import { useToast } from "@/components/toast";
import { Avatar, Badge, Button, Card, EmptyState, LoadingRows, PageHeader, SearchInput, FilterSelect, Table, Tabs, Td, Tr } from "@/components/ui";

type PromiseRow = { id: number; text: string; status: string; created_at: string; closed_at: string | null; age_days: number;
  overdue: boolean; doctor: string | null; doctor_id: number | null; rep: string | null; visit_id: number };
type Tab = "open" | "overdue" | "done" | "all";

export default function PromisesPage() {
  const toast = useToast();
  const initial = useSearchParams().get("tab") as Tab | null;
  const [tab, setTab] = useState<Tab>(initial ?? "open");
  const [q, setQ] = useState("");
  const [rep, setRep] = useState("");
  const { data, reload } = useApi<PromiseRow[]>("/promises?status=all");

  const counts = useMemo(() => {
    const d = data ?? [];
    return { open: d.filter((p) => p.status === "open").length, overdue: d.filter((p) => p.overdue && p.status === "open").length,
      done: d.filter((p) => p.status === "done").length, all: d.length };
  }, [data]);
  const reps = useMemo(() => [...new Set((data ?? []).map((p) => p.rep).filter(Boolean))].sort() as string[], [data]);
  const rows = (data ?? []).filter((p) => {
    if (tab === "open" && p.status !== "open") return false;
    if (tab === "overdue" && !(p.overdue && p.status === "open")) return false;
    if (tab === "done" && p.status !== "done") return false;
    if (rep && p.rep !== rep) return false;
    const needle = q.trim().toLowerCase();
    return !needle || `${p.text} ${p.doctor ?? ""}`.toLowerCase().includes(needle);
  });

  async function set(p: PromiseRow, status: string) {
    try {
      await api(`/promises/${p.id}`, { method: "PATCH", json: { status } });
      toast(status === "done" ? "Promise marked as done." : "Promise reopened.");
      reload();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }

  return (
    <div>
      <PageHeader title="Promises to doctors"
        sub="Studies, samples and call-backs your reps promised. Open for more than 7 days counts as overdue, and Saathi reminds the rep in their next briefing." />
      <Card pad={false}>
        <div className="flex flex-wrap items-center gap-3 border-b border-line p-4">
          <Tabs value={tab} onChange={setTab} options={[
            { value: "open", label: "Open", count: counts.open }, { value: "overdue", label: "Overdue", count: counts.overdue },
            { value: "done", label: "Done", count: counts.done }, { value: "all", label: "All", count: counts.all },
          ]} />
          <SearchInput value={q} onChange={setQ} placeholder="Search promise or doctor…" className="min-w-52 flex-1" />
          <FilterSelect label="Rep" icon={UserRound} value={rep} onChange={setRep} options={reps} />
        </div>
        {!data ? <LoadingRows /> : rows.length === 0 ? (
          <EmptyState icon={HandHeart} title={tab === "overdue" ? "Nothing overdue" : "No promises here"}>
            {tab === "overdue" ? "Every promise is within 7 days. Nice work." : "When a rep says “I'll bring the study next week”, it appears here."}
          </EmptyState>
        ) : (
          <Table head={["Promise", "Doctor", "Rep", "Age", ""]}>
            {rows.map((p) => (
              <Tr key={p.id}>
                <Td className="min-w-64">
                  <div className="font-medium text-ink">{p.text}</div>
                  <div className="mt-1 flex gap-1">
                    {p.status === "done" ? <Badge tone="good">done</Badge> : p.overdue ? <Badge tone="bad">overdue</Badge> : <Badge tone="warn">open</Badge>}
                    <Link href={`/visits/${p.visit_id}`} className="text-xs text-muted hover:text-brand">from visit</Link>
                  </div>
                </Td>
                <Td className="whitespace-nowrap">{p.doctor_id ? <Link href={`/doctors/${p.doctor_id}`} className="font-medium hover:text-brand">{p.doctor}</Link> : p.doctor ?? "–"}</Td>
                <Td><span className="flex items-center gap-2 whitespace-nowrap"><Avatar name={p.rep ?? "?"} size="sm" />{p.rep ?? "–"}</span></Td>
                <Td className={`whitespace-nowrap tabular-nums ${p.overdue && p.status === "open" ? "font-semibold text-bad" : "text-muted"}`}>{ago(p.created_at)}</Td>
                <Td className="text-right">
                  {p.status === "open" ? <Button size="sm" variant="secondary" icon={Check} onClick={() => set(p, "done")}>Mark done</Button>
                    : <Button size="sm" variant="ghost" icon={RotateCcw} onClick={() => set(p, "open")}>Reopen</Button>}
                </Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}
