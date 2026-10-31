"""Scheduled calls, retries, resuming a cut-off report, and call quality."""

import copy
from datetime import datetime

import pytest

from app import bolna, outbound
from app.models import Company, OutboundCall, ScheduledCall, Visit
from conftest import ASHA, PAYLOAD, tool, webhook


def at(hhmm, day="2026-10-29"):  # a Thursday
    return datetime.fromisoformat(f"{day}T{hhmm}:00").replace(tzinfo=outbound.TZ)


@pytest.fixture
def live(client, company, monkeypatch):
    """The company has a Bolna agent, and placing a call just returns an execution id."""
    with client.Session() as s:
        s.get(Company, company.id).bolna_agent_id = "agent-1"
        s.commit()
    placed = []
    monkeypatch.setattr(bolna, "make_call", lambda agent, to, user_data=None, from_number=None:
                        placed.append((to, user_data)) or {"execution_id": f"exec-{len(placed)}"})
    return placed


def rep_id(client):
    return next(r["id"] for r in client.get("/api/reps").json() if r["name"] == "Asha")


def tick(client, monkeypatch, hhmm, day="2026-10-29"):
    monkeypatch.setattr(outbound, "local_now", lambda: at(hhmm, day))
    with client.Session() as s:
        outbound.run_scheduled(s)


def test_schedule_validation(client, company, monkeypatch):
    monkeypatch.setattr("app.routers.dashboard.local_now", lambda: at("10:00"))
    rid = rep_id(client)
    assert client.post("/api/schedules", json={"rep_id": rid, "time": "22:30"}).status_code == 422  # too late
    assert client.post("/api/schedules", json={"rep_id": rid, "time": "7pm"}).status_code == 422
    assert client.post("/api/schedules", json={"rep_id": rid, "time": "18:30"}).json()["run_on"] == "2026-10-29"
    assert client.post("/api/schedules", json={"rep_id": rid, "time": "09:30"}).json()["run_on"] == "2026-10-30"
    assert len(client.get("/api/schedules").json()["active"]) == 2


def test_scheduled_call_runs_once_at_its_time(client, company, live, monkeypatch):
    monkeypatch.setattr("app.routers.dashboard.local_now", lambda: at("10:00"))
    sid = client.post("/api/schedules", json={"rep_id": rep_id(client), "time": "18:30"}).json()["id"]
    tick(client, monkeypatch, "18:29")
    assert live == []
    tick(client, monkeypatch, "18:31")
    tick(client, monkeypatch, "18:32")
    assert len(live) == 1 and live[0][0] == ASHA and live[0][1]["mode"] == "sweep"
    with client.Session() as s:
        sc = s.get(ScheduledCall, sid)
        assert (sc.active, sc.last_result, sc.last_execution_id) == (False, "called", "exec-1")
        assert s.query(OutboundCall).one().reason == "scheduled"


def test_report_call_skipped_when_rep_already_reported(client, company, live, monkeypatch):
    webhook(client, company, PAYLOAD)
    with client.Session() as s:
        s.query(Visit).update({Visit.visited_at: outbound.utcnow()})
        s.commit()
    monkeypatch.setattr("app.routers.dashboard.local_now", lambda: outbound.local_now())
    now = outbound.local_now()
    if not "09:00" <= now.strftime("%H:%M") <= "20:58":
        pytest.skip("needs a daytime clock")
    hhmm = now.strftime("%H:%M")
    client.post("/api/schedules", json={"rep_id": rep_id(client), "time": hhmm, "repeat": "daily"})
    with client.Session() as s:
        outbound.run_scheduled(s)
        assert s.query(ScheduledCall).filter_by(repeat="daily").one().last_result == "skipped: already reported today"
    assert live == []


def test_weekday_schedule_skips_weekends_and_unanswered_call_is_retried_once(client, company, live, monkeypatch):
    monkeypatch.setattr("app.routers.dashboard.local_now", lambda: at("10:00"))
    client.post("/api/schedules", json={"rep_id": rep_id(client), "time": "19:00", "repeat": "weekdays",
                                        "purpose": "briefing"})
    tick(client, monkeypatch, "19:01", day="2026-10-31")  # Saturday
    assert live == []
    tick(client, monkeypatch, "19:01")
    assert live[0][1]["mode"] == "briefing"
    missed = {"id": "exec-1", "agent_id": "agent-1", "status": "no-answer",
              "telephony_data": {"call_type": "outbound", "to_number": ASHA}}
    webhook(client, company, missed)
    webhook(client, company, missed)  # Bolna repeats webhooks
    with client.Session() as s:
        retries = s.query(ScheduledCall).filter_by(is_retry=True).all()
        assert len(retries) == 1 and retries[0].purpose == "briefing"


def dropped_call(client, company, call_id, heard=None):
    """A call the rep hung up on before the read-back, with the draft check_visit had built so far."""
    from app.ingest import find_rep
    from app.models import VisitDraft
    p = copy.deepcopy(PAYLOAD)
    p["id"] = call_id
    p["termination_reason"] = "user_hung_up"
    p["transcript"] = "\n".join(p["transcript"].splitlines()[:2])  # the rep started, then the line dropped
    p["extracted_data"]["Visit"]["readback_confirmed"] = "no"
    p.setdefault("telephony_data", {})["provider_call_id"] = f"sid-{call_id}"
    if heard:
        with client.Session() as s:
            rep = find_rep(s, company.id, ASHA)
            s.add(VisitDraft(company_id=company.id, rep_id=rep.id, call_sid=f"sid-{call_id}", heard=heard,
                             fields={"doctor_name": heard.get("doctor"), "area": heard.get("area")}))
            s.commit()
    return p


def test_cut_off_report_is_not_saved_and_saathi_calls_back(client, company):
    p = dropped_call(client, company, "dropped-1", heard={"doctor": "Dr Mehta", "area": "Kothrud", "products": "missing"})
    r = webhook(client, company, p, confirmed=False).json()
    assert "cut off" in r["note"]
    with client.Session() as s:
        assert s.query(Visit).count() == 0
        sc = s.query(ScheduledCall).one()
        assert sc.purpose == "resume" and sc.source_call_id == "dropped-1" and "Dr Mehta" in sc.note
    webhook(client, company, p, confirmed=False)
    with client.Session() as s:
        assert s.query(ScheduledCall).count() == 1  # one resume per call, however many webhooks


def test_a_hello_and_a_hang_up_is_not_a_cut_off_report(client, company):
    """31 Oct: the rep said "hello" and hung up; a resume call was booked for a report never started."""
    webhook(client, company, dropped_call(client, company, "hello-1"), confirmed=False)
    webhook(client, company, dropped_call(client, company, "hello-2", heard={"doctor": "missing"}), confirmed=False)
    with client.Session() as s:
        assert s.query(ScheduledCall).count() == 0


def test_a_resume_call_never_books_another(client, company):
    """31 Oct: an unanswered resume call booked the next resume call."""
    with client.Session() as s:
        from app.ingest import find_rep
        s.add(OutboundCall(company_id=company.id, rep_id=find_rep(s, company.id, ASHA).id, reason="resume",
                           execution_id="resume-1"))
        s.commit()
    webhook(client, company, dropped_call(client, company, "resume-1", heard={"doctor": "Dr Mehta"}), confirmed=False)
    with client.Session() as s:
        assert s.query(ScheduledCall).count() == 0


def test_a_recorded_visit_cancels_the_waiting_resume_call(client, company, live, monkeypatch):
    webhook(client, company, dropped_call(client, company, "dropped-2", heard={"doctor": "Dr Mehta"}), confirmed=False)
    webhook(client, company, PAYLOAD)  # the rep then reports the visit in a new call
    with client.Session() as s:
        sc = s.query(ScheduledCall).filter_by(purpose="resume").one()
        assert not sc.active and "reported since" in sc.last_result


def test_finished_call_is_not_treated_as_cut_off(client, company):
    p = copy.deepcopy(PAYLOAD)
    p["termination_reason"] = "user_hung_up"  # the rep hung up after Saathi's closing line
    assert webhook(client, company, p).json()["note"] == "ok"


def test_visit_shows_call_quality(client, company):
    tool(client, company, "resolve_names", names="doctor: Mehtaa; product: telma forty; product: Exezle 500",
         from_number=ASHA)
    webhook(client, company, PAYLOAD)
    vid = client.get("/api/visits").json()[0]["id"]
    q = client.get(f"/api/visits/{vid}").json()["quality"]
    assert [n["confidence"] for n in q["names"]] == ["high", "high", "low"]
    assert q["rep_turns"] == 3 and q["duration_s"]


def test_greeting_fits_the_rep_and_the_reason_for_calling(client, company, live, monkeypatch):
    from app.models import Rep
    from app.outbound import greeting
    with client.Session() as s:
        rep = s.query(Rep).first()
    assert greeting(rep, "inbound").startswith("नमस्ते Asha!")
    assert "पिछली visit report बीच में कट गई थी, Dr Mehta वाली" in greeting(rep, "resume", "doctor: Dr Mehta; area: Kothrud")
    assert "आज Dr Rao से मिलना है" in greeting(rep, "briefing", "doctor: Dr Rao")
    assert greeting(None, "inbound").startswith("नमस्ते!")  # unknown caller: no name
    client.post(f"/api/reps/{rep_id(client)}/call")
    assert live[-1][1]["greeting"].startswith("नमस्ते Asha!")
    lookup = client.get(f"/bolna/caller?company={company.id}&contact_number={ASHA}",
                        headers={"Authorization": f"Bearer {company.tool_token}"}).json()
    assert lookup["greeting"].startswith("नमस्ते Asha!")


def test_debrief_the_rep_did_not_confirm_is_not_saved(client, company):
    p = copy.deepcopy(PAYLOAD)
    p["termination_reason"] = "agent_ended_call"  # "cut the call, thank you": Saathi ended it politely
    p["extracted_data"]["Visit"]["readback_confirmed"] = "no"
    assert "not saved" in webhook(client, company, p).json()["note"]
    with client.Session() as s:
        assert s.query(Visit).count() == 0 and s.query(ScheduledCall).count() == 0  # and no resume call


def test_saathi_hanging_up_on_an_unconfirmed_report_calls_back_and_is_a_false_close(client, company):
    """31 Oct (d4aec100): the voice model said "यह report हो गया" on its own, never calling check_visit,
    and hung up. Nothing was saved and no callback was booked. Now Saathi calls back, and Call health
    says false_close."""
    p = dropped_call(client, company, "false-close-1", heard={"doctor": "Dr Patil", "area": "Hadapsar"})
    p["termination_reason"] = "agent_ended_call"
    webhook(client, company, p, confirmed=False)
    with client.Session() as s:
        from app.models import Call
        assert s.query(ScheduledCall).one().purpose == "resume"
        assert s.get(Call, "false-close-1").failure_stage == "false_close"
