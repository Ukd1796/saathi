"""Match what the agent heard ("Dr. Mehtaa", "telma") to the company's master lists.

A wrong match is worse than no match: an unmatched name is kept as raw text and shown for
review, while a wrong one silently files the visit under another doctor. So the rules are
strict and an ambiguous name ("Telma" when both Telma 40 and Telma H exist) stays unmatched.
"""

import re
from difflib import SequenceMatcher

DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def norm(text):
    text = str(text).translate(DEVANAGARI_DIGITS).lower()
    return re.sub(r"[^a-z0-9]", "", text)


def norm_person(text):
    text = re.sub(r"^\s*(dr\.?|doctor|डॉ\.?)\s*", "", str(text).strip(), flags=re.I)
    return norm(text)


def best_match(heard, candidates, key=lambda c: c.name, normalise=norm, threshold=0.85):
    """Return the candidate whose name matches `heard`, or None.

    Order: exact normalised match; then a unique candidate that starts with what was heard
    (or vice versa, e.g. "Cardivas 3.125" -> "Cardivas"); then fuzzy similarity, accepted only
    if it clears the threshold and beats the runner-up by a clear margin.
    """
    h = normalise(heard)
    if not h:
        return None
    named = [(normalise(key(c)), c) for c in candidates]
    for n, c in named:
        if n == h:
            return c
    prefix = [(n, c) for n, c in named if n.startswith(h) or h.startswith(n)]
    if len(prefix) > 1:
        return None  # "Pan" could be Pan 40 or Pan D; never let fuzzy matching pick one
    if len(prefix) == 1 and min(len(prefix[0][0]), len(h)) >= 4:
        return prefix[0][1]
    scored = sorted(((SequenceMatcher(None, h, n).ratio(), c) for n, c in named),
                    key=lambda s: s[0], reverse=True)
    if not scored or scored[0][0] < threshold:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.05:
        return None
    return scored[0][1]


def match_person(heard, candidates):
    return best_match(heard, candidates, normalise=norm_person, threshold=0.8)


def phone_key(number):
    """Compare phone numbers on their last 10 digits, so +91 98765 43210 == 09876543210."""
    digits = re.sub(r"\D", "", str(number or ""))
    return digits[-10:] if len(digits) >= 10 else digits
