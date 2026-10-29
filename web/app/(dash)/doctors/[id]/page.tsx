"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Check, ClipboardList, HandHeart, History, Package, PackageX, RotateCcw, Sparkles } from "lucide-react";
import { ago, api, type ApiError, useApi, when, type Visit } from "@/lib/api";
import { useToast } from "@/components/toast";
import { Items } from "@/components/visit-bits";
import { Avatar, Badge, Button, Card, EmptyState, ErrorNote, PageHeader, Skeleton, Stat } from "@/components/ui";

type Doctor = { id: number; name: string; area: string | null; speciality: string | null; rep: string | null;
  brief: { summary: string; open_promises: { id: number; text: string; overdue: boolean; created_at: string }[]; stock_outs_nearby: { product: string; chemist: string }[] };
  visits: Visit[] };

export default function DoctorPage() {
  const { id } = useParams<{ id: string }>();
  const { data: d, error, reload } = useApi<Doctor>(`/doctors/${id}`);
  const toast = useToast();
  async function setPromise(promiseId: number, status: "done" | "open") {
    try {
      await api(`/promises/${promiseId}`, { method: "PATCH", json: { status } });
      toast(status === "done" ? "Promise marked as done. Saathi won't remind the rep any more." : "Promise reopened.");
      reload();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }
  if (error) return <ErrorNote error={error} />;
  if (!d) return <div className="space-y-4"><Skeleton className="h-16 w-80" /><Skeleton className="h-40" /><Skeleton className="h-64" /></div>;

  const samples = d.visits.reduce((a, v) => a + v.samples.reduce((b, i) => b + (i.qty ?? 0), 0), 0);
  return (
    <div className="max-w-5xl">
      <PageHeader crumbs={[{ href: "/doctors", label: "Doctors" }]}
        title={<span className="flex items-center gap-3"><Avatar name={d.name} size="lg" />{d.name}</span>}
        sub={[d.speciality, d.area, d.rep ? `covered by ${d.rep}` : "unassigned"].filter(Boolean).join(" · ")} />

      <div className="mb-6 overflow-hidden rounded-2xl bg-gradient-to-br from-brand via-[#6d4fe0] to-coral p-6 text-white shadow-lg">
        <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-white/80"><Sparkles size={14} />Pre-visit briefing</div>
        <p className="mt-2 max-w-3xl text-lg font-medium leading-relaxed">{d.brief.summary}</p>
        <p className="mt-2 text-xs text-white/70">What Saathi says when the rep calls with &ldquo;{d.name} se milne ja raha hoon&rdquo; (&ldquo;I&apos;m going to see {d.name}&rdquo;).</p>
        {(d.brief.open_promises.length > 0 || d.brief.stock_outs_nearby.length > 0) && (
          <div className="mt-4 flex flex-wrap gap-2">
            {d.brief.open_promises.map((p) => <span key={p.id} className="rounded-full bg-white/20 px-3 py-1 text-xs font-medium">{p.overdue ? "⚠ " : ""}{p.text}</span>)}
            {d.brief.stock_outs_nearby.map((s) => <span key={s.product + s.chemist} className="rounded-full bg-black/15 px-3 py-1 text-xs font-medium">{s.product} out at {s.chemist}</span>)}
          </div>
        )}
      </div>

      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label="Visits recorded" value={d.visits.length} icon={ClipboardList} />
        <Stat label="Samples given" value={samples} icon={Package} tone="good" />
        <Stat label="Open promises" value={d.brief.open_promises.length} icon={HandHeart} tone={d.brief.open_promises.length ? "warn" : "default"} />
        <Stat label="Stock-outs nearby" value={d.brief.stock_outs_nearby.length} icon={PackageX} tone={d.brief.stock_outs_nearby.length ? "coral" : "default"} />
      </div>

      <Card title="Promises to this doctor" icon={HandHeart} className="mb-6"
        action={d.brief.open_promises.length > 0 && <span className="text-xs text-muted">Saathi reminds the rep about these before each visit</span>}>
        {d.brief.open_promises.length === 0 ? (
          <div className="py-2 text-sm text-muted">No open promises. Everything promised to {d.name} has been done.</div>
        ) : (
          <ul className="divide-y divide-line">
            {d.brief.open_promises.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-3 py-3 first:pt-0 last:pb-0">
                <div className="min-w-56 flex-1">
                  <div className="font-medium text-ink">{p.text}</div>
                  <div className="mt-0.5 flex items-center gap-2 text-xs text-muted">
                    Promised {ago(p.created_at)}{p.overdue ? <Badge tone="bad">overdue</Badge> : <Badge tone="warn">open</Badge>}
                  </div>
                </div>
                <Button size="sm" variant="secondary" icon={Check} onClick={() => setPromise(p.id, "done")}>Mark done</Button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Visit history" icon={History}>
        {d.visits.length === 0 ? <EmptyState icon={History} title="No visits yet">Visits appear here as soon as a rep reports one.</EmptyState> : (
          <ol className="relative space-y-6 border-l-2 border-brand-soft pl-6">
            {d.visits.map((v) => (
              <li key={v.id} className="relative">
                <span className="absolute -left-[31px] top-1 size-3.5 rounded-full border-2 border-card bg-brand" />
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                  <span className="font-semibold text-ink">{when(v.visited_at)}</span>· {v.rep ?? "unknown rep"}
                  <Link href={`/visits/${v.id}`} className="font-semibold text-brand">open</Link>
                </div>
                {v.products_discussed.length > 0 && <div className="mt-2 text-sm"><span className="text-muted">Discussed </span>{v.products_discussed.join(", ")}</div>}
                {v.samples.length > 0 && <div className="mt-1.5 flex flex-wrap items-center gap-2 text-sm"><span className="text-muted">Samples</span><Items items={v.samples} /></div>}
                {v.feedback && <div className="mt-2 rounded-xl bg-soft px-3 py-2 text-sm italic">&ldquo;{v.feedback}&rdquo;</div>}
                {v.promises.map((p) => (
                  <div key={p.id} className="mt-1.5 flex flex-wrap items-center gap-2 text-sm">
                    <HandHeart size={13} className="text-warn" />{p.text} <Badge tone={p.status === "done" ? "good" : "warn"}>{p.status}</Badge>
                    {p.status === "done" && <button onClick={() => setPromise(p.id, "open")} className="inline-flex items-center gap-1 text-xs text-muted hover:text-ink"><RotateCcw size={11} />Reopen</button>}
                  </div>
                ))}
              </li>
            ))}
          </ol>
        )}
      </Card>
    </div>
  );
}
