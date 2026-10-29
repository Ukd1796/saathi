"""Endpoints Bolna calls: the post-call webhook, the inbound caller lookup (runs before the
call starts, 3 s budget) and the two custom functions the agent uses mid-call."""

import hmac
import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..briefing import doctor_brief
from ..db import get_session
from ..ingest import find_rep, process_payload
from ..models import Company, Doctor, Promise, Rep, ToolEvent
from ..names import Resolver, parse_items, spoken
from ..outbound import maybe_callback, maybe_resume, maybe_retry, rep_context

log = logging.getLogger("saathi.bolna")
router = APIRouter(prefix="/bolna")


def _company(session, company_id) -> Company:
    company = session.get(Company, int(company_id)) if str(company_id).isdigit() else None
    if company is None:
        raise HTTPException(status_code=404, detail="unknown company")
    return company


def _check(expected, given):
    given = (given or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(given, expected):
        raise HTTPException(status_code=401, detail="bad token")


async def _params(request: Request) -> dict:
    """Custom functions may send their params as JSON, form data or the query string."""
    params = dict(request.query_params)
    body = await request.body()
    if body:
        try:
            data = json.loads(body)
            if isinstance(data, str):
                data = json.loads(data)
            params.update(data if isinstance(data, dict) else {})
        except ValueError:
            form = await request.form()
            params.update({k: str(v) for k, v in form.items()})
    return params


@router.post("/webhook/{company_id}")
async def webhook(company_id: int, request: Request, x_webhook_secret: str = Header(default=""),
                  session: Session = Depends(get_session)):
    company = _company(session, company_id)
    _check(company.webhook_secret, x_webhook_secret)
    payload = await request.json()
    try:
        call = process_payload(session, company.id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    log.info("company %s call %s status=%s note=%s", company.id, call.id, call.status, call.process_note)
    maybe_retry(session, call)
    if call.status == "completed":
        maybe_resume(session, company, call) or maybe_callback(session, company, call)
    return {"ok": True, "call_id": call.id, "status": call.status, "note": call.process_note}


def _rep_for(session, company, params) -> Rep | None:
    for key in ("from_number", "contact_number", "to_number"):
        rep = find_rep(session, company.id, params.get(key))
        if rep:
            return rep
    return None


@router.get("/caller")
def caller(request: Request, company: str = "", contact_number: str = "", authorization: str = Header(default=""),
           session: Session = Depends(get_session)):
    """Before an inbound call starts, Bolna asks who is calling. Every top-level key becomes a
    {{variable}} in the prompt, so the agent knows the rep's name and their own doctors."""
    comp = _company(session, company)
    _check(comp.tool_token, authorization or request.query_params.get("token"))
    rep = find_rep(session, comp.id, contact_number)
    if rep is None:
        return {"rep_name": "", "rep_known": "no", "mode": "inbound", "my_doctors": "(unknown caller)", "resume_notes": ""}
    return {"rep_name": rep.name, "rep_known": "yes", "mode": "inbound", "resume_notes": "", **rep_context(session, rep)}


@router.api_route("/tools/resolve_names", methods=["GET", "POST"])
async def resolve_names(request: Request, company: str = "", authorization: str = Header(default=""),
                        session: Session = Depends(get_session)):
    comp = _company(session, company)
    _check(comp.tool_token, authorization)
    params = await _params(request)
    resolver = Resolver(session, comp.id, _rep_for(session, comp, params))
    items = parse_items(params.get("names"))
    matches = resolver.resolve_all(items)
    results = [m.as_dict() for m in matches]
    hints = {i: m.hint for i, m in enumerate(matches) if m.hint}
    rep = _rep_for(session, comp, params)
    session.add_all(ToolEvent(company_id=comp.id, rep_id=rep.id if rep else None, tool="resolve_names", kind=r["kind"],
                              heard=r["heard"], best=r["best"], confidence=r["confidence"]) for r in results)
    session.commit()
    log.info("resolve_names %s -> %s", params.get("names"), [(r["best"], r["confidence"]) for r in results])
    if not results:
        return {"results": [], "message": 'No names given. Send them as "product: Azithral 500; area: Hadapsar".'}
    lines = []
    for i, r in enumerate(results):
        if r["confidence"] == "high":
            lines.append(f'{r["kind"]} "{r["heard"]}" = {r["best"]}, say "{spoken(r["best"])}" (high: use it)')
        elif r["confidence"] == "medium":
            alts = f' (or {", ".join(r["alternatives"])})' if r["alternatives"] else ""
            if i in hints:
                lines.append(f'{r["kind"]} "{r["heard"]}" = probably {r["best"]} ({hints[i]}), say "{spoken(r["best"])}" '
                             f'(medium, must ask: confirm it with the MR in one short question)')
            else:
                lines.append(f'{r["kind"]} "{r["heard"]}" = probably {r["best"]}, say "{spoken(r["best"])}"{alts} (medium)')
        else:
            lines.append(f'{r["kind"]} "{r["heard"]}" = no clear match (low: ask the MR to repeat it)')
    return {"results": results, "message": "\n".join(lines)}


@router.api_route("/tools/doctor_brief", methods=["GET", "POST"])
async def doctor_brief_tool(request: Request, company: str = "", authorization: str = Header(default=""),
                            session: Session = Depends(get_session)):
    comp = _company(session, company)
    _check(comp.tool_token, authorization)
    params = await _params(request)
    rep = _rep_for(session, comp, params)
    m = Resolver(session, comp.id, rep).resolve(params.get("doctor", ""), "doctor")
    session.add(ToolEvent(company_id=comp.id, rep_id=rep.id if rep else None, tool="doctor_brief", kind="doctor",
                          heard=params.get("doctor"), best=m.best, confidence=m.confidence))
    session.commit()
    if m.confidence == "low" or not m.best:
        return {"message": f'No doctor matches "{params.get("doctor")}". Ask the MR for the name again.'}
    if m.confidence == "medium":
        options = ", ".join([m.best, *m.alternatives])
        return {"message": f"Not sure which doctor. Ask the MR: {options}?"}
    doctor = session.scalar(select(Doctor).where(Doctor.company_id == comp.id, Doctor.name == m.best))
    brief = doctor_brief(session, doctor)
    return {"doctor": brief["doctor"], "message": f'{brief["doctor"]} ({brief["area"] or "area unknown"}): {brief["spoken"]}'}
