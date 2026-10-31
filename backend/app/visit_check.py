"""check_visit: the agent hands over what the rep has said so far; the backend decides what Saathi says next.

Either the single next question (a name to clear up, a missing item, a quantity), or, once nothing is
missing, the whole read-back, built here from the resolved names in the rep's language. The model
only has to repeat the line, so a read-back can't skip items or echo a garbled word.
"""

import json
import re
from datetime import timedelta

from sqlalchemy import select

from . import extract
from .models import VisitDraft, utcnow
from .names import HINDI_NUMBERS, Match, Resolver, _say_number, key, spoken, spoken_numbers, to_latin

MISSING, NONE = "missing", "none"
# What Saathi says when check_visit itself fails, so the rep isn't left in silence (the turn is logged).
FALLBACK = "एक second, फिर से बताइए?"
NONE_WORDS = {"none", "no", "nil"}  # the tool's own protocol values; the agent is told to send "none"
# Asked in this order; stock-outs only matter once a chemist was visited.
REQUIRED = ["doctor", "area", "products", "samples", "chemist", "stock_outs", "promise", "next_visit"]
HEARD = REQUIRED + ["orders", "feedback", "promise_material"]
# The fields the voice agent used to fill in itself. A call without any of them carries only the rep's
# words, and the backend reads them (extract.py).
AGENT_FIELDS = REQUIRED + ["orders", "feedback"]
PATCH_FIELD = {"doctor": "doctor", "area": "area", "chemist": "chemist", "next_visit": "next_visit",
               "feedback": "feedback", "promise": "promise", "product": "products", "stock_out": "stock_outs",
               "sample": "samples", "order": "orders"}
UNKNOWN = "?"  # a sample or order whose product wasn't named
# Read-back parts, and the saved fields each one shows. Names and numbers are compared in code; free
# text (feedback, promise, next visit) is reworded by the agent between turns, so it only counts as
# changed when the agent says the rep's reply was about it.
GROUPS = {"met": ["doctor_name", "area"], "discussed": ["products_discussed"], "samples": ["samples"],
          "chemist": ["chemist_name", "orders"], "stock": ["stock_outs"], "feedback": ["feedback"],
          "promise": ["promises"], "next": ["next_visit"]}
FREE_TEXT = {"feedback", "promise", "next"}
ITEM_GROUP = {"doctor": "met", "area": "met", "products": "discussed", "samples": "samples", "chemist": "chemist",
              "orders": "chemist", "stock_outs": "stock", "feedback": "feedback", "promise": "promise",
              "next_visit": "next"}
DISPUTES_BEFORE_FLAG = 2  # the same item disputed this often is kept as said and flagged for the manager
# The reply language comes from the rep's own words, not the agent's guess. Deepgram in Hindi mode
# writes Hindi speech in Devanagari and English speech in Latin letters, so the share of Devanagari
# words says which one the rep spoke (names like "श्री ganesh" are a small share of a sentence).
# A short reply ("yes", "हां") keeps the language it is in, so one word doesn't flip it.
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
HINDI_SHARE = 0.2
MIN_WORDS_FOR_LANGUAGE = 3


def detect_language(said: str, previous: str | None) -> str | None:
    words = [w for w in str(said or "").split() if re.search(r"[A-Za-zऀ-ॿ]", w)]
    if len(words) < MIN_WORDS_FOR_LANGUAGE:
        return previous
    hindi = sum(1 for w in words if DEVANAGARI.search(w))
    return "hi" if hindi / len(words) >= HINDI_SHARE else "en"
# The agent sometimes calls the tool twice before the rep has answered; the same fields again within
# this window mean the question is already out, so Saathi waits instead of asking it twice.
REPEAT_WINDOW = timedelta(seconds=15)
# A doctor, area or chemist the rep confirmed stays confirmed however the agent spells it next; a product
# only for the words it was heard as, since a visit has several.
ONE_PER_VISIT = {"doctor", "area", "chemist"}



LINES = {
    "hi": {
        "invite": "बताइए, किस doctor से मिले और क्या-क्या हुआ?",
        "doctor": "किस doctor से मिले?", "area": "{doctor} से किस area में मिले?",
        "products": "कौनसे products discuss किए?", "samples": "कोई sample दिए? किसके, और कितने?",
        "chemist": "Doctor के पास किसी chemist पे गए?", "stock_outs": "{chemist} में किसी product का stock ख़त्म था?",
        "promise": "Doctor को कुछ promise किया?", "next_visit": "अगली visit कब है?",
        "qty_sample": "{product} के कितने sample दिए?", "qty_order": "{product} का order कितना था?",
        "which_sample": "{n} sample किस product के दिए?", "which_order": "{n} का order किस product का था?",
        "pick": "कौनसा {kind} था, {options}?", "repeat": "{kind} का नाम फिर से बताइए?", "confirm": "{name} था?",
        "or": " या ", "and": " और ", "kinds": {"product": "product", "doctor": "doctor", "chemist": "chemist", "area": "area"},
        "met": "{doctor}, {area} में मिले थे।", "discussed": "{products} discuss हुए।",
        "sample": "{product} के {n} sample", "samples_given": "{items} दिए।", "no_samples": "कोई sample नहीं दिया।",
        "order": "{product} का order {n}", "at_chemist": "{chemist} में {orders} मिला।",
        "no_order": "{chemist} में कोई order नहीं मिला।", "no_chemist": "किसी chemist पे नहीं गए।",
        "stock": "{products} का stock ख़त्म था।", "no_stock": "कोई stock issue नहीं था।",
        "feedback": "Doctor ने बोला कि {feedback}।", "promised": "आपने promise किया कि {promise}।",
        "no_promise": "कोई promise नहीं था।", "next": "अगली visit {next_visit}।", "no_next": "अगली visit अभी तय नहीं है।", "ask": "सही है?",
        "recorded": "ठीक है, record हो गया।", "followup": " अगली visit के दिन सुबह मैं briefing के लिए call करूँगी।",
        "thanks": " धन्यवाद!", "whats_wrong": "क्या ठीक नहीं है?",
        "flag": "ठीक है, {item} मैं आपके शब्दों में रख लेती हूँ, manager एक बार देख लेंगे। बाकी सब सही है?",
        "again": {"met": "Doctor और area फिर से बताइए?", "discussed": "कौनसे products discuss किए, फिर से बताइए?",
                  "samples": "Samples फिर से बताइए, किसके कितने?", "chemist": "Chemist और order फिर से बताइए?",
                  "stock": "किसका stock ख़त्म था, फिर से बताइए?", "feedback": "Doctor ने क्या बोला, फिर से बताइए?",
                  "promise": "Promise क्या किया था, फिर से बताइए?", "next": "अगली visit कब है, फिर से बताइए?"},
        "items": {"met": "doctor और area", "discussed": "products", "samples": "samples", "chemist": "chemist और order",
                  "stock": "stock", "feedback": "feedback", "promise": "promise", "next": "अगली visit"},
    },
    "en": {
        "invite": "Go ahead, which doctor did you meet and what happened?",
        "doctor": "Which doctor did you meet?", "area": "Which area did you meet {doctor} in?",
        "products": "Which products did you discuss?", "samples": "Did you give any samples? Which, and how many?",
        "chemist": "Did you visit any chemist near the doctor?", "stock_outs": "Was anything out of stock at {chemist}?",
        "promise": "Did you promise the doctor anything?", "next_visit": "When is the next visit?",
        "qty_sample": "How many samples of {product} did you give?", "qty_order": "How much was the {product} order?",
        "which_sample": "Which product were the {n} samples of?", "which_order": "Which product was the order of {n} for?",
        "pick": "Which {kind} was it, {options}?", "repeat": "Could you say the {kind} name again?", "confirm": "Was it {name}?",
        "or": " or ", "and": " and ", "kinds": {"product": "product", "doctor": "doctor", "chemist": "chemist", "area": "area"},
        "met": "You met {doctor} in {area}.", "discussed": "You discussed {products}.",
        "sample": "{n} samples of {product}", "samples_given": "You gave {items}.", "no_samples": "No samples were given.",
        "order": "an order of {n} {product}", "at_chemist": "At {chemist} you got {orders}.",
        "no_order": "At {chemist} there was no order.", "no_chemist": "You didn't visit a chemist.",
        "stock": "{products} was out of stock there.", "no_stock": "There were no stock issues.",
        "feedback": "The doctor said {feedback}.", "promised": "You promised {promise}.",
        "no_promise": "There was no promise.", "next": "The next visit is {next_visit}.", "no_next": "The next visit isn't fixed yet.", "ask": "Is that right?",
        "recorded": "Okay, it's recorded.", "followup": " I'll call you that morning with a briefing.",
        "thanks": " Thank you!", "whats_wrong": "What's not right?",
        "flag": "Okay, I'll keep the {item} in your words and your manager will check it. Is the rest right?",
        "again": {"met": "Could you say the doctor and area again?", "discussed": "Which products did you discuss?",
                  "samples": "Could you tell me the samples again, which and how many?",
                  "chemist": "Could you tell me the chemist and the order again?", "stock": "What was out of stock?",
                  "feedback": "What did the doctor say?", "promise": "What did you promise the doctor?",
                  "next": "When is the next visit?"},
        "items": {"met": "doctor and area", "discussed": "products", "samples": "samples", "chemist": "chemist and order",
                  "stock": "stock-outs", "feedback": "feedback", "promise": "promise", "next": "next visit"},
    },
}


def say_quantity(n: int, lang: str) -> str:
    if lang == "hi" and 0 <= n < 100:
        return HINDI_NUMBERS[n]
    if lang == "hi" and n < 100000:
        parts = []
        if n >= 1000:
            parts.append(f"{say_quantity(n // 1000, lang)} हज़ार")
        if (n % 1000) >= 100:
            parts.append(f"{HINDI_NUMBERS[(n % 1000) // 100]} सौ")
        if n % 100:
            parts.append(HINDI_NUMBERS[n % 100])
        return " ".join(parts)
    return _say_number(str(n))


def _value(text) -> str:
    t = str(text or "").strip().strip(".")
    if not t or t.lower() in (MISSING, "null", "unknown"):
        return MISSING
    return NONE if t.lower() in NONE_WORDS else t


def _items(text) -> list[str]:
    v = _value(text)
    return [] if v in (MISSING, NONE) else [p.strip() for p in re.split(r"[;,\n]", v) if p.strip()]


def _pairs(text) -> list[tuple[str, int | None]]:
    """'Pan D: 6; Telma 40: four' -> [('Pan D', 6), ('Telma 40', 4)]; no number -> None."""
    out = []
    for part in _items(text):
        name, _, qty = part.rpartition(":") if ":" in part else (part, "", "")
        digits = re.findall(r"\d+", spoken_numbers(qty))
        out.append((name.strip() or part, int(digits[0]) if digits else None))
    return out


def check_visit(session, company, rep, fields: dict) -> dict:
    """One turn of the debrief. With a call_sid the visit is kept as a draft between turns, and once a
    read-back is out, each new reply from the rep is handled against it (see _after_read_back)."""
    call_sid = str(fields.get("call_sid") or "").strip()
    draft = session.scalar(select(VisitDraft).where(VisitDraft.company_id == company.id,
                                                    VisitDraft.call_sid == call_sid)) if call_sid else None
    if not any(k in fields for k in AGENT_FIELDS):
        fields = _read_reply(session, company, rep, draft, fields)
        if fields is None:
            return {"status": "repeat", "say": "", "matches": [], "asked": None}
    # The draft remembers what was heard: the agent tends to send only its latest reply's fields, and a
    # "missing" then would wipe the doctor named two turns ago (30 Oct: "Which doctor?" asked twice).
    # A value only changes when the agent sends a new one. A "none" clears it only if the rep's reply was
    # about that item: on 31 Oct the agent sent only the next visit and "none" for everything else, which
    # wiped the doctor, chemist and order.
    if draft and draft.heard:
        about = {i.strip() for i in str(fields.get("about") or "").split(",")}
        kept = lambda k: _value(fields.get(k)) == MISSING or _value(fields.get(k)) == NONE and k not in about
        fields = {**fields, **{k: v for k, v in draft.heard.items() if v and _value(v) != MISSING and kept(k)}}
    heard = {k: str(fields.get(k) or "").strip() for k in HEARD}
    mr_said = str(fields.get("mr_said") or "").strip()
    guess = "en" if str(fields.get("language", "")).lower().startswith("en") else "hi"  # the agent's, last resort
    lang = detect_language(mr_said, draft.language if draft and draft.language else None) or guess
    yes = str(fields.get("confirms_readback") or "").strip().lower().startswith("y")
    # The agent called again on its own: a read-back is out and the rep has said nothing since, or the
    # same words arrive again straight away. (The same "haan" later, after Saathi spoke, is a new reply.)
    # Also when nothing reached the agent but Saathi's own line (31 Oct: it sent "Kothrud था?" as the
    # rep's words), or nothing at all and nothing changed, however long after.
    recent = draft is not None and utcnow() - draft.updated_at < REPEAT_WINDOW
    if draft and (draft.confirmed  # already recorded; the closing line has been said
                  or draft.readback and not mr_said
                  or mr_said and mr_said == draft.mr_said and recent
                  or mr_said and draft.said and key(mr_said) == key(draft.said)
                  or not mr_said and not yes and draft.heard == heard):
        return {"status": "repeat", "say": "", "matches": [], "asked": None}
    pinned = dict(draft.pinned or {}) if draft else {}
    if draft and draft.pending and mr_said:
        answer = _answer(draft.pending, mr_said, yes)
        if answer:
            p = draft.pending
            pinned[f'{p["kind"]}|{"*" if p["kind"] in ONE_PER_VISIT else key(p["heard"])}'] = answer
    result = _next_line(session, company, rep, fields, lang, pinned)
    if call_sid and draft is None:
        draft = VisitDraft(company_id=company.id, rep_id=rep.id if rep else None, call_sid=call_sid, disputes={})
        session.add(draft)
    if draft is None:
        return result
    # read_back stays the basis until the visit is recorded, so even after a question in between,
    # only what changed is read back
    if draft.read_back and result["status"] == "complete":
        result = _after_read_back(draft, result, fields, yes, lang, company)
    draft.fields, draft.heard, draft.mr_said, draft.language = result["visit"], heard, mr_said, lang
    draft.pending, draft.pinned = result.get("pending"), pinned
    if result["say"]:
        draft.said = result["say"]
    if result["status"] == "complete":  # a read-back (whole or only the changed parts) is out
        flagged = (draft.read_back or {}).get("flagged", [])
        draft.readback, draft.read_back = result["say"], {**result["visit"], "flagged": flagged}
    elif result["status"] == "recorded":
        draft.fields, draft.readback, draft.confirmed = draft.read_back, None, True  # save what was read back
    elif result["status"] not in ("flagged", "asking"):  # a question about something new: not a read-back reply
        draft.readback = None
    draft.updated_at = utcnow()
    return result


def _after_read_back(draft, result, fields, yes, lang, company) -> dict:
    """The rep replied to a read-back. Compare the visit now with the one read back and answer only
    what the reply was about: the changed parts, one item asked again, or "what's not right?"."""
    L = LINES[lang]
    about = {ITEM_GROUP[i.strip()] for i in str(fields.get("about") or "").split(",") if i.strip() in ITEM_GROUP}
    interrupted = str(fields.get("interrupted") or "").strip().lower().startswith("y")
    flagged = set((draft.read_back or {}).get("flagged", []))
    changed = [g for g in GROUPS if _differs(g, result["visit"], draft.read_back)
               and (g not in FREE_TEXT or g in about)]
    if changed:
        say = " ".join([*(result["parts"][g] for g in changed if g in result["parts"]), L["ask"]])
        return {**result, "say": say}
    disputed = [g for g in GROUPS if g in about and g not in flagged]
    if disputed:
        g = disputed[0]
        draft.disputes = {**(draft.disputes or {}), g: (draft.disputes or {}).get(g, 0) + 1}
        if draft.disputes[g] >= DISPUTES_BEFORE_FLAG:  # same item garbled again: keep it, the manager checks it
            draft.read_back = {**draft.read_back, "flagged": sorted(flagged | {g})}
            return {**result, "status": "flagged", "say": L["flag"].format(item=L["items"][g]), "asked": f"flag:{g}"}
        return {**result, "status": "asking", "say": L["again"][g], "asked": f"again:{g}"}
    if interrupted:
        return {**result, "status": "asking", "say": L["whats_wrong"], "asked": "whats_wrong"}
    if not draft.readback:  # the reply was to a question, not to a read-back: a yes here records nothing
        parts = [result["parts"][g] for g in GROUPS if g in about and g in result["parts"]]
        return {**result, "say": " ".join([*parts, L["ask"]]) if parts else result["say"]}
    if not yes:
        return {**result, "status": "asking", "say": L["ask"], "asked": "confirm_readback"}
    follow = L["followup"] if company.auto_followup and draft.read_back.get("next_visit") else ""
    return {**result, "status": "recorded", "say": L["recorded"] + follow + L["thanks"]}


def _read_reply(session, company, rep, draft, fields) -> dict | None:
    """The agent sent only the rep's words: read what they change (extract.py) and turn that into the
    fields check_visit works on. None when there is no new reply to read."""
    mr_said = str(fields.get("mr_said") or "").strip()
    heard = {k: MISSING for k in HEARD} | dict((draft.heard if draft else None) or {})
    if draft and (draft.confirmed or not mr_said or draft.said and key(mr_said) == key(draft.said)
                  or mr_said == draft.mr_said and utcnow() - draft.updated_at < REPEAT_WINDOW):
        return None
    if not mr_said:
        return {**fields, **heard}
    # Replays pass the line the rep actually answered; on a call it is Saathi's last line.
    saathi = str(fields.get("saathi_said") or (draft.said if draft else "") or "")
    resolver = Resolver(session, company.id, rep)

    def same(a, b):
        if a == b or key(a) and key(a) == key(b):
            return True
        ma, mb = (resolver.resolve(x, "product") for x in (a, b))
        return bool(ma.best) and ma.best == mb.best and "low" not in (ma.confidence, mb.confidence)

    notes = str(fields.get("resume_notes") or "").strip()
    if draft is None and notes and "{{" not in notes:  # a resume call: start from the cut-off report's notes
        heard, _ = apply_patch(heard, extract.extract(heard, "", notes)["changes"], same)
    patch = extract.extract(heard, saathi, mr_said)
    new, about = apply_patch(heard, patch["changes"], same)
    yes = patch["reply"] == "yes" and not about
    return {**fields, **new, "about": ",".join(about), "confirms_readback": "yes" if yes else "no",
            "dropped": patch["dropped"], "reply": patch["reply"]}


def apply_patch(heard: dict, changes: list, same) -> tuple[dict, list]:
    """Apply a reply's changes to the visit as heard. Returns the new visit and the items the reply
    changed or said were wrong. Items the reply didn't mention are left exactly as they were."""
    h, about = dict(heard), []
    for c in changes:
        f, op, name = PATCH_FIELD[c["item"]], c["op"], (c.get("name") or "").strip()
        before = h.get(f)
        if name and not _grounded(name, c.get("quote", "")):
            if f not in ("samples", "orders"):
                continue  # a name the rep didn't say in these words is not applied
            name = ""  # a sample or order whose product wasn't in the rep's words: asked, not guessed
        if op == "dispute":
            about.append(f)
            continue
        if op == "none":
            h[f] = NONE
        elif f in ("doctor", "area", "chemist"):
            h[f] = name or h[f]
        elif f in ("next_visit", "feedback", "promise"):
            h[f] = (c.get("text") or "").strip() or h[f]
            if f == "promise":
                h["promise_material"] = "yes" if c.get("material") else "no"
        elif f in ("products", "stock_outs"):
            items = _items(h.get(f))
            if name and op == "remove":
                items = [i for i in items if not same(i, name)]
            elif name and not any(same(i, name) for i in items):
                items.append(name)
            h[f] = "; ".join(items) if items else (h[f] if op != "remove" else MISSING)
        else:  # samples, orders: one entry per product
            pairs, name, qty = _pairs(h.get(f)), name or UNKNOWN, c.get("quantity")
            if _strength_as_quantity(name, qty, c.get("quote", "")):
                qty = None  # asked instead: "<product> का order कितना था?"
            if op == "remove":
                pairs = [p for p in pairs if not same(p[0], name)]
            else:
                at = next((i for i, p in enumerate(pairs) if same(p[0], name)), None)
                unknown = [i for i, p in enumerate(pairs) if p[0] == UNKNOWN]
                if at is None and name != UNKNOWN and unknown:  # the product of an earlier "twenty का order तीस"
                    # the one with the same quantity, else the only one (STT and the model mix up
                    # strengths and quantities: "Storvas twenty का order तीस" was once read as 20)
                    at = next((i for i in unknown if qty in (None, pairs[i][1])), unknown[0] if len(unknown) == 1 else None)
                entry = (name, qty if qty is not None else (pairs[at][1] if at is not None else None))
                pairs = pairs[:at] + [entry] + pairs[at + 1:] if at is not None else pairs + [entry]
            h[f] = "; ".join(f"{n}: {q if q is not None else '?'}" for n, q in pairs) or MISSING
        if h.get(f) != before:
            about.append(f)
    return h, list(dict.fromkeys(about))


def _grounded(name, quote) -> bool:
    """The name is in the rep's own words: its letters appear in the quote. On 31 Oct "twenty का तीस
    order" came back as a Telma 40 order, the product taken from another sentence."""
    letters = re.sub(r"\d+", "", key(name, person=True))
    return not letters or letters in key(quote)


def _strength_as_quantity(name, qty, quote) -> bool:
    """The quantity is the product's own strength while the rep's words hold another number too:
    "strovas बीस का order तीस" read as Storvas 20 x 20 (31 Oct). Then the quantity isn't trusted."""
    if qty is None:
        return False
    strength = set(re.findall(r"\d+", to_latin(name)))
    said = re.findall(r"\d+", to_latin(quote))
    return str(qty) in strength and any(n != str(qty) for n in said)


def _answer(pending, mr_said, yes) -> str | None:
    """The name the rep's reply settles a name question on: the offered name said back, or a yes
    when only one name was offered ("Kothrud था?" - "हां"). Otherwise the question stays open."""
    said, person = key(mr_said), pending["kind"] == "doctor"
    named = [o for o in pending["options"] if key(o, person) and key(o, person) in said]  # "doctor patil" is Dr Patil
    if len(named) == 1:
        return named[0]
    return pending["options"][0] if yes and len(pending["options"]) == 1 else None


def _differs(group, visit, read_back) -> bool:
    norm = lambda v: json.loads(json.dumps([(v or {}).get(k) for k in GROUPS[group]]))  # tuples come back as lists
    return norm(visit) != norm(read_back)


def _next_line(session, company, rep, fields, lang, pinned=None) -> dict:
    L = LINES[lang]
    resolver = Resolver(session, company.id, rep)
    values = {k: _value(fields.get(k)) for k in REQUIRED + ["orders", "feedback"]}
    for k in ("doctor", "area"):  # every visit has these: "none" means the agent lost them, so ask
        if values[k] == NONE:
            values[k] = MISSING
    samples, orders = _pairs(fields.get("samples")), _pairs(fields.get("orders"))
    stock = [s.split(":")[0].strip() for s in _items(fields.get("stock_outs"))]  # names only, no quantities

    # The area wasn't said (or STT cut it off: "daughter patil h"), but the doctor is known: their area is
    # on file, so use it instead of asking. It is read back with the rest, so the rep can still correct it.
    if values["area"] == MISSING and values["doctor"] not in (MISSING, NONE):
        d = resolver.resolve(values["doctor"], "doctor")
        if d.best and d.confidence in ("high", "medium") and resolver.doctor_area.get(d.best):
            values["area"] = resolver.doctor_area[d.best]

    heard = []  # (kind, text) in the order they'll be asked about
    for kind in ("doctor", "area", "chemist"):
        if values[kind] not in (MISSING, NONE):
            heard.append((kind, values[kind]))
    for name in _items(fields.get("products")) + [n for n, _ in samples + orders] + stock:
        if name != UNKNOWN and ("product", name) not in heard:
            heard.append(("product", name))
    matches = dict(zip(heard, resolver.resolve_all(heard)))
    for (kind, text), m in matches.items():  # names the rep already confirmed in this call
        pin = (pinned or {}).get(f"{kind}|{key(text)}") or (
            (pinned or {}).get(f"{kind}|*") if kind in ONE_PER_VISIT and m.confidence != "high" else None)
        if pin:
            matches[(kind, text)] = Match(heard=text, kind=kind, best=pin, confidence="high", score=1.0)
    name = lambda kind, text: spoken(getattr(matches.get((kind, text)), "best", None) or text)

    def best(kind, text):
        m = matches.get((kind, text))
        return (m.best if m and m.best and m.confidence in ("high", "medium") else text)

    promise = values["promise"] if values["promise"] not in (MISSING, NONE) else None
    visit = {  # what would be saved: the parse_visit() shape, with resolved names
        "doctor_name": best("doctor", values["doctor"]) if values["doctor"] != MISSING else None,
        "area": best("area", values["area"]) if values["area"] not in (MISSING, NONE) else None,
        "products_discussed": [best("product", p) for p in _items(fields.get("products"))],
        "samples": [(best("product", p), n) for p, n in samples],
        "orders": [(best("product", p), n) for p, n in orders],
        "chemist_name": best("chemist", values["chemist"]) if values["chemist"] not in (MISSING, NONE) else None,
        "stock_outs": [best("product", p) for p in stock],
        "next_visit": values["next_visit"] if values["next_visit"] not in (MISSING, NONE) else None,
        "feedback": values["feedback"] if values["feedback"] not in (MISSING, NONE) else None,
        "promises": [promise] if promise else [],
        "promises_done": [],
        "materials": [promise] if promise and str(fields.get("promise_material", "")).lower().startswith("y") else [],
    }

    def reply(status, say, parts=None, asked=None, pending=None):
        return {"status": status, "say": say, "visit": visit, "parts": parts or {}, "asked": asked,
                "pending": pending, "matches": [m.as_dict() for m in matches.values()]}

    # 1. a name that matched nothing on the lists
    for (kind, text), m in matches.items():
        if m.confidence == "low":
            options = [spoken(o) for o in m.alternatives]
            k = L["kinds"][kind]
            if options:
                return reply("unclear", L["pick"].format(kind=k, options=L["or"].join(options)), asked=f"pick:{kind}",
                             pending={"kind": kind, "heard": text, "options": m.alternatives})
            return reply("unclear", L["repeat"].format(kind=k), asked=f"repeat:{kind}")
    # 2. a guess the matcher itself says must be confirmed (e.g. only the strength was heard)
    for (kind, text), m in matches.items():
        if m.confidence == "medium" and m.hint:
            return reply("unclear", L["confirm"].format(name=spoken(m.best)), asked=f"confirm:{kind}",
                         pending={"kind": kind, "heard": text, "options": [m.best]})
    # 3. a sample or order whose product wasn't named ("twenty का order तीस"): ask which, never guess
    for pairs, line in ((samples, "which_sample"), (orders, "which_order")):
        for product, n in pairs:
            if product == UNKNOWN:
                return reply("missing", L[line].format(n=say_quantity(n, lang) if n is not None else "").strip(),
                             asked=line)
    # 4. nothing about the visit yet: invite the whole of it, not one item; else the first missing item
    if all(values[k] == MISSING for k in REQUIRED):
        return reply("missing", L["invite"], asked="visit")
    for item in REQUIRED:
        if item == "stock_outs" and values["chemist"] in (MISSING, NONE):
            continue
        if values[item] == MISSING:
            return reply("missing", L[item].format(doctor=name("doctor", values["doctor"]) if values["doctor"] != MISSING else "",
                                                 chemist=name("chemist", values["chemist"]) if values["chemist"] not in (MISSING, NONE) else ""),
                             asked=item)
    # 5. a sample or order without a number
    for pairs, line in ((samples, "qty_sample"), (orders, "qty_order")):
        for product, n in pairs:
            if n is None:
                return reply("missing", L[line].format(product=name("product", product)), asked=line)

    # 6. everything is there: the read-back, one sentence per part (see GROUPS), so a later
    # correction can be read back on its own
    join = lambda xs: L["and"].join(xs)
    parts = {"met": L["met"].format(doctor=name("doctor", values["doctor"]), area=name("area", values["area"]))}
    products = _items(fields.get("products"))
    if products:
        parts["discussed"] = L["discussed"].format(products=join(name("product", p) for p in products))
    parts["samples"] = L["samples_given"].format(items=join(
        L["sample"].format(product=name("product", p), n=say_quantity(n, lang)) for p, n in samples)) if samples else L["no_samples"]
    if values["chemist"] == NONE:
        parts["chemist"] = L["no_chemist"]
    else:
        chemist = name("chemist", values["chemist"])
        parts["chemist"] = L["at_chemist"].format(chemist=chemist, orders=join(
            L["order"].format(product=name("product", p), n=say_quantity(n, lang)) for p, n in orders)) \
            if orders else L["no_order"].format(chemist=chemist)
        parts["stock"] = L["stock"].format(products=join(name("product", p) for p in stock)) if stock else L["no_stock"]
    if values["feedback"] not in (MISSING, NONE):
        parts["feedback"] = L["feedback"].format(feedback=values["feedback"])
    parts["promise"] = L["no_promise"] if values["promise"] == NONE else L["promised"].format(promise=values["promise"])
    parts["next"] = L["no_next"] if values["next_visit"] == NONE else L["next"].format(next_visit=values["next_visit"])
    return reply("complete", " ".join([*parts.values(), L["ask"]]), parts)
