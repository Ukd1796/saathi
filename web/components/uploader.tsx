"use client";

import { FileDown, FileUp, TriangleAlert } from "lucide-react";
import { useRef, useState } from "react";
import { api, type ApiError } from "@/lib/api";
import { useToast } from "@/components/toast";
import { Button } from "@/components/ui";

export type ListKind = "reps" | "products" | "doctors" | "chemists";
type Preview = { rows: Record<string, string>[]; new: number; updated: number; errors: string[]; committed?: boolean };

export const LIST_HINTS: Record<ListKind, string> = {
  reps: "name, phone, area (several separated by ;), manager",
  products: "name, with strength: Telma 40, Pan D",
  doctors: "name, area, speciality, rep_phone (upload reps first)",
  chemists: "name, area",
};

/** Pick a CSV, see what it would change and which rows have errors, then save. */
export function Uploader({ kind, onDone }: { kind: ListKind; onDone: () => void }) {
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);

  async function send(f: File, commit: boolean) {
    const body = new FormData();
    body.append("file", f);
    setBusy(true);
    try {
      const res = await api<Preview>(`/data/upload/${kind}?commit=${commit}`, { method: "POST", body });
      if (commit) {
        toast(`Saved ${res.rows.length} ${kind}. Re-sync the agent in Settings so calls use the new names.`);
        setPreview(null);
        setFile(null);
        onDone();
      } else {
        setPreview(res);
      }
    } catch (e) {
      toast((e as ApiError).message, "bad");
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  return (
    <div className="rounded-2xl border-2 border-dashed border-line bg-soft/40 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className="flex size-10 items-center justify-center rounded-xl bg-brand-soft text-brand"><FileUp size={18} /></span>
        <div className="min-w-48 flex-1">
          <div className="text-sm font-semibold capitalize text-ink">Upload {kind} CSV</div>
          <div className="text-xs text-muted">Columns: {LIST_HINTS[kind]}</div>
        </div>
        <a href={`/api/data/template/${kind}.csv`} className="inline-flex h-8 items-center gap-1 rounded-xl px-2.5 text-xs font-semibold text-brand hover:bg-brand-soft"><FileDown size={14} />Template</a>
        <input ref={input} type="file" accept=".csv,text/csv" className="hidden"
          onChange={(e) => { const f = e.target.files?.[0] ?? null; setFile(f); setPreview(null); if (f) send(f, false); }} />
        <Button size="sm" variant="secondary" icon={FileUp} disabled={busy} onClick={() => input.current?.click()}>Choose file</Button>
      </div>
      {preview && file && (
        <div className="mt-3 space-y-2 rounded-xl bg-card p-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span><b>{file.name}</b>: {preview.new} new, {preview.updated} updated{preview.errors.length ? `, ${preview.errors.length} skipped` : ""}</span>
            {preview.rows.length > 0 && <Button size="sm" disabled={busy} onClick={() => send(file, true)}>Save {preview.rows.length} rows</Button>}
          </div>
          {preview.errors.map((e) => <div key={e} className="flex items-start gap-1.5 text-xs text-warn"><TriangleAlert size={13} className="mt-0.5 shrink-0" />{e}</div>)}
        </div>
      )}
    </div>
  );
}
