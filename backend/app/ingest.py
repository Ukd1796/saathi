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
from .models import Call, Chemist, Doctor, Product, Promise, Rep, StockOut, Visit, VisitItem, utcnow
from .names import Resolver
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
        area=area or fields["area"] or (doctor.area if doctor else None),
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
        if call.rep is None:
            call.process_note += f"; unknown rep phone {call.rep_phone}"
    session.commit()
    return call
