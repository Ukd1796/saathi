"""Replays of real calls (tests/replays/*.json), shared by the replay tests and evals/replay.py.

Each replay file is one call: the rep's turns with what Saathi should know and ask after each
(`rep_turns[].expect`), the visit the rep meant (`truth`, from the test script they read), and the
calls the voice agent actually made to check_visit (`agent_calls`, with the parameters it sent). The
company's names are in sahyadri.json, so names resolve exactly as they did on the call.
"""

import json
from datetime import datetime
from pathlib import Path
from unittest import mock

from app import visit_check
from app.models import Chemist, Company, Doctor, Product, Rep, VisitDraft

REPLAYS = Path(__file__).parent / "replays"
SINGLE = {"doctor_name", "area", "chemist_name", "next_visit"}
PAIRS = {"samples", "orders"}


def replay_files():
    return sorted(p for p in REPLAYS.glob("*.json") if p.name != "sahyadri.json")


def load(path):
    return json.loads(Path(path).read_text())


def load_company(session):
    data = load(REPLAYS / "sahyadri.json")
    company = Company(name=data["name"])
    session.add(company)
    session.flush()
    rep = Rep(company_id=company.id, name=data["rep"]["name"], phone="+910000000000", area=data["rep"]["area"])
    session.add(rep)
    session.flush()
    session.add_all([Product(company_id=company.id, name=n) for n in data["products"]])
    session.add_all([Doctor(company_id=company.id, name=n, area=a, assigned_rep_id=rep.id) for n, a in data["doctors"]])
    session.add_all([Chemist(company_id=company.id, name=n, area=a) for n, a in data["chemists"]])
    session.commit()
    return company, rep, data


def replay_agent_calls(session, company, rep, call):
    """Run the recorded check_visit calls in order, on the clock they happened at (the repeat window
    depends on it). Returns (agent_call, result) pairs; an exception counts as status "error"."""
    out = []
    for c in call["agent_calls"]:
        at = datetime.fromisoformat(c["at"])
        with mock.patch.object(visit_check, "utcnow", return_value=at):
            try:
                r = visit_check.check_visit(session, company, rep, {**c["params"], "call_sid": call["call"]})
            except Exception as exc:  # noqa: BLE001 - a crash is a result to report
                session.rollback()
                r = {"status": "error", "say": "", "visit": None, "error": repr(exc)}
            session.commit()
        out.append((c, r))
    return out


def final_visit(session, call):
    draft = session.query(VisitDraft).filter_by(call_sid=call["call"]).one_or_none()
    return json.loads(json.dumps(draft.fields)) if draft else {}


def known_after(call, upto=None):
    """What Saathi should know after the rep's turns so far: each turn's expected visit, later wins."""
    known = {}
    for t in call["rep_turns"][:upto]:
        known.update(t.get("expect", {}).get("visit", {}))
    return known


def compare(field, got, want, names) -> bool:
    """One field of a visit against what was expected. None in `want` means "not said": nothing may be
    filled in. A pair with a None product means a quantity whose product wasn't said: it may be left
    out or kept unresolved, never filled with a product from the list. A None quantity likewise."""
    if field in SINGLE:
        if want is None:
            return not got
        if field == "next_visit":  # free text: the same words, ignoring case, spaces and script of digits
            from app.names import key
            return bool(got) and (key(want) in key(got) or key(got) in key(want))
        return got == want
    if field in PAIRS:
        got = [tuple(x) for x in (got or [])]
        for name, qty in want:
            if name is None:
                if any(g[0] in names and (qty is None or g[1] == qty) for g in got):
                    return False
            elif not any(g[0] == name and g[1] == qty for g in got):
                return False
        unknown_ok = any(w[0] is None for w in want)  # an unnamed product left over is wrong once it was named
        return all((g[0] not in names or any(w[0] == g[0] for w in want)) and (g[0] in names or unknown_ok) for g in got)
    if field == "promises":
        return bool(got) == bool(want)
    return sorted(got or []) == sorted(want)  # products discussed, stock-outs


def score(visit, want, names):
    return {f: (compare(f, visit.get(f), w, names), visit.get(f), w) for f, w in want.items()}


def replay_rep_turns(session, company, rep, call):
    """Step 2: send each of the rep's recorded replies as the agent now would (only the words), with the
    line Saathi had just said, so the backend's own extraction reads them. Returns (turn, result, visit)
    per rep turn; an exception counts as status "error"."""
    out = []
    for t in call["rep_turns"]:
        try:
            r = visit_check.check_visit(session, company, rep, {"call_sid": call["call"], "mr_said": t["rep"],
                                                                 "saathi_said": t["saathi"]})
        except Exception as exc:  # noqa: BLE001 - a crash is a result to report
            session.rollback()
            r = {"status": "error", "say": "", "asked": None, "error": repr(exc)}
        session.commit()
        out.append((t, r, final_visit(session, call)))
    return out


def ask_kind(result) -> str:
    """What Saathi's line was, in the words the replay files use for `ask`."""
    asked, status = result.get("asked") or "", result["status"]
    if status == "recorded":
        return "recorded"
    if status == "complete":
        return "readback"
    return {"visit": "invite", "which_order": "order_product", "which_sample": "sample_product",
            "confirm_readback": "confirm_readback"}.get(asked, asked)
