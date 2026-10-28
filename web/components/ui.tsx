"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronRight, Search, X, type LucideIcon } from "lucide-react";
import { useEffect, type ReactNode } from "react";

type Tone = "default" | "brand" | "coral" | "good" | "warn" | "bad";

const TINT: Record<Tone, string> = {
  default: "bg-soft text-muted",
  brand: "bg-brand-soft text-brand",
  coral: "bg-coral-soft text-coral",
  good: "bg-good/12 text-good",
  warn: "bg-warn/12 text-warn",
  bad: "bg-bad/12 text-bad",
};

export function Card({ title, icon: Icon, action, children, className = "", pad = true }: {
  title?: ReactNode; icon?: LucideIcon; action?: ReactNode; children: ReactNode; className?: string; pad?: boolean;
}) {
  return (
    <section className={`rounded-2xl border border-line bg-card shadow-[0_1px_2px_rgba(20,22,43,0.04)] ${className}`}>
      {(title || action) && (
        <div className="flex items-center justify-between gap-2 border-b border-line px-5 py-3.5">
          {title && (
            <h2 className="flex items-center gap-2 text-sm font-semibold text-ink">
              {Icon && <Icon size={16} className="text-brand" />}{title}
            </h2>
          )}
          {action}
        </div>
      )}
      <div className={pad ? "p-5" : ""}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, icon: Icon, tone = "brand", sub, href }: {
  label: string; value: ReactNode; icon: LucideIcon; tone?: Tone; sub?: ReactNode; href?: string;
}) {
  const body = (
    <div className="group flex h-full items-start gap-3 rounded-2xl border border-line bg-card p-4 transition hover:-translate-y-0.5 hover:border-brand/40 hover:shadow-md">
      <span className={`flex size-10 shrink-0 items-center justify-center rounded-xl ${TINT[tone]}`}><Icon size={19} /></span>
      <div className="min-w-0">
        <div className="text-2xl font-bold tabular-nums leading-tight text-ink">{value}</div>
        <div className="text-xs font-medium text-muted">{label}</div>
        {sub && <div className="mt-1 text-xs text-muted">{sub}</div>}
      </div>
    </div>
  );
  return href ? <Link href={href} className="block">{body}</Link> : body;
}

export function Badge({ children, tone = "default", className = "" }: { children: ReactNode; tone?: Tone; className?: string }) {
  return <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${TINT[tone]} ${className}`}>{children}</span>;
}

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger" | "coral"; size?: "sm" | "md"; icon?: LucideIcon;
};

export function Button({ children, variant = "primary", size = "md", icon: Icon, className = "", ...props }: ButtonProps) {
  const v = {
    primary: "bg-brand text-white shadow-sm hover:brightness-110",
    coral: "bg-coral text-white shadow-sm hover:brightness-105",
    secondary: "border border-line bg-card text-ink hover:border-brand/40 hover:text-brand",
    ghost: "text-muted hover:bg-soft hover:text-ink",
    danger: "bg-bad text-white hover:brightness-110",
  }[variant];
  const s = size === "sm" ? "h-8 px-2.5 text-xs" : "h-9 px-3.5 text-sm";
  return (
    <button {...props} className={`inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-xl font-semibold transition disabled:pointer-events-none disabled:opacity-50 ${v} ${s} ${className}`}>
      {Icon && <Icon size={size === "sm" ? 14 : 16} />}{children}
    </button>
  );
}

export function EmptyState({ icon: Icon, title, children, action }: { icon: LucideIcon; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-10 text-center">
      <span className="flex size-12 items-center justify-center rounded-2xl bg-brand-soft text-brand"><Icon size={22} /></span>
      <div className="mt-3 font-semibold text-ink">{title}</div>
      {children && <div className="mt-1 max-w-sm text-sm text-muted">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function PageHeader({ title, sub, crumbs, action }: {
  title: ReactNode; sub?: ReactNode; crumbs?: { href: string; label: string }[]; action?: ReactNode;
}) {
  return (
    <div className="mb-6">
      {crumbs && (
        <nav className="mb-1.5 flex items-center gap-1 text-xs text-muted">
          {crumbs.map((c) => (
            <span key={c.href} className="flex items-center gap-1">
              <Link href={c.href} className="hover:text-brand">{c.label}</Link><ChevronRight size={12} />
            </span>
          ))}
        </nav>
      )}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold tracking-tight text-ink">{title}</h1>
          {sub && <p className="mt-1 max-w-2xl text-sm text-muted">{sub}</p>}
        </div>
        {action && <div className="flex flex-wrap gap-2">{action}</div>}
      </div>
    </div>
  );
}

export function ErrorNote({ error }: { error: { message: string } | null | undefined }) {
  if (!error) return null;
  return <div className="rounded-xl border border-bad/30 bg-bad/10 px-3 py-2 text-sm text-bad">{error.message}</div>;
}

const field = "h-9 w-full rounded-xl border border-line bg-card px-3 text-sm text-ink outline-none transition placeholder:text-muted/70 focus:border-brand focus:ring-3 focus:ring-brand/15";

export function Input({ className = "", ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${field} ${className}`} />;
}

export function Select({ className = "", children, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`${field} pr-8 ${className}`}>{children}</select>;
}

export function Label({ text, children }: { text: string; children: ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-xs font-semibold text-ink">{text}</span>
      {children}
    </label>
  );
}

export function SearchInput({ value, onChange, placeholder = "Search…", className = "" }: {
  value: string; onChange: (v: string) => void; placeholder?: string; className?: string;
}) {
  return (
    <div className={`relative ${className}`}>
      <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className={`${field} pl-9`} />
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, options }: {
  value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode; count?: number }[];
}) {
  return (
    <div className="inline-flex flex-wrap gap-1 rounded-xl bg-soft p-1">
      {options.map((o) => (
        <button key={o.value} onClick={() => onChange(o.value)}
          className={`flex h-7 items-center gap-1.5 rounded-lg px-3 text-xs font-semibold transition ${o.value === value ? "bg-card text-brand shadow-sm" : "text-muted hover:text-ink"}`}>
          {o.label}
          {o.count != null && <span className={`rounded-full px-1.5 text-[10px] ${o.value === value ? "bg-brand-soft" : "bg-line"}`}>{o.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Table({ head, children }: { head: ReactNode[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-line bg-soft/60 text-xs uppercase tracking-wide text-muted">
            {head.map((h, i) => <th key={i} className="whitespace-nowrap px-4 py-2.5 font-semibold">{h}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">{children}</tbody>
      </table>
    </div>
  );
}

/** A table row that opens `href` when clicked anywhere (links and buttons inside still work). */
export function Tr({ href, children, className = "" }: { href?: string; children: ReactNode; className?: string }) {
  const router = useRouter();
  return (
    <tr onClick={href ? (e) => { if (!(e.target as HTMLElement).closest("a,button,select,input")) router.push(href); } : undefined}
      className={`transition hover:bg-brand-soft/40 ${href ? "cursor-pointer" : ""} ${className}`}>
      {children}
    </tr>
  );
}

export function Td({ children, className = "" }: { children?: ReactNode; className?: string }) {
  return <td className={`px-4 py-3 align-top ${className}`}>{children}</td>;
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-xl bg-soft ${className}`} />;
}

export function LoadingRows({ rows = 5 }: { rows?: number }) {
  return <div className="space-y-2 p-5">{Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-10" />)}</div>;
}

const AVATAR = ["bg-brand-soft text-brand", "bg-coral-soft text-coral", "bg-good/12 text-good", "bg-warn/12 text-warn", "bg-sky-500/12 text-sky-600"];

export function Avatar({ name, size = "md" }: { name: string; size?: "sm" | "md" | "lg" }) {
  const clean = name.replace(/^Dr\.?\s+/i, "");
  const initials = clean.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase() || "?";
  const hash = [...name].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);
  const s = { sm: "size-7 text-[10px]", md: "size-9 text-xs", lg: "size-14 text-lg" }[size];
  return <span className={`inline-flex shrink-0 items-center justify-center rounded-full font-bold ${s} ${AVATAR[hash % AVATAR.length]}`}>{initials}</span>;
}

export function Modal({ open, onClose, title, children, footer }: {
  open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-[#14162b]/40 p-0 backdrop-blur-sm sm:items-center sm:p-4" onClick={onClose}>
      <div role="dialog" aria-modal className="w-full max-w-lg rounded-t-2xl border border-line bg-card shadow-2xl sm:rounded-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <h3 className="font-semibold text-ink">{title}</h3>
          <button onClick={onClose} className="rounded-lg p-1 text-muted hover:bg-soft hover:text-ink" aria-label="Close"><X size={18} /></button>
        </div>
        <div className="space-y-4 px-5 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

/** Vertical bars for a short daily series. */
export function BarChart({ data, height = 160 }: { data: { label: string; value: number; hint?: string }[]; height?: number }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <div>
      <div className="flex items-end gap-1.5" style={{ height }}>
        {data.map((d, i) => (
          <div key={i} className="group relative flex h-full flex-1 flex-col justify-end">
            <span className="pointer-events-none absolute -top-1 left-1/2 z-10 -translate-x-1/2 -translate-y-full whitespace-nowrap rounded-lg bg-ink px-2 py-1 text-[11px] font-medium text-card opacity-0 transition group-hover:opacity-100">
              {d.hint ?? d.label}: {d.value}
            </span>
            <div className={`w-full rounded-t-md transition ${d.value ? "bg-brand group-hover:bg-coral" : "bg-line"}`}
              style={{ height: `${Math.max(d.value ? 6 : 3, (d.value / max) * 100)}%` }} />
          </div>
        ))}
      </div>
      <div className="mt-2 flex gap-1.5 text-[10px] text-muted">
        {data.map((d, i) => <span key={i} className="flex-1 text-center">{i % 2 === data.length % 2 ? d.label : ""}</span>)}
      </div>
    </div>
  );
}

/** A ranked list with proportional bars. */
export function HBarList({ items, tone = "brand", empty }: { items: { name: string; count: number }[]; tone?: "brand" | "coral"; empty: string }) {
  if (!items.length) return <div className="py-6 text-center text-sm text-muted">{empty}</div>;
  const max = Math.max(...items.map((i) => i.count));
  return (
    <ul className="space-y-3">
      {items.map((i) => (
        <li key={i.name}>
          <div className="mb-1 flex justify-between text-sm"><span className="truncate text-ink">{i.name}</span><span className="font-semibold tabular-nums text-muted">{i.count}</span></div>
          <div className="h-2 rounded-full bg-soft">
            <div className={`h-2 rounded-full ${tone === "brand" ? "bg-brand" : "bg-coral"}`} style={{ width: `${(i.count / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}
