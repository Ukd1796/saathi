"use client";

import { MapPin, Stethoscope } from "lucide-react";
import { useMemo, useState } from "react";
import { ago, useApi } from "@/lib/api";
import { Avatar, Badge, Card, EmptyState, LoadingRows, PageHeader, SearchInput, Select, Table, Td, Tr } from "@/components/ui";

type DoctorRow = { id: number; name: string; area: string | null; speciality: string | null; rep: string | null; last_visit: string | null; open_promises: number };

const uniq = (xs: (string | null)[]) => [...new Set(xs.filter(Boolean))].sort() as string[];

export default function DoctorsPage() {
  const { data } = useApi<DoctorRow[]>("/doctors");
  const [q, setQ] = useState("");
  const [area, setArea] = useState("");
  const [rep, setRep] = useState("");
  const [spec, setSpec] = useState("");
  const opts = useMemo(() => ({ areas: uniq((data ?? []).map((d) => d.area)), reps: uniq((data ?? []).map((d) => d.rep)),
    specs: uniq((data ?? []).map((d) => d.speciality)) }), [data]);
  const rows = (data ?? []).filter((d) => (!area || d.area === area) && (!rep || d.rep === rep) && (!spec || d.speciality === spec)
    && (!q.trim() || d.name.toLowerCase().includes(q.trim().toLowerCase())));

  return (
    <div>
      <PageHeader title="Doctors" sub="Every doctor's history lives here, whichever rep covers them. Open one to see what Saathi tells a rep before the visit." />
      <Card pad={false}>
        <div className="flex flex-wrap items-center gap-3 border-b border-line p-4">
          <SearchInput value={q} onChange={setQ} placeholder="Search doctors…" className="min-w-52 flex-1" />
          <Select value={area} onChange={(e) => setArea(e.target.value)} className="w-auto min-w-32"><option value="">All areas</option>{opts.areas.map((a) => <option key={a}>{a}</option>)}</Select>
          <Select value={spec} onChange={(e) => setSpec(e.target.value)} className="w-auto min-w-36"><option value="">All specialities</option>{opts.specs.map((a) => <option key={a}>{a}</option>)}</Select>
          <Select value={rep} onChange={(e) => setRep(e.target.value)} className="w-auto min-w-32"><option value="">All reps</option>{opts.reps.map((a) => <option key={a}>{a}</option>)}</Select>
        </div>
        {!data ? <LoadingRows /> : rows.length === 0 ? (
          <EmptyState icon={Stethoscope} title={data.length ? "No doctors match" : "No doctors yet"}>{data.length ? "Try a different filter." : "Add doctors under Master data."}</EmptyState>
        ) : (
          <Table head={["Doctor", "Speciality", "Covered by", "Last visit", "Open promises"]}>
            {rows.map((d) => (
              <Tr key={d.id} href={`/doctors/${d.id}`}>
                <Td>
                  <span className="flex items-center gap-3">
                    <Avatar name={d.name} />
                    <span><span className="block font-semibold text-ink">{d.name}</span>
                      {d.area && <span className="flex items-center gap-1 text-xs text-muted"><MapPin size={11} />{d.area}</span>}</span>
                  </span>
                </Td>
                <Td>{d.speciality ? <Badge tone="brand">{d.speciality}</Badge> : <span className="text-muted">–</span>}</Td>
                <Td>{d.rep ?? <Badge tone="warn">unassigned</Badge>}</Td>
                <Td className="whitespace-nowrap text-muted">{d.last_visit ? ago(d.last_visit) : "never"}</Td>
                <Td>{d.open_promises ? <Badge tone="warn">{d.open_promises} open</Badge> : <span className="text-muted">–</span>}</Td>
              </Tr>
            ))}
          </Table>
        )}
        {data && rows.length > 0 && <div className="border-t border-line px-4 py-2.5 text-xs text-muted">{rows.length} of {data.length} doctors</div>}
      </Card>
    </div>
  );
}
