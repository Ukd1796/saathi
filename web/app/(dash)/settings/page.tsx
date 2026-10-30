"use client";

import Link from "next/link";
import { ArrowRight, Bot, Clock, Code2, Phone, PhoneForwarded, RefreshCw, TriangleAlert, Wrench } from "lucide-react";
import { useState } from "react";
import { type Agent, api, type ApiError, type GraphNode, useApi, when } from "@/lib/api";
import { useMe } from "@/components/shell";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, Input, PageHeader, Skeleton, Tabs } from "@/components/ui";
import { NumberPicker } from "./number-picker";

const NODE_TONE = { router: "default", static: "coral", llm: "brand" } as const;

/** The graph agent's steps: what each one does and where the call goes next. */
function CallFlow({ nodes }: { nodes: GraphNode[] }) {
  return (
    <ol className="max-h-[32rem] space-y-2 overflow-auto pr-1">
      {nodes.map((n) => (
        <li key={n.id} id={`node-${n.id}`}>
          <details className="rounded-xl border border-line bg-card px-3 py-2">
            <summary className="flex cursor-pointer flex-wrap items-center gap-2 text-sm">
              <code className="font-semibold text-ink">{n.id}</code>
              <Badge tone={NODE_TONE[n.type] ?? "default"}>{n.type === "static" ? "ends the call" : n.type === "router" ? "start" : "step"}</Badge>
              {n.tool && <Badge tone="good"><Wrench size={11} />{n.tool}</Badge>}
              <span className="ml-auto flex flex-wrap gap-1 text-xs text-muted">{n.edges.map((e) => <span key={e.to + e.when} className="inline-flex items-center gap-0.5"><ArrowRight size={11} />{e.to}</span>)}</span>
            </summary>
            {n.edges.length > 0 && (
              <ul className="mt-2 space-y-1 text-xs">
                {n.edges.map((e) => <li key={e.to + e.when}><code className="text-brand">{e.to}</code> <span className="text-muted">when {e.when}</span></li>)}
              </ul>
            )}
            {n.prompt && <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-soft p-3 font-mono text-[11px] leading-relaxed">{n.prompt}</pre>}
          </details>
        </li>
      ))}
    </ol>
  );
}

export default function SettingsPage() {
  const toast = useToast();
  const { me, reload: reloadMe } = useMe();
  const agent = useApi<Agent>("/agent");
  const [sweep, setSweep] = useState(me.company.sweep_time ?? "19:00");
  const [view, setView] = useState<"flow" | "keywords" | "fields">("flow");
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      toast(ok);
      agent.reload();
      reloadMe();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    } finally {
      setBusy(false);
    }
  }
  const a = agent.data;

  return (
    <div className="max-w-4xl space-y-6">
      <PageHeader title="Settings" sub={`Voice agent, phone number and automatic calls for ${me.company.name}.`} />

      <Card title="Voice agent" icon={Bot}>
        {!a ? <Skeleton className="h-16" /> : !a.agent_id ? (
          <div className="flex flex-wrap items-center gap-3 text-sm text-muted">No agent yet.<Link href="/setup"><Button size="sm">Go to Setup</Button></Link></div>
        ) : (
          <div className="space-y-4">
            {a.localhost_warning && (
              <div className="flex gap-2 rounded-xl bg-warn/10 px-3 py-2 text-sm text-warn"><TriangleAlert size={16} className="mt-0.5 shrink-0" />
                Backend address is {a.public_base_url}. Bolna can&apos;t reach it, so tools, caller lookup and the webhook won&apos;t work until you set a public URL and re-sync.</div>
            )}
            <div className="flex flex-wrap items-center gap-3">
              <Badge tone="good">live</Badge>
              <code className="rounded-lg bg-soft px-2 py-1 text-xs">{a.agent_id}</code>
              <span className="text-xs text-muted">Last synced {when(a.synced_at)}</span>
              <Button size="sm" variant="secondary" icon={RefreshCw} disabled={busy} className="ml-auto"
                onClick={() => run(() => api("/agent/sync", { method: "POST" }), "Agent re-synced with your latest names and settings.")}>
                {busy ? "Syncing…" : "Re-sync agent"}
              </Button>
            </div>
            <p className="text-xs text-muted">Re-sync after changing master data or the backend address, so the call flow, keywords, tools and webhook stay current.</p>
          </div>
        )}
      </Card>

      <Card title="Phone number" icon={Phone}>
        {a?.agent_id ? <NumberPicker linked={a.phone_number} onLinked={() => { agent.reload(); reloadMe(); }} /> : <p className="text-sm text-muted">Create the agent first.</p>}
      </Card>

      <Card title="Automatic follow-up calls" icon={PhoneForwarded}>
        <p className="mb-3 text-sm text-muted">When a rep mentions their next visit (&ldquo;10 din baad&rdquo;, &ldquo;agle Monday&rdquo;), Saathi calls them that morning with the doctor&apos;s briefing and any open promise.</p>
        <div className="flex flex-wrap items-center gap-2">
          <Tabs value={me.company.auto_followup ? "on" : "off"} onChange={(v) => run(() => api("/settings", { method: "PATCH", json: { auto_followup: v === "on" } }), v === "on" ? "Follow-up calls on." : "Follow-up calls off.")}
            options={[{ value: "on", label: "On" }, { value: "off", label: "Off" }]} />
          {me.company.auto_followup && <>
            <span className="text-sm text-muted">at</span>
            <Input type="time" defaultValue={me.company.followup_time} className="w-32"
              onBlur={(e) => e.target.value !== me.company.followup_time && run(() => api("/settings", { method: "PATCH", json: { followup_time: e.target.value } }), `Follow-up calls at ${e.target.value}.`)} />
          </>}
        </div>
      </Card>

      <Card title="Evening sweep" icon={Clock}>
        <p className="mb-3 text-sm text-muted">Each evening, Saathi calls every active rep who hasn&apos;t reported a visit that day. A call that came through too badly to use gets one callback.</p>
        <div className="flex flex-wrap items-center gap-2">
          <Input type="time" value={sweep} onChange={(e) => setSweep(e.target.value)} className="w-32" />
          <Button size="sm" disabled={busy} onClick={() => run(() => api("/settings", { method: "PATCH", json: { sweep_time: sweep } }), `Evening sweep on, at ${sweep} IST.`)}>Save</Button>
          <Button size="sm" variant="ghost" disabled={busy || !me.company.sweep_time}
            onClick={() => run(() => api("/settings", { method: "PATCH", json: { sweep_time: "" } }), "Evening sweep turned off.")}>Turn off</Button>
          <Badge tone={me.company.sweep_time ? "good" : "default"} className="ml-auto">{me.company.sweep_time ? `On at ${me.company.sweep_time} IST` : "Off"}</Badge>
        </div>
      </Card>

      {a && (
        <Card title="What the agent knows" icon={Code2} action={<Tabs value={view} onChange={setView} options={[
          { value: "flow", label: "Call flow", count: a.nodes.length }, { value: "keywords", label: "Keywords" }, { value: "fields", label: "Fields", count: a.extractions.length },
        ]} />}>
          <div className="mb-3 rounded-xl bg-brand-soft px-3 py-2 text-sm"><span className="font-semibold text-brand">Greeting: </span>{a.welcome}</div>
          {view === "flow" && <CallFlow nodes={a.nodes} />}
          {view === "keywords" && <div className="flex flex-wrap gap-1.5">{a.keywords.split(",").map((k) => k.trim()).filter(Boolean).map((k) => <Badge key={k} tone="brand">{k}</Badge>)}</div>}
          {view === "fields" && <div className="flex flex-wrap gap-1.5">{a.extractions.map((x) => <Badge key={x}>{x}</Badge>)}</div>}
        </Card>
      )}
    </div>
  );
}
