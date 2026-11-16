import asyncio
import logging
import time
from io import BytesIO

from pyrogram import Client, filters, idle
from pyrogram.enums import ChatMemberStatus
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import (
    BOT_TOKEN, MANGA_API_BASE, DATABASE_PATH, ADMIN_IDS,
    SOURCE_CACHE_SECONDS,
)
from api.manga_api import MangaAPI
from database.db import Database
from services.pdf import build_pdf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("manga-virus")

# Pyrogram user state is kept per Telegram user for this process.
user_state = {}
api = MangaAPI(MANGA_API_BASE)
db = Database(DATABASE_PATH)
sources_cache = None


def state_for(user_id):
    return user_state.setdefault(user_id, {})


async def get_sources():
    global sources_cache
    now = time.monotonic()
    if sources_cache and now - sources_cache[0] < SOURCE_CACHE_SECONDS:
        return sources_cache[1]
    sources = await api.sources()
    sources_cache = (now, sources)
    return sources


def source_keyboard(sources, action):
    rows = [
        [InlineKeyboardButton(
            s.get("name") or s.get("id"),
            callback_data=f"{action}:{s.get('id')}",
        )]
        for s in sources if s.get("id")
    ]
    return InlineKeyboardMarkup(
        rows or [[InlineKeyboardButton("لا توجد مصادر مفعّلة", callback_data="noop")]]
    )


async def show_results(client, message, user_id, results, source):
    if not results:
        await message.reply_text("لم يتم العثور على نتائج.")
        return
    items = []
    rows = []
    for item in results[:30]:
        url = item.get("url") or item.get("id")
        if not url:
            continue
        title = item.get("title") or "بدون عنوان"
        items.append({"source": source, "url": str(url), "title": title})
        rows.append([InlineKeyboardButton(title[:55], callback_data=f"manga:{len(items)-1}")])
    state_for(user_id)["results"] = items
    if not rows:
        await message.reply_text("لم يرجع المصدر روابط صالحة للمانجا.")
        return
    await message.reply_text(
        f"نتائج البحث/التحديث: {len(items)}",
        reply_markup=InlineKeyboardMarkup(rows),
    )


@Client.on_message(filters.command("start", prefixes=["/"]))
async def start_handler(client, message):
    user = message.from_user
    if not user:
        log.warning("Received /start without from_user; chat_id=%s", message.chat.id if message.chat else None)
        return

    log.info("Received /start from user_id=%s chat_id=%s", user.id, message.chat.id if message.chat else None)

    # A database error must never prevent the welcome message from being sent.
    try:
        db.touch_user(user)
    except Exception:
        log.exception("Could not save user %s; continuing with /start", user.id)

    try:
        from config import FORCE_SUB_CHANNEL
        if FORCE_SUB_CHANNEL:
            member = await client.get_chat_member(FORCE_SUB_CHANNEL, user.id)
            if member.status not in (
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.OWNER,
            ):
                await message.reply_text(
                    "🔒 يجب الاشتراك بالقناة أولاً ثم أرسل /start مجدداً.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton(
                            "الاشتراك بالقناة",
                            url=f"https://t.me/{FORCE_SUB_CHANNEL.lstrip('@')}",
                        )
                    ]]),
                )
                return

        keyboard = [
            [
                InlineKeyboardButton("🔎 البحث عن مانجا", callback_data="menu:search"),
                InlineKeyboardButton("🆕 أحدث المانجا", callback_data="menu:latest"),
            ],
            [
                InlineKeyboardButton("📚 المصادر", callback_data="menu:sources"),
                InlineKeyboardButton("⭐ المفضلة", callback_data="menu:favorites"),
            ],
            [InlineKeyboardButton("❤️ المتابعة", callback_data="menu:follows")],
        ]
        await message.reply_text(
            "🖤 أهلاً بك في Manga Virus 🦠\n"
            "بوابتك لعالم المانجا والمانهوا.\n\n"
            "للبحث أرسل: /search اسم المانجا",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        log.info("Welcome message sent to user_id=%s", user.id)
    except Exception as exc:
        log.exception("Start handler failed for user_id=%s", user.id)
        try:
            await message.reply_text(
                "صار خطأ أثناء فتح القائمة. جرّب /start مرة ثانية.\n"
                f"التفاصيل: {str(exc)[:250]}"
            )
        except Exception:
            log.exception("Could not send /start error reply to user_id=%s", user.id)


@Client.on_message(filters.command("sources"))
async def sources_handler(client, message):
    try:
        await message.reply_text(
            "🌐 المصادر المتاحة:",
            reply_markup=source_keyboard(await get_sources(), "src"),
        )
    except Exception as exc:
        log.exception("sources request failed")
        await message.reply_text(f"تعذر جلب المصادر من API: {exc}")


@Client.on_message(filters.command("search"))
async def search_handler(client, message):
    query = message.text.partition(" ")[2].strip() if message.text else ""
    if not query:
        await message.reply_text("استخدم الأمر هكذا:\n/search Solo Leveling")
        return
    state_for(message.from_user.id)["search_query"] = query
    try:
        await message.reply_text(
            f"اختر المصدر للبحث عن: {query}",
            reply_markup=source_keyboard(await get_sources(), "searchsrc"),
        )
    except Exception as exc:
        log.exception("search setup failed")
        await message.reply_text(f"خطأ في جلب المصادر: {exc}")


@Client.on_message(filters.command("latest"))
async def latest_handler(client, message):
    try:
        await message.reply_text(
            "اختر المصدر:",
            reply_markup=source_keyboard(await get_sources(), "latest"),
        )
    except Exception as exc:
        log.exception("latest setup failed")
        await message.reply_text(f"خطأ: {exc}")


@Client.on_message(filters.command("admin"))
async def admin_handler(client, message):
    if not message.from_user or message.from_user.id not in ADMIN_IDS:
        return
    stats = db.stats()
    await message.reply_text(
        f"🛠 لوحة الإدارة\nالمستخدمون: {stats['users']}\nالتنزيلات: {stats['downloads']}"
    )


@Client.on_message(filters.text & ~filters.command(["start", "sources", "search", "latest", "admin"]))
async def text_handler(client, message):
    if not message.from_user:
        return
    state = state_for(message.from_user.id)
    source = state.pop("pending_source", None)
    if not source:
        return
    query = (message.text or "").strip()
    if not query:
        await message.reply_text("أرسل اسم مانجا صالحاً.")
        return
    try:
        result = await api.search(source, query)
        await show_results(client, message, message.from_user.id, result.get("results", []), source)
    except Exception as exc:
        log.exception("text search failed")
        await message.reply_text(f"فشل البحث في المصدر: {exc}")


@Client.on_callback_query()
async def callback_handler(client, query):
    await query.answer()
    data = query.data or ""
    user_id = query.from_user.id
    state = state_for(user_id)
    message = query.message
    try:
        if data == "noop":
            return

        if data == "menu:sources":
            await message.edit_text(
                "🌐 المصادر المتاحة:",
                reply_markup=source_keyboard(await get_sources(), "src"),
            )
        elif data == "menu:search":
            await message.edit_text("أرسل اسم المانجا بهذا الشكل:\n/search اسم المانجا")
        elif data == "menu:latest":
            await message.edit_text(
                "اختر المصدر:",
                reply_markup=source_keyboard(await get_sources(), "latest"),
            )
        elif data in ("menu:favorites", "menu:follows"):
            table = "favorites" if data.endswith("favorites") else "follows"
            items = db.list_items(table, user_id)
            if not items:
                await message.edit_text("القائمة فارغة حالياً.")
            else:
                await message.edit_text(
                    "\n".join(f"• {item['title']}\n{item['manga_url']}" for item in items[:30])
                )
        elif data.startswith("src:"):
            source = data.split(":", 1)[1]
            await message.edit_text(
                f"المصدر: {source}\nاختر العملية:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🆕 الأحدث", callback_data=f"latest:{source}")],
                    [InlineKeyboardButton("🔎 بحث", callback_data=f"asksearch:{source}")],
                ]),
            )
        elif data.startswith("asksearch:"):
            state["pending_source"] = data.split(":", 1)[1]
            await message.edit_text("أرسل الآن اسم المانجا برسالة جديدة.")
        elif data.startswith("searchsrc:"):
            source = data.split(":", 1)[1]
            term = state.get("search_query", "")
            if not term:
                await message.edit_text("استخدم /search اسم المانجا أولاً.")
                return
            result = await api.search(source, term)
            await show_results(client, message, user_id, result.get("results", []), source)
        elif data.startswith("latest:"):
            source = data.split(":", 1)[1]
            result = await api.latest(source)
            await show_results(client, message, user_id, result.get("results", []), source)
        elif data.startswith("manga:"):
            index = int(data.split(":", 1)[1])
            item = state["results"][index]
            result = await api.details(item["source"], item["url"])
            manga = result.get("manga", {})
            chapters = manga.get("chapters", []) or []
            state["current_manga"] = {
                "source": item["source"],
                "url": item["url"],
                "title": manga.get("title") or item["title"],
            }
            state["chapters"] = [
                {
                    "url": chapter.get("url") or chapter.get("id"),
                    "title": chapter.get("title") or f"Chapter {i+1}",
                }
                for i, chapter in enumerate(chapters[:80])
            ]
            rows = [
                [InlineKeyboardButton(ch["title"][:55], callback_data=f"chapter:{i}")]
                for i, ch in enumerate(state["chapters"]) if ch["url"]
            ]
            rows.append([
                InlineKeyboardButton("⭐ المفضلة", callback_data="save:favorites"),
                InlineKeyboardButton("❤️ متابعة", callback_data="save:follows"),
            ])
            await message.edit_text(
                f"📖 {state['current_manga']['title']}\nعدد الفصول: {len(chapters)}",
                reply_markup=InlineKeyboardMarkup(rows[:82]),
            )
        elif data.startswith("save:"):
            current = state.get("current_manga")
            if current:
                table = data.split(":", 1)[1]
                added = db.toggle(
                    table, user_id, current["source"], current["url"], current["title"]
                )
                await message.reply_text(
                    "تمت الإضافة إلى القائمة." if added else "تم حذفها من القائمة."
                )
        elif data.startswith("chapter:"):
            index = int(data.split(":", 1)[1])
            chapter = state["chapters"][index]
            current = state["current_manga"]
            await message.edit_text(
                f"جاري جلب صور {chapter['title']} وإنشاء PDF..."
            )
            page_data = await api.pages(current["source"], chapter["url"])
            images = page_data.get("images", [])
            pdf_bytes, count = await build_pdf(images, chapter["title"])
            document = BytesIO(pdf_bytes)
            document.name = "MangaVirus.pdf"
            await client.send_document(
                message.chat.id,
                document=document,
                caption=f"🖤 Manga Virus\n{chapter['title']}\n📄 {count} صفحة",
            )
            db.add_download(user_id)
    except Exception as exc:
        log.exception("callback failed")
        await message.reply_text(f"حدث خطأ أثناء تنفيذ الطلب:\n{str(exc)[:700]}")


async def run():
    if not BOT_TOKEN:
        raise SystemExit("ضع BOT_TOKEN داخل ملف .env أولاً")
    from config import API_ID, API_HASH
    if not API_ID or not API_HASH:
        raise SystemExit("أضف API_ID و API_HASH إلى ملف .env من my.telegram.org")

    await api.start()
    app = Client(
        "manga_virus",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=BOT_TOKEN,
        workers=16,
        sleep_threshold=30,
    )
    try:
        await app.start()
        me = await app.get_me()
        log.info("Manga Virus started as @%s using Pyrogram", me.username)
        await idle()
    finally:
        if app.is_connected:
            await app.stop()
        await api.close()


if __name__ == "__main__":
    asyncio.run(run())
