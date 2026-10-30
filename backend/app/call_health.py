"""How a call went, and if it went wrong, at which step of the graph and why.

Every finished call gets an outcome: recorded | briefing | stopped | wrong_number | failed. A failed
call names the step (failure_stage) and a reason a person can read, so the steps that break most can
be found on the Call health page and fixed. It is worked out from what the backend itself saw: the
check_visit / doctor_brief turns (AgentTurn), the call's draft, and Saathi's own lines in the
transcript, matched against the lines the backend gave it (never against the rep's words).

Stages, in the order a call goes through them:
  connect     the call never got going (no answer, error, or the rep said nothing)
  routing     the rep spoke but no tool ever ran: the call stayed in opening / listen
  collecting  check_visit ran but the visit never got as far as the read-back
  confirming  the read-back was said but the rep never said yes to it
  briefing    a briefing was asked for but no doctor was found
  false_close Saathi said the report was recorded, but no read-back was confirmed
  tool_error  a tool call failed on the backend
  loop        the agent kept calling check_visit with nothing new from the rep
  saving      the rep confirmed, but the visit could not be built from the draft
"""

import logging
from collections import Counter

from .agent_template import END_LINES, MAX_CALL_SECONDS
from .models import AgentTurn, Call, VisitDraft
from .outbound import NO_ANSWER
from .visit_check import LINES

log = logging.getLogger("saathi.health")

FAILED_STATUSES = NO_ANSWER | {"error"}
STUCK_ASKS = 3  # the same question this many times in a row: the call is stuck on that item
MAX_REPEATS = 4  # check_visit called this often with nothing new from the rep
SLOW_TURN_MS = 2500  # a tool call slower than this is a pause the rep hears
TIME_LIMIT_SLACK_S = 5
ENDED_BY = {"user_hung_up": "the rep hung up", "agent_ended_call": "Saathi ended the call",
            "max_duration_reached": "the call hit its time limit", "call-disconnected": "the line dropped",
            "network_error": "the line dropped", "silence": "the rep went silent"}


def finished(call: Call) -> bool:
    return (call.status or "").lower() in FAILED_STATUSES | {"completed"}


def _lines(call: Call, who: str) -> list[str]:
    return [l.split(":", 1)[1].strip() for l in (call.transcript or "").splitlines() if l.startswith(f"{who}:")]


def _said(lines: list[str], text: str) -> bool:
    text = text.strip(" ।.!")
    return any(text in line for line in lines)


def _ended_by(call: Call) -> str | None:
    reason = (call.raw or {}).get("termination_reason")
    if (call.duration_s or 0) >= MAX_CALL_SECONDS - TIME_LIMIT_SLACK_S:
        return ENDED_BY["max_duration_reached"]
    return ENDED_BY.get(reason, reason)


def _stuck(turns: list[AgentTurn]) -> tuple[str | None, int]:
    """The item the last question was about, and how many times in a row it was asked."""
    asked = [t.asked for t in turns if t.tool == "check_visit" and t.status not in ("repeat", "error")]
    if not asked:
        return None, 0
    last, n = asked[-1], 0
    for a in reversed(asked):
        if a != last:
            break
        n += 1
    return last, n


def diagnose(call: Call, draft: VisitDraft | None, turns: list[AgentTurn]) -> dict:
    status = (call.status or "").lower()
    out = {"outcome": "failed", "stage": None, "reason": None, "warnings": []}

    def fail(stage, reason):
        ended = _ended_by(call)
        return {**out, "stage": stage, "reason": f"{reason} ({ended})" if ended and stage != "connect" else reason}

    checks = [t for t in turns if t.tool == "check_visit"]
    briefs = [t for t in turns if t.tool == "doctor_brief"]
    counts = Counter(t.status for t in checks)
    slow = [t for t in turns if (t.ms or 0) > SLOW_TURN_MS]
    if slow:
        out["warnings"].append(f"{len(slow)} slow tool call(s), up to {max(t.ms for t in slow)} ms")
    if counts["repeat"]:
        out["warnings"].append(f"check_visit called {counts['repeat']} time(s) with nothing new")
    flagged = (draft.read_back or {}).get("flagged", []) if draft else []
    if flagged:
        out["warnings"].append("kept in the rep's words: " + ", ".join(flagged))
    if call.visit is not None and call.visit.unmatched:
        out["warnings"].append(f"{len(call.visit.unmatched)} name(s) not matched")

    if status in FAILED_STATUSES:
        return fail("connect", f"call {status}")
    rep, saathi = _lines(call, "user"), _lines(call, "assistant")
    if not rep:
        return fail("connect", "the rep said nothing")
    if call.visit is not None:
        return {**out, "outcome": "recorded"}

    confirmed = draft is not None and draft.confirmed
    if not confirmed and any(_said(saathi, L["recorded"]) for L in LINES.values()):
        return fail("false_close", "Saathi said the report was recorded, but no read-back was confirmed")
    errors = [t for t in turns if t.status == "error"]
    if errors:
        return fail("tool_error", f"{errors[-1].tool} failed: {errors[-1].error}")
    if confirmed and call.call_type != "briefing":
        return fail("saving", "the rep confirmed, but no visit could be built from the draft")
    if counts["repeat"] >= MAX_REPEATS:
        return fail("loop", f"check_visit called {counts['repeat']} times with nothing new from the rep")

    last = saathi[-1] if saathi else ""
    ended_on = next((node for node, (hi, en) in END_LINES.items() if _said([last], hi) or _said([last], en)), None)
    if any(t.status == "found" for t in briefs):
        return {**out, "outcome": "briefing"}
    if ended_on == "wrong_number":
        return {**out, "outcome": "wrong_number"}
    if ended_on == "later":
        return {**out, "outcome": "stopped"}
    if briefs:
        return fail("briefing", f"no doctor found for \"{(briefs[-1].params or {}).get('doctor')}\"")
    if not checks:
        wanted = "a briefing" if call.call_type == "briefing" else "a visit report"
        return fail("routing", f"the rep spoke but no tool ran: the call never left the opening ({wanted})")
    if any(t.status == "complete" for t in checks) or (draft is not None and draft.read_back):
        disputes = ", ".join(f"{k} ×{n}" for k, n in (draft.disputes or {}).items()) if draft else ""
        return fail("confirming", "read back, but the rep never said yes" + (f"; disputed: {disputes}" if disputes else ""))
    asked, n = _stuck(checks)
    if n >= STUCK_ASKS:
        return fail("collecting", f"stuck asking for {asked} ({n} times in a row)")
    return fail("collecting", f"ended before the read-back; last asked for {asked or 'nothing'}")


def record(call: Call, draft: VisitDraft | None, turns: list[AgentTurn]) -> dict:
    result = diagnose(call, draft, turns)
    call.outcome, call.failure_stage, call.failure_reason = result["outcome"], result["stage"], result["reason"]
    call.warnings = result["warnings"] or None
    if result["outcome"] == "failed":
        log.warning("graph failure company=%s call=%s stage=%s reason=%s", call.company_id, call.id,
                    result["stage"], result["reason"])
    return result
