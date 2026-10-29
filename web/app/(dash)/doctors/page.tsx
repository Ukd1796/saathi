"use client";

import Link from "next/link";
import { ArrowDownUp, CalendarClock, MapPin, Stethoscope, UserRound, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { ago, useApi } from "@/lib/api";
import { useFilters } from "@/lib/use-filters";
import { Avatar, Badge, Card, EmptyState, FilterSelect, LoadingRows, PageHeader, SearchInput, Table, Tabs, Td, Tr } from "@/components/ui";

type DoctorRow = { id: number; name: string; area: string | null; speciality: string | null; rep: string | null; last_visit: string | null; open_promises: number; overdue_promises: number };
type View = "all" | "due" | "promises" | "overdue" | "unassigned";
type Sort = "name" | "oldest" | "newest" | "promises";

/** A doctor not seen for this long (or never) is due for a visit. */
const DUE_DAYS = 30;
const SORTS: { value: Sort; label: string }[] = [
  { value: "name", label: "Name A–Z" },
  { value: "oldest", label: "Longest since visit" },
  { value: "newest", label: "Most recently visited" },
  { value: "promises", label: "Most open promises" },
];

const uniq = (xs: (string | null)[]) => [...new Set(xs.filter(Boolean))].sort() as string[];
const daysSince = (iso: string | null) => (iso ? (Date.now() - new Date(iso).getTime()) / 86400000 : Infinity);
const isDue = (d: DoctorRow) => daysSince(d.last_visit) > DUE_DAYS;

const VIEWS: Record<View, (d: DoctorRow) => boolean> = {
  all: () => true,
  due: isDue,
  promises: (d) => d.open_promises > 0,
  overdue: (d) => d.overdue_promises > 0,
  unassigned: (d) => !d.rep,
};

export default function DoctorsPage() {
  const { data } = useApi<DoctorRow[]>("/doctors");
  const { values: f, set, reset, active } = useFilters({ q: "", view: "all", area: "", spec: "", rep: "", sort: "name" });
  const all = useMemo(() => data ?? [], [data]);
  const [typed, setTyped] = useState(f.q);
  useEffect(() => {
    if (typed === f.q) return;
    const t = setTimeout(() => set({ q: typed }), 250);
    return () => clearTimeout(t);
  }, [typed, f.q, set]);

  const opts = useMemo(() => ({ areas: uniq(all.map((d) => d.area)), reps: uniq(all.map((d) => d.rep)), specs: uniq(all.map((d) => d.speciality)) }), [all]);
  // Dropdown and search filters apply first; the view tabs then show counts within that.
  const filtered = useMemo(() => {
    const needle = f.q.trim().toLowerCase();
    return all.filter((d) => (!f.area || d.area === f.area) && (!f.spec || d.speciality === f.spec) && (!f.rep || d.rep === f.rep)
      && (!needle || [d.name, d.area, d.speciality, d.rep].join(" ").toLowerCase().includes(needle)));
  }, [all, f.q, f.area, f.spec, f.rep]);
  const counts = useMemo(() => Object.fromEntries((Object.keys(VIEWS) as View[]).map((v) => [v, filtered.filter(VIEWS[v]).length])) as Record<View, number>, [filtered]);
  const rows = useMemo(() => {
    const out = filtered.filter(VIEWS[f.view as View] ?? VIEWS.all);
    const by: Record<Sort, (a: DoctorRow, b: DoctorRow) => number> = {
      name: (a, b) => a.name.localeCompare(b.name),
      oldest: (a, b) => daysSince(b.last_visit) - daysSince(a.last_visit) || a.name.localeCompare(b.name),
      newest: (a, b) => daysSince(a.last_visit) - daysSince(b.last_visit) || a.name.localeCompare(b.name),
      promises: (a, b) => b.overdue_promises - a.overdue_promises || b.open_promises - a.open_promises || a.name.localeCompare(b.name),
    };
    return [...out].sort(by[f.sort as Sort] ?? by.name);
  }, [filtered, f.view, f.sort]);

  const chips = [
    f.q && { key: "q", label: `“${f.q}”` },
    f.area && { key: "area", label: f.area },
    f.spec && { key: "spec", label: f.spec },
    f.rep && { key: "rep", label: f.rep },
  ].filter((c): c is { key: string; label: string } => !!c);

  return (
    <div>
      <PageHeader title="Doctors" sub="Every doctor's history lives here, whichever rep covers them. Open one to see what Saathi tells a rep before the visit." />
      <Card pad={false}>
        {/* 1. Quick views and sorting */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 pt-4 pb-3">
          <Tabs value={f.view as View} onChange={(v) => set({ view: v })} options={[
            { value: "all", label: "All", count: counts.all },
            { value: "due", label: "Due for a visit", count: counts.due },
            { value: "promises", label: "Open promises", count: counts.promises },
            { value: "overdue", label: "Overdue promises", count: counts.overdue },
            { value: "unassigned", label: "Unassigned", count: counts.unassigned },
          ]} />
          <label className="relative inline-flex h-9 items-center gap-1.5 rounded-xl px-2 text-sm text-muted hover:text-ink">
            <ArrowDownUp size={14} />
            <span>Sort:</span>
            <span className="font-semibold text-ink">{SORTS.find((s) => s.value === f.sort)?.label}</span>
            <select value={f.sort} onChange={(e) => set({ sort: e.target.value })} aria-label="Sort doctors" className="absolute inset-0 cursor-pointer appearance-none opacity-0">
              {SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </label>
        </div>

        {/* 2. Search and filters */}
        <div className="flex flex-wrap items-center gap-2 border-b border-line bg-soft/40 px-4 py-3">
          <SearchInput value={typed} onChange={setTyped} placeholder="Search doctors…" className="w-full sm:w-64" />
          <FilterSelect label="Area" icon={MapPin} value={f.area} onChange={(area) => set({ area })} options={opts.areas} />
          <FilterSelect label="Speciality" icon={Stethoscope} value={f.spec} onChange={(spec) => set({ spec })} options={opts.specs} />
          <FilterSelect label="Rep" icon={UserRound} value={f.rep} onChange={(rep) => set({ rep })} options={opts.reps} />
          <span className="ml-auto text-xs font-medium text-muted">{data ? `${rows.length} of ${all.length} doctors` : ""}</span>
        </div>

        {/* 3. What is applied, removable one by one */}
        {chips.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-2.5 text-xs">
            <span className="text-muted">Filtered by</span>
            {chips.map((c) => (
              <button key={c.key} onClick={() => { if (c.key === "q") setTyped(""); set({ [c.key]: "" }); }}
                className="inline-flex items-center gap-1 rounded-full bg-brand-soft px-2.5 py-1 font-semibold text-brand hover:bg-brand/15">
                {c.label}<X size={12} />
              </button>
            ))}
            {chips.length > 1 && <button onClick={() => { setTyped(""); set({ q: "", area: "", spec: "", rep: "" }); }} className="font-semibold text-muted hover:text-ink">Clear all</button>}
          </div>
        )}

        {!data ? <LoadingRows /> : rows.length === 0 ? (
          <EmptyState icon={Stethoscope} title={all.length ? "No doctors match" : "No doctors yet"}
            action={all.length > 0 && active > 0 && <button onClick={() => { setTyped(""); reset(); }} className="text-sm font-semibold text-brand">Clear filters</button>}>
            {all.length ? "Try removing a filter or switching to All." : "Add doctors under Master data."}
          </EmptyState>
        ) : (
          <>
          <ul className="divide-y divide-line md:hidden">
            {rows.map((d) => (
              <li key={d.id}>
                <Link href={`/doctors/${d.id}`} className="flex items-center gap-3 px-4 py-3">
                  <Avatar name={d.name} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-semibold text-ink">{d.name}</span>
                      {d.open_promises > 0 && <Badge tone={d.overdue_promises ? "bad" : "warn"}>{d.overdue_promises ? `${d.overdue_promises} overdue` : `${d.open_promises} open`}</Badge>}
                    </div>
                    <div className="truncate text-xs text-muted">{[d.speciality, d.area, d.rep ?? "unassigned"].filter(Boolean).join(" · ")}</div>
                    <div className={`text-xs ${isDue(d) ? "font-medium text-coral" : "text-muted"}`}>{d.last_visit ? `Visited ${ago(d.last_visit)}` : "Never visited"}</div>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
          <div className="hidden md:block">
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
                <Td>{d.rep ? <span className="flex items-center gap-2 whitespace-nowrap"><Avatar name={d.rep} size="sm" />{d.rep}</span> : <Badge tone="warn">unassigned</Badge>}</Td>
                <Td className="whitespace-nowrap">
                  {isDue(d)
                    ? <span className="inline-flex items-center gap-1 font-medium text-coral"><CalendarClock size={13} />{d.last_visit ? ago(d.last_visit) : "never visited"}</span>
                    : <span className="text-muted">{ago(d.last_visit)}</span>}
                </Td>
                <Td>{d.open_promises ? (
                  <span className="flex flex-wrap gap-1"><Badge tone="warn">{d.open_promises} open</Badge>{d.overdue_promises > 0 && <Badge tone="bad">{d.overdue_promises} overdue</Badge>}</span>
                ) : <span className="text-muted">–</span>}</Td>
              </Tr>
            ))}
          </Table>
          </div>
          </>
        )}
      </Card>
    </div>
  );
}
