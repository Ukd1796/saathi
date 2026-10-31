"""Calls Saathi places to reps: the evening sweep (no visit reported today), a callback after a
debrief that came through too badly to use, the manager's "call now" button, calls the manager
scheduled, and a resume call when a report was cut off. All go through call_rep(), which records an
OutboundCall row whether Bolna accepted it or not."""

import re

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from . import bolna
from .config import TIMEZONE
from .models import Call, Company, Doctor, OutboundCall, Promise, Rep, ScheduledCall, Visit, utcnow

log = logging.getLogger("saathi.outbound")
CALLBACK_GAP = timedelta(hours=1)
CALLING_HOURS = ("09:00", "21:00")  # never ring a rep outside these (local time)
LATE_LIMIT_MIN = 30  # a scheduled call missed by more than this (server down) is skipped, not placed late
RETRY_AFTER = timedelta(minutes=10)
RESUME_AFTER = timedelta(minutes=2)
MODES = {"sweep": "sweep", "callback": "callback", "scheduled": "sweep", "briefing": "briefing", "resume": "resume"}
TZ = ZoneInfo(TIMEZONE)


def local_now():
    return datetime.now(TZ)


def start_of_local_day_utc():
    start = local_now().replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


MY_DOCTORS_LIMIT = 30  # the rep's doctors in the prompt, most recently visited first


def rep_context(session, rep: Rep) -> dict:
    """What the agent knows about this rep before the call starts: their own doctors and the
    promises still open with them. The same for calls the rep makes and calls Saathi makes."""
    doctors = session.scalars(select(Doctor).where(Doctor.company_id == rep.company_id)).all()
    mine = [d for d in doctors if d.assigned_rep_id == rep.id or (d.area and d.area in rep.areas)]
    last = dict(session.execute(select(Visit.doctor_id, func.max(Visit.visited_at))
                                .where(Visit.rep_id == rep.id).group_by(Visit.doctor_id)).all())
    mine.sort(key=lambda d: (last.get(d.id) is None, -(last[d.id].timestamp() if d.id in last else 0), d.name))
    mine = mine[:MY_DOCTORS_LIMIT]
    open_ = session.scalars(select(Promise).where(Promise.status == "open",
                                                  Promise.doctor_id.in_([d.id for d in mine]))).all() if mine else []
    return {"my_doctors": ", ".join(f"{d.name} ({d.area})" if d.area else d.name for d in mine) or "none listed",
            "open_promises": "; ".join(f"{p.doctor.name}: {p.text}" for p in open_ if p.doctor) or "none"}


def _note(notes, field):
    m = re.search(rf"{field}: ([^;]+)", notes or "")
    return m.group(1).strip() if m else None


def greeting(rep: Rep | None, mode: str, notes: str = "") -> str:
    """Saathi's first line, for this rep and this reason for calling. Built from the rep's record and
    the call's notes; the agent then carries on from it."""
    name = f" {rep.name.split()[0]}" if rep and rep.name else ""
    doctor = _note(notes, "doctor")
    if mode == "resume":
        about = f", {doctor} वाली" if doctor else ""
        return f"नमस्ते{name}! साथी बोल रही हूँ। आपकी पिछली visit report बीच में कट गई थी{about}। उसे पूरा कर लें?"
    if mode == "briefing":
        if doctor:
            return f"Good morning{name}! साथी बोल रही हूँ। आज {doctor} से मिलना है। Briefing दूँ?"
        return f"Good morning{name}! साथी बोल रही हूँ। आज किस doctor से मिलने जा रहे हैं? मैं briefing दे सकती हूँ।"
    if mode == "sweep":
        return f"नमस्ते{name}! साथी बोल रही हूँ। आज की visit report बाकी है। कौनसे doctor से मिले?"
    return f"नमस्ते{name}! साथी बोल रही हूँ। Visit report देनी है, या किसी doctor की briefing चाहिए?"


def call_rep(session, company: Company, rep: Rep, reason: str, mode: str | None = None, notes: str = "") -> OutboundCall:
    row = OutboundCall(company_id=company.id, rep_id=rep.id, reason=reason)
    try:
        if not company.bolna_agent_id:
            raise bolna.BolnaError("create the voice agent first")
        mode = mode or MODES.get(reason, "inbound")
        res = bolna.make_call(company.bolna_agent_id, rep.phone,
                              user_data={"rep_name": rep.name, "mode": mode, "resume_notes": notes,
                                         "greeting": greeting(rep, mode, notes), **rep_context(session, rep)},
                              from_number=company.phone_number)
        row.execution_id = res.get("execution_id") or res.get("call_id")
    except bolna.BolnaError as exc:
        row.error = str(exc)[:300]
        log.warning("outbound %s to rep %s failed: %s", reason, rep.id, exc)
    session.add(row)
    session.commit()
    return row


def needs_callback(call: Call) -> bool:
    """A debrief that ended with nothing usable: no visit (and not a briefing) or too many unknown names."""
    if call.direction == "outbound" or call.call_type == "briefing" or call.rep is None:
        return False
    if call.visit is None:
        return (call.duration_s or 0) >= 20  # a few seconds is a pocket dial or an instant hang-up
    return len(call.visit.unmatched) > 2


def maybe_callback(session, company: Company, call: Call):
    if not needs_callback(call):
        return None
    recent = session.scalar(select(OutboundCall).where(
        OutboundCall.rep_id == call.rep_id, OutboundCall.reason == "callback",
        OutboundCall.created_at >= utcnow() - CALLBACK_GAP))
    if recent:
        return None  # at most one callback per rep per hour
    return call_rep(session, company, call.rep, "callback")


def reps_without_visits_today(session, company_id):
    since = start_of_local_day_utc()
    reported = set(session.scalars(select(Visit.rep_id).where(Visit.company_id == company_id, Visit.visited_at >= since)))
    reps = session.scalars(select(Rep).where(Rep.company_id == company_id, Rep.status == "active"))
    return [r for r in reps if r.id not in reported]


def run_sweeps(session):
    """Called every minute: run each company's evening sweep once, at or after its sweep time."""
    now = local_now()
    today = now.strftime("%Y-%m-%d")
    for company in session.scalars(select(Company).where(Company.sweep_time.is_not(None), Company.bolna_agent_id.is_not(None))):
        h, m = map(int, company.sweep_time.split(":"))
        minutes_late = now.hour * 60 + now.minute - (h * 60 + m)
        if company.last_sweep_on == today or not 0 <= minutes_late <= 120:
            continue  # not yet, already done, or too late at night to ring reps (server was down)
        company.last_sweep_on = today
        session.commit()
        for rep in reps_without_visits_today(session, company.id):
            call_rep(session, company, rep, "sweep")


def visits_today(session, company_id):
    return session.scalar(select(func.count(Visit.id)).where(Visit.company_id == company_id,
                                                              Visit.visited_at >= start_of_local_day_utc()))


# ---- scheduled calls ----------------------------------------------------------------------------

def in_calling_hours(hhmm: str) -> bool:
    return CALLING_HOURS[0] <= hhmm <= CALLING_HOURS[1]


def _due_today(sc: ScheduledCall, now) -> bool:
    today = now.strftime("%Y-%m-%d")
    if sc.repeat == "once":
        return sc.run_on == today
    if sc.repeat == "weekdays":
        return now.weekday() < 5
    return True  # daily


def reported_today(session, rep_id) -> bool:
    return session.scalar(select(func.count(Visit.id)).where(Visit.rep_id == rep_id,
                                                             Visit.visited_at >= start_of_local_day_utc())) > 0


def run_scheduled(session):
    """Called every minute: place each scheduled call once, at or just after its time."""
    now = local_now()
    today, hhmm = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
    due = session.scalars(select(ScheduledCall).join(Company, ScheduledCall.company_id == Company.id)
                          .where(ScheduledCall.active.is_(True), Company.bolna_agent_id.is_not(None)))
    for sc in due:
        if sc.repeat == "once" and sc.run_on and sc.run_on < today:
            sc.active, sc.last_result = False, "missed"  # the server was down at the time
            continue
        if not _due_today(sc, now) or sc.last_run_on == today:
            continue
        h, m = map(int, sc.time.split(":"))
        late = now.hour * 60 + now.minute - (h * 60 + m)
        if late < 0:
            continue
        sc.last_run_on = today
        if sc.repeat == "once":
            sc.active = False
        if late > LATE_LIMIT_MIN or not in_calling_hours(hhmm):
            sc.last_result = "skipped: outside calling hours"
        elif sc.rep.status != "active":
            sc.last_result = "skipped: rep has left"
        elif sc.purpose == "report" and reported_today(session, sc.rep_id):
            sc.last_result = "skipped: already reported today"
        elif sc.purpose == "resume" and reported_since(session, sc.rep_id, sc.created_at):
            sc.last_result = "skipped: the rep has reported since"
        else:
            row = call_rep(session, session.get(Company, sc.company_id), sc.rep,
                           "resume" if sc.purpose == "resume" else "scheduled",
                           mode={"report": "sweep"}.get(sc.purpose, sc.purpose), notes=sc.note or "")
            sc.last_execution_id = row.execution_id
            sc.last_result = f"failed: {row.error}" if row.error else "called"
    session.commit()


def schedule_once(session, company_id, rep_id, purpose, after: timedelta, note=None, source_call_id=None, is_retry=False):
    at = local_now() + after
    sc = ScheduledCall(company_id=company_id, rep_id=rep_id, purpose=purpose, time=at.strftime("%H:%M"),
                       repeat="once", run_on=at.strftime("%Y-%m-%d"), note=note,
                       source_call_id=source_call_id, is_retry=is_retry)
    session.add(sc)
    session.commit()
    return sc


NO_ANSWER = {"no-answer", "busy", "failed", "canceled", "call-disconnected", "not-answered"}


def maybe_retry(session, call: Call):
    """A scheduled call the rep didn't pick up gets one more try ten minutes later."""
    if (call.status or "").lower() not in NO_ANSWER:
        return None
    sc = session.scalar(select(ScheduledCall).where(ScheduledCall.last_execution_id == call.id))
    if sc is None or sc.is_retry:
        return None
    if session.scalar(select(ScheduledCall).where(ScheduledCall.source_call_id == call.id)):
        return None  # webhooks repeat; retry once
    return schedule_once(session, sc.company_id, sc.rep_id, sc.purpose, RETRY_AFTER, note=sc.note,
                         source_call_id=call.id, is_retry=True)


# ---- reports cut off before the read-back ---------------------------------------------------------

def started(draft) -> bool:
    """The rep had begun telling a visit: the call's draft holds something they said, and they never
    confirmed it. A "hello" and a hang-up leaves no draft (31 Oct: it booked a resume call)."""
    return draft is not None and not draft.confirmed and any(
        str(v or "").strip().lower() not in ("", "missing") for k, v in (draft.heard or {}).items() if k != "promise_material")


# However the call ended, a report the rep started and never confirmed is not saved, so Saathi calls back.
# Including when Saathi itself ended it: on 31 Oct the voice model said "report हो गया" on its own, without
# check_visit, and hung up (d4aec100); and when the line went silent after a read-back Bolna never played
# (ac4a0650, inactivity_timeout).
CUT_OFF_ENDINGS = ("user_hung_up", "call-disconnected", "network_error", "max_duration_reached",
                   "agent_ended_call", "inactivity_timeout", "silence")


def cut_off(session, call: Call) -> bool:
    """The call ended before the rep said yes to the read-back, with part of the visit already told."""
    if call.call_type == "briefing" or call.rep is None or call.visit is not None:
        return False
    raw = call.raw or {}
    if (raw.get("termination_reason") or "") not in CUT_OFF_ENDINGS:
        return False
    from .ingest import call_draft
    return started(call_draft(session, call))


def reported_since(session, rep_id, since) -> bool:
    return session.scalar(select(func.count(Visit.id)).where(Visit.rep_id == rep_id, Visit.visited_at >= since)) > 0


def cancel_resumes(session, rep_id):
    """The rep recorded a visit: a resume call still waiting for an earlier cut-off report goes."""
    for sc in session.scalars(select(ScheduledCall).where(ScheduledCall.rep_id == rep_id, ScheduledCall.purpose == "resume",
                                                          ScheduledCall.active.is_(True))):
        sc.active, sc.last_result = False, "cancelled: the rep has reported since"
    session.commit()


def resume_notes(draft) -> str:
    """What the cut-off call's draft already held, for the agent to read back on the resume call."""
    fields = draft.fields or {}
    parts = []
    for key, label in (("doctor_name", "doctor"), ("area", "area"), ("products_discussed", "discussed"),
                       ("samples", "samples"), ("orders", "orders"), ("chemist_name", "chemist"),
                       ("stock_outs", "stock-outs"), ("promises", "promises"), ("next_visit", "next visit")):
        v = fields.get(key)
        if isinstance(v, list):  # samples/orders are (name, qty) pairs, the rest plain strings
            v = ", ".join(f"{x[0]} {x[1]}" if isinstance(x, (list, tuple)) else str(x) for x in v)
        if v:
            parts.append(f"{label}: {v}")
    return "; ".join(parts)


def maybe_resume(session, company: Company, call: Call):
    # A resume call never books another: on 31 Oct an unanswered one booked the next, and so on.
    if session.scalar(select(OutboundCall).where(OutboundCall.execution_id == call.id, OutboundCall.reason == "resume")):
        return None
    if not cut_off(session, call):
        return None
    if session.scalar(select(ScheduledCall).where(ScheduledCall.source_call_id == call.id)):
        return None
    from .ingest import call_draft
    return schedule_once(session, company.id, call.rep_id, "resume", RESUME_AFTER,
                         note=resume_notes(call_draft(session, call)), source_call_id=call.id)
