"""check_visit decides Saathi's next line from what the rep said: one question at a time, then the
whole read-back. Names are the Pune demo data."""

from app.models import VisitDraft
from app.visit_check import check_visit

FULL = {"doctor": "Dr Qureshi", "area": "Wakad", "products": "Pan D; Amlong 5", "samples": "Pan D: 6",
        "chemist": "Wellness Chemist", "orders": "Amlong 5: 30", "stock_outs": "Ecosprin 75",
        "feedback": "Pan D से patients को जल्दी आराम मिल रहा है", "promise": "Saturday को patient leaflet लाएँगे",
        "next_visit": "दस दिन बाद", "language": "hi"}


def run(client, company, **changes):
    with client.Session() as s:
        return check_visit(s, company, None, {**FULL, **changes})


def test_full_visit_gets_the_whole_read_back(client, company):
    r = run(client, company)
    assert r["status"] == "complete"
    say = r["say"]
    for part in ("Dr Qureshi", "Wakad", "Pan D के छह sample", "Amlong five का order तीस", "Wellness Chemist",
                 "Ecosprin seventy five का stock ख़त्म था", "patient leaflet", "दस दिन बाद", "सही है?"):
        assert part in say, part
    assert not any(ch.isdigit() for ch in say)  # the voice engine misreads digits


def test_english_read_back(client, company):
    r = run(client, company, language="en", feedback="Pan D gives quick relief", promise="the patient leaflet on Saturday",
            next_visit="in ten days")
    assert r["status"] == "complete"
    assert "six samples of Pan D" in r["say"] and "an order of thirty Amlong five" in r["say"]
    assert r["say"].endswith("Is that right?")


def test_asks_for_the_first_missing_item_only(client, company):
    r = run(client, company, chemist="missing", orders="missing", stock_outs="missing", promise="missing")
    assert (r["status"], r["say"]) == ("missing", "Doctor के पास किसी chemist पे गए?")
    r = run(client, company, chemist="none", orders="missing", stock_outs="missing")
    assert r["status"] == "complete" and "किसी chemist पे नहीं गए" in r["say"]  # no stock question without a chemist


def test_quantity_without_a_number_is_asked(client, company):
    r = run(client, company, samples="Pan D: ?")
    assert (r["status"], r["say"]) == ("missing", "Pan D के कितने sample दिए?")


def test_only_the_strength_heard_is_confirmed_not_guessed(client, company):
    r = run(client, company, stock_outs="seventy five")
    assert (r["status"], r["say"]) == ("unclear", "Ecosprin seventy five था?")


def test_unknown_name_is_asked_without_repeating_the_garble(client, company):
    r = run(client, company, products="Pan D; qwzxv")
    assert r["status"] == "unclear" and "qwzxv" not in r["say"]


def turn(client, company, **fields):
    with client.Session() as s:
        r = check_visit(s, company, None, {**FULL, "call_sid": "sid-1", **fields})
        s.commit()
        return r


def read_back(client, company, **fields):
    r = turn(client, company, mr_said="मैं Dr Qureshi से मिला और पूरी visit बताई", **fields)
    assert r["status"] == "complete" and r["say"].endswith("सही है?")
    return r


def test_a_yes_counts_only_after_the_backends_own_read_back(client, company):
    # a yes to a name question is just an answer: the next line is the read-back, not "recorded"
    assert turn(client, company, stock_outs="seventy five", mr_said="मैं Dr Qureshi से मिला और पूरी visit बताई")["say"] == "Ecosprin seventy five था?"
    r = turn(client, company, stock_outs="Ecosprin 75", confirms_readback="yes", mr_said="हां")
    assert r["status"] == "complete" and r["say"].endswith("सही है?")
    # the yes to that read-back is what records it
    r = turn(client, company, stock_outs="Ecosprin 75", confirms_readback="yes", mr_said="हां सही है")
    assert r["status"] == "recorded" and r["say"].startswith("ठीक है, record हो गया।")


def test_a_yes_the_rep_never_said_records_nothing(client, company):
    read_back(client, company)
    # the agent calls again straight after its own read-back, claiming a yes: the rep has said nothing
    assert turn(client, company, confirms_readback="yes", mr_said="")["status"] == "repeat"


def test_a_correction_reads_back_only_what_changed(client, company):
    read_back(client, company)
    r = turn(client, company, orders="Amlong 5: 35", about="orders", mr_said="order पैंतीस था")
    assert r["status"] == "complete"
    assert r["say"] == "Wellness Chemist में Amlong five का order पैंतीस मिला। सही है?"
    r = turn(client, company, orders="Amlong 5: 35", confirms_readback="yes", mr_said="हां")
    assert r["status"] == "recorded"


def test_an_objection_without_a_new_value_asks_for_that_item_then_flags_it(client, company):
    read_back(client, company)
    r = turn(client, company, about="promise", mr_said="नहीं, वो नहीं")
    assert (r["status"], r["say"]) == ("asking", "Promise क्या किया था, फिर से बताइए?")
    r = turn(client, company, about="promise", mr_said="patient वाला, वो नहीं")  # garbled the same way again
    assert r["status"] == "flagged" and "manager" in r["say"]
    r = turn(client, company, confirms_readback="yes", mr_said="हां बाकी सही है")
    assert r["status"] == "recorded"
    with client.Session() as s:
        assert s.query(VisitDraft).one().fields["flagged"] == ["promise"]


def test_an_interruption_is_never_a_yes(client, company):
    read_back(client, company)
    r = turn(client, company, interrupted="yes", confirms_readback="yes", mr_said="हां रुको")
    assert (r["status"], r["say"]) == ("asking", "क्या ठीक नहीं है?")


def test_reworded_free_text_alone_does_not_trigger_a_read_back(client, company):
    read_back(client, company)
    r = turn(client, company, promise="Saturday को leaflet लाएँगे", confirms_readback="yes", mr_said="हां")
    assert r["status"] == "recorded"  # the agent reworded the promise; the rep changed nothing


def test_the_same_call_twice_does_not_ask_twice(client, company):
    assert turn(client, company, promise="missing", mr_said="मैं Dr Qureshi से मिला और visit बताई")["status"] == "missing"
    assert turn(client, company, promise="missing", mr_said="मैं Dr Qureshi से मिला और visit बताई")["status"] == "repeat"


def test_language_comes_from_the_reps_words():
    from app.visit_check import detect_language
    # lines from real calls (Deepgram, Hindi mode)
    assert detect_language("i think you are doing something wrong i went to the श्री ganesh medical", "hi") == "en"
    assert detect_language("doctor joshi से मिला baner में thyronorm fifty और telma h की बात हुई", "en") == "hi"
    assert detect_language("हां और ecosprin seventy five ख़त्म था wellness chemist के पास", "en") == "hi"
    assert detect_language("yes", "hi") == "hi" and detect_language("हां", "en") == "en"  # too short to switch


def test_an_english_rep_gets_english_even_if_the_agent_guesses_hindi(client, company):
    r = turn(client, company, language="hi", samples="missing",
             mr_said="i met the doctor and we discussed two products but i forgot the samples")
    assert r["say"] == "Did you give any samples? Which, and how many?"


def test_the_draft_remembers_what_was_heard(client, company):
    """30 Oct: the agent sent only its latest reply's fields, the doctor came back "missing", and Saathi
    asked "Which doctor?" again. A later "missing" never erases what was heard."""
    empty = {k: "missing" for k in FULL if k != "language"}
    assert turn(client, company, **empty, mr_said="i would like to give a visit report", language="en")["say"] == \
        "Go ahead, which doctor did you meet and what happened?"
    r = turn(client, company, **{**empty, "doctor": "daughter qureshi", "area": "wakad"}, mr_said="i met doctor qureshi in wakad")
    assert r["say"] == "Which products did you discuss?"
    r = turn(client, company, **{**empty, "products": "Pan D", "samples": "Pan D: 6"},
             mr_said="we discussed pan d and i gave six samples")  # doctor and area not sent again
    assert r["say"] == "Did you visit any chemist near the doctor?"


def test_a_missing_area_comes_from_the_doctors_record(client, company):
    """30 Oct: STT cut "Dr Patil in Hadapsar" to "daughter patil h"; Saathi asked the area four times,
    although the doctor's area is on file."""
    r = run(client, company, doctor="daughter qureshi", area="missing")
    assert r["status"] == "complete" and r["say"].startswith("Dr Qureshi, Wakad में मिले थे।")
