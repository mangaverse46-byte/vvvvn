import logging
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from config import BOT_TOKEN, MANGA_API_BASE, DATABASE_PATH, ADMIN_IDS, SOURCE_CACHE_SECONDS
from api.manga_api import MangaAPI
from database.db import Database
from handlers.start import start
from services.pdf import build_pdf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("manga-virus")

async def get_sources(context):
    now = time.monotonic()
    cached = context.bot_data.get("sources_cache")
    if cached and now - cached[0] < SOURCE_CACHE_SECONDS:
        return cached[1]
    sources = await context.bot_data["api"].sources()
    context.bot_data["sources_cache"] = (now, sources)
    return sources

def source_keyboard(sources, action):
    rows = [[InlineKeyboardButton(s.get("name") or s.get("id"), callback_data=f"{action}:{s.get('id')}")]
            for s in sources if s.get("id")]
    return InlineKeyboardMarkup(rows or [[InlineKeyboardButton("لا توجد مصادر مفعّلة", callback_data="noop")]])

async def sources_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sources = await get_sources(context)
        await update.message.reply_text("🌐 المصادر المتاحة:", reply_markup=source_keyboard(sources, "src"))
    except Exception as e:
        await update.message.reply_text(f"تعذر جلب المصادر من API: {e}")

async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("استخدم الأمر هكذا:\n/search Solo Leveling")
        return
    context.user_data["search_query"] = query
    try:
        sources = await get_sources(context)
        await update.message.reply_text(f"اختر المصدر للبحث عن: {query}", reply_markup=source_keyboard(sources, "searchsrc"))
    except Exception as e:
        await update.message.reply_text(f"خطأ في جلب المصادر: {e}")

async def latest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sources = await get_sources(context)
        await update.message.reply_text("اختر المصدر:", reply_markup=source_keyboard(sources, "latest"))
    except Exception as e:
        await update.message.reply_text(f"خطأ: {e}")

async def show_results(query, results, update, context, source):
    if not results:
        await update.effective_message.reply_text("لم يتم العثور على نتائج.")
        return
    rows = []
    for item in results[:30]:
        title = item.get("title") or "بدون عنوان"
        url = item.get("url") or item.get("id")
        if url:
            context.user_data.setdefault("result_map", {})[str(url)] = {"source": source, "url": str(url), "title": title}
            rows.append([InlineKeyboardButton(title[:55], callback_data=f"manga:{len(context.user_data['result_map'])-1}")])
    # use stable per-user list instead of serializing URLs in callback_data
    context.user_data["results"] = [{"source": source, "url": x.get("url") or x.get("id"), "title": x.get("title") or "بدون عنوان"} for x in results[:30]]
    rows = [[InlineKeyboardButton(x["title"][:55], callback_data=f"manga:{i}")]
            for i, x in enumerate(context.user_data["results"]) if x["url"]]
    await update.effective_message.reply_text(f"نتائج البحث: {len(results)}", reply_markup=InlineKeyboardMarkup(rows))

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    api = context.bot_data["api"]
    db = context.bot_data["db"]
    try:
        if data == "noop":
            return
        if data == "menu:sources":
            sources = await get_sources(context)
            await q.edit_message_text("🌐 المصادر المتاحة:", reply_markup=source_keyboard(sources, "src"))
        elif data == "menu:search":
            await q.edit_message_text("أرسل اسم المانجا بهذا الشكل:\n/search اسم المانجا")
        elif data == "menu:latest":
            sources = await get_sources(context)
            await q.edit_message_text("اختر المصدر:", reply_markup=source_keyboard(sources, "latest"))
        elif data == "menu:favorites" or data == "menu:follows":
            table = "favorites" if data.endswith("favorites") else "follows"
            items = db.list_items(table, q.from_user.id)
            if not items:
                await q.edit_message_text("القائمة فارغة حالياً.")
            else:
                await q.edit_message_text("\n".join(f"• {x['title']}\n{x['manga_url']}" for x in items[:30]))
        elif data.startswith("src:"):
            source = data.split(":", 1)[1]
            await q.edit_message_text(f"المصدر: {source}\nاختر العملية:", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🆕 الأحدث", callback_data=f"latest:{source}")],
                [InlineKeyboardButton("🔎 بحث", callback_data=f"asksearch:{source}")]
            ]))
        elif data.startswith("asksearch:"):
            source = data.split(":", 1)[1]
            context.user_data["pending_source"] = source
            await q.edit_message_text("أرسل الآن اسم المانجا برسالة جديدة، أو استخدم /search اسم المانجا.")
        elif data.startswith("searchsrc:"):
            source = data.split(":", 1)[1]
            term = context.user_data.get("search_query", "")
            if not term:
                await q.edit_message_text("استخدم /search اسم المانجا أولاً.")
                return
            result = await api.search(source, term)
            await show_results(term, result.get("results", []), update, context, source)
        elif data.startswith("latest:"):
            source = data.split(":", 1)[1]
            result = await api.latest(source)
            await show_results("latest", result.get("results", []), update, context, source)
        elif data.startswith("manga:"):
            index = int(data.split(":", 1)[1])
            item = context.user_data["results"][index]
            result = await api.details(item["source"], item["url"])
            manga = result.get("manga", {})
            chapters = manga.get("chapters", []) or []
            context.user_data["current_manga"] = {"source": item["source"], "url": item["url"], "title": manga.get("title") or item["title"]}
            rows = []
            for i, ch in enumerate(chapters[:80]):
                churl = ch.get("url") or ch.get("id")
                if churl:
                    context.user_data.setdefault("chapter_map", {})[str(i)] = churl
                    rows.append([InlineKeyboardButton((ch.get("title") or f"Chapter {i+1}")[:55], callback_data=f"chapter:{i}")])
            title = manga.get("title") or item["title"]
            context.user_data["chapters"] = [{"url": c.get("url") or c.get("id"), "title": c.get("title") or f"Chapter {i+1}"} for i,c in enumerate(chapters[:80])]
            rows = [[InlineKeyboardButton(c["title"][:55], callback_data=f"chapter:{i}")] for i,c in enumerate(context.user_data["chapters"]) if c["url"]]
            rows.append([InlineKeyboardButton("⭐ المفضلة", callback_data="save:favorites"),
                         InlineKeyboardButton("❤️ متابعة", callback_data="save:follows")])
            await q.edit_message_text(f"📖 {title}\nعدد الفصول: {len(chapters)}", reply_markup=InlineKeyboardMarkup(rows[:82]))
        elif data.startswith("save:"):
            current = context.user_data.get("current_manga")
            if current:
                table = data.split(":", 1)[1]
                added = db.toggle(table, q.from_user.id, current["source"], current["url"], current["title"])
                await q.answer("تمت الإضافة" if added else "تم الحذف", show_alert=True)
        elif data.startswith("chapter:"):
            index = int(data.split(":", 1)[1])
            chapter = context.user_data["chapters"][index]
            current = context.user_data["current_manga"]
            await q.edit_message_text(f"جاري جلب صور {chapter['title']} وإنشاء PDF...")
            page_data = await api.pages(current["source"], chapter["url"])
            images = page_data.get("images", [])
            pdf, count = await build_pdf(images, chapter["title"])
            filename = "MangaVirus.pdf"
            from io import BytesIO
            bio = BytesIO(pdf)
            bio.name = filename
            await context.bot.send_document(q.message.chat_id, document=bio, caption=f"🖤 Manga Virus\n{chapter['title']}\n📄 {count} صفحة")
            db.add_download(q.from_user.id)
        elif data.startswith("latest:"):
            pass
    except Exception as e:
        log.exception("callback failed")
        await q.message.reply_text(f"حدث خطأ أثناء تنفيذ الطلب:\n{str(e)[:700]}")

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    stats = context.bot_data["db"].stats()
    await update.message.reply_text(f"🛠 لوحة الإدارة\nالمستخدمون: {stats['users']}\nالتنزيلات: {stats['downloads']}")

async def post_init(app: Application):
    app.bot_data["api"] = MangaAPI(MANGA_API_BASE)
    await app.bot_data["api"].start()
    app.bot_data["db"] = Database(DATABASE_PATH)
    try:
        sources = await app.bot_data["api"].sources()
        app.bot_data["sources_cache"] = (time.monotonic(), sources)
        log.info("Loaded %s enabled sources", len(sources))
    except Exception:
        log.exception("Could not load sources at startup; will retry on demand")

async def post_shutdown(app: Application):
    await app.bot_data["api"].close()

def main():
    if not BOT_TOKEN:
        raise SystemExit("ضع BOT_TOKEN داخل ملف .env أولاً")
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("sources", sources_cmd))
    app.add_handler(CommandHandler("search", search_cmd))
    app.add_handler(CommandHandler("latest", latest_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CallbackQueryHandler(callback))
    log.info("Manga Virus is starting...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
