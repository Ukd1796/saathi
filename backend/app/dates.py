"""Spoken dates to real ones: "10 din baad", "agle hafte", "Monday ko", "in two weeks"."""

import re
from datetime import date, timedelta

from .names import spoken_numbers, to_latin

# Hindi number words as reps say them for counts of days and weeks (English ones go through
# names.spoken_numbers). Only used next to din/hafte/mahine, so "do" here can't mean "give".
HINDI_NUMBERS = {"ek": 1, "do": 2, "teen": 3, "tin": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "chhe": 6,
                 "che": 6, "saat": 7, "sat": 7, "aath": 8, "ath": 8, "nau": 9, "das": 10, "dus": 10, "pandrah": 15,
                 "bees": 20, "bis": 20}
UNIT_DAYS = {"din": 1, "dino": 1, "day": 1, "days": 1, "hafte": 7, "hafta": 7, "hafton": 7, "week": 7, "weeks": 7,
             "mahine": 30, "mahina": 30, "month": 30, "months": 30}
WEEKDAYS = [("monday", "somvar", "somwar"), ("tuesday", "mangalvar", "mangalwar"), ("wednesday", "budhvar", "budhwar"),
            ("thursday", "guruvar", "guruwar", "brihaspativar"), ("friday", "shukravar", "shukrawar"),
            ("saturday", "shanivar", "shaniwar"), ("sunday", "ravivar", "raviwar", "itvaar", "itwar")]


def _clean(text):
    text = spoken_numbers(to_latin(str(text)).lower())
    return re.sub(r"[^a-z0-9 ]", " ", text)


def parse_when(text, today: date) -> date | None:
    """The date a rep meant, relative to today, or None if it can't be told."""
    if not text:
        return None
    t = _clean(text)
    words = t.split()
    for i, w in enumerate(words):
        if w in UNIT_DAYS:
            prev = words[i - 1] if i else ""
            n = int(prev) if prev.isdigit() else HINDI_NUMBERS.get(prev)
            if n is None and prev in ("agle", "agla", "next", "ek", "a"):
                n = 1
            if n:
                return today + timedelta(days=n * UNIT_DAYS[w])
    if re.search(r"\b(parso|parson|day after tomorrow)\b", t):
        return today + timedelta(days=2)
    if re.search(r"\b(kal|tomorrow)\b", t):  # "kal" is also yesterday, but a next visit is never in the past
        return today + timedelta(days=1)
    for wd, names in enumerate(WEEKDAYS):
        if any(re.search(rf"\b{n}\b", t) for n in names):
            ahead = (wd - today.weekday()) % 7 or 7
            return today + timedelta(days=ahead)
    return None
