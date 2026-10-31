"""Score how well each call's visit was understood, against what the rep actually said.

    uv run python -m evals.replay            # the recorded agent calls (current baseline)
    uv run python -m evals.replay --extract  # step 2: the backend reads each rep reply (needs OPENAI_API_KEY)

For every replay in tests/replays, the recorded agent calls are run through check_visit and the
draft they leave is compared, field by field, with what Saathi should know by the end of the call
(the rep turns' expected visits). That is the baseline for the current design, where the voice agent
fills in the fields; a backend extractor (step 2) is scored on the same replays, turn by turn.
"""

import sys
import tempfile
from pathlib import Path

from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from app.db import init_db, make_engine  # noqa: E402
from replay_support import (ask_kind, final_visit, known_after, load, load_company, replay_agent_calls,  # noqa: E402
                            replay_files, replay_rep_turns, score)


def session_for(tmp):
    engine = make_engine(f"sqlite:///{tmp}/replay.db")
    init_db(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def extract_mode():
    """Score after every rep turn: what Saathi knows then, and whether it asked the right thing."""
    import logging
    import time
    from app import extract
    logging.basicConfig(level=logging.WARNING, format="     %(message)s")
    logging.getLogger("saathi.extract").setLevel(logging.INFO)  # shows changes dropped by the quote check
    print(f"model {extract.MODEL}, reasoning {extract.REASONING}\n")
    total = right = asks = asks_ok = 0
    times = []
    for path in replay_files():
        call = load(path)
        with tempfile.TemporaryDirectory() as tmp, session_for(tmp) as s:
            company, rep, data = load_company(s)
            names = set(data["products"])
            print(f"{path.stem} ({call['script']})")
            original = extract.extract

            def timed(*a, **k):
                t0 = time.monotonic()
                try:
                    return original(*a, **k)
                finally:
                    times.append(time.monotonic() - t0)

            extract.extract = timed
            try:
                turns = replay_rep_turns(s, company, rep, call)
            finally:
                extract.extract = original
            for i, (t, r, visit) in enumerate(turns):
                e = t.get("expect", {})
                scores = score(visit, known_after(call, i + 1), names) if e.get("visit") is not None else {}
                ok = sum(1 for good, _, _ in scores.values() if good)
                total, right = total + len(scores), right + ok
                kind = ask_kind(r)
                ask_good = None
                if e.get("ask"):
                    ask_good = kind in e["ask"] or kind.startswith("readback") and any(a.startswith("readback") for a in e["ask"])
                if e.get("ask_not"):
                    ask_good = kind not in e["ask_not"] if ask_good is None else ask_good and kind not in e["ask_not"]
                if ask_good is not None:
                    asks, asks_ok = asks + 1, asks_ok + ask_good
                mark = "" if ask_good is None else (" ✓" if ask_good else f" ✗ (expected {e.get('ask') or 'not ' + str(e.get('ask_not'))})")
                print(f"  {i + 1}. rep: {t['rep'][:60]}")
                print(f"     saathi: {r['say'] or '(nothing)'} [{kind}]{mark}" + (f" ERROR {r.get('error')}" if r["status"] == "error" else ""))
                for field, (good, got, want) in scores.items():
                    if not good:
                        print(f"     ✗ {field}: got {got!r}, expected {want!r}")
            print()
    print(f"Fields right after each turn: {right}/{total} ({right / max(total, 1):.0%})")
    print(f"Right next line: {asks_ok}/{asks}")
    if times:
        times.sort()
        print(f"Extraction time: median {times[len(times) // 2]:.2f}s, slowest {times[-1]:.2f}s over {len(times)} calls")


def main():
    if "--extract" in sys.argv:
        return extract_mode()
    total = right = 0
    for path in replay_files():
        call = load(path)
        if not call["agent_calls"]:
            print(f"{path.stem}: no agent calls recorded, skipped\n")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            engine = make_engine(f"sqlite:///{tmp}/replay.db")
            init_db(engine)
            with sessionmaker(bind=engine, expire_on_commit=False)() as s:
                company, rep, data = load_company(s)
                results = replay_agent_calls(s, company, rep, call)
                visit = final_visit(s, call)
        names = set(data["products"])
        scores = score(visit, known_after(call), names)
        ok = sum(1 for good, _, _ in scores.values() if good)
        total, right = total + len(scores), right + ok
        errors = sum(1 for _, r in results if r["status"] == "error")
        print(f"{path.stem} ({call['script']}): {ok}/{len(scores)} fields right, {errors} crashes")
        for field, (good, got, want) in scores.items():
            if not good:
                print(f"  ✗ {field}: got {got!r}, expected {want!r}")
        print()
    if total:
        print(f"All replays: {right}/{total} fields right ({right / total:.0%})")


if __name__ == "__main__":
    main()
