"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  AudioLines, ClipboardList, Database, Inbox, LayoutDashboard, LogOut, Menu, PackageX, Rocket,
  Settings, Stethoscope, UserCog, Users, X, type LucideIcon,
} from "lucide-react";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { type ActionItem, api, useApi, type Me } from "@/lib/api";
import { ToastProvider } from "@/components/toast";

const MeContext = createContext<{ me: Me; reload: () => void } | null>(null);

export function useMe() {
  const ctx = useContext(MeContext);
  if (!ctx) throw new Error("useMe outside Shell");
  return ctx;
}

type NavItem = { href: string; label: string; icon: LucideIcon; admin?: boolean; badge?: "actions" };
const NAV: { group: string; items: NavItem[] }[] = [
  { group: "Today", items: [
    { href: "/overview", label: "Overview", icon: LayoutDashboard },
    { href: "/actions", label: "Actions", icon: Inbox, badge: "actions" },
    { href: "/visits", label: "Visits", icon: ClipboardList },
  ] },
  { group: "Field", items: [
    { href: "/doctors", label: "Doctors", icon: Stethoscope },
    { href: "/stock-outs", label: "Stock-outs", icon: PackageX },
  ] },
  { group: "Team & data", items: [
    { href: "/reps", label: "Reps & handover", icon: Users },
    { href: "/users", label: "Users", icon: UserCog, admin: true },
    { href: "/data", label: "Master data", icon: Database, admin: true },
  ] },
];

type Counts = Record<"reps" | "products" | "doctors" | "chemists", number>;

export function useSetupProgress(me: Me) {
  const { data: counts, reload } = useApi<Counts>("/data/summary");
  const steps = [!!counts && counts.products > 0 && counts.reps > 0, !!me.company.agent_id, !!me.company.phone_number];
  return { counts, steps, done: steps.filter(Boolean).length, reload };
}

function NavLink({ item, path, onClick, badge }: { item: NavItem; path: string; onClick?: () => void; badge?: number }) {
  const active = path === item.href || path.startsWith(item.href + "/");
  const Icon = item.icon;
  return (
    <Link href={item.href} onClick={onClick}
      className={`flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition ${active ? "bg-white text-[#312e81] shadow-sm" : "text-sidebar-ink/75 hover:bg-white/10 hover:text-white"}`}>
      <Icon size={17} className={active ? "text-brand" : ""} />
      <span className="flex-1">{item.label}</span>
      {!!badge && <span className="rounded-full bg-coral px-1.5 py-0.5 text-[10px] font-bold text-white">{badge}</span>}
    </Link>
  );
}

function Sidebar({ me, path, onNavigate, logout }: { me: Me; path: string; onNavigate?: () => void; logout: () => void }) {
  const { done } = useSetupProgress(me);
  const { data: actions } = useApi<ActionItem[]>("/actions", 30000);
  const admin = me.role === "admin";
  return (
    <div className="flex h-full flex-col bg-sidebar px-3 py-4 text-sidebar-ink">
      <Link href="/overview" onClick={onNavigate} className="mb-6 flex items-center gap-2 px-2">
        <span className="flex size-8 items-center justify-center rounded-xl bg-gradient-to-br from-brand to-coral text-white"><AudioLines size={17} /></span>
        <span className="text-lg font-bold text-white">Saathi</span>
      </Link>
      <nav className="flex-1 space-y-5 overflow-y-auto">
        {NAV.map((g) => (
          <div key={g.group}>
            <div className="mb-1.5 px-3 text-[10px] font-bold uppercase tracking-widest text-sidebar-ink/45">{g.group}</div>
            <div className="space-y-0.5">
              {g.items.filter((item) => admin || !item.admin).map((item) => <NavLink key={item.href} item={item} path={path}
                onClick={onNavigate} badge={item.badge === "actions" ? actions?.length : undefined} />)}
            </div>
          </div>
        ))}
      </nav>
      <div className="space-y-0.5 border-t border-white/10 pt-3">
        {admin && <>
        <Link href="/setup" onClick={onNavigate}
          className={`flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition ${path === "/setup" ? "bg-white text-[#312e81]" : "text-sidebar-ink/75 hover:bg-white/10 hover:text-white"}`}>
          <Rocket size={17} />
          <span className="flex-1">Setup</span>
          {done < 3 ? <span className="rounded-full bg-coral/90 px-1.5 py-0.5 text-[10px] font-bold text-white">{done}/3</span>
            : <span className="text-[10px] font-semibold text-good">done</span>}
        </Link>
        <NavLink item={{ href: "/settings", label: "Settings", icon: Settings }} path={path} onClick={onNavigate} />
        </>}
        <div className="mt-3 flex items-center gap-2 rounded-xl bg-white/5 p-2.5">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-coral text-xs font-bold text-white">
            {me.name.slice(0, 1).toUpperCase()}
          </span>
          <div className="min-w-0 flex-1">
            <div className="truncate text-xs font-semibold text-white">{me.name}</div>
            <div className="truncate text-[11px] text-sidebar-ink/60">{admin ? "Admin" : "Manager"} · {me.company.name}</div>
          </div>
          <button onClick={logout} title="Log out" className="rounded-lg p-1.5 text-sidebar-ink/60 hover:bg-white/10 hover:text-white"><LogOut size={15} /></button>
        </div>
      </div>
    </div>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const { data: me, error, loading, reload } = useApi<Me>("/auth/me");
  const router = useRouter();
  const path = usePathname();
  const [drawer, setDrawer] = useState(false);

  useEffect(() => {
    if (error?.status === 401) router.replace(`/login?next=${encodeURIComponent(path)}`);
  }, [error, router, path]);

  const adminOnly = ["/setup", "/settings", "/data", "/users"].some((p) => path === p || path.startsWith(p + "/"));
  useEffect(() => {
    if (me?.role === "manager" && adminOnly) router.replace("/overview");
  }, [me, adminOnly, router]);

  if (loading || !me) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-2 text-sm text-muted">
        <span className="size-2 animate-ping rounded-full bg-brand" />{error && error.status !== 401 ? error.message : "Loading Saathi…"}
      </div>
    );
  }

  async function logout() {
    await api("/auth/logout", { method: "POST" });
    router.replace("/login");
  }

  const live = !!me.company.agent_id;
  return (
    <MeContext.Provider value={{ me, reload }}>
      <ToastProvider>
        <div className="flex min-h-screen">
          <aside className="sticky top-0 hidden h-screen w-64 shrink-0 lg:block">
            <Sidebar me={me} path={path} logout={logout} />
          </aside>
          {drawer && (
            <div className="fixed inset-0 z-40 bg-[#14162b]/50 lg:hidden" onClick={() => setDrawer(false)}>
              <div className="h-full w-72 [animation:drawer-in_.2s_ease-out]" onClick={(e) => e.stopPropagation()}>
                <Sidebar me={me} path={path} logout={logout} onNavigate={() => setDrawer(false)} />
              </div>
              <button className="absolute right-4 top-4 rounded-lg bg-white/10 p-2 text-white" aria-label="Close menu"><X size={18} /></button>
            </div>
          )}
          <div className="flex min-w-0 flex-1 flex-col">
            <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-card/85 px-4 backdrop-blur md:px-8">
              <button className="rounded-lg p-1.5 text-ink hover:bg-soft lg:hidden" onClick={() => setDrawer(true)} aria-label="Open menu"><Menu size={20} /></button>
              <span className="truncate text-sm font-semibold text-ink lg:hidden">Saathi</span>
              <span className="hidden truncate text-sm text-muted lg:block">{me.company.name}</span>
              <div className="ml-auto flex items-center gap-2">
                {me.role === "manager" ? (
                  <span className="flex items-center gap-1.5 rounded-full bg-brand-soft px-3 py-1 text-xs font-semibold text-brand">
                    <Users size={13} />Your team · {me.team_size ?? 0} rep{me.team_size === 1 ? "" : "s"}
                  </span>
                ) : (
                <Link href={live ? "/settings" : "/setup"}
                  className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${live ? "bg-good/12 text-good" : "bg-coral-soft text-coral"}`}>
                  <span className={`size-1.5 rounded-full ${live ? "animate-pulse bg-good" : "bg-coral"}`} />
                  {live ? me.company.phone_number ?? "Agent live" : "Agent not set up"}
                </Link>
                )}
              </div>
            </header>
            <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 md:px-8 md:py-8">{children}</main>
          </div>
        </div>
      </ToastProvider>
    </MeContext.Provider>
  );
}
