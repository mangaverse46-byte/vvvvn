import asyncio
import logging
from pyrogram import filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
from .keyboards import main_menu, manga_results, chapter_buttons

log = logging.getLogger(__name__)

def register_handlers(app, cfg, db, manga_api, pdf_engine, state):
    async def guard(message):
        user = message.from_user
        if not user:
            return False
        db.touch_user(user)
        if db.is_banned(user.id) and user.id != cfg.owner_id:
            await message.reply_text("🚫 حسابك غير مسموح له باستخدام البوت.")
            return False
        return True

    @app.on_message(filters.private & filters.command("start"))
    async def start_handler(client, message):
        log.info("START_RECEIVED user_id=%s", message.from_user.id if message.from_user else None)
        try:
            if not await guard(message):
                return
            await message.reply_text(
                "🖤 أهلاً بك في **Manga Virus** 🦠\n"
                "بوابتك لعالم المانجا والمانهوا.\n\n"
                "اختر الخدمة من القائمة:",
                reply_markup=main_menu(),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            log.exception("START_HANDLER_FAILED")
            try:
                await message.reply_text("حدث خطأ أثناء فتح القائمة. حاول مرة أخرى.")
            except Exception:
                log.exception("START_ERROR_REPLY_FAILED")

    @app.on_message(filters.private & filters.command("help"))
    async def help_handler(client, message):
        if await guard(message):
            await message.reply_text(
                "**الأوامر المتاحة**\n"
                "/start — القائمة الرئيسية\n"
                "/search اسم المانجا — البحث\n"
                "/latest — أحدث الإضافات\n"
                "/favorites — المفضلة\n"
                "/stats — إحصائيات الإدارة",
                parse_mode=ParseMode.MARKDOWN,
            )

    @app.on_message(filters.private & filters.command("search"))
    async def search_handler(client, message):
        if not await guard(message):
            return
        query = message.text.split(maxsplit=1)[1].strip() if len(message.text.split(maxsplit=1)) > 1 else ""
        if not query:
            await message.reply_text("اكتب اسم المانجا بعد الأمر، مثال:\n/search Solo Leveling")
            return
        status = await message.reply_text("🔎 جاري البحث في المصادر...")
        try:
            sources = await manga_api.sources()
            semaphore = asyncio.Semaphore(5)
            async def search_one(source):
                async with semaphore:
                    try:
                        return source, await manga_api.search(str(source["id"]), query)
                    except Exception as exc:
                        log.warning("SEARCH_SOURCE_FAILED source=%s error=%s", source.get("id"), exc)
                        return source, []
            batches = await asyncio.gather(*(search_one(x) for x in sources))
            rows = []
            for source, items in batches:
                for item in items[:8]:
                    if item.get("url"):
                        token = state.put({"kind":"manga","source":str(source["id"]),"manga":item})
                        rows.append((token,item))
            if not rows:
                await status.edit_text("لم أجد نتائج. جرّب اسماً آخر.")
                return
            await status.edit_text(
                f"🔎 نتائج البحث عن **{query}**\nاختر المانجا:",
                reply_markup=manga_results(rows[:30]),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as exc:
            log.exception("SEARCH_FAILED")
            await status.edit_text(f"تعذر البحث حالياً: {str(exc)[:180]}")

    @app.on_message(filters.private & filters.command("latest"))
    async def latest_handler(client, message):
        if not await guard(message):
            return
        status = await message.reply_text("🆕 أجلب أحدث الإضافات...")
        try:
            sources = await manga_api.sources()
            async def get_latest(source):
                try:
                    return source, await manga_api.latest(str(source["id"]))
                except Exception as exc:
                    log.warning("LATEST_SOURCE_FAILED %s: %s", source.get("id"), exc)
                    return source, []
            batches = await asyncio.gather(*(get_latest(x) for x in sources))
            rows = []
            for source, items in batches:
                for item in items[:5]:
                    if item.get("url"):
                        token = state.put({"kind":"manga","source":str(source["id"]),"manga":item})
                        rows.append((token,item))
            if not rows:
                await status.edit_text("لا توجد تحديثات متاحة حالياً.")
                return
            await status.edit_text("🆕 **أحدث المانجا والفصول**", reply_markup=manga_results(rows[:30]),
                                   parse_mode=ParseMode.MARKDOWN)
        except Exception as exc:
            log.exception("LATEST_FAILED")
            await status.edit_text(f"تعذر جلب التحديثات: {str(exc)[:180]}")

    @app.on_message(filters.private & filters.command("favorites"))
    async def favorites_handler(client, message):
        if not await guard(message):
            return
        items = db.favorites(message.from_user.id)
        if not items:
            await message.reply_text("⭐ قائمة المفضلة فارغة.")
            return
        buttons = []
        for item in items[:40]:
            token = state.put({"kind":"manga","source":item["source_id"],"manga":{
                "id":item["manga_id"],"title":item["title"],"url":item["manga_url"],"cover_url":item["cover_url"]}})
            buttons.append([InlineKeyboardButton(item["title"][:48], callback_data=f"manga:{token}")])
        await message.reply_text("⭐ **مانجاتك المفضلة**", reply_markup=InlineKeyboardMarkup(buttons),
                                 parse_mode=ParseMode.MARKDOWN)

    @app.on_message(filters.private & filters.command("stats"))
    async def stats_handler(client, message):
        if not await guard(message):
            return
        if message.from_user.id != cfg.owner_id:
            return
        stats = db.stats()
        await message.reply_text(
            "📊 **إحصائيات Manga Virus**\n"
            f"👥 المستخدمون: {stats['users']}\n"
            f"⭐ المفضلة: {stats['favorites']}\n"
            f"📥 التنزيلات المسجلة: {stats['downloads']}\n"
            f"📨 الشكاوى المفتوحة: {stats['complaints']}",
            parse_mode=ParseMode.MARKDOWN,
        )

    @app.on_callback_query()
    async def callback_handler(client, query):
        try:
            data = query.data or ""
            uid = query.from_user.id
            if data == "menu:home":
                await query.message.edit_text("🖤 **Manga Virus**\nاختر الخدمة:", reply_markup=main_menu(),
                                              parse_mode=ParseMode.MARKDOWN)
                await query.answer()
                return
            if data == "menu:search":
                await query.answer("استخدم: /search اسم المانجا", show_alert=True)
                return
            if data == "menu:latest":
                await query.answer()
                await latest_handler(client, query.message)
                return
            if data == "menu:favs":
                await query.answer()
                items = db.favorites(uid)
                if not items:
                    await query.message.reply_text("⭐ قائمة المفضلة فارغة.")
                else:
                    buttons=[]
                    for item in items[:40]:
                        token=state.put({"kind":"manga","source":item["source_id"],"manga":{
                            "id":item["manga_id"],"title":item["title"],"url":item["manga_url"],"cover_url":item["cover_url"]}})
                        buttons.append([InlineKeyboardButton(item["title"][:48],callback_data=f"manga:{token}")])
                    await query.message.reply_text("⭐ المفضلة",reply_markup=InlineKeyboardMarkup(buttons))
                return
            if data == "menu:sources":
                sources = await manga_api.sources()
                text = "📚 **المصادر المتاحة**\n" + "\n".join(f"• {x.get('name') or x['id']}" for x in sources)
                await query.message.edit_text(text, reply_markup=main_menu(), parse_mode=ParseMode.MARKDOWN)
                await query.answer()
                return
            if data == "menu:help":
                await query.message.edit_text("استخدم /search للبحث أو /latest لأحدث الإضافات.",
                                              reply_markup=main_menu())
                await query.answer()
                return
            if data.startswith("manga:"):
                token = data.split(":",1)[1]
                item = state.get(token)
                if not item or item.get("kind") != "manga":
                    await query.answer("انتهت صلاحية النتيجة. أعد البحث.", show_alert=True)
                    return
                await query.answer("أجلب الفصول...")
                info = await manga_api.details(item["source"], item["manga"]["url"])
                manga = {**item["manga"],"title":info["title"],"url":item["manga"]["url"],
                         "cover_url":info.get("cover_url")}
                detail_token = state.put({"kind":"details","source":item["source"],"manga":manga,"info":info})
                chapters = info["chapters"]
                caption = f"📖 **{info['title']}**\n\n{info.get('description','')[:500]}\n\nعدد الفصول: **{len(chapters)}**"
                await query.message.edit_text(caption,reply_markup=chapter_buttons(detail_token,chapters),
                                              parse_mode=ParseMode.MARKDOWN)
                return
            if data.startswith("chapters:"):
                _,token,page=data.split(":")
                item=state.get(token)
                if not item:
                    await query.answer("انتهت صلاحية القائمة.",show_alert=True); return
                await query.message.edit_reply_markup(chapter_buttons(token,item["info"]["chapters"],int(page)))
                await query.answer()
                return
            if data.startswith("favorite:"):
                token=data.split(":",1)[1]
                item=state.get(token)
                if not item:
                    await query.answer("انتهت صلاحية النتيجة.",show_alert=True); return
                ok=db.add_favorite(uid,item["source"],item["manga"])
                await query.answer("⭐ أضيفت للمفضلة" if ok else "موجودة مسبقاً",show_alert=True)
                return
            if data.startswith("chapter:"):
                _,token,index=data.split(":")
                item=state.get(token)
                if not item:
                    await query.answer("انتهت صلاحية الفصل.",show_alert=True); return
                chapters=item["info"]["chapters"]
                chapter=chapters[int(index)]
                await query.answer("بدأ تجهيز الفصل...")
                status=await query.message.reply_text(f"⏳ استخراج صور {chapter['title']}...")
                urls=await manga_api.chapter_images(item["source"],chapter["url"])
                await status.edit_text(f"🧩 تم استخراج {len(urls)} صورة. جاري إنشاء PDF...")
                pdf, meta=await pdf_engine.create(urls)
                await client.send_document(uid,pdf,caption=f"📖 {item['manga']['title']}\n{chapter['title']}\nالصفحات: {meta.get('pages',len(urls))}")
                await status.delete()
                log.info("DOWNLOAD_SENT user=%s source=%s chapter=%s",uid,item["source"],chapter["title"])
                return
            await query.answer()
        except Exception as exc:
            log.exception("CALLBACK_FAILED data=%s",query.data)
            try:
                await query.answer(f"حدث خطأ: {str(exc)[:150]}",show_alert=True)
            except Exception:
                pass
