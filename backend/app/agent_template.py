"""Build the Bolna agent for one company: prompt, voice settings, custom functions, caller
lookup and extractions. The voice settings copy the hand-tuned prototype agent (endpointing
900 ms, gpt-5.4-mini with no reasoning, 180 s cap) because those were fixed on real test calls.
"""

from sqlalchemy import select

from .config import PUBLIC_BASE_URL, ROOT
from .models import Chemist, Company, Doctor, Product, Rep

MAX_PROMPT_NAMES = 300  # beyond this, resolve_names and the per-rep list carry the load
MAX_KEYWORDS = 50  # Bolna's transcriber keyword limit

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
]


def company_names(session, company_id):
    products = list(session.scalars(select(Product.name).where(Product.company_id == company_id).order_by(Product.name)))
    doctors = list(session.scalars(select(Doctor).where(Doctor.company_id == company_id).order_by(Doctor.name)))
    chemists = list(session.scalars(select(Chemist).where(Chemist.company_id == company_id).order_by(Chemist.name)))
    areas = {d.area for d in doctors} | {c.area for c in chemists}
    for r in session.scalars(select(Rep).where(Rep.company_id == company_id)):
        areas |= set(r.areas)
    return {"products": products, "doctors": [d.name for d in doctors],
            "chemists": [c.name for c in chemists], "areas": sorted(a for a in areas if a)}


def build_prompt(company: Company, names: dict) -> str:
    text = (ROOT / "templates" / "agent_prompt.md").read_text()
    for marker, values in (("PRODUCTS", names["products"]), ("DOCTORS", names["doctors"]),
                           ("CHEMISTS", names["chemists"]), ("AREAS", names["areas"])):
        shown = values[:MAX_PROMPT_NAMES]
        text = text.replace(f"[[{marker}]]", ", ".join(shown) + (" (and more)" if len(values) > len(shown) else "") or "none")
    return text.replace("[[COMPANY]]", company.name)


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
                    "synthesizer": {
                        "provider": "elevenlabs", "stream": True, "caching": True, "buffer_size": 220, "audio_format": "wav",
                        "provider_config": {"model": "eleven_turbo_v2_5", "voice": "Riya Rao - Confident and Professional",
                                            "voice_id": "mfMM3ijQgz8QtMeKifko", "speed": 0.9, "temperature": 0.5,
                                            "similarity_boost": 0.6, "style": 0.0},
                    },
                    "transcriber": {"provider": "deepgram", "model": "nova-3", "language": "hi", "stream": True,
                                    "encoding": "linear16", "sampling_rate": 16000, "endpointing": 900,
                                    "keywords": keywords(names)},
                    "input": {"provider": "vobiz", "format": "wav"},
                    "output": {"provider": "vobiz", "format": "wav"},
                    "api_tools": api_tools(company),
                },
                "task_config": {
                    "call_terminate": 180, "hangup_after_silence": 15, "hangup_after_LLMCall": True,
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
