"use client";

import { MapPin, PackageCheck, PackageX, Stethoscope, Store } from "lucide-react";
import { useMemo, useState } from "react";
import { ago, useApi } from "@/lib/api";
import { Badge, Card, EmptyState, PageHeader, FilterSelect, Skeleton, Tabs } from "@/components/ui";

type Group = { product: string; reports: number; last_seen: string; chemists: { name: string; area: string | null }[]; areas: string[]; doctors_nearby: string[] };

export default function StockOutsPage() {
  const [days, setDays] = useState<"7" | "14" | "30">("14");
  const [area, setArea] = useState("");
  const { data } = useApi<Group[]>(`/stockouts?days=${days}`);
  const areas = useMemo(() => [...new Set((data ?? []).flatMap((g) => g.areas))].sort(), [data]);
  const rows = (data ?? []).filter((g) => !area || g.areas.includes(area));
  const max = Math.max(1, ...rows.map((g) => g.reports));

  return (
    <div>
      <PageHeader title="Stock-outs"
        sub="Products reps found missing at chemists, next to the doctors in that area who prescribe them. Every empty shelf near a prescriber is a lost sale."
        action={<>
          <FilterSelect label="Area" icon={MapPin} value={area} onChange={setArea} options={areas} />
          <Tabs value={days} onChange={setDays} options={[{ value: "7", label: "7 days" }, { value: "14", label: "14 days" }, { value: "30", label: "30 days" }]} />
        </>} />
      {!data ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-44" />)}</div>
      ) : rows.length === 0 ? (
        <Card><EmptyState icon={PackageCheck} title="No stock-outs reported">Nothing missing at chemists in the last {days} days{area ? ` in ${area}` : ""}.</EmptyState></Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {rows.map((g) => (
            <Card key={g.product} title={g.product} icon={PackageX} action={<Badge tone="coral">{g.reports} report{g.reports > 1 ? "s" : ""}</Badge>}>
              <div className="mb-4 h-1.5 rounded-full bg-soft"><div className="h-1.5 rounded-full bg-coral" style={{ width: `${(g.reports / max) * 100}%` }} /></div>
              <div className="space-y-3 text-sm">
                <div className="flex gap-2"><Store size={15} className="mt-0.5 shrink-0 text-muted" /><span>{g.chemists.map((c) => c.name).join(", ") || "–"}</span></div>
                <div className="flex gap-2"><MapPin size={15} className="mt-0.5 shrink-0 text-muted" /><span className="flex flex-wrap gap-1">{g.areas.map((a) => <Badge key={a}>{a}</Badge>)}</span></div>
                <div className="flex gap-2"><Stethoscope size={15} className="mt-0.5 shrink-0 text-muted" /><span>{g.doctors_nearby.join(", ") || <span className="text-muted">No doctors on file nearby</span>}</span></div>
              </div>
              <div className="mt-4 border-t border-line pt-3 text-xs text-muted">Last reported {ago(g.last_seen)}</div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
