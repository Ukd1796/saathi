"use client";

import { Phone } from "lucide-react";
import { useState } from "react";
import { api, type ApiError } from "@/lib/api";
import { useToast } from "@/components/toast";
import { Badge, Button } from "@/components/ui";

type NumberRow = { id: string; phone_number: string; agent_id: string | null; provider: string; mine: boolean };

export function NumberPicker({ linked, onLinked }: { linked: string | null; onLinked: () => void }) {
  const toast = useToast();
  const [numbers, setNumbers] = useState<NumberRow[] | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    setBusy(true);
    try {
      setNumbers(await api<NumberRow[]>("/agent/numbers"));
    } catch (e) {
      toast((e as ApiError).message, "bad");
    } finally {
      setBusy(false);
    }
  }
  async function link(n: NumberRow) {
    setBusy(true);
    try {
      await api("/agent/number", { method: "POST", json: { phone_number_id: n.id } });
      toast(`Reps can now call ${n.phone_number}.`);
      setNumbers(null);
      onLinked();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        {linked ? <Badge tone="good"><Phone size={12} />{linked}</Badge> : <span className="text-sm text-muted">No number linked yet.</span>}
        <Button size="sm" variant="secondary" disabled={busy} onClick={load}>{busy && !numbers ? "Loading…" : linked ? "Change number" : "Choose a number"}</Button>
      </div>
      {numbers && (
        <div className="space-y-1.5">
          {numbers.length === 0 && <div className="rounded-xl bg-soft px-3 py-2 text-sm text-muted">No numbers in your Bolna account yet. Buy one in the Bolna dashboard, then come back.</div>}
          {numbers.map((n) => (
            <div key={n.id} className="flex items-center justify-between gap-2 rounded-xl border border-line px-3 py-2 text-sm">
              <span className="font-medium">{n.phone_number} <span className="text-xs font-normal text-muted">{n.provider}{n.agent_id && !n.mine ? " · used by another agent" : ""}</span></span>
              {n.mine ? <Badge tone="good">linked</Badge> : <Button size="sm" disabled={busy} onClick={() => link(n)}>Use this</Button>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
