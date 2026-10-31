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


def test_a_none_for_items_the_reply_was_not_about_wipes_nothing(client, company):
    """31 Oct: after the read-back the rep added only the next visit; the agent sent "none" for every
    other item, which wiped the doctor and crashed the check. Only the item the reply was about changes."""
    read_back(client, company)
    nones = {k: "none" for k in FULL if k not in ("language", "next_visit")}
    r = turn(client, company, **nones, next_visit="दो हफ़्ते बाद", about="next_visit",
             mr_said="अगली visit दो हफ़्ते बाद है")
    assert r["status"] == "complete" and r["say"] == "अगली visit दो हफ़्ते बाद। सही है?"
    assert r["visit"]["doctor_name"] == "Dr Qureshi" and r["visit"]["chemist_name"] == "Wellness Chemist"


def test_a_none_the_reply_was_about_still_clears(client, company):
    read_back(client, company)
    r = turn(client, company, stock_outs="none", about="stock_outs", mr_said="नहीं कोई stock issue नहीं था")
    assert r["visit"]["stock_outs"] == [] and "कोई stock issue नहीं था।" in r["say"]


def test_a_doctor_sent_as_none_is_asked_not_a_crash(client, company):
    r = run(client, company, doctor="none")
    assert (r["status"], r["say"]) == ("missing", "किस doctor से मिले?")


def test_no_next_visit_is_said_in_words_not_none(client, company):
    r = run(client, company, next_visit="none")
    assert r["status"] == "complete" and "अगली visit अभी तय नहीं है।" in r["say"] and "none" not in r["say"]


def test_a_yes_to_a_name_question_settles_it_even_if_the_agent_resends_the_garble(client, company):
    """31 Oct: "Kothrud था?" - "हां", but the agent kept sending the garbled area, so Saathi asked again
    until the rep hung up. The backend remembers what it asked; the yes settles it."""
    r = turn(client, company, stock_outs="seventy five", mr_said="Ecosprin seventy five का stock नहीं था")
    assert r["say"] == "Ecosprin seventy five था?"
    r = turn(client, company, stock_outs="seventy five", mr_said="हां", confirms_readback="yes")
    assert r["status"] == "complete" and "Ecosprin seventy five का stock ख़त्म था" in r["say"]


def test_the_offered_name_said_back_settles_it(client, company):
    turn(client, company, stock_outs="seventy five", mr_said="seventy five ka stock nahi tha")
    r = turn(client, company, stock_outs="seventy five", mr_said="Ecosprin 75 tha")
    assert r["status"] == "complete"


def test_a_no_leaves_the_name_question_open(client, company):
    turn(client, company, stock_outs="seventy five", mr_said="seventy five ka stock nahi tha")
    r = turn(client, company, stock_outs="seventy five", mr_said="नहीं वो नहीं था", confirms_readback="no")
    assert r["say"] == "Ecosprin seventy five था?"


def test_saathis_own_line_or_nothing_new_is_not_a_reply(client, company):
    """31 Oct: the agent called again with no rep words, and once with Saathi's own question as them."""
    r = turn(client, company, stock_outs="seventy five", mr_said="seventy five ka stock nahi tha")
    assert turn(client, company, stock_outs="seventy five", mr_said=r["say"])["status"] == "repeat"
    assert turn(client, company, stock_outs="seventy five", mr_said="")["status"] == "repeat"


# ---- step 2: the agent sends only the rep's words; the backend reads them (extract.py) -------------

def change(item, op="set", name=None, quantity=None, text=None, quote="", material=None):
    return {"item": item, "op": op, "name": name, "quantity": quantity, "text": text, "material": material,
            "quote": quote}


def reply(client, company, monkeypatch, mr_said, changes, answer="info"):
    """One rep reply, with the model's patch given by the test."""
    from app import extract
    monkeypatch.setattr(extract, "extract", lambda heard, saathi, said: {
        "reply": answer, "changes": [c for c in changes if c["quote"] in said], "dropped": []})
    with client.Session() as s:
        r = check_visit(s, company, None, {"call_sid": "sid-2", "mr_said": mr_said})
        s.commit()
        return r


MONOLOGUE = ("Dr Qureshi se mila Wakad mein, Pan D discuss kiya, Pan D ke chhe sample, Wellness Chemist pe "
             "twenty ka order tees, koi stock issue nahi, koi promise nahi, next visit das din baad")
MONOLOGUE_PATCH = [
    change("doctor", name="Dr Qureshi", quote="Dr Qureshi"), change("area", name="Wakad", quote="Wakad"),
    change("product", "add", name="Pan D", quote="Pan D discuss kiya"),
    change("sample", name="Pan D", quantity=6, quote="Pan D ke chhe sample"),
    change("chemist", name="Wellness Chemist", quote="Wellness Chemist"),
    change("order", name=None, quantity=30, quote="twenty ka order tees"),
    change("stock_out", "none", quote="koi stock issue nahi"), change("promise", "none", quote="koi promise nahi"),
    change("next_visit", text="das din baad", quote="next visit das din baad")]


def test_an_order_without_a_product_is_asked_never_guessed(client, company, monkeypatch):
    """31 Oct: "twenty का order तीस" was saved as a Telma 40 order. The product is asked for."""
    r = reply(client, company, monkeypatch, MONOLOGUE, MONOLOGUE_PATCH)
    assert (r["asked"], r["say"]) == ("which_order", "Which product was the order of thirty for?")
    r = reply(client, company, monkeypatch, "Amlong 5 ka", [change("order", name="Amlong 5", quantity=None, quote="Amlong 5")])
    assert r["status"] == "complete" and "an order of thirty Amlong five" in r["say"]
    assert r["visit"]["orders"] == [("Amlong 5", 30)]


def test_a_reply_changes_only_what_it_mentions(client, company, monkeypatch):
    """31 Oct: a correction to the order replaced the products discussed and dropped the samples."""
    reply(client, company, monkeypatch, MONOLOGUE, MONOLOGUE_PATCH)
    reply(client, company, monkeypatch, "Amlong 5 ka", [change("order", name="Amlong 5", quote="Amlong 5")])
    r = reply(client, company, monkeypatch, "order Amlong 5 ka chalees tha",
              [change("order", name="Amlong 5", quantity=40, quote="Amlong 5 ka chalees")])
    assert r["say"] == "At Wellness Chemist you got an order of forty Amlong five. Is that right?"
    assert r["visit"]["products_discussed"] == ["Pan D"] and r["visit"]["samples"] == [("Pan D", 6)]


def test_restating_what_was_read_back_is_a_yes_not_a_dispute(client, company, monkeypatch):
    """31 Oct: the rep repeated the corrected order, it counted as a dispute and got flagged."""
    reply(client, company, monkeypatch, MONOLOGUE, MONOLOGUE_PATCH)
    reply(client, company, monkeypatch, "Amlong 5 ka", [change("order", name="Amlong 5", quote="Amlong 5")])
    r = reply(client, company, monkeypatch, "haan Wellness Chemist pe Amlong 5 ka order tees",
              [change("order", name="Amlong 5", quantity=30, quote="Amlong 5 ka order tees")], answer="yes")
    assert r["status"] == "recorded"


def test_a_change_without_the_reps_words_behind_it_is_not_applied(client, company, monkeypatch):
    from app import extract
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    content = {"reply": "info", "changes": [change("doctor", name="Dr Qureshi", quote="Dr Qureshi"),
                                            change("sample", name="Pan D", quantity=1, quote="one strip")]}

    class Response:
        status_code = 200
        def json(self):
            import json
            return {"choices": [{"message": {"content": json.dumps(content)}}]}

    monkeypatch.setattr(extract.httpx, "post", lambda *a, **k: Response())
    patch = extract.extract({}, "", "Dr Qureshi se mila, Pan D ka sample diya")
    assert [c["item"] for c in patch["changes"]] == ["doctor"] and patch["dropped"][0]["quote"] == "one strip"


def test_naming_the_product_fills_the_unnamed_order_even_if_the_quantity_was_misread(client, company, monkeypatch):
    """Replay 66441c37: "twenty का order तीस" was read as an order of 20; "Storvas twenty का order
    तीस" then added a second order instead of naming the first, and the question came back."""
    patch = [c if c["item"] != "order" else change("order", name=None, quantity=20, quote="twenty ka order tees")
             for c in MONOLOGUE_PATCH]
    reply(client, company, monkeypatch, MONOLOGUE, patch)
    r = reply(client, company, monkeypatch, "Amlong 5 ka order tees",
              [change("order", name="Amlong 5", quantity=30, quote="Amlong 5 ka order tees")])
    assert r["visit"]["orders"] == [("Amlong 5", 30)] and r["status"] == "complete"
