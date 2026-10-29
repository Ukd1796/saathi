"use client";

import Link from "next/link";
import { ClipboardList, Download, MapPin, UserRound } from "lucide-react";
import { useMemo, useState } from "react";
import { downloadCsv, isoDay, useApi, when, type Visit } from "@/lib/api";
import { DoctorCell, Items } from "@/components/visit-bits";
import { Avatar, Button, Card, EmptyState, LoadingRows, PageHeader, SearchInput, FilterSelect, Table, Tabs, Td, Tr } from "@/components/ui";

type Range = "today" | "7" | "30" | "all";
const RANGES: { value: Range; label: string }[] = [
  { value: "today", label: "Today" }, { value: "7", label: "7 days" }, { value: "30", label: "30 days" }, { value: "all", label: "All" },
];

function rangeQuery(r: Range) {
  if (r === "all") return "";
  return `?date_from=${isoDay(r === "today" ? 0 : Number(r) - 1)}&date_to=${isoDay(0)}`;
}

const itemText = (items: Visit["samples"]) => items.map((i) => `${i.product}${i.qty != null ? ` x${i.qty}` : ""}`).join("; ");

export default function VisitsPage() {
  const [range, setRange] = useState<Range>("30");
  const [q, setQ] = useState("");
  const [rep, setRep] = useState("");
  const [area, setArea] = useState("");
  const { data } = useApi<Visit[]>(`/visits${rangeQuery(range)}`, 10000);

  const reps = useMemo(() => [...new Set((data ?? []).map((v) => v.rep).filter(Boolean))].sort() as string[], [data]);
  const areas = useMemo(() => [...new Set((data ?? []).map((v) => v.area).filter(Boolean))].sort() as string[], [data]);
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (data ?? []).filter((v) => {
      if (rep && v.rep !== rep) return false;
      if (area && v.area !== area) return false;
      if (!needle) return true;
      const hay = [v.doctor, v.doctor_heard, v.rep, v.area, v.chemist, v.feedback, ...v.products_discussed,
        ...v.samples.map((i) => i.product), ...v.orders.map((i) => i.product), ...v.stock_outs].join(" ").toLowerCase();
      return hay.includes(needle);
    });
  }, [data, q, rep, area]);

  function exportCsv() {
    downloadCsv(`saathi-visits-${isoDay()}.csv`, [
      ["Date", "Rep", "Doctor", "Area", "Products discussed", "Samples", "Orders", "Chemist", "Stock-outs", "Promises", "Feedback", "Next visit", "Unmatched names"],
      ...rows.map((v) => [when(v.visited_at), v.rep, v.doctor ?? v.doctor_heard, v.area, v.products_discussed.join("; "),
        itemText(v.samples), itemText(v.orders), v.chemist, v.stock_outs.join("; "), v.promises.map((p) => p.text).join("; "),
        v.feedback, v.next_visit, v.unmatched.map((u) => u.heard).join("; ")]),
    ]);
  }

  return (
    <div>
      <PageHeader title="Visits" sub="Every doctor visit your reps reported by phone, structured and searchable."
        action={<Button variant="secondary" icon={Download} onClick={exportCsv} disabled={!rows.length}>Export CSV</Button>} />

      <Card pad={false}>
        <div className="flex flex-wrap items-center gap-3 border-b border-line p-4">
          <SearchInput value={q} onChange={setQ} placeholder="Search doctor, product, chemist…" className="w-full sm:w-72" />
          <FilterSelect label="Rep" icon={UserRound} value={rep} onChange={setRep} options={reps} />
          <FilterSelect label="Area" icon={MapPin} value={area} onChange={setArea} options={areas} />
          <Tabs value={range} onChange={setRange} options={RANGES} />
        </div>

        {!data ? <LoadingRows /> : rows.length === 0 ? (
          <EmptyState icon={ClipboardList} title={data.length ? "No visits match these filters" : "No visits yet"}>
            {data.length ? "Try clearing the search or widening the date range." : "When a rep calls Saathi after a doctor visit, it shows up here within seconds."}
          </EmptyState>
        ) : (
          <>
            <div className="hidden md:block">
              <Table head={["When", "Rep", "Doctor", "Samples", "Orders", "Chemist", "Promises"]}>
                {rows.map((v) => (
                  <Tr key={v.id} href={`/visits/${v.id}`}>
                    <Td className="whitespace-nowrap text-muted">{when(v.visited_at)}</Td>
                    <Td><span className="flex items-center gap-2 whitespace-nowrap"><Avatar name={v.rep ?? "?"} size="sm" />{v.rep ?? "–"}</span></Td>
                    <Td><DoctorCell v={v} />{v.area && <div className="flex items-center gap-1 text-xs text-muted"><MapPin size={11} />{v.area}</div>}</Td>
                    <Td><Items items={v.samples} /></Td>
                    <Td><Items items={v.orders} /></Td>
                    <Td>
                      <div>{v.chemist ?? <span className="text-muted">–</span>}</div>
                      {v.stock_outs.length > 0 && <div className="mt-0.5 text-xs font-medium text-coral">Out: {v.stock_outs.join(", ")}</div>}
                    </Td>
                    <Td className="max-w-56 text-xs text-muted">{v.promises.map((p) => <div key={p.id} className="line-clamp-2">{p.text}</div>)}</Td>
                  </Tr>
                ))}
              </Table>
            </div>
            <ul className="divide-y divide-line md:hidden">
              {rows.map((v) => (
                <li key={v.id}>
                  <Link href={`/visits/${v.id}`} className="block space-y-1.5 px-4 py-3">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold text-ink">{v.doctor ?? `? ${v.doctor_heard}`}</span>
                    </div>
                    <div className="text-xs text-muted">{when(v.visited_at)} · {v.rep ?? "–"}{v.area ? ` · ${v.area}` : ""}</div>
                    {v.samples.length > 0 && <Items items={v.samples} />}
                  </Link>
                </li>
              ))}
            </ul>
            <div className="border-t border-line px-4 py-2.5 text-xs text-muted">{rows.length} of {data.length} visits</div>
          </>
        )}
      </Card>
    </div>
  );
}
