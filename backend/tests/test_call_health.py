"""Every finished call gets an outcome, and a failed one the step of the graph where it went wrong."""

import copy

import pytest
from sqlalchemy import select

from app import visit_check
from app.agent_template import END_LINES
from app.models import AgentTurn, Call, Rep, VisitDraft
from conftest import PAYLOAD, tool, webhook

SID = "sid-health"


def run(client, company, transcript, turns=(), draft=None, confirmed=False, **payload):
    """A call with these check_visit / doctor_brief turns (tool, status, asked, extra) and transcript."""
    with client.Session() as s:
        rep = s.scalar(select(Rep).where(Rep.company_id == company.id))
        for t, status, asked, *extra in turns:
            s.add(AgentTurn(company_id=company.id, rep_id=rep.id, call_sid=SID, tool=t, status=status, asked=asked,
                            params=extra[0] if extra else {}, ms=300))
        if draft is not None:
            s.add(VisitDraft(company_id=company.id, rep_id=rep.id, call_sid=SID, **draft))
        s.commit()
    p = copy.deepcopy(PAYLOAD)
    p["telephony_data"]["provider_call_id"] = SID
    p["transcript"] = transcript
    p.update(payload)
    webhook(client, company, p, confirmed=confirmed)
    with client.Session() as s:
        return s.get(Call, p["id"])


REP = "user: Dr Mehta se mila\n"


def test_a_saved_visit_is_recorded(client, company):
    call = webhook(client, company, PAYLOAD).json()
    with client.Session() as s:
        c = s.get(Call, call["call_id"])
        assert (c.outcome, c.failure_stage) == ("recorded", None)


@pytest.mark.parametrize("status", ["no-answer", "busy", "failed"])
def test_an_unanswered_call_fails_to_connect(client, company, status):
    c = run(client, company, "", status=status)
    assert (c.outcome, c.failure_stage) == ("failed", "connect")


def test_a_rep_who_said_nothing_fails_to_connect(client, company):
    c = run(client, company, "assistant: नमस्ते!\n")
    assert c.failure_stage == "connect" and c.failure_reason == "the rep said nothing"


def test_no_tool_ever_ran_is_a_routing_failure(client, company):
    c = run(client, company, "assistant: नमस्ते!\n" + REP, termination_reason="user_hung_up")
    assert c.failure_stage == "routing" and "the rep hung up" in c.failure_reason


def test_saying_recorded_without_a_confirmed_read_back_is_a_false_close(client, company):
    hi = visit_check.LINES["hi"]["recorded"]
    c = run(client, company, f"assistant: नमस्ते!\n{REP}assistant: {hi} धन्यवाद!\n",
            turns=[("check_visit", "missing", "area")])
    assert c.failure_stage == "false_close"


def test_a_check_visit_crash_keeps_the_call_going_and_is_logged(client, company, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("bad draft")
    monkeypatch.setattr("app.routers.bolna_hooks.check_visit", boom)
    r = tool(client, company, "check_visit", call_sid=SID, doctor="Dr Mehta", from_number="+919876543210").json()
    assert r["status"] == "error" and visit_check.FALLBACK in r["message"]
    c = run(client, company, "assistant: नमस्ते!\n" + REP)
    assert c.failure_stage == "tool_error" and "bad draft" in c.failure_reason


def test_the_same_question_again_and_again_is_stuck_collecting(client, company):
    c = run(client, company, "assistant: नमस्ते!\n" + REP, turns=[("check_visit", "missing", "area")] * 3,
            draft={"fields": {}, "heard": {}})
    assert c.failure_stage == "collecting" and "stuck asking for area (3 times" in c.failure_reason


def test_ending_before_the_read_back_names_the_last_question(client, company):
    c = run(client, company, "assistant: नमस्ते!\n" + REP,
            turns=[("check_visit", "missing", "area"), ("check_visit", "unclear", "pick:product")])
    assert c.failure_stage == "collecting" and c.failure_reason.endswith("last asked for pick:product")


def test_a_read_back_with_no_yes_fails_confirming(client, company):
    c = run(client, company, "assistant: नमस्ते!\n" + REP,
            turns=[("check_visit", "complete", None), ("check_visit", "asking", "again:samples")],
            draft={"fields": {}, "read_back": {"doctor_name": "Dr Mehta"}, "disputes": {"samples": 1}},
            conversation_duration=300)
    assert c.failure_stage == "confirming" and "samples ×1" in c.failure_reason
    assert "time limit" in c.failure_reason


def test_repeated_empty_checks_are_a_loop(client, company):
    c = run(client, company, "assistant: नमस्ते!\n" + REP, turns=[("check_visit", "repeat", None)] * 4)
    assert c.failure_stage == "loop"


def test_a_confirmed_draft_that_cannot_be_built_fails_saving(client, company):
    c = run(client, company, "assistant: नमस्ते!\n" + REP, turns=[("check_visit", "recorded", None)],
            draft={"fields": {}, "confirmed": True}, extracted_data=None)
    assert c.failure_stage == "saving"


def test_briefings_stops_and_wrong_numbers_are_not_failures(client, company):
    c = run(client, company, "assistant: नमस्ते!\n" + REP, turns=[("doctor_brief", "found", "doctor")])
    assert (c.outcome, c.failure_stage) == ("briefing", None)


def test_a_briefing_with_no_doctor_found_fails(client, company):
    c = run(client, company, "assistant: नमस्ते!\n" + REP,
            turns=[("doctor_brief", "not_found", "doctor", {"doctor": "Dr Xyz"})])
    assert c.failure_stage == "briefing" and "Dr Xyz" in c.failure_reason


@pytest.mark.parametrize("node, outcome", [("later", "stopped"), ("wrong_number", "wrong_number")])
def test_ending_on_an_end_node(client, company, node, outcome):
    c = run(client, company, f"assistant: नमस्ते!\n{REP}assistant: {END_LINES[node][0]}\n")
    assert (c.outcome, c.failure_stage) == (outcome, None)


def test_call_health_page_lists_failures_by_stage(client, company):
    run(client, company, "assistant: नमस्ते!\n" + REP)
    r = client.get("/api/health/calls").json()
    assert r["stages"] == {"routing": 1} and r["calls"][0]["failure_stage"] == "routing"
    trace = client.get(f"/api/health/calls/{r['calls'][0]['id']}").json()
    assert trace["call"]["failure_stage"] == "routing" and trace["turns"] == []
