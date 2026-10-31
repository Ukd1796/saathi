"""Resolve a name the transcriber heard ("Exezle 500", "हजस पर") to the company's own master data.

Used two ways: live on the call, by the `resolve_names` custom function, so the agent can
confirm "Azithral 500?" before the read-back; and after the call, by ingest, to link a visit.

Steps: transliterate Devanagari to Latin, check the company's learnt aliases, then score every
candidate on spelling (rapidfuzz) and sound (metaphone). The rep's own doctors are searched
before the rest of the company. Strength numbers ("500", "40") must agree, because "Telma 40"
and "Telma H" differ only there. The result carries a confidence the agent acts on:
  high   -> use it silently;  medium -> confirm with the rep;  low -> ask them to repeat.
"""

import re
import unicodedata
from dataclasses import dataclass, field

import jellyfish
from indic_transliteration import sanscript
from rapidfuzz import fuzz
from sqlalchemy import select

from .matching import DEVANAGARI_DIGITS
from .models import Chemist, Doctor, NameAlias, Product, Rep

KINDS = ("product", "doctor", "chemist", "area")
HIGH, MEDIUM = 0.86, 0.6
TITLE = re.compile(r"^\s*(dr\.?|doctor|डॉ\.?|डॉक्टर)\s*", re.I)


def to_latin(text):
    """'हदापसर' -> 'hadapsar'. Drops the inherent final 'a' Hindi doesn't pronounce."""
    text = spoken_numbers(str(text).translate(DEVANAGARI_DIGITS))
    if not re.search(r"[ऀ-ॿ]", text):
        return text
    out = []
    for word in re.split(r"(\s+)", text):
        if re.search(r"[ऀ-ॿ]", word):
            word = sanscript.transliterate(word, sanscript.DEVANAGARI, sanscript.IAST)
            word = word.replace("ś", "sh").replace("ṣ", "sh").replace("c", "ch").replace("ṃ", "n")
            word = unicodedata.normalize("NFKD", word).encode("ascii", "ignore").decode()
            if len(word) >= 3 and word.endswith("a"):
                word = word[:-1]
        out.append(word)
    return "".join(out)


UNITS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                     "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split(), 0) if w != "_"}
NUMBER_RUN = re.compile(r"\b(?:(?:%s|hundred|point)\b\s*)+" % "|".join([*UNITS, *TENS]), re.I)


def _run_to_digits(run):
    """'five hundred' -> '500', 'forty' -> '40', 'six point two five' -> '6.25'."""
    words = run.lower().split()
    whole, _, frac = " ".join(words).partition("point")
    whole = whole.split()
    digits = "".join(str(UNITS[w]) for w in frac.split() if w in UNITS)
    if "hundred" in whole:
        total = 0
        for w in whole:
            if w == "hundred":
                total = (total or 1) * 100
            else:
                total += UNITS.get(w, 0) + TENS.get(w, 0)
        number = str(total)
    else:
        # Strengths are often said digit-group by digit-group: "six twenty five" is 625, not 31.
        groups = []
        for w in whole:
            if w in UNITS and groups and groups[-1] % 10 == 0 and groups[-1] >= 20 and UNITS[w] < 10:
                groups[-1] += UNITS[w]
            elif w in UNITS or w in TENS:
                groups.append(UNITS.get(w, TENS.get(w)))
        number = "".join(str(g) for g in groups) if groups else "0"
    return f"{number}.{digits}" if digits else number


# Hindi numbers as speech-to-text writes them in Devanagari, 0-99 in order (also what Saathi says).
HINDI_NUMBERS = ("शून्य एक दो तीन चार पाँच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस बीस "
                 "इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस इकतीस बत्तीस तैंतीस चौंतीस पैंतीस "
                 "छत्तीस सैंतीस अड़तीस उनतालीस चालीस इकतालीस बयालीस तैंतालीस चवालीस पैंतालीस छियालीस सैंतालीस "
                 "अड़तालीस उनचास पचास इक्यावन बावन तिरेपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ साठ इकसठ बासठ "
                 "तिरेसठ चौंसठ पैंसठ छियासठ सड़सठ अड़सठ उनहत्तर सत्तर इकहत्तर बहत्तर तिहत्तर चौहत्तर पचहत्तर "
                 "छिहत्तर सतहत्तर अठहत्तर उनासी अस्सी इक्यासी बयासी तिरासी चौरासी पचासी छियासी सत्तासी अट्ठासी "
                 "नवासी नब्बे इक्यानवे बानवे तिरानवे चौरानवे पचानवे छियानवे सत्तानवे अट्ठानवे निन्यानवे").split()
# Other spellings speech-to-text uses for the same numbers
HINDI_NUMBER_WORDS = {w: i for i, w in enumerate(HINDI_NUMBERS)} | {"पांच": 5, "छः": 6, "छे": 6, "छै": 6}
HINDI_NUMBER = re.compile(r"(?<![ऀ-ॿ])(" + "|".join(sorted(map(re.escape, HINDI_NUMBER_WORDS), key=len, reverse=True)) + r")(?![ऀ-ॿ])")


def spoken_numbers(text):
    """Speech-to-text often writes strengths as words ("telma forty", "strovas बीस"): turn them into digits."""
    text = HINDI_NUMBER.sub(lambda m: str(HINDI_NUMBER_WORDS[m.group(0)]), text)
    return NUMBER_RUN.sub(lambda m: _run_to_digits(m.group(0)) + " ", text).strip()


WORDS = {v: k for k, v in UNITS.items()} | {v: k for k, v in TENS.items()}


def _say_number(n):
    """40 -> 'forty', 625 -> 'six hundred twenty five', 6.25 -> 'six point two five'."""
    whole, _, frac = n.partition(".")
    i = int(whole)
    if i >= 10000:
        out = " ".join(WORDS[int(d)] for d in whole)
    else:
        parts = []
        if i >= 1000:
            parts.append(WORDS[i // 1000] + " thousand")
            i %= 1000
        if i >= 100:
            parts.append(WORDS[i // 100] + " hundred")
            i %= 100
        if i >= 20:
            parts.append(WORDS[i - i % 10] + (" " + WORDS[i % 10] if i % 10 else ""))
        elif i or not parts:
            parts.append(WORDS[i])
        out = " ".join(parts)
    return out + (" point " + " ".join(WORDS[int(d)] for d in frac) if frac else "")


def _say_strength(n):
    """Strengths are said in digit groups: 625 is "six twenty five", 120 "one twenty"; round
    hundreds stay "five hundred". Other numbers are read normally."""
    if "." not in n and len(n) == 3 and not n.endswith("00"):
        rest = int(n[1:])
        return f"{WORDS[int(n[0])]} " + (_say_number(str(rest)) if rest >= 10 else f"oh {WORDS[rest]}")
    return _say_number(n)


def spoken(text):
    """What the voice should say: 'Telma 40' -> 'Telma forty', so digits never reach the speech engine."""
    text = re.sub(r"\d+(?:\.\d+)?", lambda m: f" {_say_strength(m.group(0))} ", text)
    return re.sub(r"\s+([.,;:!?])", r"\1", re.sub(r"\s+", " ", text)).strip()


def key(text, person=False):
    """Normalised form used for exact and alias lookups: lowercase letters and digits only."""
    text = to_latin(TITLE.sub("", text) if person else text)
    if person:
        text = TITLE.sub("", text)
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _sound(text):
    letters = re.sub(r"[^a-z ]", " ", text.lower()).split()
    return "".join(jellyfish.metaphone(w) for w in letters)


def _numbers(text):
    return re.findall(r"\d+", text)


@dataclass
class Match:
    heard: str
    kind: str
    best: str | None = None
    confidence: str = "low"
    score: float = 0.0
    alternatives: list = field(default_factory=list)
    hint: str | None = None  # why this is the best guess, when it isn't from the name itself

    def as_dict(self):
        return {"heard": self.heard, "kind": self.kind, "best": self.best,
                "confidence": self.confidence, "alternatives": self.alternatives}


def score(heard, candidate, person=False):
    h, c = to_latin(TITLE.sub("", heard) if person else heard), candidate  # "डॉक्टर" before it becomes "doktar"
    if person:
        h, c = TITLE.sub("", h), TITLE.sub("", c)
    hn, cn = _numbers(h), _numbers(c)
    if hn and cn and hn != cn:
        return 0.0  # "Telma 40" is never "Telma 80"
    variant = [t for t in re.findall(r"[a-z]+", c.lower()) if len(t) <= 2]
    if hn and not cn and any(t not in h.lower().split() for t in variant):
        return 0.0  # "Telma 80" is not "Telma H": the strength/variant part disagrees
    hk, ck = key(h), key(c)
    if not hk or not ck:
        return 0.0
    if hk == ck:
        return 1.0
    spelling = fuzz.ratio(hk, ck) / 100
    sound = fuzz.ratio(_sound(h), _sound(c)) / 100 if _sound(h) and _sound(c) else 0
    # A heard name that is the start of exactly one candidate ("Cardivas" in "Cardivas 3.125")
    prefix = 0.9 if min(len(hk), len(ck)) >= 4 and (ck.startswith(hk) or hk.startswith(ck)) else 0
    s = max(prefix, 0.55 * spelling + 0.45 * sound)
    if hn and hn == cn:
        s = min(1.0, s + 0.1)
    return s


class Resolver:
    """Loads one company's names once; resolve() many names against them."""

    def __init__(self, session, company_id, rep: Rep | None = None):
        self.names = {
            "product": [p.name for p in session.scalars(select(Product).where(Product.company_id == company_id))],
            "chemist": [c.name for c in session.scalars(select(Chemist).where(Chemist.company_id == company_id))],
        }
        doctors = list(session.scalars(select(Doctor).where(Doctor.company_id == company_id)))
        self.names["doctor"] = [d.name for d in doctors]
        areas = {d.area for d in doctors} | set(session.scalars(select(Chemist.area).where(Chemist.company_id == company_id)))
        for r in session.scalars(select(Rep).where(Rep.company_id == company_id)):
            areas |= set(r.areas)
        self.names["area"] = sorted(a for a in areas if a)
        # The rep's own doctors first: a rep in Kothrud saying "Mehta" means their Dr Mehta.
        self.mine = set()
        if rep:
            self.mine = {d.name for d in doctors if d.assigned_rep_id == rep.id or (d.area and d.area in rep.areas)}
            self.mine |= set(rep.areas)  # and the areas of their own territory
        self.doctor_area = {d.name: d.area for d in doctors}
        self.aliases = {(a.kind, a.heard): a.target for a in
                        session.scalars(select(NameAlias).where(NameAlias.company_id == company_id))}

    def resolve(self, heard, kind):
        m = Match(heard=heard, kind=kind)
        if kind not in KINDS or not key(heard):
            return m
        person = kind == "doctor"
        alias = self.aliases.get((kind, key(heard, person)))
        if alias:
            m.best, m.confidence, m.score = alias, "high", 1.0
            return m
        scored = sorted(((score(heard, n, person), n) for n in self.names[kind]), reverse=True)
        if self.mine and kind in ("doctor", "area"):
            scored = sorted(((s + (0.05 if n in self.mine else 0), n) for s, n in scored), reverse=True)
        scored = [(min(s, 1.0), n) for s, n in scored if s > 0.3]
        if not scored or scored[0][0] < MEDIUM:
            near = self._same_name_other_strength(heard, kind)
            if near:
                m.best, m.confidence, m.score = near, "medium", MEDIUM
                m.hint = f"heard a different strength; your list has {near}"
                return m
            same = self._strength_only(heard, kind)
            if len(same) == 1:
                m.best, m.confidence, m.score = same[0], "medium", MEDIUM
                m.hint = f"only the strength was heard; {same[0]} is the only product with it"
                return m
            if same:
                m.alternatives = same[:2]
                return m
        if not scored:
            return m
        (top, best), runner = scored[0], (scored[1][0] if len(scored) > 1 else 0)
        m.best, m.score = best, round(top, 3)
        m.alternatives = [n for s, n in scored[1:3] if top - s < 0.2]
        if top >= HIGH and top - runner >= 0.08:
            m.confidence = "high"
        elif top >= MEDIUM:
            m.confidence = "medium"
        else:
            m.best = None
            m.alternatives = [n for _, n in scored[:2]]
        return m

    def _same_name_other_strength(self, heard, kind):
        """'Thyronorm 500' when the list only has Thyronorm 50: the name is clear, the number isn't.
        Offer the one product with that name so the agent can ask, instead of making the rep repeat."""
        if kind != "product" or not _numbers(to_latin(heard)):
            return None
        bare = key(re.sub(r"[\d.]+", "", to_latin(heard)))
        same = [n for n in self.names["product"] if _numbers(n) and key(re.sub(r"[\d.]+", "", n)) == bare]
        return same[0] if len(same) == 1 else None

    def _strength_only(self, heard, kind):
        """'seventy five' with the name lost: the products whose strength is that number."""
        latin = to_latin(heard)
        if kind != "product" or not _numbers(latin) or re.search(r"[a-z]", latin.lower()):
            return []
        return [n for n in self.names["product"] if _numbers(n) == _numbers(latin)]

    def resolve_all(self, items):
        """Resolve a call's names together, so they help each other: when the area is unclear but the
        doctor is known, the doctor's area on file is the likely answer (confirm it, don't assume)."""
        results = [self.resolve(heard, kind) for kind, heard in items]
        doctors = [m.best for m in results if m.kind == "doctor" and m.best and m.confidence in ("high", "medium")]
        area = self.doctor_area.get(doctors[0]) if doctors else None
        for m in results:
            if m.kind == "area" and m.confidence == "low" and area:
                m.best, m.confidence, m.alternatives = area, "medium", []
                m.hint = f"{doctors[0]}'s area"
        return results

    def link(self, heard, kind):
        """Name to store on a visit: only a high-confidence match, never a guess."""
        m = self.resolve(heard, kind)
        return m.best if m.confidence == "high" else None


def learn_alias(session, company_id, kind, heard, target):
    k = key(heard, kind == "doctor")
    if not k or k == key(target, kind == "doctor"):
        return
    row = session.scalar(select(NameAlias).where(NameAlias.company_id == company_id,
                                                 NameAlias.kind == kind, NameAlias.heard == k))
    row = row or NameAlias(company_id=company_id, kind=kind, heard=k)
    row.target = target
    session.add(row)


def parse_items(text):
    """'product: Exezle 500; area: हजस पर' -> [('product', 'Exezle 500'), ('area', 'हजस पर')]."""
    out = []
    for part in re.split(r"[;\n]", str(text or "")):
        if ":" in part:
            kind, heard = part.split(":", 1)
            kind = kind.strip().lower().rstrip("s")
            if kind in KINDS and heard.strip():
                out.append((kind, heard.strip()))
    return out
