import os
from dotenv import load_dotenv

load_dotenv()

def _ids(value: str) -> set[int]:
    result = set()
    for item in value.split(","):
        item = item.strip()
        if item.isdigit():
            result.add(int(item))
    return result

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
API_ID = int(os.getenv("API_ID", "0") or 0)
API_HASH = os.getenv("API_HASH", "").strip()
MANGA_API_BASE = os.getenv("MANGA_API_BASE", "https://pixelflow-callback-harbor.lovable.app/api/public/manga").rstrip("/")
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/manga_virus.sqlite3")
ADMIN_IDS = _ids(os.getenv("ADMIN_IDS", ""))
FORCE_SUB_CHANNEL = os.getenv("FORCE_SUB_CHANNEL", "").strip()
MAX_DOWNLOAD_CONCURRENCY = max(1, min(30, int(os.getenv("MAX_DOWNLOAD_CONCURRENCY", "12"))))
MAX_MERGE_CHAPTERS = max(1, int(os.getenv("MAX_MERGE_CHAPTERS", "10")))
MAX_PDF_PAGES = max(1, int(os.getenv("MAX_PDF_PAGES", "500")))
SOURCE_CACHE_SECONDS = max(30, int(os.getenv("SOURCE_CACHE_SECONDS", "300")))
