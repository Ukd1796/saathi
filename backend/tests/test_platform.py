import copy

from app.models import Promise, Visit, utcnow
from app.names import Resolver, parse_items, to_latin
from app.outbound import reps_without_visits_today
from conftest import ASHA, PAYLOAD, signup, tool, webhook


def test_resolver_on_real_misheard_names(client, company):
    with client.Session() as s:
        r = Resolver(s, company.id)
        assert r.resolve("Montar LC", "product").as_dict()["best"] == "Montair LC"
        assert r.resolve("हदापसर", "area").confidence == "high"
        assert r.resolve("चार दिवस", "product").best == "Cardivas"   # the call that became "four days"
        assert r.resolve("Telma", "product").confidence == "medium"  # Telma 40 or Telma H: confirm
        assert r.resolve("Telma 80", "product").best is None         # strength must agree
        assert r.resolve("पाटिल", "doctor").best == "Dr Patil"
        assert r.resolve("Exezle 500", "product").confidence == "low"  # don't guess: ask again
        assert r.resolve("telma forty", "product").as_dict()["confidence"] == "high"  # strength said as a word
        assert r.resolve("azithral five hundred", "product").best == "Azithral 500"
    assert to_latin("औंध") == "aundh"
    assert parse_items("product: Exezle 500; area: हजस पर; nonsense") == [("product", "Exezle 500"), ("area", "हजस पर")]


def test_review_fix_teaches_an_alias(client, company):
    p = copy.deepcopy(PAYLOAD)
    p["extracted_data"]["Visit"].update(samples="Exezle 500: 6", products_discussed="Exezle 500")
    webhook(client, company, p)
    [item] = [i for i in client.get("/api/review").json() if i["heard"] == "Exezle 500"]
    r = client.post("/api/review/resolve", json={"visit_id": item["visit_id"], "kind": "product",
                                                 "heard": "Exezle 500", "target": "Azithral 500"})
    assert r.json()["samples"] == [{"product": "Azithral 500", "qty": 6, "matched": True}]
    res = tool(client, company, "resolve_names", names="product: exezle 500", from_number=ASHA).json()
    assert res["results"][0] == {"heard": "exezle 500", "kind": "product", "best": "Azithral 500",
                                 "confidence": "high", "alternatives": []}


def test_tools_need_the_company_token(client, company):
    r = client.post(f"/bolna/tools/resolve_names?company={company.id}", json={"names": "product: Telma 40"},
                    headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_doctor_brief_tool_and_caller_lookup(client, company):
    webhook(client, company, PAYLOAD)
    msg = tool(client, company, "doctor_brief", doctor="Mehta", from_number=ASHA).json()["message"]
    assert "Dr Mehta" in msg and "Telma 40 4" in msg and "Cardivas clinical study" in msg
    assert "Cardivas at Sharma Medical" in msg  # stock-out at a chemist in the doctor's area
    caller = client.get(f"/bolna/caller?company={company.id}&contact_number={ASHA}",
                        headers={"Authorization": f"Bearer {company.tool_token}"}).json()
    assert caller["rep_name"] == "Asha" and "Dr Mehta (Kothrud)" in caller["my_doctors"]
    assert "Cardivas clinical study" in caller["open_promises"]


def test_promise_done_closes_open_promise(client, company):
    webhook(client, company, PAYLOAD)
    p = copy.deepcopy(PAYLOAD)
    p["id"] = "second"
    p["extracted_data"]["Visit"].update(promises="none", promises_done="Gave the Cardivas study")
    webhook(client, company, p)
    with client.Session() as s:
        assert [x.status for x in s.query(Promise).all()] == ["done"]


def test_companies_cannot_see_each_other(client, company):
    webhook(client, company, PAYLOAD)
    client.post("/api/auth/logout")
    signup(client, email="other@rival.test", company="Rival Pharma", phone="+919999988888")
    assert client.get("/api/visits").json() == []
    assert client.get("/api/review").json() == []
    r = client.post(f"/bolna/webhook/{company.id}", json=PAYLOAD, headers={"X-Webhook-Secret": "guess"})
    assert r.status_code == 401


def test_csv_upload_preview_then_commit(client, company):
    csv = "Name,Phone,Area\nRavi Kumar,98765 11111,Baner\nBad Phone,123,Wakad\nRavi Kumar,9876511111,Baner\n"
    r = client.post("/api/data/upload/reps", files={"file": ("reps.csv", csv)}).json()
    assert r["new"] == 1 and len(r["errors"]) == 2
    r = client.post("/api/data/upload/reps?commit=true", files={"file": ("reps.csv", csv)}).json()
    assert r["counts"]["reps"] == 2
    bad = client.post("/api/data/upload/doctors", files={"file": ("d.csv", "area\nKothrud\n")}).json()
    assert "missing column" in bad["errors"][0]


def test_handover_moves_doctors_and_history(client, company):
    webhook(client, company, PAYLOAD)
    client.post("/api/data/upload/reps?commit=true", files={"file": ("r.csv", "name,phone\nRavi,9876511111\n")})
    reps = {r["name"]: r["id"] for r in client.get("/api/reps").json()}
    r = client.post(f"/api/reps/{reps['Asha']}/handover", json={"to_rep_id": reps["Ravi"]}).json()
    assert r["moved_doctors"] == 10 and r["open_promises"] == 1
    ravi = next(r for r in client.get("/api/reps").json() if r["name"] == "Ravi")
    assert ravi["doctors"] == 10 and "Kothrud" in ravi["area"]


def test_sweep_targets_only_silent_reps(client, company):
    client.post("/api/data/upload/reps?commit=true", files={"file": ("r.csv", "name,phone\nRavi,9876511111\n")})
    webhook(client, company, PAYLOAD)
    with client.Session() as s:
        s.query(Visit).update({Visit.visited_at: utcnow()})
        s.commit()
        assert [r.name for r in reps_without_visits_today(s, company.id)] == ["Ravi"]


def test_overview_counts(client, company):
    webhook(client, company, PAYLOAD)
    o = client.get("/api/overview").json()
    assert o["open_promises"] == 1 and o["stock_outs_week"] == 1 and o["needs_review"] == 0
    assert o["recent_calls"][0]["note"] == "ok"


def test_overview_insights_and_visit_filters(client, company):
    webhook(client, company, PAYLOAD)
    o = client.get("/api/overview").json()
    assert len(o["trend"]) == 14 and sum(d["visits"] for d in o["trend"]) == 1
    assert o["leaderboard"][0] == {"id": o["leaderboard"][0]["id"], "name": "Asha", "visits": 1}
    assert o["top_products"] and o["top_stockouts"][0]["count"] == 1
    day = o["trend"][-1]["date"] if o["trend"][-1]["visits"] else next(d["date"] for d in o["trend"] if d["visits"])
    assert len(client.get(f"/api/visits?date_from={day}&date_to={day}").json()) == 1
    assert client.get("/api/visits?date_from=2001-01-01&date_to=2001-01-02").json() == []
    area = client.get("/api/visits").json()[0]["area"]
    assert len(client.get(f"/api/visits?area={area.upper()}").json()) == 1
    assert client.get("/api/visits?area=Nowhere").json() == []
    assert client.get("/api/visits?date_from=yesterday").status_code == 422


def test_data_add_edit_delete(client, company):
    r = client.post("/api/data/products", json={"name": "Vitneurin 500"})
    assert r.status_code == 200
    pid = r.json()["id"]
    assert client.post("/api/data/products", json={"name": "vitneurin 500"}).status_code == 409
    assert client.patch(f"/api/data/products/{pid}", json={"name": "Vitneurin"}).json()["name"] == "Vitneurin"
    assert client.post("/api/data/reps", json={"name": "Ravi", "phone": "123"}).status_code == 422
    rep = client.post("/api/data/reps", json={"name": "Ravi", "phone": "9876511111", "area": "Baner"}).json()
    doc = client.post("/api/data/doctors", json={"name": "wadekar", "area": "Baner", "rep_id": rep["id"]}).json()
    assert doc["name"] == "Dr wadekar" and doc["rep"] == "Ravi"
    assert client.delete(f"/api/data/reps/{rep['id']}").status_code == 409  # still has a doctor
    assert client.delete(f"/api/data/doctors/{doc['id']}").status_code == 200
    assert client.delete(f"/api/data/products/{pid}").json()["deleted"] == pid


def test_data_rows_with_history_or_other_company_are_protected(client, company):
    webhook(client, company, PAYLOAD)
    visit = client.get("/api/visits").json()[0]
    assert client.delete(f"/api/data/doctors/{visit['doctor_id']}").status_code == 409
    client.post("/api/auth/logout")
    signup(client, email="other@rival.test", company="Rival Pharma", phone="+919999988888")
    assert client.patch(f"/api/data/doctors/{visit['doctor_id']}", json={"name": "Hacked"}).status_code == 404
    assert client.delete(f"/api/data/doctors/{visit['doctor_id']}").status_code == 404
