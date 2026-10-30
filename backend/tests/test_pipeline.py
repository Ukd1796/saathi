"""Ported from the prototype (saathi/tests/test_pipeline.py), now per company."""

import copy

from sqlalchemy import select

from app.extraction import parse_visit
from app.matching import best_match, match_person
from app.models import Rep, Visit, VisitDraft
from conftest import PAYLOAD, webhook


def test_completed_call_creates_matched_visit(client, company):
    r = webhook(client, company, PAYLOAD)
    assert r.status_code == 200, r.text
    assert r.json()["note"] == "ok"
    [v] = client.get("/api/visits").json()
    assert v["rep"] == "Asha"
    assert v["doctor"] == "Dr Mehta"          # heard "Dr. Mehtaa"
    assert v["chemist"] == "Sharma Medical"   # heard "Sharma Medicals"
    assert v["samples"] == [{"product": "Telma 40", "qty": 4, "matched": True}]
    assert v["orders"] == []
    assert v["stock_outs"] == ["Cardivas"]
    assert v["promises"][0]["text"] == "Bring the Cardivas clinical study next visit"


def test_status_updates_and_repeats_are_idempotent(client, company):
    early = copy.deepcopy(PAYLOAD)
    early.update(status="in-progress", extracted_data=None)
    assert webhook(client, company, early).json()["note"] is None
    webhook(client, company, PAYLOAD)
    webhook(client, company, PAYLOAD)
    with client.Session() as s:
        assert s.query(Visit).count() == 1


def test_visit_does_not_wait_for_the_extraction(client, company):
    """The confirmed draft is there from the call itself, so a `completed` without extracted data is enough."""
    from conftest import confirmed_draft
    p = confirmed_draft(client, company, {**copy.deepcopy(PAYLOAD), "id": "late"})
    first = {**copy.deepcopy(p), "extracted_data": None}
    assert webhook(client, company, first, confirmed=False).json()["note"] == "ok"
    webhook(client, company, p, confirmed=False)
    with client.Session() as s:
        assert len(s.scalars(select(Visit)).all()) == 1


def test_wrong_secret_is_rejected(client, company):
    r = client.post(f"/bolna/webhook/{company.id}", json=PAYLOAD, headers={"X-Webhook-Secret": "nope"})
    assert r.status_code == 401


def test_outbound_call_identifies_rep_by_to_number(client, company):
    p = copy.deepcopy(PAYLOAD)
    p["id"] = "out"
    p["telephony_data"] = {"from_number": "+918000000000", "to_number": "09876543210", "call_type": "outbound"}
    webhook(client, company, p)
    [v] = client.get("/api/visits").json()
    assert v["rep"] == "Asha"


def test_unknown_and_ambiguous_names_go_to_review(client, company):
    p = copy.deepcopy(PAYLOAD)
    p["extracted_data"]["Visit"].update(doctor_name="Dr Fernandes", samples="Telma: 3")
    assert "not matched" in webhook(client, company, p).json()["note"]
    [v] = client.get("/api/visits").json()
    assert v["doctor"] is None and v["doctor_heard"] == "Dr Fernandes"
    # "Telma" could be Telma 40 or Telma H, so it must stay unmatched.
    assert any(u["kind"] == "product" and u["heard"] == "Telma" for u in v["unmatched"])


def test_briefing_call_makes_no_visit(client, company):
    p = copy.deepcopy(PAYLOAD)
    p["extracted_data"]["Visit"]["call_type"] = "briefing"
    assert webhook(client, company, p).json()["note"].startswith("briefing")
    assert client.get("/api/visits").json() == []


def test_parse_visit_handles_corrections_and_formats():
    f = parse_visit({"doctor_name": {"subjective": "Dr Iyer"}, "samples": "5 strips Storvas 20, Rosuvas 10: 30",
                     "stock_outs": "Pan D and Janumet", "promises": "Send samples; Call back, after 2 days"})
    assert f["samples"] == [("Storvas 20", 5), ("Rosuvas 10", 30)]
    assert f["stock_outs"] == ["Pan D", "Janumet"]
    assert f["promises"] == ["Send samples", "Call back, after 2 days"]


def test_matching_rules():
    class N:
        def __init__(self, name):
            self.name = name
    products = [N("Pan 40"), N("Pan D"), N("Cardivas")]
    assert best_match("pan-d", products).name == "Pan D"
    assert best_match("Pan", products) is None
    assert match_person("Doctor Rao", [N("Dr Rao")]).name == "Dr Rao"


def graph_call(client, company, confirmed):
    """A graph-agent call: the visit was checked live through check_visit, and the transcript the
    extraction read is garbled ("Dr. Mehtaa", "Sharma Medicals")."""
    with client.Session() as s:
        rep = s.scalar(select(Rep).where(Rep.company_id == company.id))
        s.add(VisitDraft(company_id=company.id, rep_id=rep.id, call_sid="plivo-123", confirmed=confirmed, fields={
            "doctor_name": "Dr Mehta", "area": "Kothrud", "products_discussed": ["Telma 40", "Cardivas"],
            "samples": [["Telma 40", 4]], "orders": [], "chemist_name": "Sharma Medical", "stock_outs": ["Cardivas"],
            "next_visit": "next Tuesday", "feedback": None, "promises": ["Cardivas clinical study"],
            "promises_done": [], "materials": ["Cardivas clinical study"]}))
        s.commit()
    payload = copy.deepcopy(PAYLOAD)
    payload["telephony_data"]["provider_call_id"] = "plivo-123"
    return webhook(client, company, payload)


def test_graph_call_is_saved_from_the_confirmed_draft(client, company):
    assert graph_call(client, company, confirmed=True).json()["note"] == "ok"  # every name linked
    with client.Session() as s:
        v = s.scalars(select(Visit)).one()
        assert v.doctor.name == "Dr Mehta" and v.chemist.name == "Sharma Medical" and not v.unmatched


def test_graph_call_without_a_confirmed_read_back_is_not_saved(client, company):
    # the extraction says "readback_confirmed: yes", but the backend never heard a yes to its read-back
    assert graph_call(client, company, confirmed=False).json()["note"] == "not saved: the rep didn't confirm the read-back"


def test_call_without_a_check_is_not_saved_from_the_transcript(client, company):
    """check_visit never ran: the extraction says confirmed, but nothing is saved."""
    assert webhook(client, company, PAYLOAD, confirmed=False).json()["note"] == "not saved: the rep didn't confirm the read-back"
    with client.Session() as s:
        assert s.scalars(select(Visit)).first() is None
