import asyncio
import logging
import signal
from pyrogram import Client, idle
from .config import Config
from .database import Database
from .manga_api import MangaAPI
from .pdf_engine import PDFEngine
from .handlers import register_handlers
from .state import StateStore

def setup_logging(level):
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler()],
    )

async def run():
    cfg = Config.load()
    setup_logging(cfg.log_level)
    log = logging.getLogger("mangavirus")
    db = Database(cfg.database_path)
    manga_api = MangaAPI(cfg.manga_api)
    pdf_url = cfg.manga_api.split("/api/public/manga", 1)[0] + "/api/public/pdf"
    pdf_engine = PDFEngine(pdf_url)
    state = StateStore()

    app = Client(
        "mangavirus_v2",
        api_id=cfg.api_id,
        api_hash=cfg.api_hash,
        bot_token=cfg.bot_token,
        workers=16,
        sleep_threshold=20,
    )
    register_handlers(app, cfg, db, manga_api, pdf_engine, state)

    started = False
    try:
        # Important: bind Pyrogram to this exact asyncio loop before dispatcher startup.
        app.loop = asyncio.get_running_loop()
        log.info("Starting Manga Virus v2...")
        await app.start()
        started = True
        me = await app.get_me()
        log.info("CONNECTED username=@%s id=%s", me.username, me.id)
        log.info("READY: waiting for Telegram updates")
        await idle()
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("BOT_RUNTIME_FAILED")
        raise
    finally:
        if started and app.is_connected:
            log.info("Stopping Telegram client...")
            try:
                await app.stop()
            except Exception:
                log.exception("PYROGRAM_STOP_FAILED")
        log.info("Manga Virus stopped.")

def main():
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("Manga Virus stopped by keyboard interrupt.")

if __name__ == "__main__":
    main()
