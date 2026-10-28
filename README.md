# Saathi platform

The medical rep's memory, on any phone. A pharma company signs up, uploads its reps,
products, doctors and chemists, and clicks one button to get its own Bolna voice agent.
Reps then call to report a visit (debrief) or to hear about a doctor before walking in
(briefing). Misheard names are checked against the company's own lists during the call.

```
backend/   FastAPI + SQLAlchemy (uv, Python 3.13). SQLite locally, Postgres via DATABASE_URL.
web/       Next.js 16 dashboard. /api/* is forwarded to the backend (next.config.ts).
```

The single-company prototype in `../saathi/` is unchanged and still works on its own.

## How a call flows

1. **Before the call:** Bolna asks `GET /bolna/caller` who is calling. The prompt gets
   `{{rep_name}}`, `{{my_doctors}}` (the rep's own doctors) and `{{open_promises}}`.
2. **During the call:** the agent calls two custom functions on the backend. Bolna adds the
   caller's number, so the backend knows the rep.
   - `resolve_names` (`app/names.py`): converts Devanagari to Latin, checks learnt aliases,
     then matches on spelling and sound against the company's lists. Each name comes back
     with a confidence. **High:** the agent uses it. **Medium:** the agent confirms it
     ("Azithral 500?"). **Low:** the agent asks the rep to repeat it.
   - `get_doctor_brief` (`app/briefing.py`): last visit, samples given, open or overdue
     promises, feedback, and stock-outs at chemists in the same area.
3. **After the call:** the webhook `POST /bolna/webhook/{company}` stores the call and
   builds the visit from 12 extraction fields (`app/ingest.py`). Only high-confidence names
   are linked. The rest are kept as heard and shown on the visit as "not on your lists".
4. **Outbound** (`app/outbound.py`):
   - an evening sweep calls reps with no visit reported (off until set in Setup);
   - one callback after a debrief that came through too badly to use (at most 1 per rep per hour);
   - a "Call now" button.

## Run locally

```bash
# 1. Backend (port 8001; the old prototype uses 8000)
cd backend
cp .env.example .env        # set BOLNA_API_KEY, SECRET_KEY, PUBLIC_BASE_URL
uv run uvicorn app.main:app --port 8001 --reload

# 2. Tunnel, so Bolna can reach the backend (new URL every restart)
caffeinate -dims cloudflared tunnel --url http://localhost:8001
#    put the https://….trycloudflare.com URL in backend/.env as PUBLIC_BASE_URL,
#    restart the backend, then press "Re-sync agent" in Setup.

# 3. Website
cd web && npm install && npm run dev      # http://localhost:3000
```

Then sign up with your own mobile number. `demo-data/` has Mumbai CSVs to upload (put your own
mobile in place of `REPLACE_WITH_YOUR_MOBILE`). Under **Setup**:
1. Load the demo data (you become the first rep).
2. Create the voice agent.
3. Link a number, or use **Reps → Call now** to have Saathi call you.

## Tests

```bash
cd backend && uv run pytest     # pipeline, resolver, tools, tenancy, CSV, handover, sweep
cd web && npm run lint && npm run build
```

## Deploy

- **`web`** → Vercel. Set `BACKEND_URL` to the backend's URL.
- **`backend`** → Render or Railway. It needs an always-on process for the sweep scheduler.
  Use Postgres via `DATABASE_URL`. Set `PUBLIC_BASE_URL` to the backend's own https URL,
  and `COOKIE_SECURE=1`.
- After deploying, press **Re-sync agent** so the agent's webhook, tools and caller lookup
  point at the fixed URL.
