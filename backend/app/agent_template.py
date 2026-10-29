"""Build the Bolna agent for one company: prompt, voice settings, custom functions, caller
lookup and extractions. The voice settings copy the hand-tuned prototype agent (endpointing
900 ms, gpt-5.4-mini with no reasoning, 180 s cap) because those were fixed on real test calls.
"""

import re

from sqlalchemy import select

from .names import spoken
from .config import PUBLIC_BASE_URL, ROOT, TRANSCRIBER, VOICE
from .models import Chemist, Company, Doctor, Product, Rep, Visit, utcnow

# The prompt carries only the names most likely in a call; resolve_names searches the full lists.
# A shorter prompt is also a faster first word from the model.
PROMPT_LIMITS = {"products": 40, "chemists": 20, "areas": 40}
USAGE_DAYS = 90
MAX_KEYWORDS = 50  # Bolna's transcriber keyword limit

# A debrief with a couple of re-asked names runs past 3 minutes; ending mid-read-back loses it.
MAX_CALL_SECONDS = 300

# Voices to compare on real calls; pick one with the VOICE env var and re-sync the agent.
# Sarvam's "enhi" voices are trained on Hindi-English code-mixed speech, i.e. how MRs talk.
VOICES = {
    "sarvam-ishita": {"provider": "sarvam", "stream": True, "buffer_size": 150, "audio_format": "wav",
                      "provider_config": {"model": "bulbul:v4-flash", "voice": "Ishita (Customer Expressive) [code-mixed]",
                                          "voice_id": "ishita_enhi_customer_expressive", "language": "hi", "speed": 0.95}},
    "sarvam-simran": {"provider": "sarvam", "stream": True, "buffer_size": 150, "audio_format": "wav",
                      "provider_config": {"model": "bulbul:v4-flash", "voice": "Simran (Customer) [code-mixed]",
                                          "voice_id": "simran_enhi_customer", "language": "hi", "speed": 0.95}},
    "elevenlabs-riya": {"provider": "elevenlabs", "stream": True, "caching": True, "buffer_size": 220, "audio_format": "wav",
                        "provider_config": {"model": "eleven_turbo_v2_5", "voice": "Riya Rao - Confident and Professional",
                                            "voice_id": "mfMM3ijQgz8QtMeKifko", "speed": 0.9, "temperature": 0.5,
                                            "similarity_boost": 0.6, "style": 0.0}},
}

def transcriber(company, names):
    """Speech-to-text, biased towards this company's own names. Pick one with the TRANSCRIBER env var
    and re-sync: Sarvam is trained on Indian, code-mixed speech; Deepgram nova-3 is English-first."""
    products = ", ".join(names["products"][:8])
    configs = {
        "sarvam-saaras": {"provider": "sarvam", "model": "saaras:v4", "language": "hi", "stream": True,
                          "endpointing": 900, "keywords": keywords(names),
                          "context": (f"Phone line where {company.name} medical representatives report doctor visits "
                                      f"or ask for a briefing, in Hindi, English or a mix. They name doctors, chemists, "
                                      f"areas and pharma products with strengths, such as {products}.")},
        "deepgram-nova3": {"provider": "deepgram", "model": "nova-3", "language": "hi", "stream": True,
                           "encoding": "linear16", "sampling_rate": 16000, "endpointing": 900,
                           "keywords": keywords(names)},
    }
    return configs.get(TRANSCRIBER, configs["sarvam-saaras"])


WELCOME = "नमस्ते! साथी बोल रही हूँ। Visit report देनी है, या किसी doctor की briefing चाहिए?"
HANGUP_MESSAGE = "Dhanyavaad!"
HANGUP_PROMPT = """End the call only in one of these cases:
1. The agent has read back the full visit and the MR clearly confirmed it (e.g. "haan", "sahi hai", "correct", "yes", "that's right") with no correction or new detail in the same reply.
2. The agent gave a briefing and the MR has nothing else.
3. The MR clearly wants to stop, e.g. says bye, "baad mein karta hoon", "abhi nahi", "I'll call later", or "not now".
4. The caller is not an MR (wrong number).
5. The MR has not responded after two prompts from the agent.
The MR may speak Hindi, Hinglish or English; judge the meaning, not the language.
Do NOT end the call if the MR's last reply contains a correction, a new detail, or a question, even if it also contains "haan" or "yes"."""

EXTRACTIONS = [
    ("call_type", 'Was this call a visit report or a request for a pre-visit briefing about a doctor? Answer exactly "debrief" or "briefing". It is "briefing" if the MR asked about the last visit or history of a doctor, or said they are about to meet a doctor, and did not report a new visit of their own. Saathi reading out an earlier visit is a briefing, not a visit report. Answer "debrief" only if the MR reported a new visit (if they did both, "debrief").'),
    ("doctor_name", 'Which doctor did the MR report visiting? Give the name in English letters, e.g. "Dr Mehta". Use the name the agent read back and the MR confirmed. Write "none" if this was only a briefing.'),
    ("area", "Which area was the visit in? English letters, as confirmed in the read-back."),
    ("products_discussed", 'Which products were discussed with the doctor? Separated by semicolons, in English letters with strength, e.g. "Telma 40; Cardivas". Write "none" if none.'),
    ("samples", 'Which samples were given, and how many of each? Format exactly "Product: number; Product: number", using digits, e.g. "Telma 40: 4; Pan D: 15". Use the number exactly as the MR said it (4 strips is 4): never convert strips or packs into tablets. Use the final value the MR confirmed after any correction. Write "none" if none.'),
    ("orders", 'Were any orders taken? Format exactly "Product: number; Product: number" with digits. Use the final confirmed value. Write "none" if none.'),
    ("chemist_name", 'Which chemist near the doctor did the MR visit? English letters. Write "none" if none.'),
    ("stock_outs", 'Which products were out of stock at that chemist? Separate with semicolons. Write "none" if none.'),
    ("next_visit", 'When is the next visit, as the MR said it, in English, e.g. "next Tuesday", "in 2 weeks". Do not convert it to a date.'),
    ("feedback", 'What did the doctor say about the products (feedback or objections)? One sentence in English. Write "none" if nothing.'),
    ("promises", "What did the MR promise the doctor in this visit (e.g. bring samples, share a study, call back)? One short English sentence per promise, separated by semicolons, keeping any timing the MR gave (e.g. \"Bring the clinical study next week\"). Speech-to-text may garble common words: \"netsuvic\" is most likely \"next week\", so never turn a garbled word into a product or study name. Never include gifts, money or favours. Only promises the MR explicitly said. Never infer or add follow-ups that were not said. Write \"none\" if nothing."),
    ("promises_done", 'Did the MR say that an earlier promise to this doctor has now been completed (e.g. "study de diya")? One short English sentence per completed promise, separated by semicolons. Write "none" if nothing.'),
    ("readback_confirmed", 'Did the MR say yes ("haan", "sahi hai", "yes", "correct") to Saathi\'s full read-back of the visit, with no correction left open? Answer exactly "yes" or "no".'),
    ("materials", 'Which of the promises are about handing the doctor material: a study, literature, a leaflet, samples, a chart, an invite or similar? Copy each such promise exactly as you wrote it in the promises field, separated by semicolons. Write "none" if none.'),
]


def _by_use(names, counts):
    """Most used in recent visits first, then alphabetical."""
    return sorted(names, key=lambda n: (-counts.get(n, 0), n))


def company_names(session, company_id):
    from collections import Counter
    from datetime import timedelta
    since = utcnow() - timedelta(days=USAGE_DAYS)
    recent = session.scalars(select(Visit).where(Visit.company_id == company_id, Visit.visited_at >= since)).all()
    used = Counter()
    for v in recent:
        used.update(set(v.products_discussed or []) | {i.product.name for i in v.items if i.product})
        if v.chemist:
            used[v.chemist.name] += 1
        if v.doctor:
            used[v.doctor.name] += 1
    products = _by_use(session.scalars(select(Product.name).where(Product.company_id == company_id)), used)
    doctors = sorted(session.scalars(select(Doctor).where(Doctor.company_id == company_id)), key=lambda d: (-used[d.name], d.name))
    chemists = sorted(session.scalars(select(Chemist).where(Chemist.company_id == company_id)), key=lambda c: (-used[c.name], c.name))
    areas = {d.area for d in doctors} | {c.area for c in chemists}
    for r in session.scalars(select(Rep).where(Rep.company_id == company_id)):
        areas |= set(r.areas)
    return {"products": products, "doctors": [d.name for d in doctors],
            "chemists": [c.name for c in chemists], "areas": sorted(a for a in areas if a),
            "doctor_areas": {d.name: d.area for d in doctors}, "chemist_areas": {c.name: c.area for c in chemists}}


def examples(names: dict) -> dict:
    """Example names for the prompt, taken from this company's own lists so no company's agent is
    nudged towards another company's doctors or products. Neutral wording when a list is empty."""
    doctors = [d for d in names["doctors"] if names["doctor_areas"].get(d)] or names["doctors"]
    doctor = doctors[0] if doctors else "Dr Kumar"
    area = names["doctor_areas"].get(doctor) or (names["areas"][0] if names["areas"] else "the area")
    chemists = names["chemists"]
    chemist = next((c for c in chemists if names["chemist_areas"].get(c) == area), chemists[0] if chemists else "the chemist")
    products = names["products"]
    with_strength = [p for p in products if re.search(r"\d", p)] or products or ["the product"]
    product, other = with_strength[0], (with_strength[1:] or products[1:] or with_strength)[0]
    stock = next((p for p in products if p not in (product, other)), other)
    # Two products sharing a name ("Telma 40" / "Telma H") are the real "which one?" case; else any two.
    by_base = {}
    for p in products:
        by_base.setdefault(p.split()[0].lower(), []).append(p)
    pair = next((v[:2] for v in by_base.values() if len(v) > 1), [product, other])
    return {"EX_DOCTOR": doctor, "EX_AREA": area, "EX_CHEMIST": chemist, "EX_STOCK": stock,
            "EX_PRODUCT": product, "EX_PRODUCT_SAY": spoken(product), "EX_OTHER_SAY": spoken(other),
            "EX_PAIR_SAY": f"{spoken(pair[0])} ya {spoken(pair[1])}"}


def build_prompt(company: Company, names: dict) -> str:
    text = (ROOT / "templates" / "agent_prompt.md").read_text()
    for kind, limit in PROMPT_LIMITS.items():
        values = names[kind]
        shown = values[:limit]
        text = text.replace(f"[[{kind.upper()}]]", ", ".join(shown) + (" (and more)" if len(values) > len(shown) else "") or "none")
    for marker, value in examples(names).items():
        text = text.replace(f"[[{marker}]]", value)
    followups = (' If the MR gave a next-visit day, add "Us din subah main aapko briefing ke liye call karungi." / '
                 '"I\'ll call you that morning with a briefing." If they reported a stock-out, add "Stock-out ki khabar '
                 'manager tak pahunch jayegi." / "Your manager will hear about the stock-out."') if company.auto_followup else ""
    return text.replace("[[FOLLOWUPS]]", followups).replace("[[COMPANY]]", company.name)


def keywords(names: dict) -> str:
    """Products are misheard most, then areas, then doctor surnames."""
    words = names["products"] + names["areas"] + [d.replace("Dr ", "") for d in names["doctors"]] + names["chemists"]
    seen = []
    for w in words:
        if w and w not in seen:
            seen.append(w)
    return ", ".join(seen[:MAX_KEYWORDS])


def _tool(name, description, params, path, company):
    props = {p: {"type": "string", "description": d} for p, d in params.items()}
    return (
        {"name": name, "description": description, "key": "custom_task", "pre_call_message": "एक second...",
         "parameters": {"type": "object", "properties": props, "required": list(params)}},
        {"method": "POST", "url": f"{PUBLIC_BASE_URL}{path}?company={company.id}",
         "api_token": f"Bearer {company.tool_token}",
         # from_number / to_number are filled in by Bolna, so the backend knows which rep is calling.
         "param": {**{p: f"%({p})s" for p in params}, "from_number": "%(from_number)s", "to_number": "%(to_number)s"}},
    )


def api_tools(company):
    tools = [
        _tool("resolve_names",
              "Check doctor, area, chemist and product names against the company's records before the read-back. "
              "Returns, for each name, the best match and a confidence: high (use it), medium (confirm with the MR), low (ask again).",
              {"names": 'All names heard, as "doctor: <name>; area: <name>; chemist: <name>; product: <name>"'},
              "/bolna/tools/resolve_names", company),
        _tool("get_doctor_brief",
              "Get the pre-visit briefing for a doctor: last visit, samples given, open promises, feedback and nearby stock-outs.",
              {"doctor": "The doctor's name as the MR said it"},
              "/bolna/tools/doctor_brief", company),
    ]
    return {"tools": [t for t, _ in tools], "tools_params": {t["name"]: p for t, p in tools}}


def agent_config(session, company: Company) -> dict:
    names = company_names(session, company.id)
    return {
        "agent_config": {
            "agent_name": f"Saathi - {company.name}"[:60],
            "agent_welcome_message": WELCOME,
            "webhook_url": f"{PUBLIC_BASE_URL}/bolna/webhook/{company.id}",
            "webhook_headers": {"X-Webhook-Secret": company.webhook_secret},
            "call_summary_enabled": False,
            "ingest_source_config": {
                "source_type": "api",
                "source_url": f"{PUBLIC_BASE_URL}/bolna/caller?company={company.id}",
                "source_auth_token": company.tool_token,
            },
            "tasks": [{
                "task_type": "conversation",
                "toolchain": {"execution": "parallel", "pipelines": [["transcriber", "llm", "synthesizer"]]},
                "tools_config": {
                    "llm_agent": {
                        "agent_type": "simple_llm_agent",
                        "agent_flow_type": "streaming",
                        "llm_config": {"provider": "openai", "family": "openai", "model": "gpt-5.4-mini",
                                       "max_tokens": 500, "temperature": 1.0, "reasoning_effort": "none",
                                       "verbosity": "low", "agent_flow_type": "streaming"},
                    },
                    "synthesizer": VOICES.get(VOICE, VOICES["sarvam-ishita"]),
                    "transcriber": transcriber(company, names),
                    "input": {"provider": "vobiz", "format": "wav"},
                    "output": {"provider": "vobiz", "format": "wav"},
                    "api_tools": api_tools(company),
                },
                "task_config": {
                    "call_terminate": MAX_CALL_SECONDS, "hangup_after_silence": 15, "hangup_after_LLMCall": True,
                    "call_cancellation_prompt": HANGUP_PROMPT, "call_hangup_message": HANGUP_MESSAGE,
                    "incremental_delay": 300, "number_of_words_for_interruption": 3,
                    "check_if_user_online": True, "trigger_user_online_message_after": 10,
                    "check_user_online_message": {"hi": "Hello, kya aap line par hain?", "en": "Hello, are you still on the line?"},
                    "optimize_latency": True, "welcome_message_delay": 250,
                },
            }],
        },
        "agent_prompts": {"task_1": {"system_prompt": build_prompt(company, names)}},
    }


def dispositions(agent_id):
    return {"agent_id": agent_id,
            "dispositions": [{"name": n, "question": q, "category": "Visit", "is_subjective": True,
                              "subjective_type": "text"} for n, q in EXTRACTIONS]}
