"""What a visit sets in motion: alerts, material requests, due dates, the follow-up call; and what
a manager can see and do."""

import copy
from datetime import date, timedelta

import pytest

from app import db
from app.dates import parse_when
from app.models import Action, Company, Promise, ScheduledCall
from conftest import ASHA, PAYLOAD, webhook

THU = date(2026, 10, 29)
RAVI = "+919876511111"


@pytest.mark.parametrize("said, days", [
    ("10 din baad", 10), ("in 10 days", 10), ("दस दिन बाद", 10), ("next week", 7), ("agle hafte", 7),
    ("do hafte baad", 14), ("in two weeks", 14), ("ek mahine baad", 30), ("kal", 1), ("parso", 2),
    ("Monday ko", 4), ("somvar", 4), ("next Tuesday", 5), ("Bring the study next week", 7),
])
def test_spoken_dates(said, days):
    assert parse_when(said, THU) == THU + timedelta(days=days)


def test_unparseable_dates():
    assert parse_when("jab time mile", THU) is None and parse_when("", THU) is None


def test_visit_creates_stockout_and_material_actions_and_a_followup(client, company):
    webhook(client, company, PAYLOAD)
    webhook(client, company, PAYLOAD)  # repeated webhooks change nothing
    items = client.get("/api/actions").json()
    kinds = sorted(i["kind"] for i in items)
    assert kinds == ["material", "stockout"]
    stock = next(i for i in items if i["kind"] == "stockout")
    assert stock["title"] == "Cardivas out at Sharma Medical (Kothrud)" and "Dr Mehta" in stock["detail"]
    with client.Session() as s:
        follow = s.query(ScheduledCall).filter_by(purpose="briefing").one()
        assert follow.note == "doctor: Dr Mehta" and follow.time == "09:30" and follow.repeat == "once"
        assert date.fromisoformat(follow.run_on).weekday() == 1  # "next Tuesday"


def test_no_followup_when_switched_off(client, company):
    client.patch("/api/settings", json={"auto_followup": False})
    webhook(client, company, PAYLOAD)
    with client.Session() as s:
        assert s.query(ScheduledCall).filter_by(purpose="briefing").count() == 0
    assert client.patch("/api/settings", json={"followup_time": "06:00"}).status_code == 422


def test_approve_material_and_handle_stockout(client, company):
    webhook(client, company, PAYLOAD)
    items = {i["kind"]: i for i in client.get("/api/actions").json()}
    mat, stock = items["material"]["action_id"], items["stockout"]["action_id"]
    assert client.patch(f"/api/actions/{mat}", json={"status": "done"}).status_code == 422  # materials are approved
    assert client.patch(f"/api/actions/{mat}", json={"status": "approved"}).json()["status"] == "approved"
    assert client.patch(f"/api/actions/{stock}", json={"status": "done"}).status_code == 200
    assert client.get("/api/actions").json() == []
    assert {i["status"] for i in client.get("/api/actions?status=done").json()} == {"approved", "done"}


def test_promise_with_a_day_is_overdue_after_that_day(client, company):
    p = copy.deepcopy(PAYLOAD)
    p["extracted_data"]["Visit"]["promises"] = "Send the dosing chart on Monday"
    webhook(client, company, p)
    with client.Session() as s:
        promise = s.query(Promise).one()
        assert promise.due_on
        promise.due_on = "2020-01-01"
        s.commit()
    overdue = [i for i in client.get("/api/actions").json() if i["kind"] == "overdue"]
    assert len(overdue) == 1 and "due 1 Jan" in overdue[0]["detail"]


# ---- roles --------------------------------------------------------------------------------------

def two_teams(client, company):
    """Asha's team (the demo rep) and Ravi's, with one visit each. Returns the manager's password."""
    client.post("/api/data/upload/reps?commit=true", files={"file": ("r.csv", "name,phone,area,manager\nRavi,9876511111,Baner,Priya\n")})
    reps = {r["name"]: r["id"] for r in client.get("/api/reps").json()}
    webhook(client, company, PAYLOAD)
    other = copy.deepcopy(PAYLOAD)
    other["id"] = "ravi-call"
    other["telephony_data"]["from_number"] = RAVI
    other["extracted_data"]["Visit"].update(doctor_name="Dr Joshi", area="Baner", chemist_name="none", stock_outs="none")
    webhook(client, company, other)
    joshi = next(d for d in client.get("/api/data/list/doctors").json() if d["name"] == "Dr Joshi")
    client.patch(f"/api/data/doctors/{joshi['id']}", json={"rep_id": reps["Ravi"], "area": "Baner"})
    made = client.post("/api/users", json={"name": "Rahul", "email": "rahul@sahyadri.test", "rep_ids": [reps["Asha"]]}).json()
    return made["password"], reps


def test_manager_sees_only_their_team(client, company):
    password, reps = two_teams(client, company)
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"email": "rahul@sahyadri.test", "password": password}).status_code == 200
    me = client.get("/api/auth/me").json()
    assert me["role"] == "manager" and me["team_size"] == 1
    assert [v["rep"] for v in client.get("/api/visits").json()] == ["Asha"]
    assert [r["name"] for r in client.get("/api/reps").json()] == ["Asha"]
    assert "Dr Joshi" not in [d["name"] for d in client.get("/api/doctors").json()]
    assert all(i["rep"] == "Asha" for i in client.get("/api/actions").json())
    o = client.get("/api/overview").json()
    assert o["visits_today"] + sum(d["visits"] for d in o["trend"]) >= 1 and [r["name"] for r in o["leaderboard"]] == ["Asha"]
    assert all(c["rep"] == "Asha" for c in o["recent_calls"])
    assert client.post("/api/schedules", json={"rep_id": reps["Ravi"], "time": "19:00"}).status_code == 404
    assert client.post(f"/api/reps/{reps['Ravi']}/call").status_code == 404


def test_manager_cannot_use_admin_pages(client, company):
    password, _ = two_teams(client, company)
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "rahul@sahyadri.test", "password": password})
    for method, path in [("get", "/api/users"), ("get", "/api/agent"), ("post", "/api/agent/sync"),
                         ("patch", "/api/settings"), ("post", "/api/data/products"), ("get", "/api/data/list/reps")]:
        r = getattr(client, method)(path, **({"json": {}} if method != "get" else {}))
        assert r.status_code in (403, 422), (path, r.status_code)
        assert r.status_code == 403 or method != "get", path


def test_users_suggestions_reset_and_remove(client, company):
    password, reps = two_teams(client, company)
    users = client.get("/api/users").json()
    assert [s["name"] for s in users["suggested"]] == ["Priya"]  # from the reps CSV, no login yet
    rahul = next(u for u in users["users"] if u["role"] == "manager")
    assert rahul["rep_ids"] == [reps["Asha"]]
    assert client.patch(f"/api/users/{rahul['id']}", json={"rep_ids": [reps["Asha"], reps["Ravi"]]}).json()["rep_ids"] \
        == sorted([reps["Asha"], reps["Ravi"]])
    new = client.post(f"/api/users/{rahul['id']}/reset-password").json()["password"]
    assert new != password
    assert client.delete(f"/api/users/{rahul['id']}").status_code == 200
    assert all(r["manager_user_id"] is None for r in client.get("/api/reps").json())
    me = client.get("/api/auth/me").json()
    assert client.delete(f"/api/users/{me['id']}").status_code == 422


def test_upgrade_adds_missing_columns(tmp_path):
    from sqlalchemy import create_engine, inspect, text
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as c:  # yesterday's tables, without the new columns
        c.execute(text("CREATE TABLE companies (id INTEGER PRIMARY KEY, name VARCHAR(120))"))
        c.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, company_id INTEGER)"))
        c.execute(text("CREATE TABLE reps (id INTEGER PRIMARY KEY, company_id INTEGER, name VARCHAR(120))"))
        c.execute(text("CREATE TABLE promises (id INTEGER PRIMARY KEY, text TEXT)"))
        c.execute(text("INSERT INTO companies (id, name) VALUES (1, 'Old Pharma')"))
    db.upgrade(engine)
    cols = {t: {c["name"] for c in inspect(engine).get_columns(t)} for t in ("companies", "reps", "promises")}
    assert {"auto_followup", "followup_time"} <= cols["companies"] and "manager_user_id" in cols["reps"]
    assert "due_on" in cols["promises"]
    with engine.connect() as c:
        assert c.execute(text("SELECT followup_time FROM companies")).scalar() == "09:30"
    db.upgrade(engine)  # running it again is a no-op
