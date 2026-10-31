"""Real calls replayed through check_visit with the exact parameters the voice agent sent. These check
the backend's handling of what the agent sends (no crash, no loop, nothing wiped); how well the
fields themselves are filled in is scored by evals/replay.py."""

import pytest
from sqlalchemy.orm import sessionmaker

from app.db import init_db, make_engine
from replay_support import load, load_company, replay_agent_calls, replay_files

RECORDED = [p for p in replay_files() if load(p)["agent_calls"]]
MAX_SAME_QUESTION = 2


@pytest.fixture
def session(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'replay.db'}")
    init_db(engine)
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        yield s


@pytest.mark.parametrize("path", RECORDED, ids=lambda p: p.stem)
def test_recorded_agent_calls(session, path):
    call = load(path)
    company, rep, _ = load_company(session)
    results = replay_agent_calls(session, company, rep, call)
    said = [r["say"] for _, r in results if r["say"]]
    for i, (c, r) in enumerate(results):
        where = f'agent call {i} (mr_said "{c["params"].get("mr_said", "")[:40]}")'
        assert r["status"] != "error", f'{where}: {r.get("error")}'
        if r["status"] == "recorded":
            assert str(c["params"].get("confirms_readback", "")).startswith("y"), f"{where}: recorded without a yes"
        e = c.get("expect", {})
        if "status" in e:
            assert r["status"] == e["status"], where
        if "status_not" in e:
            assert r["status"] != e["status_not"], where
        if "say_not" in e:
            assert r["say"] != e["say_not"], where
        for field, want in e.get("visit", {}).items():
            assert (r["visit"] or {}).get(field) == want, f"{where}: {field}"
    for line in set(said):
        assert said.count(line) <= MAX_SAME_QUESTION, f'"{line}" said {said.count(line)} times'
