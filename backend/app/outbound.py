"""Calls Saathi places to reps: the evening sweep (no visit reported today), a callback after a
debrief that came through too badly to use, and the manager's "call now" button. All three go
through call_rep(), which records an OutboundCall row whether Bolna accepted it or not."""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from . import bolna
from .config import TIMEZONE
from .models import Call, Company, OutboundCall, Rep, Visit, utcnow

log = logging.getLogger("saathi.outbound")
CALLBACK_GAP = timedelta(hours=1)
TZ = ZoneInfo(TIMEZONE)


def local_now():
    return datetime.now(TZ)


def start_of_local_day_utc():
    start = local_now().replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def call_rep(session, company: Company, rep: Rep, reason: str) -> OutboundCall:
    row = OutboundCall(company_id=company.id, rep_id=rep.id, reason=reason)
    try:
        if not company.bolna_agent_id:
            raise bolna.BolnaError("create the voice agent first")
        mode = {"sweep": "sweep", "callback": "callback"}.get(reason, "inbound")
        res = bolna.make_call(company.bolna_agent_id, rep.phone,
                              user_data={"rep_name": rep.name, "mode": mode, "my_doctors": "", "open_promises": ""},
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
