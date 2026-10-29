"use client";

import { Copy, KeyRound, Pencil, Sparkles, Trash2, UserCog, UserPlus } from "lucide-react";
import { useState } from "react";
import { api, type ApiError, useApi, type UserRow } from "@/lib/api";
import { useMe } from "@/components/shell";
import { useToast } from "@/components/toast";
import { Avatar, Badge, Button, Card, EmptyState, Input, Label, LoadingRows, Modal, PageHeader, Table, Td, Tr } from "@/components/ui";

type Users = { users: UserRow[]; suggested: { name: string; rep_ids: number[] }[] };
type RepLite = { id: number; name: string; area: string | null; status: string; manager: string | null };

function slug(name: string) {
  return name.toLowerCase().replace(/\(.*?\)/g, "").trim().replace(/[^a-z0-9]+/g, ".").replace(/^\.|\.$/g, "");
}

function TeamPicker({ reps, value, onChange }: { reps: RepLite[]; value: number[]; onChange: (v: number[]) => void }) {
  return (
    <div className="max-h-56 space-y-1 overflow-auto rounded-xl border border-line p-2">
      {reps.filter((r) => r.status === "active").map((r) => (
        <label key={r.id} className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-soft">
          <input type="checkbox" checked={value.includes(r.id)} className="accent-[var(--brand)]"
            onChange={(e) => onChange(e.target.checked ? [...value, r.id] : value.filter((x) => x !== r.id))} />
          <span className="flex-1 text-ink">{r.name}</span>
          <span className="text-xs text-muted">{r.area ?? ""}</span>
        </label>
      ))}
    </div>
  );
}

export default function UsersPage() {
  const toast = useToast();
  const { me } = useMe();
  const users = useApi<Users>("/users");
  const reps = useApi<RepLite[]>("/reps");
  const [form, setForm] = useState<{ id?: number; name: string; email: string; rep_ids: number[] } | null>(null);
  const [password, setPassword] = useState<{ name: string; email: string; value: string } | null>(null);
  const [removing, setRemoving] = useState<UserRow | null>(null);
  const [busy, setBusy] = useState(false);

  const repName = (id: number) => reps.data?.find((r) => r.id === id)?.name ?? "";
  function refresh() {
    users.reload();
    reps.reload();
  }

  async function save() {
    if (!form) return;
    setBusy(true);
    try {
      if (form.id) {
        await api(`/users/${form.id}`, { method: "PATCH", json: { name: form.name, rep_ids: form.rep_ids } });
        toast(`${form.name}'s team updated.`);
      } else {
        const r = await api<{ password: string }>("/users", { method: "POST", json: form });
        setPassword({ name: form.name, email: form.email, value: r.password });
      }
      setForm(null);
      refresh();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    } finally {
      setBusy(false);
    }
  }

  async function reset(u: UserRow) {
    try {
      const r = await api<{ password: string }>(`/users/${u.id}/reset-password`, { method: "POST" });
      setPassword({ name: u.name, email: u.email, value: r.password });
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }

  async function remove(u: UserRow) {
    try {
      await api(`/users/${u.id}`, { method: "DELETE" });
      toast(`${u.name} removed. Their reps are unassigned.`);
      setRemoving(null);
      refresh();
    } catch (e) {
      toast((e as ApiError).message, "bad");
    }
  }

  const domain = me.email.split("@")[1] ?? "company.com";
  const loginUrl = typeof window !== "undefined" ? `${window.location.origin}/login` : "/login";

  return (
    <div className="max-w-5xl">
      <PageHeader title="Users" sub="Managers log in to see only their own team: their reps' visits, doctors, stock-outs and actions."
        action={<Button icon={UserPlus} onClick={() => setForm({ name: "", email: "", rep_ids: [] })}>Add manager</Button>} />

      {users.data && users.data.suggested.length > 0 && (
        <div className="mb-4 rounded-2xl border border-brand/30 bg-brand-soft/60 p-4">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-ink"><Sparkles size={15} className="text-brand" />Managers named in your reps list</div>
          <div className="flex flex-wrap gap-2">
            {users.data.suggested.map((s) => (
              <Button key={s.name} size="sm" variant="secondary" icon={UserPlus}
                onClick={() => setForm({ name: s.name.replace(/\s*\(.*\)$/, ""), email: `${slug(s.name)}@${domain}`, rep_ids: s.rep_ids })}>
                {s.name} · {s.rep_ids.length} rep{s.rep_ids.length > 1 ? "s" : ""}
              </Button>
            ))}
          </div>
        </div>
      )}

      <Card pad={false}>
        {!users.data ? <LoadingRows rows={3} /> : users.data.users.length === 0 ? (
          <EmptyState icon={UserCog} title="No users yet" />
        ) : (
          <Table head={["Name", "Role", "Team", ""]}>
            {users.data.users.map((u) => (
              <Tr key={u.id}>
                <Td>
                  <span className="flex items-center gap-3"><Avatar name={u.name} />
                    <span><span className="block font-semibold text-ink">{u.name}{u.id === me.id && <span className="font-normal text-muted"> (you)</span>}</span>
                      <span className="text-xs text-muted">{u.email}</span></span></span>
                </Td>
                <Td><Badge tone={u.role === "admin" ? "brand" : "default"} className="capitalize">{u.role}</Badge></Td>
                <Td className="text-sm">{u.role === "admin" ? <span className="text-muted">Everyone</span>
                  : u.rep_ids.length ? u.rep_ids.map(repName).join(", ") : <span className="text-warn">No reps yet</span>}</Td>
                <Td className="whitespace-nowrap text-right">
                  {u.role === "manager" && <>
                    <button onClick={() => setForm({ id: u.id, name: u.name, email: u.email, rep_ids: u.rep_ids })} className="rounded-lg p-1.5 text-muted hover:bg-brand-soft hover:text-brand" aria-label={`Edit ${u.name}`} title="Edit team"><Pencil size={15} /></button>
                    <button onClick={() => reset(u)} className="rounded-lg p-1.5 text-muted hover:bg-brand-soft hover:text-brand" aria-label={`Reset password for ${u.name}`} title="Reset password"><KeyRound size={15} /></button>
                    <button onClick={() => setRemoving(u)} className="rounded-lg p-1.5 text-muted hover:bg-bad/10 hover:text-bad" aria-label={`Remove ${u.name}`} title="Remove"><Trash2 size={15} /></button>
                  </>}
                </Td>
              </Tr>
            ))}
          </Table>
        )}
      </Card>

      <Modal open={!!form} onClose={() => setForm(null)} title={form?.id ? `Edit ${form.name}` : "Add a manager"}
        footer={<><Button variant="ghost" onClick={() => setForm(null)}>Cancel</Button>
          <Button disabled={busy || !form?.name.trim() || !form?.email.trim()} onClick={save}>{form?.id ? "Save" : "Add manager"}</Button></>}>
        {form && <>
          <Label text="Name"><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Rahul Desai" autoFocus /></Label>
          {!form.id && <Label text="Work email (their login)"><Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="rahul@company.com" /></Label>}
          <Label text={`Their reps (${form.rep_ids.length})`}>
            <TeamPicker reps={reps.data ?? []} value={form.rep_ids} onChange={(rep_ids) => setForm({ ...form, rep_ids })} />
          </Label>
        </>}
      </Modal>

      <Modal open={!!password} onClose={() => setPassword(null)} title={`Login for ${password?.name}`}
        footer={<Button onClick={() => setPassword(null)}>Done</Button>}>
        <p className="text-sm text-muted">Share these with them. The password is shown only now.</p>
        <div className="space-y-1 rounded-xl bg-soft p-3 font-mono text-sm">
          <div>{loginUrl}</div><div>{password?.email}</div><div className="font-semibold text-ink">{password?.value}</div>
        </div>
        <Button variant="secondary" icon={Copy} onClick={() => {
          navigator.clipboard?.writeText(`Saathi login\n${loginUrl}\nEmail: ${password?.email}\nPassword: ${password?.value}`);
          toast("Copied.");
        }}>Copy login details</Button>
      </Modal>

      <Modal open={!!removing} onClose={() => setRemoving(null)} title={`Remove ${removing?.name}?`}
        footer={<><Button variant="ghost" onClick={() => setRemoving(null)}>Cancel</Button>
          <Button variant="danger" icon={Trash2} onClick={() => removing && remove(removing)}>Remove</Button></>}>
        <p className="text-sm text-muted">They can no longer log in. Their reps stay, unassigned, and nothing they did is lost.</p>
      </Modal>
    </div>
  );
}
