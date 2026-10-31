"""Build the Bolna agent for one company: a graph agent (one node per job, see graph_nodes), its
voice settings, custom functions, caller lookup and extractions. The voice settings were fixed on
real test calls (gpt-5.4-mini with no reasoning, 1200 ms endpointing, 300 s cap).
"""

import re

from sqlalchemy import select

from .names import spoken
from .config import PUBLIC_BASE_URL, ROOT, TRANSCRIBER, VOICE
from .models import Chemist, Company, Doctor, Product, Rep, Visit, utcnow

# The prompt carries only the names most likely in a call; check_visit searches the full lists.
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
    # Tested 29 Oct: Sarvam (transcribe mode, Hindi) wrote English speech in Devanagari and garbled it
    # ("visit report" -> "बजट रिपोर्ट"), so English calls fell apart. Deepgram keeps English words in Latin.
    return configs.get(TRANSCRIBER, configs["deepgram-nova3"])


# The opening line is built per call (rep's name, and why Saathi is calling): see outbound.greeting().
WELCOME = "{{greeting}}"
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
    """Placeholders for the examples in the prompt. They are deliberately not real names: on a call
    the model couldn't follow, it read realistic example names (the company's own doctors and
    products) back to the rep as if they had said them. Company names belong in the Known names
    list and the speech-to-text keywords, never in examples."""
    return {"EX_DOCTOR": "Dr <name>", "EX_AREA": "<area>", "EX_CHEMIST": "<chemist>", "EX_STOCK": "<product>",
            "EX_PRODUCT": "<product> 40", "EX_PRODUCT_SAY": "<product> forty", "EX_OTHER_SAY": "<product> six twenty five",
            "EX_PAIR_SAY": "<product> forty ya <product> H"}


def fill(text: str, company: Company, names: dict) -> str:
    """Fill a prompt template's [[MARKERS]]: name lists, placeholder examples, follow-ups, company."""
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


def build_prompt(company: Company, names: dict) -> str:
    return fill((ROOT / "templates" / "agent_prompt.md").read_text(), company, names)


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
    """check_visit for a debrief and get_doctor_brief for a briefing, each scoped to its one node."""
    tools = [check_visit_tool(company), doctor_brief_tool(company)]
    params = {t["name"]: {**p, "scope": "node", "nodes": TOOL_SCOPES[t["name"]]} for t, p in tools}
    return {"tools": [t for t, _ in tools], "tools_params": params}


def doctor_brief_tool(company):
    tool, params = _tool("get_doctor_brief",
                         "Get the pre-visit briefing for a doctor: last visit, samples given, open promises, feedback and nearby stock-outs.",
                         {"doctor": "The doctor's name as the MR said it"}, "/bolna/tools/doctor_brief", company)
    params["param"]["call_sid"] = "%(call_sid)s"  # filled in by Bolna; links the turn to its call
    return tool, params


# ---- the call graph ------------------------------------------------------------------------------
# The call split into nodes, one job each (Bolna graph agents). The debrief has one tool,
# check_visit: the agent passes on the rep's words, the backend reads the visit from them, resolves the
# names and returns the one line to say next (a question, or the read-back). It keeps the visit as a
# draft per call; the draft the rep said yes to is what ingest saves.
TOOL_SCOPES = {"check_visit": ["visit"], "get_doctor_brief": ["briefing"]}
# Reps pause mid-list ("Pan D aur... Amlong"); at 900 ms the turn ended inside the sentence (graph G1).
ENDPOINTING_MS = 1200
# Back on mini: on 30 Oct gpt-5.4 made the opening re-ask "report or briefing?" on a clear answer and was
# slower (0.85-1.6 s a turn). A stronger model gets tested again on its own, one change at a time.
MODEL = "gpt-5.4-mini"
STOP = "The MR wants to stop or call back later"
# The call ends on Saathi's own closing line, which check_visit gives only after a yes to its read-back.
HANGUP_PROMPT = """End the call only in one of these cases:
1. Saathi's last line said the report is recorded ("record हो गया" / "it's recorded").
2. Saathi gave a briefing and the MR has nothing else.
Never end the call because of anything the MR said; the conversation handles that."""


def check_visit_tool(company):
    """The agent only passes the rep's words on; the backend reads the visit from them (extract.py). On
    30-31 Oct the agent filling in the visit itself dropped items, wiped them with "none" and guessed."""
    fields = {"mr_said": ("The MR's words since Saathi's last line, copied exactly from the transcript; empty if the "
                          "MR has said nothing since"),
              "resume_notes": "The earlier notes, only on the first call of a resume call where the MR confirmed "
                              "them; otherwise empty"}
    tool, params = _tool("check_visit",
                         "Send the MR's latest words. Returns the one line Saathi says next: a single question, "
                         "the read-back, or the closing line. Call it after every reply from the MR.",
                         fields, "/bolna/tools/check_visit", company)
    tool["parameters"]["required"] = ["mr_said"]
    params["param"]["call_sid"] = "%(call_sid)s"  # filled in by Bolna; keeps one draft per call
    return tool, params


# The end nodes' closing lines (hi, en); Call health tells from them how a call ended.
END_LINES = {
    "later": ("ठीक है, बाद में call कर लीजिए। धन्यवाद!", "No problem, call back later. Thank you!"),
    "bye": ("All the best! धन्यवाद!", "All the best! Thank you!"),
    "wrong_number": ("माफ़ कीजिए, गलती हो गई। धन्यवाद!", "Sorry, wrong number. Thank you!"),
}


def _edge(to, condition):
    return {"to_node_id": to, "condition_type": "llm", "condition": condition}


def _end(node_id, hi, en):
    return {"id": node_id, "node_type": "static", "static_message": {"hi": hi, "en": en},
            "function_call": "end_call", "edges": []}


def graph_nodes(company: Company, names: dict) -> list[dict]:
    prompt = lambda node: fill((ROOT / "templates" / "graph" / f"{node}.md").read_text(), company, names)
    mode = lambda value, to: {"to_node_id": to, "condition_type": "expression",
                              "expression": {"logic": "and", "conditions": [
                                  {"variable": "recipient_data.mode", "operator": "eq", "value": value}]}}
    return [
        {"id": "route", "node_type": "router", "description": "Start where the reason for this call says",
         "edges": [mode("resume", "resume"), mode("briefing", "briefing"), mode("sweep", "visit"),
                   {"to_node_id": "opening", "condition_type": "unconditional"}]},
        {"id": "opening", "prompt": prompt("opening"), "edges": [
            _edge("visit", "The MR wants to report a visit, or has started describing one"),
            _edge("briefing", "The MR wants a briefing about a doctor they are about to meet"),
            # Only a clear "not now" ends the call; an unclear or short reply stays here and gets re-asked.
            _edge("later", "The MR clearly says not now: busy, will call back later, or doesn't want anything"),
            _edge("wrong_number", "The caller is not a medical rep (wrong number)")]},
        # A report goes straight to the check; with nothing said yet, check_visit returns the invite. There
        # used to be a `listen` node in between: the rep's whole monologue arrived as the call entered it,
        # so `listen` answered with its own read-back and the check only ran a turn later (31 Oct).
        {"id": "visit", "prompt": prompt("visit"), "function_call": "check_visit", "edges": [
            _edge("visit", "The MR replied to Saathi: answered, confirmed, corrected or added something"),
            _edge("later", STOP)]},
        {"id": "briefing", "prompt": prompt("briefing"), "edges": [
            _edge("visit", "The MR now wants to report a visit"),
            _edge("bye", "The MR has nothing else")]},
        {"id": "resume", "prompt": prompt("resume"), "edges": [
            _edge("visit", "The MR confirmed the earlier notes and told the rest"),
            _edge("visit", "The MR says the notes are wrong or wants to report a different visit"),
            _edge("later", STOP)]},
        *(_end(node_id, hi, en) for node_id, (hi, en) in END_LINES.items()),
    ]


def graph_llm_config(company: Company, names: dict) -> dict:
    return {"provider": "openai", "family": "openai", "model": MODEL, "max_tokens": 500,
            "temperature": 1.0,  # Bolna requires 1 for reasoning models (gpt-5.x)
            "reasoning_effort": "none", "verbosity": "low", "agent_flow_type": "streaming",
            "routing_provider": "openai", "routing_model": MODEL, "routing_reasoning_effort": "none",
            "agent_information": fill((ROOT / "templates" / "graph" / "agent_information.md").read_text(), company, names),
            "routing_instructions": "You route a medical rep's call with Saathi, their visit-report assistant. "
                                    "Judge the meaning of the MR's reply, in Hindi, Hinglish or English.",
            "current_node_id": "route", "nodes": graph_nodes(company, names)}


def agent_config(session, company: Company) -> dict:
    names = company_names(session, company.id)
    llm_config = graph_llm_config(company, names)
    config = {
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
                    "llm_agent": {"agent_type": "graph_agent", "agent_flow_type": "streaming", "llm_config": llm_config},
                    "synthesizer": VOICES.get(VOICE, VOICES["sarvam-ishita"]),
                    "transcriber": {**transcriber(company, names), "endpointing": ENDPOINTING_MS},
                    "input": {"provider": "vobiz", "format": "wav"},
                    "output": {"provider": "vobiz", "format": "wav"},
                    "api_tools": api_tools(company),
                },
                "task_config": {
                    "call_terminate": MAX_CALL_SECONDS, "hangup_after_silence": 15, "hangup_after_LLMCall": True,
                    # The graph's end nodes decide when the call ends; the hangup check only has to recognise
                    # Saathi's own closing line, so the MR's words never end the call.
                    "call_cancellation_prompt": HANGUP_PROMPT,
                    "incremental_delay": 300, "number_of_words_for_interruption": 3,
                    "check_if_user_online": True, "trigger_user_online_message_after": 10,
                    "check_user_online_message": {"hi": "Hello, kya aap line par hain?", "en": "Hello, are you still on the line?"},
                    "optimize_latency": True, "welcome_message_delay": 250,
                },
            }],
        },
        "agent_prompts": {"task_1": {"system_prompt": llm_config["agent_information"]}},
    }
    return config


def graph_summary(company: Company, names: dict) -> list[dict]:
    """The call flow as the settings page shows it: each node, what it says or does, where it goes."""
    out = []
    for n in graph_nodes(company, names):
        out.append({"id": n["id"], "type": n.get("node_type", "llm"), "description": n.get("description"),
                    "prompt": n.get("prompt") or " / ".join(n.get("static_message", {}).values()) or None,
                    "tool": n.get("function_call"),
                    "edges": [{"to": e["to_node_id"], "when": e.get("condition") or (
                        "always" if e["condition_type"] == "unconditional" else
                        " and ".join(f'{c["variable"]} = {c["value"]}' for c in e["expression"]["conditions"]))}
                              for e in n["edges"]]})
    return out


def dispositions(agent_id):
    return {"agent_id": agent_id,
            "dispositions": [{"name": n, "question": q, "category": "Visit", "is_subjective": True,
                              "subjective_type": "text"} for n, q in EXTRACTIONS]}
