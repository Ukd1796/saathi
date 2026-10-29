"use client";

import Link from "next/link";
import { ArrowRightLeft, CalendarClock, ClipboardList, MapPin, PhoneCall, PhoneOutgoing, Stethoscope, UserPlus, Users } from "lucide-react";
import { useState } from "react";
import { api, type ApiError, ago, mask, useApi } from "@/lib/api";
import { useToast } from "@/components/toast";
import { useMe } from "@/components/shell";
import { ScheduledList, ScheduleModal, type Schedules } from "@/components/scheduled-calls";
import { Avatar, Badge, Button, Card, EmptyState, Label, Modal, PageHeader, Select, Skeleton, Tabs } from "@/components/ui";

type RepRow = { id: number; name: string; phone: string; area: string | null; manager: string | null; status: string;
  visits_7d: number; doctors: number; last_outbound: { reason: string; at: string; error: string | null } | null };

export default function RepsPage() {
  const toast = useToast();
  const { me } = useMe();
  const { data, reload } = useApi<RepRow[]>("/reps");
  const [show, setShow] = useState<"active" | "left">("active");
  const schedules = useApi<Schedules>("/schedules", 30000);
  const [calling, setCalling] = useState<RepRow | null>(null);
  const [scheduling, setScheduling] = useState<RepRow | null>(null);
  const [handover, setHandover] = useState<RepRow | null>(null);
  const [to, setTo] = useState("");
  const [busy, setBusy] = useState(false);

  async function act(fn: () => Promise<string>) {
    setBusy(true);
    try {
      toast(await fn());
      reload();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    } finally {
      setBusy(false);
    }
  }

  const all = data ?? [];
  const active = all.filter((r) => r.status === "active");
  const rows = all.filter((r) => r.status === show);

  return (
    <div>
      <PageHeader title="Reps & handover"
        sub="Your field team. When a rep leaves, hand their doctors to someone else: every visit, open promise and briefing moves with the doctors."
        action={me.role === "admin" && <Link href="/data?tab=reps"><Button variant="secondary" icon={UserPlus}>Add reps</Button></Link>} />
      <div className="mb-4">
        <Tabs value={show} onChange={setShow} options={[
          { value: "active", label: "Active", count: active.length }, { value: "left", label: "Left", count: all.length - active.length },
        ]} />
      </div>

      {show === "active" && <ScheduledList data={schedules.data} onChange={schedules.reload} />}

      {!data ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-56" />)}</div>
      ) : rows.length === 0 ? (
        <Card><EmptyState icon={Users} title={show === "active" ? "No reps yet" : "No one has left"}
          action={show === "active" && me.role === "admin" && <Link href="/data?tab=reps"><Button icon={UserPlus}>Add reps</Button></Link>}>
          {show === "active" ? "Upload your reps list so Saathi recognises them when they call." : "Reps you hand over appear here."}
        </EmptyState></Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {rows.map((r) => (
            <div key={r.id} className={`flex flex-col rounded-2xl border border-line bg-card p-5 transition hover:shadow-md ${r.status === "left" ? "opacity-70" : ""}`}>
              <div className="flex items-start gap-3">
                <Avatar name={r.name} size="lg" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2"><span className="truncate font-semibold text-ink">{r.name}</span>{r.status === "left" && <Badge>left</Badge>}</div>
                  <div className="text-sm tabular-nums text-muted">{mask(r.phone)}</div>
                  {r.manager && <div className="truncate text-xs text-muted">Reports to {r.manager}</div>}
                </div>
              </div>
              {r.area && (
                <div className="mt-3 flex flex-wrap gap-1"><MapPin size={13} className="mt-0.5 text-muted" />
                  {r.area.split(";").map((a) => a.trim()).filter(Boolean).map((a) => <Badge key={a} tone="brand">{a}</Badge>)}</div>
              )}
              <div className="mt-4 grid grid-cols-2 gap-2">
                <div className="rounded-xl bg-soft px-3 py-2"><div className="flex items-center gap-1 text-xs text-muted"><ClipboardList size={12} />Visits, 7 days</div><div className="text-lg font-bold tabular-nums">{r.visits_7d}</div></div>
                <div className="rounded-xl bg-soft px-3 py-2"><div className="flex items-center gap-1 text-xs text-muted"><Stethoscope size={12} />Doctors</div><div className="text-lg font-bold tabular-nums">{r.doctors}</div></div>
              </div>
              <div className="mt-3 flex items-center gap-1.5 text-xs text-muted">
                <PhoneOutgoing size={12} />
                {r.last_outbound ? <>Saathi called ({r.last_outbound.reason}) {ago(r.last_outbound.at)}{r.last_outbound.error && <span className="text-bad"> · failed</span>}</> : "Saathi hasn't called yet"}
              </div>
              <div className="mt-4 flex gap-2 border-t border-line pt-4">
                {r.status === "active" ? <>
                  <Button size="sm" icon={PhoneCall} className="flex-1" onClick={() => setCalling(r)}>Call now</Button>
                  <Button size="sm" variant="secondary" icon={ArrowRightLeft} className="flex-1" onClick={() => { setHandover(r); setTo(""); }}>Hand over</Button>
                  <Button size="sm" variant="secondary" icon={CalendarClock} aria-label={`Schedule a call to ${r.name}`} title="Schedule a call" onClick={() => setScheduling(r)} />
                </> : (
                  <Button size="sm" variant="secondary" className="flex-1" disabled={busy} onClick={() => act(async () => {
                    await api(`/reps/${r.id}`, { method: "PATCH", json: { status: "active" } });
                    return `${r.name} is active again.`;
                  })}>Reactivate</Button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <Modal open={!!calling} onClose={() => setCalling(null)} title={`Call ${calling?.name}?`}
        footer={<>
          <Button variant="ghost" onClick={() => setCalling(null)}>Cancel</Button>
          <Button icon={PhoneCall} disabled={busy} onClick={() => calling && act(async () => {
            await api(`/reps/${calling.id}/call`, { method: "POST" });
            setCalling(null);
            return `Calling ${calling.name} now. The call shows on Overview.`;
          })}>Call {calling && mask(calling.phone)}</Button>
        </>}>
        <p className="text-sm text-muted">Saathi will phone this rep right away and take a visit report or give a briefing. Only call real numbers you&apos;re allowed to call.</p>
      </Modal>

      <ScheduleModal key={scheduling?.id ?? "none"} rep={scheduling} onClose={() => setScheduling(null)}
        onDone={() => { setScheduling(null); schedules.reload(); }} />

      <Modal open={!!handover} onClose={() => setHandover(null)} title={`Hand over ${handover?.name}'s doctors`}
        footer={<>
          <Button variant="ghost" onClick={() => setHandover(null)}>Cancel</Button>
          <Button icon={ArrowRightLeft} disabled={!to || busy} onClick={() => handover && act(async () => {
            const r = await api<{ moved_doctors: number; open_promises: number; to: string }>(`/reps/${handover.id}/handover`, { method: "POST", json: { to_rep_id: Number(to) } });
            setHandover(null);
            return `${r.moved_doctors} doctors moved to ${r.to}, with ${r.open_promises} open promise(s). ${handover.name} is marked as left.`;
          })}>Hand over</Button>
        </>}>
        <p className="text-sm text-muted">
          All {handover?.doctors} doctors, with their visit history and open promises, move to the new rep. Their territory is added, and {handover?.name} is marked as left.
        </p>
        <Label text="New rep">
          <Select value={to} onChange={(e) => setTo(e.target.value)}>
            <option value="">Choose a rep…</option>
            {active.filter((r) => r.id !== handover?.id).map((r) => <option key={r.id} value={r.id}>{r.name}{r.area ? ` (${r.area})` : ""}</option>)}
          </Select>
        </Label>
      </Modal>
    </div>
  );
}
