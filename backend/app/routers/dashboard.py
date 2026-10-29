"""Read and act on the field data: overview, visits, doctors, promises, stock-outs, the review
queue for names the matcher could not place, and rep handover."""

import re
from collections import Counter
from datetime import datetime, timedelta

from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..briefing import doctor_brief, is_overdue
from ..ingest import call_events
from ..db import get_session
from ..models import (Action, Call, Chemist, Doctor, OutboundCall, Product, Promise, Rep, ScheduledCall, StockOut,
                      ToolEvent, User, Visit, utcnow)
from ..auth import Scope, admin_user, current_user, team_scope
from ..names import Resolver, learn_alias
from ..outbound import TZ, in_calling_hours, local_now, reps_without_visits_today, start_of_local_day_utc

router = APIRouter(prefix="/api")


def _iso(dt):
    return dt.isoformat() + "Z" if dt else None


def item_name(i):
    return i.product.name if i.product else i.product_raw


def visit_json(v: Visit, full=False):
    out = {
        "id": v.id, "call_id": v.call_id, "visited_at": _iso(v.visited_at),
        "rep": v.rep.name if v.rep else None, "rep_id": v.rep_id,
        "doctor": v.doctor.name if v.doctor else None, "doctor_id": v.doctor_id, "doctor_heard": v.doctor_raw,
        "area": v.area, "products_discussed": v.products_discussed,
        "samples": [{"product": item_name(i), "qty": i.quantity, "matched": i.product_id is not None}
                    for i in v.items if i.kind == "sample"],
        "orders": [{"product": item_name(i), "qty": i.quantity, "matched": i.product_id is not None}
                   for i in v.items if i.kind == "order"],
        "chemist": v.chemist.name if v.chemist else v.chemist_raw, "chemist_matched": v.chemist_id is not None,
        "stock_outs": [item_name(s) for s in v.stock_outs],
        "promises": [{"id": p.id, "text": p.text, "status": p.status, "due_on": p.due_on} for p in v.promises],
        "feedback": v.feedback, "next_visit": v.next_visit_raw, "unmatched": v.unmatched,
    }
    if full and v.call:
        out["call"] = {"duration_s": v.call.duration_s, "transcript": v.call.transcript, "direction": v.call.direction,
                       "extracted": v.call.extracted, "cost": v.call.cost, "recording_url": recording_url(v.call.raw)}
    return out


REASK = re.compile(r"dobara|दोबारा|phir se|फिर से|repeat|say that again|samajh nahi|समझ नहीं", re.I)


def call_quality(session, call: Call):
    """How hard the call was for the rep: names Saathi checked (and how sure it was), how often it
    asked again, and how the call ended."""
    raw = call.raw or {}
    events = call_events(session, call)
    lines = (call.transcript or "").splitlines()
    names = [{"kind": e.kind, "heard": e.heard, "best": e.best, "confidence": e.confidence} for e in events]
    return {
        "duration_s": call.duration_s,
        "rep_turns": sum(1 for l in lines if l.startswith("user:")),
        "reasks": sum(1 for l in lines if l.startswith("assistant:") and REASK.search(l)),
        "names": names,
        "ended_by": {"agent_ended_call": "Saathi", "user_hung_up": "rep"}.get(raw.get("termination_reason"), raw.get("termination_reason")),
    }


def recording_url(raw):
    raw = raw or {}
    return (raw.get("telephony_data") or {}).get("recording_url") or raw.get("recording_url")


def local_date(dt):
    return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ).date()


def _visit(session, scope: Scope, visit_id) -> Visit:
    v = session.get(Visit, visit_id)
    if v is None or v.company_id != scope.company_id or not scope.rep_ok(v.rep_id):
        raise HTTPException(404, "no such visit")
    return v


@router.get("/overview")
def overview(scope: Scope = Depends(team_scope), session: Session = Depends(get_session)):
    cid = scope.company_id
    today = start_of_local_day_utc()
    week = utcnow() - timedelta(days=7)
    calls = session.scalars(scope.reps(select(Call).where(Call.company_id == cid), Call.rep_id)
                            .order_by(Call.created_at.desc()).limit(15)).all()
    open_promises = session.scalars(scope.reps(select(Promise).join(Visit).where(Visit.company_id == cid,
                                                                                  Promise.status == "open"), Visit.rep_id)).all()
    overdue = [p for p in open_promises if is_overdue(p)]
    reps = session.scalars(scope.reps(select(Rep).where(Rep.company_id == cid, Rep.status == "active"), Rep.id)).all()
    per_rep = dict(session.execute(scope.reps(select(Visit.rep_id, func.count(Visit.id))
                                              .where(Visit.company_id == cid, Visit.visited_at >= today), Visit.rep_id)
                                   .group_by(Visit.rep_id)).all())
    overdue_by_rep = Counter(p.visit.rep_id for p in overdue)
    return {
        "visits_today": sum(per_rep.values()),
        "calls_today": session.scalar(scope.reps(select(func.count(Call.id)).where(Call.company_id == cid,
                                                                                   Call.created_at >= today), Call.rep_id)),
        "open_promises": len(open_promises), "overdue_promises": len(overdue),
        "stock_outs_week": session.scalar(scope.reps(select(func.count(StockOut.id)).join(Visit)
                                                     .where(Visit.company_id == cid, StockOut.created_at >= week), Visit.rep_id)),
        "open_actions": len(scoped_actions(session, scope, "open")),
        "reps_today": [{"id": r.id, "name": r.name, "visits": per_rep.get(r.id, 0)} for r in reps],
        "silent_reps": [r.name for r in reps_without_visits_today(session, cid) if scope.rep_ok(r.id)],
        **insights(session, cid, reps, scope, overdue_by_rep),
        "recent_calls": [{"id": c.id, "status": c.status, "rep": c.rep.name if c.rep else c.rep_phone,
                          "direction": c.direction, "call_type": c.call_type, "duration_s": c.duration_s,
                          "note": c.process_note, "visit_id": c.visit.id if c.visit else None,
                          "created_at": _iso(c.created_at)} for c in calls],
    }


TREND_DAYS = 14


def insights(session, cid, reps, scope: Scope, overdue_by_rep):
    """Chart data for the overview: visits per local day, per rep this week, top products and stock-outs."""
    since = start_of_local_day_utc() - timedelta(days=TREND_DAYS - 1)
    month = utcnow() - timedelta(days=30)
    week = utcnow() - timedelta(days=7)
    recent = session.scalars(scope.reps(select(Visit).where(Visit.company_id == cid, Visit.visited_at >= month),
                                        Visit.rep_id)).all()
    by_day = Counter(local_date(v.visited_at) for v in recent if v.visited_at >= since)
    first = local_date(since)
    trend = [{"date": (first + timedelta(days=i)).isoformat(), "visits": by_day.get(first + timedelta(days=i), 0)}
             for i in range(TREND_DAYS)]
    weekly = Counter(v.rep_id for v in recent if v.visited_at >= week)
    products = Counter(p for v in recent for p in set(v.products_discussed or []) | {item_name(i) for i in v.items})
    stockouts = Counter(item_name(s) for v in recent for s in v.stock_outs)
    return {
        "trend": trend,
        "leaderboard": sorted(({"id": r.id, "name": r.name, "visits": weekly.get(r.id, 0),
                                "overdue": overdue_by_rep.get(r.id, 0)} for r in reps), key=lambda r: -r["visits"]),
        "top_products": [{"name": n, "count": c} for n, c in products.most_common(6)],
        "top_stockouts": [{"name": n, "count": c} for n, c in stockouts.most_common(6)],
    }


def _parse_day(value, end=False):
    """'2026-10-29' (a local date) -> naive UTC bound for that day."""
    day = datetime.fromisoformat(value).replace(tzinfo=TZ)
    if end:
        day += timedelta(days=1)
    return day.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


@router.get("/visits")
def list_visits(rep_id: int | None = None, doctor_id: int | None = None, needs_review: bool = False, limit: int = 500,
                area: str | None = None, date_from: str | None = None, date_to: str | None = None,
                scope: Scope = Depends(team_scope), session: Session = Depends(get_session)):
    q = scope.reps(select(Visit).where(Visit.company_id == scope.company_id), Visit.rep_id)
    if rep_id:
        q = q.where(Visit.rep_id == rep_id)
    if doctor_id:
        q = q.where(Visit.doctor_id == doctor_id)
    if area:
        q = q.where(func.lower(Visit.area) == area.lower())
    try:
        if date_from:
            q = q.where(Visit.visited_at >= _parse_day(date_from))
        if date_to:
            q = q.where(Visit.visited_at < _parse_day(date_to, end=True))
    except ValueError:
        raise HTTPException(422, "dates must be YYYY-MM-DD")
    visits = session.scalars(q.order_by(Visit.visited_at.desc()).limit(limit)).all()
    return [visit_json(v) for v in visits if v.unmatched or not needs_review]


@router.get("/visits/{visit_id}")
def get_visit(visit_id: int, scope: Scope = Depends(team_scope), session: Session = Depends(get_session)):
    v = _visit(session, scope, visit_id)
    out = visit_json(v, full=True)
    if v.call:
        out["quality"] = call_quality(session, v.call)
    follow = session.scalar(select(ScheduledCall).where(ScheduledCall.source_call_id == v.call_id,
                                                        ScheduledCall.purpose == "briefing"))
    out["followup"] = {"run_on": follow.run_on, "time": follow.time, "active": follow.active,
                       "result": follow.last_result} if follow else None
    return out


@router.get("/doctors/{doctor_id}")
def get_doctor(doctor_id: int, scope: Scope = Depends(team_scope), session: Session = Depends(get_session)):
    d = session.get(Doctor, doctor_id)
    if d is None or d.company_id != scope.company_id or not scope.doctor_ok(d):
        raise HTTPException(404, "no such doctor")
    visits = session.scalars(select(Visit).where(Visit.doctor_id == d.id).order_by(Visit.visited_at.desc())).all()
    return {"id": d.id, "name": d.name, "area": d.area, "speciality": d.speciality,
            "rep": d.assigned_rep.name if d.assigned_rep else None, "rep_id": d.assigned_rep_id,
            "brief": doctor_brief(session, d),
            "visits": [visit_json(v) for v in visits]}


@router.get("/promises")
def list_promises(status: str = "open", scope: Scope = Depends(team_scope), session: Session = Depends(get_session)):
    q = scope.reps(select(Promise).join(Visit).where(Visit.company_id == scope.company_id), Visit.rep_id)
    if status in ("open", "done"):
        q = q.where(Promise.status == status)
    rows = session.scalars(q.order_by(Promise.created_at)).all()
    return [{"id": p.id, "text": p.text, "status": p.status, "created_at": _iso(p.created_at),
             "closed_at": _iso(p.closed_at), "age_days": (utcnow() - p.created_at).days,
             "overdue": is_overdue(p), "due_on": p.due_on,
             "doctor": p.doctor.name if p.doctor else p.visit.doctor_raw, "doctor_id": p.doctor_id,
             "rep": p.visit.rep.name if p.visit.rep else None, "visit_id": p.visit_id} for p in rows]


class PromiseUpdate(BaseModel):
    status: str


@router.patch("/promises/{promise_id}")
def update_promise(promise_id: int, body: PromiseUpdate, scope: Scope = Depends(team_scope),
                   session: Session = Depends(get_session)):
    p = session.get(Promise, promise_id)
    if (p is None or p.visit.company_id != scope.company_id or body.status not in ("open", "done")
            or not (scope.rep_ok(p.visit.rep_id) or (p.doctor and scope.doctor_ok(p.doctor)))):
        raise HTTPException(404, "no such promise")
    p.status = body.status
    p.closed_at = utcnow() if body.status == "done" else None
    session.commit()
    return {"id": p.id, "status": p.status}


@router.get("/stockouts")
def list_stockouts(days: int = 14, scope: Scope = Depends(team_scope), session: Session = Depends(get_session)):
    """Stock-outs grouped by product, with the chemists and areas they were seen in. A doctor
    in the same area as a stock-out is prescribing into an empty shelf."""
    since = utcnow() - timedelta(days=days)
    rows = session.scalars(scope.reps(select(StockOut).join(Visit).where(Visit.company_id == scope.company_id,
                                                                         StockOut.created_at >= since), Visit.rep_id)
                           .order_by(StockOut.created_at.desc())).all()
    groups = {}
    for s in rows:
        name = item_name(s)
        g = groups.setdefault(name, {"product": name, "reports": 0, "chemists": {}, "areas": set(), "last_seen": None})
        g["reports"] += 1
        chem = s.chemist.name if s.chemist else (s.visit.chemist_raw or "unknown chemist")
        area = s.chemist.area if s.chemist else s.visit.area
        g["chemists"][chem] = area
        if area:
            g["areas"].add(area)
        g["last_seen"] = max(filter(None, [g["last_seen"], _iso(s.created_at)]))
    doctors = [d for d in session.scalars(select(Doctor).where(Doctor.company_id == scope.company_id)) if scope.doctor_ok(d)]
    out = []
    for g in groups.values():
        affected = [d.name for d in doctors if d.area in g["areas"]]
        out.append({"product": g["product"], "reports": g["reports"], "last_seen": g["last_seen"],
                    "chemists": [{"name": n, "area": a} for n, a in g["chemists"].items()],
                    "areas": sorted(g["areas"]), "doctors_nearby": affected})
    return sorted(out, key=lambda g: -g["reports"])


# ---- review queue: names the matcher could not place --------------------------------------

@router.get("/review")
def review_queue(user: User = Depends(admin_user), session: Session = Depends(get_session)):
    visits = session.scalars(select(Visit).where(Visit.company_id == user.company_id)
                             .order_by(Visit.visited_at.desc())).all()
    resolver = Resolver(session, user.company_id)
    items = []
    for v in visits:
        for u in v.unmatched or []:
            options = resolver.names.get(u["kind"], [])
            items.append({"visit_id": v.id, "visited_at": _iso(v.visited_at), "rep": v.rep.name if v.rep else None,
                          "kind": u["kind"], "heard": u["heard"], "suggestion": u.get("suggestion"), "options": options})
    return items


class Resolution(BaseModel):
    visit_id: int
    kind: str
    heard: str
    target: str | None = None  # canonical name; None = dismiss (keep as typed)


@router.post("/review/resolve")
def resolve(body: Resolution, user: User = Depends(admin_user), session: Session = Depends(get_session)):
    """Link the heard name to the right record on this visit, and remember it for next time."""
    v = _visit(session, Scope(session, user), body.visit_id)
    cid = user.company_id
    if body.target:
        model = {"product": Product, "doctor": Doctor, "chemist": Chemist}.get(body.kind)
        if body.kind == "area":
            v.area = body.target
        else:
            obj = session.scalar(select(model).where(model.company_id == cid, model.name == body.target)) if model else None
            if obj is None:
                raise HTTPException(422, f"{body.target} is not in your {body.kind} list")
            if body.kind == "doctor" and v.doctor_raw == body.heard:
                v.doctor = obj
                v.area = v.area or obj.area
                for p in v.promises:
                    p.doctor_id = obj.id
            elif body.kind == "chemist" and v.chemist_raw == body.heard:
                v.chemist = obj
                for s in v.stock_outs:
                    s.chemist_id = obj.id
            elif body.kind == "product":
                for i in [*v.items, *v.stock_outs]:
                    if i.product_raw == body.heard:
                        i.product_id = obj.id
                v.products_discussed = [body.target if p == body.heard else p for p in v.products_discussed]
        learn_alias(session, cid, body.kind, body.heard, body.target)
    v.unmatched = [u for u in v.unmatched if not (u["kind"] == body.kind and u["heard"] == body.heard)]
    session.commit()
    return visit_json(v)


# ---- reps and handover -------------------------------------------------------------------

@router.get("/reps")
def list_reps(scope: Scope = Depends(team_scope), session: Session = Depends(get_session)):
    cid = scope.company_id
    reps = session.scalars(scope.reps(select(Rep).where(Rep.company_id == cid), Rep.id).order_by(Rep.status, Rep.name)).all()
    week = utcnow() - timedelta(days=7)
    counts = dict(session.execute(select(Visit.rep_id, func.count(Visit.id))
                                  .where(Visit.company_id == cid, Visit.visited_at >= week).group_by(Visit.rep_id)).all())
    doctors = dict(session.execute(select(Doctor.assigned_rep_id, func.count(Doctor.id))
                                   .where(Doctor.company_id == cid).group_by(Doctor.assigned_rep_id)).all())
    last_out = {}
    for o in session.scalars(select(OutboundCall).where(OutboundCall.company_id == cid).order_by(OutboundCall.created_at)):
        last_out[o.rep_id] = {"reason": o.reason, "at": _iso(o.created_at), "error": o.error}
    return [{"id": r.id, "name": r.name, "phone": r.phone, "area": r.area, "manager": r.manager, "status": r.status,
             "manager_user_id": r.manager_user_id,
             "visits_7d": counts.get(r.id, 0), "doctors": doctors.get(r.id, 0), "last_outbound": last_out.get(r.id)}
            for r in reps]


class Handover(BaseModel):
    to_rep_id: int


@router.post("/reps/{rep_id}/handover")
def handover(rep_id: int, body: Handover, scope: Scope = Depends(team_scope), session: Session = Depends(get_session)):
    """A rep leaves: their doctors (and with them the full history, open promises and briefings)
    move to the new rep. Nothing is copied, because everything is keyed by doctor."""
    old, new = session.get(Rep, rep_id), session.get(Rep, body.to_rep_id)
    cid = scope.company_id
    if (not old or not new or old.company_id != cid or new.company_id != cid or old.id == new.id
            or not scope.rep_ok(old.id) or not scope.rep_ok(new.id)):
        raise HTTPException(404, "pick two different reps from your team")
    doctors = session.scalars(select(Doctor).where(Doctor.assigned_rep_id == old.id)).all()
    for d in doctors:
        d.assigned_rep_id = new.id
    old.status = "left"
    for area in old.areas:
        if area not in new.areas:
            new.area = "; ".join([*new.areas, area])
    session.commit()
    open_promises = session.scalar(select(func.count(Promise.id)).where(
        Promise.status == "open", Promise.doctor_id.in_([d.id for d in doctors]))) if doctors else 0
    return {"moved_doctors": len(doctors), "open_promises": open_promises, "to": new.name}


class RepStatus(BaseModel):
    status: str


@router.patch("/reps/{rep_id}")
def update_rep(rep_id: int, body: RepStatus, scope: Scope = Depends(team_scope), session: Session = Depends(get_session)):
    rep = session.get(Rep, rep_id)
    if rep is None or rep.company_id != scope.company_id or not scope.rep_ok(rep.id) or body.status not in ("active", "left"):
        raise HTTPException(404, "no such rep")
    rep.status = body.status
    session.commit()
    return {"id": rep.id, "status": rep.status}


@router.get("/doctors")
def list_doctors(scope: Scope = Depends(team_scope), session: Session = Depends(get_session)):
    cid = scope.company_id
    doctors = [d for d in session.scalars(select(Doctor).where(Doctor.company_id == cid).order_by(Doctor.name))
               if scope.doctor_ok(d)]
    last = dict(session.execute(select(Visit.doctor_id, func.max(Visit.visited_at))
                                .where(Visit.company_id == cid).group_by(Visit.doctor_id)).all())
    open_ = session.scalars(select(Promise).join(Visit).where(Visit.company_id == cid, Promise.status == "open")).all()
    open_count = Counter(p.doctor_id for p in open_)
    overdue = Counter(p.doctor_id for p in open_ if is_overdue(p))
    return [{"id": d.id, "name": d.name, "area": d.area, "speciality": d.speciality,
             "rep": d.assigned_rep.name if d.assigned_rep else None, "last_visit": _iso(last.get(d.id)),
             "open_promises": open_count.get(d.id, 0), "overdue_promises": overdue.get(d.id, 0)} for d in doctors]


# ---- actions: what calls produced for the manager to act on --------------------------------

def scoped_actions(session, scope: Scope, status="open"):
    from ..actions import inbox
    return inbox(session, scope, status)


@router.get("/actions")
def list_actions(status: str = "open", scope: Scope = Depends(team_scope), session: Session = Depends(get_session)):
    return scoped_actions(session, scope, "open" if status == "open" else "done")


class ActionUpdate(BaseModel):
    status: str  # approved | declined | done | open


@router.patch("/actions/{action_id}")
def update_action(action_id: int, body: ActionUpdate, scope: Scope = Depends(team_scope),
                  session: Session = Depends(get_session)):
    a = session.get(Action, action_id)
    if a is None or a.company_id != scope.company_id or not scope.rep_ok(a.rep_id):
        raise HTTPException(404, "no such action")
    allowed = {"material": ("approved", "declined", "open"), "stockout": ("done", "open")}.get(a.kind, ())
    if body.status not in allowed:
        raise HTTPException(422, f"a {a.kind} action can be set to {', '.join(allowed)}")
    a.status = body.status
    a.resolved_at, a.resolved_by = (None, None) if body.status == "open" else (utcnow(), scope.user.id)
    session.commit()
    return {"id": a.id, "status": a.status}


# ---- scheduled calls -------------------------------------------------------------------------

class ScheduleIn(BaseModel):
    rep_id: int
    time: str  # HH:MM local
    repeat: str = "once"  # once | weekdays | daily
    purpose: str = "report"  # report | briefing


def schedule_json(sc: ScheduledCall):
    return {"id": sc.id, "rep_id": sc.rep_id, "rep": sc.rep.name, "purpose": sc.purpose, "time": sc.time,
            "repeat": sc.repeat, "run_on": sc.run_on, "active": sc.active, "last_run_on": sc.last_run_on,
            "last_result": sc.last_result, "automatic": sc.source_call_id is not None}


@router.get("/schedules")
def list_schedules(scope: Scope = Depends(team_scope), session: Session = Depends(get_session)):
    """Active schedules, plus the last few that ran, so the manager sees what happened."""
    rows = session.scalars(scope.reps(select(ScheduledCall).where(ScheduledCall.company_id == scope.company_id),
                                      ScheduledCall.rep_id).order_by(ScheduledCall.created_at.desc()).limit(50)).all()
    active = sorted((r for r in rows if r.active), key=lambda r: (r.run_on or "", r.time))
    done = [r for r in rows if not r.active][:8]
    return {"active": [schedule_json(r) for r in active], "recent": [schedule_json(r) for r in done]}


@router.post("/schedules")
def create_schedule(body: ScheduleIn, scope: Scope = Depends(team_scope), session: Session = Depends(get_session)):
    user = scope.user
    rep = session.get(Rep, body.rep_id)
    if rep is None or rep.company_id != user.company_id or rep.status != "active" or not scope.rep_ok(rep.id):
        raise HTTPException(404, "no such active rep")
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", body.time):
        raise HTTPException(422, "time must be HH:MM")
    if not in_calling_hours(body.time):
        raise HTTPException(422, "Saathi only calls reps between 9:00 and 21:00")
    if body.repeat not in ("once", "weekdays", "daily") or body.purpose not in ("report", "briefing"):
        raise HTTPException(422, "unknown repeat or purpose")
    now = local_now()
    run_on = None
    if body.repeat == "once":  # today if the time is still ahead, otherwise tomorrow
        day = now if body.time > now.strftime("%H:%M") else now + timedelta(days=1)
        run_on = day.strftime("%Y-%m-%d")
    sc = ScheduledCall(company_id=user.company_id, rep_id=rep.id, purpose=body.purpose, time=body.time,
                       repeat=body.repeat, run_on=run_on)
    session.add(sc)
    session.commit()
    return schedule_json(sc)


@router.delete("/schedules/{schedule_id}")
def cancel_schedule(schedule_id: int, scope: Scope = Depends(team_scope), session: Session = Depends(get_session)):
    sc = session.get(ScheduledCall, schedule_id)
    if sc is None or sc.company_id != scope.company_id or not scope.rep_ok(sc.rep_id):
        raise HTTPException(404, "no such schedule")
    sc.active, sc.last_result = False, "cancelled"
    session.commit()
    return schedule_json(sc)
