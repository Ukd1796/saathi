"""What one reply from the rep changes in the visit, read by the backend's own model (step 2).

The voice agent only passes the rep's words on. Here a model reads them against the visit so far and
Saathi's last line, and returns the changes the reply makes, each with the rep's own words as its
quote. Anything the reply doesn't mention stays as it is, so a slip can only touch what the rep just
talked about; a change whose quote isn't in the rep's words is dropped.
"""

import json
import logging
import os

import httpx

from .names import key

log = logging.getLogger("saathi.extract")

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
# Chosen on the replays (31 Oct): gpt-5.4-mini with low reasoning got every field right at a median
# 1.4 s; gpt-5.4 (low) timed out on long monologues, and no reasoning got fields or questions wrong.
MODEL = os.environ.get("EXTRACT_MODEL", "gpt-5.4-mini")
REASONING = os.environ.get("EXTRACT_REASONING", "low")
TIMEOUT_S = 8

ITEMS = ["doctor", "area", "product", "sample", "order", "chemist", "stock_out", "feedback", "promise", "next_visit"]
OPS = ["set", "add", "remove", "none", "dispute"]
REPLIES = ["yes", "no", "stop", "info"]

INSTRUCTIONS = """You read one reply from a pharma medical representative (MR) on a phone call with Saathi, the assistant that records their doctor visits. Speech-to-text wrote the reply from Hindi, English or a mix, and may have garbled words. You get the visit as Saathi has it so far, Saathi's last line, and the MR's reply. Return only what this reply changes in the visit.

Items:
- doctor, area: the doctor the MR met and where.
- product: a product discussed with the doctor (op add, remove or none).
- sample: samples given to the doctor, a product with a quantity.
- chemist: the chemist shop the MR visited near the doctor.
- order: an order taken at the chemist, a product with a quantity.
- stock_out: a product out of stock at that chemist (op add, remove or none).
- feedback: what the doctor said about the products, one short sentence in the MR's language.
- promise: what the MR promised the doctor, with any timing, in the MR's language; material is true if it is handing over something (a study, leaflet, chart, samples).
- next_visit: only when the next visit is, as the MR said it, in their language ("दो हफ़्ते बाद", "next Tuesday"), without words like "next visit" or "है".

Ops: set gives a single item its value, or a sample/order its product and quantity (it replaces the same product's earlier quantity). add and remove change a list. none means the MR said there was none. dispute means the MR says an item is wrong without giving the new value.

Rules:
- Only what this reply says. Never restate items from the visit so far that the reply doesn't change.
- quote: the MR's exact words this change comes from, copied unchanged from the reply.
- Write names as heard, in Latin letters, keeping the strength ("telma forty", "sharma medical"). Never swap in a different name.
- A number right after a product name is its strength and part of the name, in English or Hindi words ("<product> forty", "<product> बीस"). The quantity is the number that goes with the sample or order: "<product> बीस का order तीस" is name "<product> बीस", quantity 30. One number never counts as both.
- A number alone ("twenty") is not a product. If the product of a sample or order wasn't named, name is null.
- If no quantity was said, quantity is null. Never make up a number. Use the number as said (four strips is 4).
- Samples go to the doctor, orders come from the chemist, products are what was discussed. Never move a product from one to another.
- none only when the MR says there was none ("koi stock issue nahi" is stock_out none; "koi promise nahi" is promise none).
- A garbled word that may be a common word ("netsuvic" for "next week") is never a product or a name.
- reply is "yes" if the reply simply agrees with Saathi's last line, including repeating back what Saathi just said; "no" if it simply disagrees with nothing more; "stop" if the MR wants to stop or talk later; otherwise "info"."""

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["changes", "reply"],
    "properties": {
        "reply": {"type": "string", "enum": REPLIES},
        "changes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["item", "op", "name", "quantity", "text", "material", "quote"],
            "properties": {
                "item": {"type": "string", "enum": ITEMS},
                "op": {"type": "string", "enum": OPS},
                "name": {"type": ["string", "null"], "description": "doctor, area, chemist or product name as heard"},
                "quantity": {"type": ["integer", "null"]},
                "text": {"type": ["string", "null"], "description": "feedback, promise or next visit"},
                "material": {"type": ["boolean", "null"]},
                "quote": {"type": "string"},
            }}},
    },
}


class ExtractError(Exception):
    pass


def _visit_text(heard: dict) -> str:
    shown = {k: v for k, v in (heard or {}).items() if v and v != "missing" and k != "promise_material"}
    return json.dumps(shown, ensure_ascii=False) if shown else "(nothing yet)"


def extract(heard: dict, saathi_said: str, mr_said: str) -> dict:
    """{"reply": ..., "changes": [...], "dropped": [...]}: the changes whose quote is in the rep's words,
    and the ones dropped because it isn't."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ExtractError("OPENAI_API_KEY is not set on the backend")
    user = (f"Visit so far: {_visit_text(heard)}\n"
            f"Saathi's last line: {saathi_said or '(none)'}\n"
            f"MR's reply: {mr_said}")
    body = {"model": MODEL, "reasoning_effort": REASONING,
            "messages": [{"role": "system", "content": INSTRUCTIONS}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "visit_patch", "strict": True, "schema": SCHEMA}}}
    try:
        r = httpx.post(OPENAI_URL, json=body, headers={"Authorization": f"Bearer {api_key}"}, timeout=TIMEOUT_S)
    except httpx.HTTPError as exc:
        raise ExtractError(f"OpenAI unreachable: {exc}") from exc
    if r.status_code >= 400:
        raise ExtractError(f"OpenAI {r.status_code}: {r.text[:300]}")
    patch = json.loads(r.json()["choices"][0]["message"]["content"])
    said = key(mr_said)
    kept = [c for c in patch["changes"] if key(c["quote"]) and key(c["quote"]) in said]
    dropped = [c for c in patch["changes"] if c not in kept]
    if dropped:
        log.info("dropped changes whose quote isn't in the rep's words: %s", dropped)
    return {"reply": patch["reply"], "changes": kept, "dropped": dropped}
