import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()

DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{ROOT / 'saathi.db'}"
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")  # signs login cookies
BOLNA_API_KEY = os.environ.get("BOLNA_API_KEY", "")
BOLNA_API = "https://api.bolna.ai"
# The URL Bolna uses to reach this backend (tunnel or deployed). Webhook, caller lookup and
# custom functions are all built from it when an agent is created or re-synced.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Kolkata")
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"
