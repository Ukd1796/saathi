"""What a reported visit sets in motion: alerts and requests for the manager, a due date on each
promise, and Saathi's own follow-up call on the next-visit day. Nothing is ever sent to a doctor:
material requests (studies, literature, samples) wait for a manager's approval."""

import re
from datetime import date, timedelta

from sqlalchemy import select

from .briefing import is_overdue, local_today
from .dates import parse_when
from .models import Action, Company, Doctor, Promise, ScheduledCall, Visit, utcnow

STOCKOUT_REPEAT = timedelta(days=7)  # one open alert per product and chemist a week


def _name(item):
    return item.product.name if item.product else item.product_raw


def _today() -> date:
    return date.fromisoformat(local_today())


def on_visit(session, visit: Visit):
    """Run once, when a visit is first built (the visit and its promises are already flushed)."""
    company = session.get(Company, visit.company_id)
    today = _today()
    for p in visit.promises:
        due = parse_when(p.text, today)
        p.due_on = due.isoformat() if due else None
    stockout_alerts(session, visit)
    material_requests(session, visit)
    schedule_followup(session, company, visit, today)


def stockout_alerts(session, visit: Visit):
    chem = visit.chemist
    area = chem.area if chem else visit.area
    for so in visit.stock_outs:
        where = chem.name if chem else (visit.chemist_raw or "a chemist")
        title = f"{_name(so)} out at {where}" + (f" ({area})" if area else "")
        if session.scalar(select(Action).where(Action.company_id == visit.company_id, Action.kind == "stockout",
                                               Action.status == "open", Action.title == title,
                                               Action.created_at >= utcnow() - STOCKOUT_REPEAT)):
            continue
        nearby = [d.name for d in session.scalars(select(Doctor).where(Doctor.company_id == visit.company_id,
                                                                       Doctor.area == area))] if area else []
        detail = f"Reported by {visit.rep.name if visit.rep else 'a rep'}"
        if nearby:
            detail += f". Doctors nearby who may be prescribing it: {', '.join(nearby)}"
        session.add(Action(company_id=visit.company_id, kind="stockout", rep_id=visit.rep_id, doctor_id=visit.doctor_id,
                           visit_id=visit.id, chemist_id=chem.id if chem else None, title=title, detail=detail))


def material_requests(session, visit: Visit):
    """The extraction lists which promises are material for the doctor; match them to the promises."""
    from rapidfuzz import fuzz
    from .extraction import parse_visit
    wanted = (parse_visit(visit.call.extracted) or {}).get("materials", []) if visit.call else []
    doctor = visit.doctor.name if visit.doctor else visit.doctor_raw
    for p in visit.promises:
        if not any(fuzz.token_set_ratio(p.text, m) >= 80 for m in wanted):
            continue
        detail = f"For {doctor}, promised by {visit.rep.name if visit.rep else 'a rep'}"
        if p.due_on:
            detail += f", due {p.due_on}"
        session.add(Action(company_id=visit.company_id, kind="material", rep_id=visit.rep_id, doctor_id=visit.doctor_id,
                           visit_id=visit.id, promise_id=p.id, title=p.text, detail=detail))


def schedule_followup(session, company: Company, visit: Visit, today: date):
    """'Next visit 10 din baad' -> Saathi calls the rep that morning with the doctor's briefing."""
    if not company.auto_followup or visit.rep is None or visit.doctor is None:
        return None
    day = parse_when(visit.next_visit_raw, today)
    if day is None or day <= today:
        return None
    if session.scalar(select(ScheduledCall).where(ScheduledCall.source_call_id == visit.call_id,
                                                  ScheduledCall.purpose == "briefing")):
        return None
    sc = ScheduledCall(company_id=company.id, rep_id=visit.rep_id, purpose="briefing", time=company.followup_time,
                       repeat="once", run_on=day.isoformat(), note=f"doctor: {visit.doctor.name}",
                       source_call_id=visit.call_id)
    session.add(sc)
    return sc


# ---- the inbox ---------------------------------------------------------------------------------

DONE = ("approved", "declined", "done")


def _human(text):
    """'due 2026-11-25' -> 'due 25 Nov' for people reading the inbox."""
    return re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b",
                  lambda m: date(int(m[1]), int(m[2]), int(m[3])).strftime("%-d %b"), text or "") or None


def inbox(session, scope, status="open"):
    """Stored actions for this user, plus open promises that have gone overdue (worked out when
    read, so there is nothing to keep in sync)."""
    q = scope.reps(select(Action).where(Action.company_id == scope.company_id), Action.rep_id)
    q = q.where(Action.status == "open") if status == "open" else q.where(Action.status.in_(DONE))
    items = [{"id": f"a{a.id}", "action_id": a.id, "kind": a.kind, "status": a.status, "title": a.title,
              "detail": _human(a.detail), "rep": a.rep.name if a.rep else None, "doctor": a.doctor.name if a.doctor else None,
              "doctor_id": a.doctor_id, "visit_id": a.visit_id, "created_at": a.created_at.isoformat() + "Z",
              "resolved_at": a.resolved_at.isoformat() + "Z" if a.resolved_at else None}
             for a in session.scalars(q.order_by(Action.created_at.desc()).limit(200))]
    if status == "open":
        promises = session.scalars(scope.reps(select(Promise).join(Visit).where(Visit.company_id == scope.company_id,
                                                                               Promise.status == "open"), Visit.rep_id))
        for p in promises:
            if is_overdue(p):
                items.append({"id": f"p{p.id}", "promise_id": p.id, "kind": "overdue", "status": "open", "title": p.text,
                              "detail": _human(f"Promised to {p.doctor.name if p.doctor else p.visit.doctor_raw}"
                                               + (f", due {p.due_on}" if p.due_on else "")),
                              "rep": p.visit.rep.name if p.visit.rep else None,
                              "doctor": p.doctor.name if p.doctor else None, "doctor_id": p.doctor_id,
                              "visit_id": p.visit_id, "created_at": p.created_at.isoformat() + "Z", "resolved_at": None})
    return items
