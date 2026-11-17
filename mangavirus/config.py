from dataclasses import dataclass
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Config:
    api_id: int
    api_hash: str
    bot_token: str
    owner_id: int
    database_path: str
    manga_api: str
    image_api: str
    log_level: str

    @classmethod
    def load(cls):
        required = ("API_ID", "API_HASH", "BOT_TOKEN", "OWNER_ID")
        missing = [key for key in required if not os.getenv(key)]
        if missing:
            raise RuntimeError("متغيرات البيئة الناقصة: " + ", ".join(missing))
        db = os.getenv("DATABASE_PATH", "data/mangavirus.sqlite3")
        Path(db).parent.mkdir(parents=True, exist_ok=True)
        return cls(
            api_id=int(os.environ["API_ID"]),
            api_hash=os.environ["API_HASH"],
            bot_token=os.environ["BOT_TOKEN"],
            owner_id=int(os.environ["OWNER_ID"]),
            database_path=db,
            manga_api=os.getenv("MANGA_API", "https://pixelflow-callback-harbor.lovable.app/api/public/manga").rstrip("/"),
            image_api=os.getenv("IMAGE_API", "https://pixelflow-callback-harbor.lovable.app/api/public/image").rstrip("/"),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
