"""The pre-visit briefing: what the rep (or whoever had this doctor before them) needs to
remember before walking in. Keyed by doctor, not rep, so a handover gets the full history."""

from datetime import timedelta

from sqlalchemy import select

from .models import Chemist, Doctor, Promise, StockOut, Visit, utcnow

OVERDUE_DAYS = 7
STOCKOUT_DAYS = 14


def _ago(when):
    days = (utcnow() - when).days
    return "today" if days <= 0 else "yesterday" if days == 1 else f"{days} days ago"


def doctor_brief(session, doctor: Doctor) -> dict:
    visits = list(session.scalars(select(Visit).where(Visit.doctor_id == doctor.id)
                                  .order_by(Visit.visited_at.desc()).limit(3)))
    promises = list(session.scalars(select(Promise).where(Promise.doctor_id == doctor.id, Promise.status == "open")
                                    .order_by(Promise.created_at)))
    since = utcnow() - timedelta(days=STOCKOUT_DAYS)
    stock_outs = []
    if doctor.area:
        rows = session.execute(select(StockOut, Chemist).join(Chemist, StockOut.chemist_id == Chemist.id)
                               .where(Chemist.company_id == doctor.company_id, Chemist.area == doctor.area,
                                      StockOut.created_at >= since))
        seen = set()
        for so, chem in rows:
            name = so.product.name if so.product else so.product_raw
            if (name, chem.name) not in seen:
                seen.add((name, chem.name))
                stock_outs.append({"product": name, "chemist": chem.name})

    lines = []
    if visits:
        v = visits[0]
        who = f" by {v.rep.name}" if v.rep else ""
        lines.append(f"Last visit {_ago(v.visited_at)}{who}.")
        samples = [(f"{i.quantity} of " if i.quantity else "") + (i.product.name if i.product else i.product_raw)
                   for i in v.items if i.kind == "sample"]
        if samples:
            lines.append("Samples given: " + ", ".join(samples) + ".")  # "4 of Telma 40", never "Telma 40 4"
        if v.feedback:
            lines.append(f"Doctor's feedback: {v.feedback}")
        if v.next_visit_raw:
            lines.append(f"Planned next visit: {v.next_visit_raw}.")
    else:
        lines.append("No earlier visits recorded for this doctor.")
    for p in promises:
        overdue = (utcnow() - p.created_at).days > OVERDUE_DAYS
        lines.append(f"{'OVERDUE promise' if overdue else 'Open promise'} ({_ago(p.created_at)}): {p.text}")
    if stock_outs:
        lines.append("Out of stock nearby: " + ", ".join(f"{s['product']} at {s['chemist']}" for s in stock_outs) + ".")

    return {
        "doctor": doctor.name, "area": doctor.area, "speciality": doctor.speciality,
        "summary": " ".join(lines),
        "visits": [{"id": v.id, "visited_at": v.visited_at.isoformat(), "rep": v.rep.name if v.rep else None,
                    "feedback": v.feedback} for v in visits],
        "open_promises": [{"id": p.id, "text": p.text, "created_at": p.created_at.isoformat(),
                           "overdue": (utcnow() - p.created_at).days > OVERDUE_DAYS} for p in promises],
        "stock_outs_nearby": stock_outs,
    }
