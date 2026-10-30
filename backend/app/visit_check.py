"""check_visit: the agent hands over what the rep has said so far; the backend decides what Saathi says next.

Either the single next question (a name to clear up, a missing item, a quantity), or, once nothing is
missing, the whole read-back, built here from the resolved names in the rep's language. The model
only has to repeat the line, so a read-back can't skip items or echo a garbled word.
"""

import json
import re
from datetime import timedelta

from sqlalchemy import select

from .models import VisitDraft, utcnow
from .names import Resolver, _say_number, spoken, spoken_numbers

MISSING, NONE = "missing", "none"
NONE_WORDS = {"none", "no", "nil"}  # the tool's own protocol values; the agent is told to send "none"
# Asked in this order; stock-outs only matter once a chemist was visited.
REQUIRED = ["doctor", "area", "products", "samples", "chemist", "stock_outs", "promise", "next_visit"]
HEARD = REQUIRED + ["orders", "feedback", "promise_material"]
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

HINDI_NUMBERS = ("शून्य एक दो तीन चार पाँच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस बीस "
                 "इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस इकतीस बत्तीस तैंतीस चौंतीस पैंतीस "
                 "छत्तीस सैंतीस अड़तीस उनतालीस चालीस इकतालीस बयालीस तैंतालीस चवालीस पैंतालीस छियालीस सैंतालीस "
                 "अड़तालीस उनचास पचास इक्यावन बावन तिरेपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ साठ इकसठ बासठ "
                 "तिरेसठ चौंसठ पैंसठ छियासठ सड़सठ अड़सठ उनहत्तर सत्तर इकहत्तर बहत्तर तिहत्तर चौहत्तर पचहत्तर "
                 "छिहत्तर सतहत्तर अठहत्तर उनासी अस्सी इक्यासी बयासी तिरासी चौरासी पचासी छियासी सत्तासी अट्ठासी "
                 "नवासी नब्बे इक्यानवे बानवे तिरानवे चौरानवे पचानवे छियानवे सत्तानवे अट्ठानवे निन्यानवे").split()

LINES = {
    "hi": {
        "invite": "बताइए, किस doctor से मिले और क्या-क्या हुआ?",
        "doctor": "किस doctor से मिले?", "area": "{doctor} से किस area में मिले?",
        "products": "कौनसे products discuss किए?", "samples": "कोई sample दिए? किसके, और कितने?",
        "chemist": "Doctor के पास किसी chemist पे गए?", "stock_outs": "{chemist} में किसी product का stock ख़त्म था?",
        "promise": "Doctor को कुछ promise किया?", "next_visit": "अगली visit कब है?",
        "qty_sample": "{product} के कितने sample दिए?", "qty_order": "{product} का order कितना था?",
        "pick": "कौनसा {kind} था, {options}?", "repeat": "{kind} का नाम फिर से बताइए?", "confirm": "{name} था?",
        "or": " या ", "and": " और ", "kinds": {"product": "product", "doctor": "doctor", "chemist": "chemist", "area": "area"},
        "met": "{doctor}, {area} में मिले थे।", "discussed": "{products} discuss हुए।",
        "sample": "{product} के {n} sample", "samples_given": "{items} दिए।", "no_samples": "कोई sample नहीं दिया।",
        "order": "{product} का order {n}", "at_chemist": "{chemist} में {orders} मिला।",
        "no_order": "{chemist} में कोई order नहीं मिला।", "no_chemist": "किसी chemist पे नहीं गए।",
        "stock": "{products} का stock ख़त्म था।", "no_stock": "कोई stock issue नहीं था।",
        "feedback": "Doctor ने बोला कि {feedback}।", "promised": "आपने promise किया कि {promise}।",
        "no_promise": "कोई promise नहीं था।", "next": "अगली visit {next_visit}।", "ask": "सही है?",
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
        "pick": "Which {kind} was it, {options}?", "repeat": "Could you say the {kind} name again?", "confirm": "Was it {name}?",
        "or": " or ", "and": " and ", "kinds": {"product": "product", "doctor": "doctor", "chemist": "chemist", "area": "area"},
        "met": "You met {doctor} in {area}.", "discussed": "You discussed {products}.",
        "sample": "{n} samples of {product}", "samples_given": "You gave {items}.", "no_samples": "No samples were given.",
        "order": "an order of {n} {product}", "at_chemist": "At {chemist} you got {orders}.",
        "no_order": "At {chemist} there was no order.", "no_chemist": "You didn't visit a chemist.",
        "stock": "{products} was out of stock there.", "no_stock": "There were no stock issues.",
        "feedback": "The doctor said {feedback}.", "promised": "You promised {promise}.",
        "no_promise": "There was no promise.", "next": "The next visit is {next_visit}.", "ask": "Is that right?",
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
    # The draft remembers what was heard: the agent tends to send only its latest reply's fields, and a
    # "missing" then would wipe the doctor named two turns ago (30 Oct: "Which doctor?" asked twice).
    # A value only changes when the agent sends a new one; "none" still clears it.
    if draft and draft.heard:
        fields = {**fields, **{k: v for k, v in draft.heard.items()
                               if v and _value(v) != MISSING and _value(fields.get(k)) == MISSING}}
    heard = {k: str(fields.get(k) or "").strip() for k in HEARD}
    mr_said = str(fields.get("mr_said") or "").strip()
    guess = "en" if str(fields.get("language", "")).lower().startswith("en") else "hi"  # the agent's, last resort
    lang = detect_language(mr_said, draft.language if draft and draft.language else None) or guess
    yes = str(fields.get("confirms_readback") or "").strip().lower().startswith("y")
    # The agent called again on its own: a read-back is out and the rep has said nothing since, or the
    # same words arrive again straight away. (The same "haan" later, after Saathi spoke, is a new reply.)
    recent = draft is not None and utcnow() - draft.updated_at < REPEAT_WINDOW
    if draft and (draft.confirmed  # already recorded; the closing line has been said
                  or draft.readback and not mr_said
                  or mr_said and mr_said == draft.mr_said and recent
                  or not mr_said and not yes and draft.heard == heard and recent):
        return {"status": "repeat", "say": "", "matches": []}
    result = _next_line(session, company, rep, fields, lang)
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
            return {**result, "status": "flagged", "say": L["flag"].format(item=L["items"][g])}
        return {**result, "status": "asking", "say": L["again"][g]}
    if interrupted:
        return {**result, "status": "asking", "say": L["whats_wrong"]}
    if not draft.readback:  # the reply was to a question, not to a read-back: a yes here records nothing
        parts = [result["parts"][g] for g in GROUPS if g in about and g in result["parts"]]
        return {**result, "say": " ".join([*parts, L["ask"]]) if parts else result["say"]}
    if not yes:
        return {**result, "status": "asking", "say": L["ask"]}
    follow = L["followup"] if company.auto_followup and draft.read_back.get("next_visit") else ""
    return {**result, "status": "recorded", "say": L["recorded"] + follow + L["thanks"]}


def _differs(group, visit, read_back) -> bool:
    norm = lambda v: json.loads(json.dumps([(v or {}).get(k) for k in GROUPS[group]]))  # tuples come back as lists
    return norm(visit) != norm(read_back)


def _next_line(session, company, rep, fields, lang) -> dict:
    L = LINES[lang]
    resolver = Resolver(session, company.id, rep)
    values = {k: _value(fields.get(k)) for k in REQUIRED + ["orders", "feedback"]}
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
        if ("product", name) not in heard:
            heard.append(("product", name))
    matches = dict(zip(heard, resolver.resolve_all(heard)))
    name = lambda kind, text: spoken(matches[(kind, text)].best or text)

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

    def reply(status, say, parts=None):
        return {"status": status, "say": say, "visit": visit, "parts": parts or {},
                "matches": [m.as_dict() for m in matches.values()]}

    # 1. a name that matched nothing on the lists
    for (kind, text), m in matches.items():
        if m.confidence == "low":
            options = [spoken(o) for o in m.alternatives]
            k = L["kinds"][kind]
            if options:
                return reply("unclear", L["pick"].format(kind=k, options=L["or"].join(options)))
            return reply("unclear", L["repeat"].format(kind=k))
    # 2. a guess the matcher itself says must be confirmed (e.g. only the strength was heard)
    for m in matches.values():
        if m.confidence == "medium" and m.hint:
            return reply("unclear", L["confirm"].format(name=spoken(m.best)))
    # 3. nothing about the visit yet: invite the whole of it, not one item; else the first missing item
    if all(values[k] == MISSING for k in REQUIRED):
        return reply("missing", L["invite"])
    for key in REQUIRED:
        if key == "stock_outs" and values["chemist"] in (MISSING, NONE):
            continue
        if values[key] == MISSING:
            return reply("missing", L[key].format(doctor=name("doctor", values["doctor"]) if values["doctor"] != MISSING else "",
                                                 chemist=name("chemist", values["chemist"]) if values["chemist"] not in (MISSING, NONE) else ""))
    # 4. a sample or order without a number
    for pairs, line in ((samples, "qty_sample"), (orders, "qty_order")):
        for product, n in pairs:
            if n is None:
                return reply("missing", L[line].format(product=name("product", product)))

    # 5. everything is there: the read-back, one sentence per part (see GROUPS), so a later
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
    parts["next"] = L["next"].format(next_visit=values["next_visit"])
    return reply("complete", " ".join([*parts.values(), L["ask"]]), parts)
