import os
from dotenv import load_dotenv

load_dotenv()

def _int(name: str, default: int = 0) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default

def _ids(name: str) -> set[int]:
    values = set()
    for item in os.getenv(name, "").split(","):
        try:
            if item.strip(): values.add(int(item.strip()))
        except ValueError:
            pass
    return values

API_ID = _int("API_ID")
API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = _ids("ADMIN_IDS")
FORCE_CHANNEL = os.getenv("FORCE_CHANNEL", "").strip()
MANGA_API_BASE = os.getenv("MANGA_API_BASE", "").strip().rstrip("/")
MANGA_API_KEY = os.getenv("MANGA_API_KEY", "").strip()
PDF_API_URL = os.getenv("PDF_API_URL", "").strip()
DB_PATH = os.getenv("DB_PATH", "data/mangavirus.db")

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("Set API_ID, API_HASH and BOT_TOKEN in .env")
