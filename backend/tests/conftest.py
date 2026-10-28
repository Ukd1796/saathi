import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import db, main
from app.db import init_db, make_engine

PAYLOAD = json.loads((Path(__file__).parent / "fixtures" / "execution_completed.json").read_text())
ASHA = "+919876543210"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DISABLE_SCHEDULER", "1")
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db, "SessionLocal", Session)
    monkeypatch.setattr(main, "SessionLocal", Session)

    def get_session():
        with Session() as s:
            yield s

    main.app.dependency_overrides[db.get_session] = get_session
    with TestClient(main.app) as c:
        c.Session = Session
        yield c
    main.app.dependency_overrides.clear()


def signup(client, email="admin@sahyadri.test", company="Sahyadri Pharma", phone=ASHA):
    r = client.post("/api/auth/signup", json={"company_name": company, "name": "Asha", "email": email,
                                              "password": "password123", "phone": phone})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def company(client):
    """A signed-up company with the Pune demo data and Asha (the admin) as its first rep."""
    me = signup(client)
    assert client.post("/api/data/demo").status_code == 200
    from app.models import Company
    with client.Session() as s:
        return s.get(Company, me["company"]["id"])


def webhook(client, company, payload):
    return client.post(f"/bolna/webhook/{company.id}", json=payload,
                       headers={"X-Webhook-Secret": company.webhook_secret})


def tool(client, company, name, **params):
    return client.post(f"/bolna/tools/{name}?company={company.id}", json=params,
                       headers={"Authorization": f"Bearer {company.tool_token}"})
