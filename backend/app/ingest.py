"""Bolna execution payload -> Call row, and for completed debrief calls, a Visit.

Bolna POSTs the webhook on every status change (queued, ringing, in-progress, ...), each time
with the full execution. Only `completed` has the transcript and extracted_data filled in, so
that's the one that creates the Visit. Processing is idempotent: a repeated `completed` for the
same execution id updates the Call and leaves the existing Visit alone, while one that arrives
after a `completed` without extracted data still gets its Visit built.

Names are linked only on a high-confidence match (names.Resolver.link). Anything else is kept
as raw text in `visit.unmatched`, with the resolver's suggestion, for the review queue.
"""

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from .extraction import call_type, parse_visit
from .matching import phone_key
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .models import Call, Chemist, Doctor, Product, Promise, Rep, StockOut, ToolEvent, Visit, VisitItem, utcnow
from .names import Resolver, learn_alias
from .actions import on_visit
from .outbound import cut_off


def _rep_phone(payload):
    """The rep is the caller on inbound calls and the callee on outbound (sweep) calls."""
    tel = payload.get("telephony_data") or {}
    direction = (tel.get("call_type") or "").lower() or None
    if direction == "outbound":
        number = tel.get("to_number") or payload.get("user_number")
    else:
        number = tel.get("from_number") or payload.get("user_number")
    return direction, number


def find_rep(session, company_id, number):
    key = phone_key(number)
    if not key:
        return None
    for rep in session.scalars(select(Rep).where(Rep.company_id == company_id)):
        if phone_key(rep.phone) == key:
            return rep
    return None


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def upsert_call(session: Session, company_id: int, payload: dict) -> Call:
    call_id = str(payload.get("id") or payload.get("execution_id") or "")
    if not call_id:
        raise ValueError("payload has no execution id")
    direction, number = _rep_phone(payload)
    call = session.get(Call, call_id) or Call(id=call_id, company_id=company_id, raw={}, status="unknown")
    if call.company_id != company_id:
        raise ValueError("execution belongs to another company")
    call.agent_id = payload.get("agent_id") or call.agent_id
    call.status = payload.get("status") or call.status
    call.direction = direction or call.direction
    call.rep_phone = number or call.rep_phone
    call.rep = call.rep or find_rep(session, company_id, number)
    call.duration_s = _to_float(payload.get("conversation_duration")) or call.duration_s
    call.cost = _to_float(payload.get("total_cost")) or call.cost
    call.transcript = payload.get("transcript") or call.transcript
    call.extracted = payload.get("extracted_data") or payload.get("custom_extractions") or call.extracted
    call.raw = payload
    session.add(call)
    return call


def _by_name(session, model, company_id, name):
    if not name:
        return None
    return session.scalar(select(model).where(model.company_id == company_id, model.name == name))


def build_visit(session: Session, call: Call) -> Visit | None:
    fields = parse_visit(call.extracted)
    if fields is None:
        return None
    with session.no_autoflush:  # the half-built Visit must not flush while names are looked up
        return _build_visit(session, call, fields)


def _build_visit(session, call, fields):
    cid = call.company_id
    resolver = Resolver(session, cid, call.rep)
    unmatched = []

    def link(kind, model, heard):
        m = resolver.resolve(heard, kind)
        if m.confidence == "high":
            return _by_name(session, model, cid, m.best)
        miss = {"kind": kind, "heard": heard, "suggestion": m.best or (m.alternatives or [None])[0]}
        if not any(u["kind"] == kind and u["heard"] == heard for u in unmatched):
            unmatched.append(miss)  # same name can appear in discussed, samples and stock-outs
        return None

    doctor = link("doctor", Doctor, fields["doctor_name"])
    chemist = link("chemist", Chemist, fields["chemist_name"]) if fields["chemist_name"] else None
    area = resolver.link(fields["area"], "area") if fields["area"] else None
    discussed = []
    for name in fields["products_discussed"]:
        p = link("product", Product, name)
        discussed.append(p.name if p else name)

    visit = Visit(
        company_id=cid, call=call, rep=call.rep, doctor=doctor, doctor_raw=fields["doctor_name"],
        area=area or (doctor.area if doctor else None) or fields["area"],  # a garbled area loses to the doctor's
        chemist=chemist, chemist_raw=fields["chemist_name"],
        products_discussed=discussed, feedback=fields["feedback"],
        next_visit_raw=fields["next_visit"], visited_at=call.created_at or utcnow(),
    )
    for kind in ("samples", "orders"):
        for name, qty in fields[kind]:
            visit.items.append(VisitItem(kind=kind[:-1], product=link("product", Product, name),
                                         product_raw=name, quantity=qty))
    for name in fields["stock_outs"]:
        visit.stock_outs.append(StockOut(chemist=chemist, product=link("product", Product, name), product_raw=name))
    for text in fields["promises"]:
        visit.promises.append(Promise(doctor_id=doctor.id if doctor else None, text=text))
    if doctor and fields["promises_done"]:
        close_promises(session, doctor.id, fields["promises_done"])
    visit.unmatched = unmatched
    session.add(visit)
    return visit


def close_promises(session, doctor_id, done_texts):
    """The rep said an earlier promise was kept ("study de diya"): close the closest open one."""
    open_ = list(session.scalars(select(Promise).where(Promise.doctor_id == doctor_id, Promise.status == "open")))
    for text in done_texts:
        best = max(open_, key=lambda p: fuzz.token_set_ratio(p.text, text), default=None)
        if best and fuzz.token_set_ratio(best.text, text) >= 60:
            best.status, best.closed_at = "done", utcnow()
            open_.remove(best)


def process_payload(session: Session, company_id: int, payload: dict) -> Call:
    call = upsert_call(session, company_id, payload)
    session.flush()
    call.call_type = call_type(call.extracted) or call.call_type
    # Extraction can finish after the first `completed` POST, so keep trying until a visit exists.
    if call.status == "completed" and call.visit is None:
        call.processed_at = utcnow()
        dropped = call.call_type != "briefing" and cut_off(call)
        visit = None if call.call_type == "briefing" or dropped else build_visit(session, call)
        if call.call_type == "briefing":
            call.process_note = "briefing"
        elif dropped:
            call.process_note = "cut off before the read-back; Saathi will call back"
        elif visit is None:
            call.process_note = "no visit in extracted_data"
        elif visit.unmatched:
            call.process_note = f"{len(visit.unmatched)} name(s) not matched"
        else:
            call.process_note = "ok"
        if visit is not None:
            session.flush()  # the visit and its promises need ids before actions point at them
            on_visit(session, visit)
            learn_from_call(session, visit)
        if call.rep is None:
            call.process_note += f"; unknown rep phone {call.rep_phone}"
    session.commit()
    return call


def _when(raw, key_):
    try:
        return datetime.fromisoformat(raw[key_].replace("Z", "+00:00")).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    except (KeyError, AttributeError, TypeError, ValueError):
        return None


def call_events(session, call: Call):
    """The names Saathi checked during this call (tool calls carry the rep's number, not the call id)."""
    if not call.rep_id:
        return []
    raw = call.raw or {}
    start = _when(raw, "initiated_at") or call.created_at
    end = _when(raw, "updated_at") or (start + timedelta(seconds=(call.duration_s or 0) + 120))
    return session.scalars(select(ToolEvent).where(ToolEvent.company_id == call.company_id, ToolEvent.rep_id == call.rep_id,
                                                   ToolEvent.created_at >= start - timedelta(seconds=5),
                                                   ToolEvent.created_at <= end + timedelta(seconds=5))
                           .order_by(ToolEvent.created_at)).all()


def learn_from_call(session, visit: Visit):
    """The rep confirmed the read-back, so every name Saathi was unsure of during the call now has a
    known answer: remember the heard form, and next time it resolves straight away. Learning comes
    from the company's own calls, not from rules written in advance."""
    names = Resolver(session, visit.company_id).names
    final = {
        "doctor": [visit.doctor.name] if visit.doctor else [],
        "chemist": [visit.chemist.name] if visit.chemist else [],
        "area": [visit.area] if visit.area in names["area"] else [],
        "product": sorted({i.product.name for i in [*visit.items, *visit.stock_outs] if i.product}
                          | {p for p in visit.products_discussed or [] if p in names["product"]}),
    }
    events = [e for e in call_events(session, visit.call) if e.tool == "resolve_names" and e.heard]
    for kind, answers in final.items():
        for e in events:
            # Only a guess that turned out right is learnt ("Dr Rao?" -> "haan"). A word Saathi couldn't
            # place at all is never tied to the confirmed name: on 29 Oct "बजट रिपोर्ट" (a garbled
            # "visit report") got learnt as Dr Kulkarni that way.
            if e.kind == kind and e.confidence == "medium" and e.best in answers:
                learn_alias(session, visit.company_id, kind, e.heard, e.best)
