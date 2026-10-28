"""Turn a Bolna execution's extracted_data into plain Python values.

Copied from the single-company prototype (saathi/saathi/extraction.py), whose rules match the
H1 scorer, plus two fields: call_type (debrief | briefing) and promises_done.
"""

import json
import re

FIELDS = ["doctor_name", "area", "products_discussed", "samples", "orders",
          "chemist_name", "stock_outs", "next_visit", "feedback", "promises",
          "call_type", "promises_done"]
NONE_WORDS = {"", "none", "na", "n/a", "null", "nil", "no", "nahi", "nothing",
              "koi nahi", "kahi nahi", "-", "not mentioned", "not applicable"}
DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def is_none(value):
    if value is None:
        return True
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return str(value).strip().lower().strip(".") in NONE_WORDS


def pick_value(value):
    """Bolna extraction values may be plain or {'subjective'|'objective': ..., 'confidence': ...}."""
    if isinstance(value, dict):
        for key in ("subjective", "objective", "value", "answer"):
            if key in value and not is_none(value[key]):
                return pick_value(value[key])
        return None
    if isinstance(value, list):
        return "; ".join(str(pick_value(v)) for v in value if not is_none(pick_value(v)))
    return value


def find_fields(obj, out):
    """Collect FIELDS from anywhere in the (possibly nested, possibly JSON-string) object."""
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except ValueError:
            return
    if not isinstance(obj, dict):
        return
    for key, value in obj.items():
        k = key.strip().lower().replace(" ", "_")
        if k in FIELDS:
            out.setdefault(k, pick_value(value))
        elif isinstance(value, (dict, str)):
            find_fields(value, out)


def split_items(value):
    if is_none(value):
        return []
    if isinstance(value, list):
        items = [str(v) for v in value]
    else:
        items = re.split(r"[;\n]|,|\s+and\s+|\s+aur\s+", str(value))
    return [i.strip() for i in items if not is_none(i)]


def parse_qty_items(value):
    """'Telma 40: 4; Pan D: 15' -> [('Telma 40', 4), ('Pan D', 15)]."""
    out = []
    for item in split_items(value):
        item = item.translate(DEVANAGARI_DIGITS)
        leading = re.match(r"^\s*(\d+)\s*(?:x\s+)?(.+)$", item)
        if ":" in item:
            name, qty_part = item.rsplit(":", 1)
            nums = re.findall(r"\d+", qty_part)
        elif leading:  # "5 strips Telma 40": quantity first, so the strength stays in the name
            nums, name = [leading.group(1)], leading.group(2)
        else:
            nums = re.findall(r"\d+", item)
            name = re.sub(r"\d+(?!.*\d)", "", item) if nums else item
        name = re.sub(r"\b(strips?|boxes?|box|tabs?|tablets?|units?|pcs|pieces?|x)\b", "", name, flags=re.I)
        out.append((name.strip(" -=x"), int(nums[-1]) if nums else None))
    return out


def text_or_none(value):
    return None if is_none(value) else str(value).strip()


def call_type(extracted):
    raw = {}
    find_fields(extracted, raw)
    value = (text_or_none(raw.get("call_type")) or "").lower()
    return next((t for t in ("briefing", "debrief") if t in value), None)


def parse_visit(extracted):
    """extracted_data -> dict of clean fields, or None if the call didn't report a visit."""
    raw = {}
    find_fields(extracted, raw)
    doctor = text_or_none(raw.get("doctor_name"))
    if not doctor:
        return None
    return {
        "doctor_name": doctor,
        "area": text_or_none(raw.get("area")),
        "products_discussed": split_items(raw.get("products_discussed")),
        "samples": parse_qty_items(raw.get("samples")),
        "orders": parse_qty_items(raw.get("orders")),
        "chemist_name": text_or_none(raw.get("chemist_name")),
        "stock_outs": split_items(raw.get("stock_outs")),
        "next_visit": text_or_none(raw.get("next_visit")),
        "feedback": text_or_none(raw.get("feedback")),
        "promises": split_sentences(raw.get("promises")),
        "promises_done": split_sentences(raw.get("promises_done")),
    }


def split_sentences(value):
    """Promises are sentences, so only split on semicolons and newlines, never on commas."""
    return [p.strip() for p in re.split(r"[;\n]", str(value or "")) if not is_none(p)]
