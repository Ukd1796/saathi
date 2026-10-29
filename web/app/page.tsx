import Link from "next/link";
import {
  ArrowRight, AudioLines, BrainCircuit, HandHeart, Languages, PackageX, PhoneCall, ShieldCheck, Sparkles, SpellCheck,
  Upload, Users,
} from "lucide-react";

const FEATURES = [
  { icon: PhoneCall, title: "Debrief in 60 seconds", text: "After each visit the rep calls and talks naturally. Saathi asks only for what's missing, reads it back, and the visit is on your dashboard before they reach the next clinic." },
  { icon: BrainCircuit, title: "Briefing before the visit", text: "\"Dr Patil se milne ja raha hoon\" (\"I'm going to see Dr Patil\"). Saathi recaps the last visit, the samples given, open promises and nearby stock-outs." },
  { icon: SpellCheck, title: "Your names, not a guess", text: "Every product, doctor and chemist is checked against your own lists while the call is still going. Corrections are learnt, so the same mistake never happens twice." },
  { icon: Users, title: "Nothing lost when a rep leaves", text: "History lives with the doctor. The next rep gets every promise and every objection on day one." },
  { icon: HandHeart, title: "Promises kept", text: "\"I'll bring the study next week\" becomes a tracked follow-up, and it's flagged once it's overdue." },
  { icon: PackageX, title: "Stock-outs near prescribers", text: "Empty shelves are grouped by area, next to the doctors prescribing that brand nearby." },
];

const STEPS = [
  { icon: Upload, title: "Upload your lists", text: "Reps, products, doctors and chemists, as CSV. One click creates your voice agent." },
  { icon: PhoneCall, title: "Reps call after each visit", text: "On any phone, in Hinglish or English. No app to install, no forms to fill." },
  { icon: Sparkles, title: "Everything lands structured", text: "Visits, samples, orders, promises and stock-outs, per doctor, live." },
];

const TRANSCRIPT = [
  { who: "Rep", text: "Dr Sharma se mil ke aaya, Andheri mein. Telma 40 ke 4 strip diye." },
  { who: "Saathi", text: "Theek hai. Koi chemist visit kiya?" },
  { who: "Rep", text: "Krishna Medical, Montair LC ka order 30. Pan D khatam hai wahan." },
  { who: "Saathi", text: "Dr Sharma, Andheri: Telma 40 ke 4 sample, Krishna Medical pe Montair LC 30, Pan D stock-out. Sahi hai?" },
];

export default function Home() {
  return (
    <div className="bg-bg">
      <div className="relative overflow-hidden bg-gradient-to-br from-[#1e1b4b] via-brand to-[#7c3aed] text-white">
        <div className="pointer-events-none absolute -right-32 -top-32 size-[28rem] rounded-full bg-coral/40 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-40 left-1/3 size-[24rem] rounded-full bg-sky-400/20 blur-3xl" />
        <header className="relative mx-auto flex max-w-6xl items-center justify-between px-4 py-5 md:px-6">
          <span className="flex items-center gap-2 text-lg font-bold">
            <span className="flex size-8 items-center justify-center rounded-xl bg-white/15"><AudioLines size={17} /></span>Saathi
          </span>
          <div className="flex items-center gap-2 text-sm">
            <Link href="/login" className="rounded-xl px-3 py-2 font-medium text-white/80 hover:text-white">Log in</Link>
            <Link href="/signup" className="rounded-xl bg-white px-4 py-2 font-semibold text-[#14162b] shadow-sm hover:bg-white/90">Get started</Link>
          </div>
        </header>

        <section className="relative mx-auto grid max-w-6xl items-center gap-10 px-4 pb-20 pt-10 md:px-6 lg:grid-cols-2 lg:pt-16">
          <div>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-white/15 px-3 py-1 text-xs font-semibold"><Languages size={13} />Built for Hinglish-speaking field teams</span>
            <h1 className="mt-5 text-4xl font-extrabold leading-[1.1] tracking-tight md:text-5xl">The medical rep&apos;s memory, <span className="text-coral">on any phone.</span></h1>
            <p className="mt-5 max-w-xl text-lg text-white/80">
              Reps make a one-minute call after each doctor visit. Saathi turns it into a structured visit report, checks every name against your own lists, and remembers every promise, sample and stock-out per doctor.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/signup" className="inline-flex items-center gap-2 rounded-xl bg-coral px-5 py-3 font-semibold text-white shadow-lg shadow-coral/30 hover:brightness-105">
                Set up your company <ArrowRight size={17} />
              </Link>
              <Link href="/login" className="rounded-xl border border-white/30 px-5 py-3 font-semibold text-white hover:bg-white/10">I have an account</Link>
            </div>
            <p className="mt-4 text-xs text-white/60">Keep your existing SFA. No app for reps to install.</p>
          </div>

          <div className="rounded-3xl bg-white/10 p-3 shadow-2xl ring-1 ring-white/20 backdrop-blur">
            <div className="rounded-2xl bg-card p-5 text-ink">
              <div className="mb-4 flex items-center gap-2 text-xs font-semibold text-muted">
                <span className="size-2 animate-pulse rounded-full bg-good" />Live call · 0:42
              </div>
              <div className="space-y-2.5">
                {TRANSCRIPT.map((t, i) => (
                  <div key={i} className={`flex ${t.who === "Saathi" ? "justify-start" : "justify-end"}`}>
                    <div className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-sm ${t.who === "Saathi" ? "rounded-tl-sm bg-brand-soft" : "rounded-tr-sm bg-brand text-white"}`}>{t.text}</div>
                  </div>
                ))}
              </div>
              <div className="mt-4 grid grid-cols-3 gap-2 border-t border-line pt-4 text-center">
                <div className="rounded-xl bg-brand-soft py-2"><div className="text-lg font-bold text-brand">4</div><div className="text-[11px] text-muted">samples</div></div>
                <div className="rounded-xl bg-good/12 py-2"><div className="text-lg font-bold text-good">30</div><div className="text-[11px] text-muted">ordered</div></div>
                <div className="rounded-xl bg-coral-soft py-2"><div className="text-lg font-bold text-coral">1</div><div className="text-[11px] text-muted">stock-out</div></div>
              </div>
            </div>
          </div>
        </section>
      </div>

      <section className="mx-auto max-w-6xl px-4 py-20 md:px-6">
        <div className="text-center">
          <div className="text-sm font-bold uppercase tracking-widest text-coral">How it works</div>
          <h2 className="mt-2 text-3xl font-bold tracking-tight text-ink">Live in an afternoon</h2>
        </div>
        <div className="mt-10 grid gap-5 md:grid-cols-3">
          {STEPS.map((s, i) => (
            <div key={s.title} className="relative rounded-2xl border border-line bg-card p-6">
              <span className="absolute right-5 top-5 text-4xl font-extrabold text-brand-soft">{i + 1}</span>
              <span className="flex size-11 items-center justify-center rounded-xl bg-brand text-white"><s.icon size={20} /></span>
              <h3 className="mt-4 font-semibold text-ink">{s.title}</h3>
              <p className="mt-1.5 text-sm text-muted">{s.text}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 pb-20 md:px-6">
        <div className="text-center">
          <div className="text-sm font-bold uppercase tracking-widest text-coral">What you get</div>
          <h2 className="mt-2 text-3xl font-bold tracking-tight text-ink">Field intelligence, without the forms</h2>
        </div>
        <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <div key={f.title} className="rounded-2xl border border-line bg-card p-6 transition hover:-translate-y-0.5 hover:shadow-lg">
              <span className="flex size-11 items-center justify-center rounded-xl bg-coral-soft text-coral"><f.icon size={20} /></span>
              <h3 className="mt-4 font-semibold text-ink">{f.title}</h3>
              <p className="mt-1.5 text-sm text-muted">{f.text}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 pb-20 md:px-6">
        <div className="grid items-center gap-8 rounded-3xl bg-gradient-to-r from-brand to-[#7c3aed] p-8 text-white md:grid-cols-[1fr_auto] md:p-12">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-white/80"><ShieldCheck size={16} />Made for India</div>
            <h2 className="mt-2 text-2xl font-bold md:text-3xl">Veeva&apos;s voice agent doesn&apos;t list Hindi. No Indian pharma SFA has voice at all.</h2>
            <p className="mt-3 max-w-2xl text-white/80">Saathi is built for it: Hindi, English and everything in between, with Indian brand names matched against your own catalogue.</p>
          </div>
          <Link href="/signup" className="inline-flex items-center justify-center gap-2 rounded-xl bg-white px-6 py-3 font-semibold text-[#14162b] hover:bg-white/90">Get started <ArrowRight size={17} /></Link>
        </div>
      </section>

      <footer className="border-t border-line py-8 text-center text-xs text-muted">Saathi · Built on Bolna voice agents</footer>
    </div>
  );
}
