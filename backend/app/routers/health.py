"""Call health: how each call went, and for the ones that failed, the step of the graph and the
turn-by-turn trace (see call_health)."""

from collections import Counter
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import admin_user
from ..db import get_session
from ..ingest import call_draft, call_turns
from ..models import Call, User, utcnow
from .dashboard import _iso, recording_url

router = APIRouter(prefix="/api/health")
MAX_DAYS = 90


def call_row(c: Call):
    return {"id": c.id, "at": _iso(c.created_at), "rep": c.rep.name if c.rep else None, "rep_phone": c.rep_phone,
            "direction": c.direction, "call_type": c.call_type, "duration_s": c.duration_s, "status": c.status,
            "outcome": c.outcome, "failure_stage": c.failure_stage, "failure_reason": c.failure_reason,
            "warnings": c.warnings or [], "visit_id": c.visit.id if c.visit else None}


@router.get("/calls")
def health_calls(days: int = 7, user: User = Depends(admin_user), session: Session = Depends(get_session)):
    since = utcnow() - timedelta(days=max(1, min(days, MAX_DAYS)))
    calls = session.scalars(select(Call).where(Call.company_id == user.company_id, Call.created_at >= since,
                                               Call.outcome.is_not(None))
                            .order_by(Call.created_at.desc())).all()
    return {"days": days, "outcomes": dict(Counter(c.outcome for c in calls)),
            "stages": dict(Counter(c.failure_stage for c in calls if c.failure_stage)),
            "calls": [call_row(c) for c in calls]}


@router.get("/calls/{call_id}")
def health_call(call_id: str, user: User = Depends(admin_user), session: Session = Depends(get_session)):
    c = session.get(Call, call_id)
    if c is None or c.company_id != user.company_id:
        raise HTTPException(404, "call not found")
    draft = call_draft(session, c)
    return {
        "call": {**call_row(c), "transcript": c.transcript, "process_note": c.process_note,
                 "ended_by": (c.raw or {}).get("termination_reason"), "recording_url": recording_url(c.raw)},
        "turns": [{"at": _iso(t.created_at), "tool": t.tool, "status": t.status, "asked": t.asked, "say": t.say,
                   "mr_said": t.mr_said, "ms": t.ms, "error": t.error, "params": t.params}
                  for t in call_turns(session, c)],
        "draft": {"heard": draft.heard, "read_back": draft.read_back, "disputes": draft.disputes,
                  "confirmed": draft.confirmed, "language": draft.language} if draft else None,
    }
