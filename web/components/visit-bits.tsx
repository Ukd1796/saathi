import Link from "next/link";
import type { Item, Visit } from "@/lib/api";
import { Badge } from "@/components/ui";

export function Items({ items }: { items: Item[] }) {
  if (!items.length) return <span className="text-muted">–</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {items.map((i, n) => (
        <Badge key={n} tone={i.matched ? "brand" : "warn"}>{i.product}{i.qty != null ? ` × ${i.qty}` : ""}</Badge>
      ))}
    </span>
  );
}

export function DoctorCell({ v }: { v: Visit }) {
  if (v.doctor && v.doctor_id) return <Link href={`/doctors/${v.doctor_id}`} className="font-semibold text-ink hover:text-brand">{v.doctor}</Link>;
  return <span className="font-medium text-warn">? {v.doctor_heard}</span>;
}
