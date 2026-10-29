"use client";

import Link from "next/link";
import { BookOpen, Check, CircleCheck, Clock, PackageX, X, type LucideIcon } from "lucide-react";
import { useState } from "react";
import { type ActionItem, ago, api, type ApiError, useApi } from "@/lib/api";
import { useMe } from "@/components/shell";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, EmptyState, FilterSelect, LoadingRows, PageHeader, Tabs } from "@/components/ui";

const KIND: Record<ActionItem["kind"], { icon: LucideIcon; label: string; tint: string }> = {
  material: { icon: BookOpen, label: "Material request", tint: "bg-brand-soft text-brand" },
  stockout: { icon: PackageX, label: "Stock-out", tint: "bg-coral-soft text-coral" },
  overdue: { icon: Clock, label: "Overdue promise", tint: "bg-bad/12 text-bad" },
};
const FILTERS = { "Material requests": "material", "Stock-outs": "stockout", "Overdue promises": "overdue" } as const;

function Row({ a, onDone }: { a: ActionItem; onDone: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const k = KIND[a.kind];

  async function set(status: string, msg: string) {
    setBusy(true);
    try {
      await api(`/actions/${a.action_id}`, { method: "PATCH", json: { status } });
      toast(msg);
      onDone();
    } catch (e) {
      toast((e as ApiError).message, "bad");
      setBusy(false);
    }
  }

  return (
    <li className="flex flex-wrap items-center gap-3 px-5 py-4 sm:flex-nowrap">
      <span className={`flex size-9 shrink-0 items-center justify-center rounded-xl ${k.tint}`}><k.icon size={17} /></span>
      <div className="min-w-0 flex-1">
        <div className="font-medium text-ink">{a.title}</div>
        <div className="mt-0.5 text-xs text-muted">
          {k.label}{a.rep ? ` · ${a.rep}` : ""}{a.doctor && a.doctor_id ? <> · <Link href={`/doctors/${a.doctor_id}`} className="hover:text-brand">{a.doctor}</Link></> : ""} · {ago(a.created_at)}
        </div>
        {a.detail && <div className="mt-1 text-xs text-muted">{a.detail}</div>}
      </div>
      <div className="flex w-full shrink-0 justify-end gap-2 pl-12 sm:w-auto sm:pl-0">
        {a.status !== "open" ? (
          <Badge tone={a.status === "declined" ? "default" : "good"} className="capitalize">{a.status}</Badge>
        ) : a.kind === "material" ? <>
          <Button size="sm" variant="ghost" icon={X} disabled={busy} onClick={() => set("declined", "Request declined.")}>Decline</Button>
          <Button size="sm" icon={Check} disabled={busy} onClick={() => set("approved", `Approved. ${a.rep ?? "The rep"} can go ahead.`)}>Approve</Button>
        </> : a.kind === "stockout" ? (
          <Button size="sm" variant="secondary" icon={CircleCheck} disabled={busy} onClick={() => set("done", "Marked as handled.")}>Handled</Button>
        ) : a.doctor_id ? (
          <Link href={`/doctors/${a.doctor_id}`}><Button size="sm" variant="secondary">Open doctor</Button></Link>
        ) : null}
      </div>
    </li>
  );
}

export default function ActionsPage() {
  const { me } = useMe();
  const [tab, setTab] = useState<"open" | "done">("open");
  const [type, setType] = useState("");
  const { data, reload } = useApi<ActionItem[]>(`/actions?status=${tab}`, 30000);
  const want = type ? FILTERS[type as keyof typeof FILTERS] : null;
  const rows = (data ?? []).filter((a) => !want || a.kind === want);

  return (
    <div className="max-w-4xl">
      <PageHeader title="Actions"
        sub={me.role === "manager" ? "What your team's calls need from you: requests to approve, stock-outs near prescribers, and promises running late."
          : "What reps' calls need from a manager: requests to approve, stock-outs near prescribers, and promises running late."} />
      <Card pad={false}>
        <div className="flex flex-wrap items-center gap-3 border-b border-line p-4">
          <Tabs value={tab} onChange={setTab} options={[{ value: "open", label: "To do", count: tab === "open" ? data?.length : undefined }, { value: "done", label: "Done" }]} />
          <FilterSelect label="Type" value={type} onChange={setType} options={Object.keys(FILTERS)} />
        </div>
        {!data ? <LoadingRows rows={4} /> : rows.length === 0 ? (
          <EmptyState icon={CircleCheck} title={tab === "open" ? "You're all caught up" : "Nothing done yet"}>
            {tab === "open" ? "New requests and alerts appear here as soon as a rep's call ends." : "Approved, declined and handled items show up here."}
          </EmptyState>
        ) : (
          <ul className="divide-y divide-line">{rows.map((a) => <Row key={a.id} a={a} onDone={reload} />)}</ul>
        )}
      </Card>
    </div>
  );
}
