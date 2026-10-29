"use client";

import { CalendarClock, X } from "lucide-react";
import { useState } from "react";
import { api, type ApiError } from "@/lib/api";
import { useToast } from "@/components/toast";
import { Avatar, Button, Input, Label, Modal, Tabs } from "@/components/ui";

export type Schedule = { id: number; rep_id: number; rep: string; purpose: "report" | "briefing" | "resume"; time: string;
  repeat: "once" | "weekdays" | "daily"; run_on: string | null; active: boolean; last_run_on: string | null;
  last_result: string | null; automatic: boolean };
export type Schedules = { active: Schedule[]; recent: Schedule[] };

const PURPOSE = { report: "Visit report", briefing: "Morning briefing", resume: "Resume cut-off report" };

function when(s: Schedule) {
  const t = new Date(`2000-01-01T${s.time}`).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
  if (s.repeat === "weekdays") return `Weekdays · ${t}`;
  if (s.repeat === "daily") return `Every day · ${t}`;
  const today = new Date().toLocaleDateString("en-CA");
  return `${s.run_on === today ? "Today" : s.run_on ? new Date(s.run_on).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : ""} · ${t}`;
}

/** The manager's view of automatic calls: what is coming up, and what just happened. Hidden when empty. */
export function ScheduledList({ data, onChange }: { data: Schedules | null; onChange: () => void }) {
  const toast = useToast();
  if (!data || (data.active.length === 0 && data.recent.length === 0)) return null;
  async function cancel(s: Schedule) {
    try {
      await api(`/schedules/${s.id}`, { method: "DELETE" });
      toast(`Cancelled the call to ${s.rep}.`);
      onChange();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }
  return (
    <section className="mb-6 rounded-2xl border border-line bg-card">
      <div className="flex items-center gap-2 border-b border-line px-5 py-3 text-sm font-semibold text-ink">
        <CalendarClock size={16} className="text-brand" />Scheduled calls
        <span className="text-xs font-normal text-muted">Saathi only calls between 9am and 9pm</span>
      </div>
      <ul className="divide-y divide-line">
        {data.active.map((s) => (
          <li key={s.id} className="flex items-center gap-3 px-5 py-2.5 text-sm">
            <Avatar name={s.rep} size="sm" />
            <span className="min-w-0 flex-1 truncate"><span className="font-medium text-ink">{s.rep}</span>
              <span className="text-muted"> · {PURPOSE[s.purpose]}{s.automatic ? " (automatic)" : ""}</span></span>
            <span className="whitespace-nowrap text-xs font-medium text-ink">{when(s)}</span>
            <button onClick={() => cancel(s)} aria-label={`Cancel call to ${s.rep}`} className="rounded-lg p-1 text-muted hover:bg-soft hover:text-bad"><X size={15} /></button>
          </li>
        ))}
        {data.recent.slice(0, 3).map((s) => (
          <li key={s.id} className="flex items-center gap-3 px-5 py-2 text-xs text-muted">
            <span className="w-7" />
            <span className="min-w-0 flex-1 truncate">{s.rep} · {PURPOSE[s.purpose]}</span>
            <span className={s.last_result?.startsWith("failed") ? "text-bad" : ""}>{s.last_result ?? "done"}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ScheduleModal({ rep, onClose, onDone }: { rep: { id: number; name: string } | null; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [purpose, setPurpose] = useState<"report" | "briefing">("report");
  const [time, setTime] = useState("19:00");
  const [repeat, setRepeat] = useState<"once" | "weekdays" | "daily">("once");
  const [busy, setBusy] = useState(false);
  const inHours = time >= "09:00" && time <= "21:00";

  async function save() {
    if (!rep) return;
    setBusy(true);
    try {
      await api("/schedules", { method: "POST", json: { rep_id: rep.id, time, repeat, purpose } });
      toast(`Saathi will call ${rep.name}${repeat === "once" ? "" : repeat === "weekdays" ? " every weekday" : " every day"} at ${time}.`);
      onDone();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={!!rep} onClose={onClose} title={`Schedule a call to ${rep?.name}`}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button icon={CalendarClock} disabled={busy || !inHours} onClick={save}>Schedule</Button></>}>
      <Label text="Saathi will">
        <Tabs value={purpose} onChange={setPurpose} options={[{ value: "report", label: "Take the visit report" }, { value: "briefing", label: "Give a morning briefing" }]} />
      </Label>
      <div className="flex flex-wrap items-end gap-4">
        <Label text="At"><Input type="time" value={time} onChange={(e) => setTime(e.target.value)} className="w-32" /></Label>
        <Label text="Repeat">
          <Tabs value={repeat} onChange={setRepeat} options={[{ value: "once", label: "Once" }, { value: "weekdays", label: "Weekdays" }, { value: "daily", label: "Every day" }]} />
        </Label>
      </div>
      <p className={`text-xs ${inHours ? "text-muted" : "text-bad"}`}>
        {inHours
          ? purpose === "report" ? "Skipped automatically if the rep has already reported that day. If they don't pick up, Saathi tries once more 10 minutes later."
            : "Saathi asks which doctor they're seeing today and briefs them. One retry if they don't pick up."
          : "Pick a time between 9:00 and 21:00."}
      </p>
    </Modal>
  );
}
