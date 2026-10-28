"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Database, Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { api, type ApiError, mask, useApi } from "@/lib/api";
import { useToast } from "@/components/toast";
import { Uploader, type ListKind } from "@/components/uploader";
import { Badge, Button, Card, EmptyState, Input, Label, LoadingRows, Modal, PageHeader, SearchInput, Select, Table, Tabs, Td, Tr } from "@/components/ui";

type Row = { id: number; name: string; phone?: string; area?: string | null; manager?: string | null; status?: string;
  speciality?: string | null; rep?: string | null; rep_id?: number | null };
type Counts = Record<ListKind, number>;

const FIELDS: Record<ListKind, { key: keyof Row; label: string; placeholder: string }[]> = {
  products: [{ key: "name", label: "Product name, with strength", placeholder: "Telma 40" }],
  doctors: [
    { key: "name", label: "Name", placeholder: "Dr Sharma" },
    { key: "area", label: "Area", placeholder: "Andheri" },
    { key: "speciality", label: "Speciality", placeholder: "Cardiologist" },
  ],
  chemists: [{ key: "name", label: "Name", placeholder: "Krishna Medical" }, { key: "area", label: "Area", placeholder: "Andheri" }],
  reps: [
    { key: "name", label: "Name", placeholder: "Sneha Kulkarni" },
    { key: "phone", label: "Mobile number", placeholder: "98xxxxxxxx" },
    { key: "area", label: "Territory (separate areas with ;)", placeholder: "Dadar; Parel" },
    { key: "manager", label: "Manager", placeholder: "Rahul Desai" },
  ],
};
const SINGULAR: Record<ListKind, string> = { products: "product", doctors: "doctor", chemists: "chemist", reps: "rep" };

function EditModal({ kind, row, reps, onClose, onSaved }: { kind: ListKind; row: Row | "new"; reps: Row[]; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const isNew = row === "new";
  const [form, setForm] = useState<Record<string, string>>(() => {
    const r = isNew ? {} as Row : row;
    return Object.fromEntries([...FIELDS[kind].map((f) => [f.key, String(r[f.key] ?? "")]), ["rep_id", String(r.rep_id ?? "")]]);
  });
  const [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true);
    try {
      const body: Record<string, unknown> = { ...form };
      if (kind === "doctors") body.rep_id = form.rep_id ? Number(form.rep_id) : null;
      else delete body.rep_id;
      await api(isNew ? `/data/${kind}` : `/data/${kind}/${row.id}`, { method: isNew ? "POST" : "PATCH", json: body });
      toast(`${form.name} ${isNew ? "added" : "saved"}.`);
      onSaved();
    } catch (e) {
      toast((e as ApiError).message, "bad");
      setBusy(false);
    }
  }
  return (
    <Modal open onClose={onClose} title={isNew ? `Add ${SINGULAR[kind]}` : `Edit ${row.name}`}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button disabled={busy || !form.name?.trim()} onClick={save}>{isNew ? "Add" : "Save"}</Button></>}>
      {FIELDS[kind].map((f) => (
        <Label key={f.key} text={f.label}>
          <Input value={form[f.key]} placeholder={f.placeholder} onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
            inputMode={f.key === "phone" ? "tel" : undefined} autoFocus={f.key === "name"} />
        </Label>
      ))}
      {kind === "doctors" && (
        <Label text="Covered by">
          <Select value={form.rep_id} onChange={(e) => setForm({ ...form, rep_id: e.target.value })}>
            <option value="">Unassigned</option>
            {reps.filter((r) => r.status !== "left").map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </Select>
        </Label>
      )}
    </Modal>
  );
}

export default function DataPage() {
  const toast = useToast();
  const router = useRouter();
  const tab = (useSearchParams().get("tab") as ListKind | null) ?? "products";
  const counts = useApi<Counts>("/data/summary");
  const list = useApi<Row[]>(`/data/list/${tab}`);
  const reps = useApi<Row[]>("/data/list/reps");
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<Row | "new" | null>(null);
  const [deleting, setDeleting] = useState<Row | null>(null);
  const [changed, setChanged] = useState(false);

  function refresh() {
    list.reload();
    counts.reload();
    reps.reload();
    setChanged(true);
  }

  async function remove(r: Row) {
    try {
      await api(`/data/${tab}/${r.id}`, { method: "DELETE" });
      toast(`${r.name} deleted.`);
      setDeleting(null);
      refresh();
    } catch (e) {
      toast((e as ApiError).message, "bad");
      setDeleting(null);
    }
  }

  const rows = (list.data ?? []).filter((r) => {
    const needle = q.trim().toLowerCase();
    return !needle || [r.name, r.area, r.speciality, r.rep, r.manager].join(" ").toLowerCase().includes(needle);
  });
  const c = counts.data;
  const head = { products: ["Product"], doctors: ["Doctor", "Area", "Speciality", "Covered by"], chemists: ["Chemist", "Area"],
    reps: ["Rep", "Phone", "Territory", "Manager", "Status"] }[tab];

  return (
    <div>
      <PageHeader title="Master data"
        sub="The names Saathi checks every call against. The more complete these lists, the more accurately Saathi recognises them."
        action={<Button icon={Plus} onClick={() => setEditing("new")}>Add {SINGULAR[tab]}</Button>} />

      {changed && (
        <div className="mb-4 flex flex-wrap items-center gap-3 rounded-2xl border border-brand/30 bg-brand-soft px-4 py-3 text-sm text-ink">
          <RefreshCw size={16} className="text-brand" />
          <span className="flex-1">Lists changed. Re-sync the voice agent so the prompt and recognition keywords include the new names.</span>
          <Link href="/settings"><Button size="sm">Go to re-sync</Button></Link>
        </div>
      )}

      <div className="mb-4">
        <Tabs value={tab} onChange={(t) => { setQ(""); router.replace(`/data?tab=${t}`); }}
          options={(["products", "doctors", "chemists", "reps"] as ListKind[]).map((k) => ({ value: k, label: <span className="capitalize">{k}</span>, count: c?.[k] }))} />
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <Card pad={false} className="xl:col-span-2">
          <div className="border-b border-line p-4"><SearchInput value={q} onChange={setQ} placeholder={`Search ${tab}…`} /></div>
          {!list.data ? <LoadingRows /> : rows.length === 0 ? (
            <EmptyState icon={Database} title={list.data.length ? "No matches" : `No ${tab} yet`}
              action={!list.data.length && <Button icon={Plus} onClick={() => setEditing("new")}>Add {SINGULAR[tab]}</Button>}>
              {list.data.length ? "Try a different search." : "Upload a CSV on the right, or add them one by one."}
            </EmptyState>
          ) : (
            <Table head={[...head, ""]}>
              {rows.map((r) => (
                <Tr key={r.id}>
                  <Td className="font-semibold text-ink">{r.name}</Td>
                  {tab === "doctors" && <><Td>{r.area ?? "–"}</Td><Td>{r.speciality ? <Badge tone="brand">{r.speciality}</Badge> : "–"}</Td><Td>{r.rep ?? <Badge tone="warn">unassigned</Badge>}</Td></>}
                  {tab === "chemists" && <Td>{r.area ?? "–"}</Td>}
                  {tab === "reps" && <>
                    <Td className="whitespace-nowrap tabular-nums text-muted">{mask(r.phone)}</Td>
                    <Td>{r.area ?? "–"}</Td><Td>{r.manager ?? "–"}</Td>
                    <Td><Badge tone={r.status === "left" ? "default" : "good"}>{r.status}</Badge></Td>
                  </>}
                  <Td className="whitespace-nowrap text-right">
                    <button onClick={() => setEditing(r)} className="rounded-lg p-1.5 text-muted hover:bg-brand-soft hover:text-brand" aria-label={`Edit ${r.name}`}><Pencil size={15} /></button>
                    <button onClick={() => setDeleting(r)} className="rounded-lg p-1.5 text-muted hover:bg-bad/10 hover:text-bad" aria-label={`Delete ${r.name}`}><Trash2 size={15} /></button>
                  </Td>
                </Tr>
              ))}
            </Table>
          )}
        </Card>
        <div className="space-y-4">
          <Uploader key={tab} kind={tab} onDone={refresh} />
          <p className="px-1 text-xs text-muted">Re-uploading is safe: rows are matched by name ({tab === "reps" ? "phone for reps" : "case-insensitive"}) and updated, never duplicated.</p>
        </div>
      </div>

      {editing && <EditModal kind={tab} row={editing} reps={reps.data ?? []} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); refresh(); }} />}
      <Modal open={!!deleting} onClose={() => setDeleting(null)} title={`Delete ${deleting?.name}?`}
        footer={<><Button variant="ghost" onClick={() => setDeleting(null)}>Cancel</Button><Button variant="danger" icon={Trash2} onClick={() => deleting && remove(deleting)}>Delete</Button></>}>
        <p className="text-sm text-muted">This removes it from your list. Anything with visits on record can&apos;t be deleted, so history stays intact{tab === "reps" ? ": hand the rep over instead" : ""}.</p>
      </Modal>
    </div>
  );
}
