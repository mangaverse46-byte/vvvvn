import asyncio, logging, re, sqlite3, time, os, io, html, tempfile
from urllib.parse import quote

import aiohttp
import fitz  # PyMuPDF
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Message
from pyrogram.enums import ParseMode

# ============ إعداداتك ============
API_ID = 5442915
API_HASH = "b6a556aba92ae96f271b936cacd930a6"
BOT_TOKEN = "8812455288:AAEZkr2bmYziv53JfDZkWI-EpwNUBmeY47g"

API_MANGA = "https://pixelflow-callback-harbor.lovable.app/api/public/manga"
API_IMAGE = "https://pixelflow-callback-harbor.lovable.app/api/public/image"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger(__name__)

PDF_LOCKS = {}
A4_W, A4_H = 595, 842

# ============ قاعدة البيانات ============
DB = "bot_data.db"

def conn():
    c = sqlite3.connect(DB, timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c

def db_init():
    c = conn()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS urls (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT UNIQUE);
    CREATE TABLE IF NOT EXISTS users (uid INTEGER PRIMARY KEY, source TEXT DEFAULT 'mangalik', query TEXT);
    CREATE TABLE IF NOT EXISTS chapters (
        manga_url TEXT, idx INTEGER, title TEXT, url TEXT, num REAL,
        PRIMARY KEY (manga_url, idx)
    );
    CREATE TABLE IF NOT EXISTS progress (
        uid INTEGER, manga_url TEXT, chapter_idx INTEGER, ts INTEGER,
        PRIMARY KEY (uid, manga_url)
    );
    """)
    c.commit(); c.close()

def store_url(url):
    c = conn()
    r = c.execute("SELECT id FROM urls WHERE url=?", (url,)).fetchone()
    if r: c.close(); return r[0]
    cur = c.execute("INSERT INTO urls(url) VALUES(?)", (url,)); c.commit()
    i = cur.lastrowid; c.close(); return i

def get_url(i):
    c = conn()
    r = c.execute("SELECT url FROM urls WHERE id=?", (i,)).fetchone(); c.close()
    return r[0] if r else None

def get_user(uid):
    c = conn()
    r = c.execute("SELECT source, query FROM users WHERE uid=?", (uid,)).fetchone()
    if not r:
        c.execute("INSERT OR IGNORE INTO users(uid) VALUES(?)", (uid,)); c.commit(); c.close()
        return {"source": "mangalik", "query": None}
    c.close()
    return {"source": r[0] or "mangalik", "query": r[1]}

def set_user(uid, source=None, query=None):
    c = conn()
    c.execute("INSERT OR IGNORE INTO users(uid) VALUES(?)", (uid,))
    if source: c.execute("UPDATE users SET source=? WHERE uid=?", (source, uid))
    if query is not None: c.execute("UPDATE users SET query=? WHERE uid=?", (query, uid))
    c.commit(); c.close()

def save_chapters(manga_url, chapters):
    c = conn()
    c.execute("DELETE FROM chapters WHERE manga_url=?", (manga_url,))
    for i, ch in enumerate(chapters):
        c.execute(
            "INSERT INTO chapters(manga_url, idx, title, url, num) VALUES(?,?,?,?,?)",
            (manga_url, i, ch_name(ch), ch_url(ch), ch_num(ch))
        )
    c.commit(); c.close()

def get_chapter(manga_url, idx):
    c = conn()
    r = c.execute("SELECT title, url FROM chapters WHERE manga_url=? AND idx=?", (manga_url, idx)).fetchone()
    c.close()
    return r

def count_chapters(manga_url):
    c = conn()
    r = c.execute("SELECT COUNT(*) FROM chapters WHERE manga_url=?", (manga_url,)).fetchone()
    c.close()
    return r[0] if r else 0

def save_progress(uid, manga_url, idx):
    c = conn()
    c.execute("INSERT OR REPLACE INTO progress(uid, manga_url, chapter_idx, ts) VALUES(?,?,?,?)",
              (uid, manga_url, idx, int(time.time())))
    c.commit(); c.close()

def get_progress(uid, manga_url):
    c = conn()
    r = c.execute("SELECT chapter_idx FROM progress WHERE uid=? AND manga_url=?", (uid, manga_url)).fetchone()
    c.close()
    return r[0] if r else None

db_init()

# ============ API (مع retries) ============
async def _api_get(session, **p):
    for attempt in range(3):
        try:
            async with session.get(API_MANGA, params=p, timeout=aiohttp.ClientTimeout(total=45)) as r:
                if r.status == 200:
                    try: return await r.json()
                    except Exception as e: log.error(f"json: {e}"); return None
                if r.status < 500: return None
                log.warning(f"API {p.get('action')} HTTP {r.status} attempt {attempt+1}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.error(f"API {p.get('action')} attempt {attempt+1}: {e}")
        if attempt < 2: await asyncio.sleep(2 ** attempt)
    return None

async def _api_post(session, payload, timeout_total):
    for attempt in range(3):
        try:
            async with session.post(API_MANGA, json=payload,
                                    timeout=aiohttp.ClientTimeout(total=timeout_total)) as r:
                if r.status == 200:
                    try: return await r.json(content_type=None)
                    except Exception as e: log.error(f"json: {e}"); return None
                if r.status < 500:
                    try: body = (await r.text())[:200]
                    except: body = ""
                    log.error(f"API {payload.get('action')} HTTP {r.status}: {body}")
                    return None
                log.warning(f"API {payload.get('action')} HTTP {r.status} attempt {attempt+1}")
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.error(f"API {payload.get('action')} attempt {attempt+1}: {e}")
        if attempt < 2: await asyncio.sleep(2 ** attempt)
    return None

async def api_sources(s):            return (await _api_get(s, action="sources")) or {}
async def api_search(s, x, q, p=1):  return await _api_get(s, action="search", source=x, q=q, page=p)
async def api_latest(s, x, p=1):     return await _api_get(s, action="latest", source=x, page=p)
async def api_details(s, x, u):      return await _api_get(s, action="details", source=x, url=u)
async def api_genres(s, x):          return await _api_get(s, action="genres", source=x)
async def api_genre_manga(s, x, u, p=1): return await _api_get(s, action="genre-manga", source=x, genre_url=u, page=p)

async def api_convert(session, source, chapter_url):
    return await _api_post(session, {"action": "convert", "source": source, "chapter_url": chapter_url}, 300)

async def api_merge(session, source, manga_url):
    return await _api_post(session, {"action": "merge", "source": source, "manga_url": manga_url}, 1800)

# ============ تنزيل الصور ============
async def download_converted_images(session, images, strict=True):
    """strict=True: يفشل عند أي صورة ناقصة. strict=False: يتخطى."""
    sem = asyncio.Semaphore(15)

    async def download(item):
        async with sem:
            try:
                url = item if isinstance(item, str) else item.get("url")
                if not url: return None
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=90)) as r:
                    if r.status != 200:
                        log.error(f"Image HTTP {r.status}: {url[:80]}")
                        return None
                    content = await r.read()
                    return content if content else None
            except Exception as e:
                log.error(f"Image dl: {e}")
                return None

    results = await asyncio.gather(*(download(it) for it in images))
    if strict:
        failed = sum(x is None for x in results)
        if failed:
            raise Exception(f"فشل تنزيل {failed} صورة من {len(images)}")
    return [x for x in results if x]

# ============ PDF (PyMuPDF) ============
def _add_image_to_doc(doc, data):
    """يضيف صورة كصفحة واحدة. يتكيّف تلقائياً مع الصور العريضة (spreads)."""
    if not data: return False
    try:
        pix = fitz.Pixmap(data)
        iw, ih = pix.width, pix.height
        pix = None
        # صفحة أفقية للمانجا العريضة
        if iw > ih * 1.3:
            pw, ph = A4_H, A4_W
        else:
            pw, ph = A4_W, A4_H
        page = doc.new_page(width=pw, height=ph)
        scale = min(pw / iw, ph / ih)
        nw, nh = iw * scale, ih * scale
        x0 = (pw - nw) / 2
        y0 = (ph - nh) / 2
        page.insert_image(fitz.Rect(x0, y0, x0 + nw, y0 + nh), stream=data)
        return True
    except Exception as e:
        log.warning(f"img add: {e}")
        return False

def build_pdf_from_bytes(image_bytes_list, out_path=None):
    """
    - out_path=None  → يرجِع bytes (للإرسال من الذاكرة).
    - out_path=path  → يحفظ الملف ويرجعه.
    - None عند الفشل الكامل.
    """
    doc = fitz.open()
    added = 0
    for data in image_bytes_list:
        if _add_image_to_doc(doc, data):
            added += 1
    if added == 0:
        doc.close()
        return None
    try:
        if out_path:
            doc.save(out_path, deflate=True, garbage=3)
            doc.close()
            return out_path
        b = doc.tobytes(deflate=True, garbage=3)
        doc.close()
        return b
    except Exception as e:
        log.error(f"PDF save: {e}")
        try: doc.close()
        except: pass
        return None

def _append_all_images(doc, bytes_list):
    return sum(1 for d in bytes_list if _add_image_to_doc(doc, d))

# ============ استخراج ============
def safe_name(s, maxlen=60):
    s = re.sub(r'[\\/:*?"<>|\n\r\t]', '_', str(s or "file")).strip() or "file"
    return s[:maxlen]

def list_of(data):
    if isinstance(data, dict):
        for k in ("results", "data", "items"):
            v = data.get(k)
            if isinstance(v, list): return v
    return []

def manga_of(d):
    return (d.get("manga") if isinstance(d, dict) else None) or {}

def chapters_of(manga):
    for k in ("chapters", "chapter_list", "episodes"):
        v = manga.get(k)
        if isinstance(v, list) and v: return v
    return []

def ch_url(ch):
    if isinstance(ch, str): return ch
    for k in ("url", "link", "id", "chapter_url"):
        if ch.get(k): return ch[k]
    return None

def ch_num(ch):
    if not isinstance(ch, dict): return 0
    for k in ("title", "name", "number", "chapter"):
        v = ch.get(k)
        if v:
            m = re.search(r'(\d+(?:\.\d+)?)', str(v))
            if m: return float(m.group(1))
    for k in ("url", "id"):
        v = ch.get(k)
        if v:
            m = re.findall(r'(\d+(?:\.\d+)?)', str(v))
            if m: return float(m[-1])
    return 0

def ch_name(ch):
    if isinstance(ch, str):
        m = re.search(r'(\d+(?:\.\d+)?)', ch)
        return m.group(1) if m else "?"
    for k in ("title", "name", "chapter", "number"):
        v = ch.get(k)
        if v:
            m = re.search(r'(\d+(?:\.\d+)?)', str(v))
            if m: return m.group(1)
    u = ch_url(ch)
    if u:
        m = re.findall(r'(\d+(?:\.\d+)?)', str(u))
        if m: return m[-1]
    return "?"

def sort_chapters(chs_raw):
    with_num = [c for c in chs_raw if ch_num(c) > 0]
    without = [c for c in chs_raw if ch_num(c) == 0]
    return sorted(with_num, key=ch_num) + without

def img(u): return f"{API_IMAGE}?url={quote(u, safe='')}"

# ============ أزرار ============
def buttons_manga(items, extra=None):
    btns = []
    for it in items[:12]:
        t = (it.get("title") or "?")[:50]
        u = it.get("url") or it.get("id")
        if u:
            btns.append([InlineKeyboardButton(t, callback_data=f"d:{store_url(u)}")])
    if extra: btns.extend(extra)
    return InlineKeyboardMarkup(btns)

def nav_row(page, prefix):
    return [
        InlineKeyboardButton("⬅️", callback_data=f"{prefix}:{page-1}") if page>1 else InlineKeyboardButton("•", callback_data="noop"),
        InlineKeyboardButton(f"{page}", callback_data="noop"),
        InlineKeyboardButton("➡️", callback_data=f"{prefix}:{page+1}")
    ]

def chapter_page_markup(mid, page, total, murl, extra_top=None):
    per = 20
    pages = max(1, (total + per - 1) // per)
    page = max(1, min(page, pages))
    start = (page-1)*per
    end = min(start+per, total)
    btns = []
    if extra_top: btns.extend(extra_top)
    row = []
    for i in range(start, end):
        ch = get_chapter(murl, i)
        name = ch[0] if ch else str(i+1)
        row.append(InlineKeyboardButton(name, callback_data=f"p:{mid}:{i}"))
        if len(row) == 4: btns.append(row); row = []
    if row: btns.append(row)
    nav = []
    if page > 1: nav.append(InlineKeyboardButton("⬅️", callback_data=f"cp:{mid}:{page-1}"))
    nav.append(InlineKeyboardButton(f"{page}/{pages}", callback_data="noop"))
    if page < pages: nav.append(InlineKeyboardButton("➡️", callback_data=f"cp:{mid}:{page+1}"))
    if nav: btns.append(nav)
    btns.append([InlineKeyboardButton("🔙", callback_data="m")])
    return InlineKeyboardMarkup(btns)

# ============ البوت ============
app = Client("MangaBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

MAIN_TEXT = """📚 <b>بوت المانجا</b>

<b>المصدر:</b> <code>{src}</code>

🔍 /search <code>اسم</code>
📖 /latest
🏷️ /genres
⚙️ /source"""

MAIN_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("🔍", callback_data="hlp"), InlineKeyboardButton("📖", callback_data="l:1")],
    [InlineKeyboardButton("🏷️", callback_data="g:1"), InlineKeyboardButton("⚙️", callback_data="m_src")],
])

def _main_text(src):
    return MAIN_TEXT.format(src=html.escape(src or "mangalik"))

@app.on_message(filters.command("start"))
async def cmd_start(c, m):
    u = get_user(m.from_user.id)
    await m.reply(_main_text(u["source"]), parse_mode=ParseMode.HTML, reply_markup=MAIN_KB)

@app.on_message(filters.command("help"))
async def cmd_help(c, m): await cmd_start(c, m)

@app.on_message(filters.command("source"))
async def cmd_source(c, m):
    async with aiohttp.ClientSession() as s:
        d = await api_sources(s)
    srcs = [x["id"] for x in d.get("sources", []) if x.get("enabled")]
    btns = [[InlineKeyboardButton(f"📚 {x}", callback_data=f"src:{x}")] for x in srcs]
    await m.reply("⚙️", reply_markup=InlineKeyboardMarkup(btns))

@app.on_message(filters.command("search"))
async def cmd_search(c, m):
    if len(m.command) < 2:
        await m.reply("❗ /search <اسم>"); return
    q = " ".join(m.command[1:])
    u = get_user(m.from_user.id)
    set_user(m.from_user.id, query=q)
    msg = await m.reply(f"🔎 {html.escape(q)}...")
    await render_search(c, msg, u["source"], q, 1)

async def render_search(c, msg, src, q, page):
    if page < 1: page = 1
    async with aiohttp.ClientSession() as s:
        d = await api_search(s, src, q, page)
    items = list_of(d)
    if not items:
        try: await msg.edit_text(f"❌ {html.escape(q)} | {html.escape(src)}")
        except: pass
        return
    extra = [nav_row(page, "s"), [InlineKeyboardButton("🔙", callback_data="m")]]
    try:
        await msg.edit_text(
            f"🔍 <b>{html.escape(q)}</b> | <code>{html.escape(src)}</code> | {page}",
            reply_markup=buttons_manga(items, extra),
            parse_mode=ParseMode.HTML)
    except Exception as e: log.warning(f"search: {e}")

@app.on_message(filters.command("latest"))
async def cmd_latest(c, m):
    u = get_user(m.from_user.id)
    msg = await m.reply("📖...")
    await render_latest(c, msg, u["source"], 1)

async def render_latest(c, msg, src, page):
    async with aiohttp.ClientSession() as s:
        d = await api_latest(s, src, page)
    items = list_of(d)
    if not items:
        try: await msg.edit_text("❌")
        except: pass
        return
    extra = [nav_row(page, "l"), [InlineKeyboardButton("🔙", callback_data="m")]]
    try:
        await msg.edit_text(
            f"📖 <code>{html.escape(src)}</code> | {page}",
            reply_markup=buttons_manga(items, extra),
            parse_mode=ParseMode.HTML)
    except: pass

@app.on_message(filters.command("genres"))
async def cmd_genres(c, m):
    u = get_user(m.from_user.id)
    msg = await m.reply("🏷️...")
    await render_genres(c, msg, u["source"], 1)

async def render_genres(c, msg, src, page, per=20):
    async with aiohttp.ClientSession() as s:
        d = await api_genres(s, src)
    items = list_of(d)
    if not items:
        try: await msg.edit_text("❌")
        except: pass
        return
    total = len(items)
    pages = max(1, (total + per - 1) // per)
    page = max(1, min(page, pages))
    chunk = items[(page-1)*per : page*per]
    btns, row = [], []
    for g in chunk:
        n = (g.get("name") or "?")[:22]
        u = g.get("url") or g.get("id")
        if not u: continue
        cnt = g.get("count", 0)
        row.append(InlineKeyboardButton(f"{n} ({cnt})", callback_data=f"gm:{store_url(u)}:1"))
        if len(row) == 2: btns.append(row); row = []
    if row: btns.append(row)
    nav = []
    if page > 1: nav.append(InlineKeyboardButton("⬅️", callback_data=f"g:{page-1}"))
    nav.append(InlineKeyboardButton(f"{page}/{pages}", callback_data="noop"))
    if page < pages: nav.append(InlineKeyboardButton("➡️", callback_data=f"g:{page+1}"))
    btns.append(nav)
    btns.append([InlineKeyboardButton("🔙", callback_data="m")])
    try:
        await msg.edit_text(
            f"🏷️ <code>{html.escape(src)}</code> ({total})",
            reply_markup=InlineKeyboardMarkup(btns),
            parse_mode=ParseMode.HTML)
    except: pass

# ============ Callbacks ============
@app.on_callback_query()
async def on_cb(c, q: CallbackQuery):
    d = q.data
    uid = q.from_user.id
    u = get_user(uid)
    src = u["source"]

    if d == "noop": await q.answer(); return
    if d == "hlp": await q.answer("/search <اسم>", show_alert=True); return

    if d == "m":
        await q.answer()
        try: await q.message.edit_text(_main_text(src), parse_mode=ParseMode.HTML, reply_markup=MAIN_KB)
        except: pass
        return

    if d == "m_src":
        await q.answer()
        async with aiohttp.ClientSession() as s:
            dd = await api_sources(s)
        btns = [[InlineKeyboardButton(f"📚 {x['id']}", callback_data=f"src:{x['id']}")]
                for x in dd.get("sources", []) if x.get("enabled")]
        btns.append([InlineKeyboardButton("🔙", callback_data="m")])
        try: await q.message.edit_text("⚙️", reply_markup=InlineKeyboardMarkup(btns))
        except: pass
        return

    if d.startswith("src:"):
        new = d.split(":", 1)[1]
        set_user(uid, source=new)
        await q.answer(f"✅ {new}")
        try: await q.message.edit_text(_main_text(new), parse_mode=ParseMode.HTML, reply_markup=MAIN_KB)
        except: pass
        return

    if d.startswith("s:"):
        page = int(d.split(":")[1]); await q.answer()
        if not u["query"]: return
        await render_search(c, q.message, src, u["query"], page); return

    if d.startswith("l:"):
        page = int(d.split(":")[1]); await q.answer()
        await render_latest(c, q.message, src, page); return

    if d.startswith("g:"):
        page = int(d.split(":")[1]); await q.answer()
        await render_genres(c, q.message, src, page); return

    if d.startswith("gm:"):
        _, gid, page = d.split(":")
        gid, page = int(gid), int(page)
        gurl = get_url(gid)
        if not gurl: await q.answer("❌", show_alert=True); return
        await q.answer("...")
        async with aiohttp.ClientSession() as s:
            dd = await api_genre_manga(s, src, gurl, page)
        items = list_of(dd)
        if not items:
            try: await q.message.edit_text("❌")
            except: pass
            return
        nav = []
        if page > 1: nav.append(InlineKeyboardButton("⬅️", callback_data=f"gm:{gid}:{page-1}"))
        nav.append(InlineKeyboardButton(f"{page}", callback_data="noop"))
        nav.append(InlineKeyboardButton("➡️", callback_data=f"gm:{gid}:{page+1}"))
        extra = [nav, [InlineKeyboardButton("🔙", callback_data="g:1")]]
        try: await q.message.edit_text(f"📚 {page}", reply_markup=buttons_manga(items, extra))
        except: pass
        return

    # ========== تفاصيل المانجا ==========
    if d.startswith("d:"):
        mid = int(d.split(":", 1)[1])
        murl = get_url(mid)
        if not murl: await q.answer("❌", show_alert=True); return
        await q.answer("...")
        async with aiohttp.ClientSession() as s:
            dd = await api_details(s, src, murl)
        if not dd:
            try: await q.message.edit_text("❌")
            except: pass
            return
        manga = manga_of(dd)
        title = (manga.get("title") or "?")[:100]
        desc = (manga.get("description") or "")[:400]
        cover = manga.get("cover") or manga.get("image") or manga.get("thumbnail")
        chs_raw = chapters_of(manga)
        if not chs_raw:
            try: await q.message.edit_text("❌")
            except: pass
            return

        sorted_chs = sort_chapters(chs_raw)
        save_chapters(murl, sorted_chs)
        total = len(sorted_chs)

        prog = get_progress(uid, murl)
        progress_btn = []
        if prog is not None and prog < total:
            ch = get_chapter(murl, prog)
            if ch:
                progress_btn.append([InlineKeyboardButton(f"▶️ {ch[0]}", callback_data=f"p:{mid}:{prog}")])
        progress_btn.append([InlineKeyboardButton("🔀 دمج الكل PDF", callback_data=f"merge:{mid}")])
        progress_btn.append([InlineKeyboardButton("📚 كل الفصول PDF", callback_data=f"pdfmenu:{mid}")])

        pages_count = max(1, (total + 19)//20)
        text = f"📚 <b>{html.escape(title)}</b>\n\n{html.escape(desc)}\n\n📖 {total} | 1/{pages_count}"
        markup = chapter_page_markup(mid, 1, total, murl, progress_btn)

        chat_id = q.message.chat.id
        try: await q.message.delete()
        except: pass

        sent = False
        if cover:
            try:
                await c.send_photo(chat_id, img(cover), caption=text,
                                   parse_mode=ParseMode.HTML, reply_markup=markup)
                sent = True
            except Exception as e: log.warning(f"cover: {e}")
        if not sent:
            await c.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return

    # ========== صفحة فصول ==========
    if d.startswith("cp:"):
        _, mid, page = d.split(":")
        mid, page = int(mid), int(page)
        murl = get_url(mid)
        if not murl: await q.answer("❌", show_alert=True); return
        total = count_chapters(murl)
        if not total: await q.answer("❌", show_alert=True); return
        await q.answer()
        markup = chapter_page_markup(mid, page, total, murl)
        try: await q.message.edit_reply_markup(markup)
        except:
            try: await q.message.reply_text("📖", reply_markup=markup)
            except: pass
        return

    # ========== قراءة فصل → PDF (في الذاكرة) ==========
    if d.startswith("p:"):
        _, mid, idx = d.split(":")
        mid, idx = int(mid), int(idx)
        murl = get_url(mid)
        if not murl: await q.answer("❌", show_alert=True); return
        ch = get_chapter(murl, idx)
        if not ch:
            await q.answer("❌", show_alert=True); return
        ch_title, ch_url_val = ch
        save_progress(uid, murl, idx)
        await q.answer(f"📄 {ch_title}")

        chat_id = q.message.chat.id
        status = await c.send_message(
            chat_id, f"⏳ استخراج الفصل <b>{html.escape(str(ch_title))}</b>...",
            parse_mode=ParseMode.HTML)

        async with aiohttp.ClientSession() as s:
            dd = await api_convert(s, src, ch_url_val)
            if not dd:
                await status.edit_text("❌ فشل استخراج صور الفصل.")
                return

            images = dd.get("images", [])
            try: await status.edit_text(f"📥 {len(images)} صورة — جاري التنزيل...")
            except: pass

            try:
                images_bytes = await download_converted_images(s, images, strict=True)
            except Exception as e:
                await status.edit_text(f"❌ {html.escape(str(e))}", parse_mode=ParseMode.HTML)
                return

        try: await status.edit_text(f"📄 بناء PDF من {len(images_bytes)} صورة...")
        except: pass

        pdf_bytes = await asyncio.get_event_loop().run_in_executor(
            None, build_pdf_from_bytes, images_bytes, None
        )
        if not pdf_bytes:
            await status.edit_text("❌ فشل بناء PDF")
            return

        size_mb = len(pdf_bytes) / (1024 * 1024)
        total_ch = count_chapters(murl)
        fname = safe_name(ch_title) + ".pdf"

        row = []
        if idx > 0:
            row.append(InlineKeyboardButton("⬅️", callback_data=f"p:{mid}:{idx-1}"))
        row.append(InlineKeyboardButton("📖", callback_data=f"cp:{mid}:{(idx//20)+1}"))
        if idx < total_ch - 1:
            row.append(InlineKeyboardButton("➡️", callback_data=f"p:{mid}:{idx+1}"))
        nav_btns = [row, [InlineKeyboardButton("🔙", callback_data=f"d:{mid}")]]

        last = [0.0, -1]
        async def progress_cb(current, total_b):
            now = time.time()
            pct = int(current * 100 / total_b)
            if now - last[0] > 3 or pct - last[1] >= 10 or pct == 100:
                last[0], last[1] = now, pct
                try: await status.edit_text(f"📤 رفع PDF ({size_mb:.1f}MB) — {pct}%")
                except: pass

        try:
            await c.send_document(
                chat_id, io.BytesIO(pdf_bytes),
                caption=f"📄 {html.escape(str(ch_title))} • {len(images_bytes)} صورة • {size_mb:.1f}MB",
                file_name=fname,
                parse_mode=ParseMode.HTML,
                progress=progress_cb,
                reply_markup=InlineKeyboardMarkup(nav_btns),
            )
            try: await status.delete()
            except: pass
        except Exception as e:
            log.error(f"send pdf: {e}")
            await status.edit_text(f"❌ {html.escape(str(e))[:200]}", parse_mode=ParseMode.HTML)
        return

    # ========== 🔀 دمج الكل ==========
    if d.startswith("merge:"):
        mid = int(d.split(":")[1])
        murl = get_url(mid)
        if not murl: await q.answer("❌", show_alert=True); return
        if PDF_LOCKS.get(mid):
            await q.answer("⏳ يعمل حالياً...", show_alert=True); return

        PDF_LOCKS[mid] = True
        await q.answer("🔀...")
        chat_id = q.message.chat.id
        status = await q.message.reply_text("🔀 جاري دمج كل الفصول عبر المحرك...")

        try:
            async with aiohttp.ClientSession() as s:
                dd = await api_merge(s, src, murl)
                if not dd:
                    await status.edit_text("❌ فشل الدمج — جرّب 📚 كل الفصول PDF")
                    return

                images = dd.get("images", [])
                try: await status.edit_text(f"📥 {len(images)} صورة — جاري التنزيل...")
                except: pass

                try:
                    images_bytes = await download_converted_images(s, images, strict=False)
                except Exception as e:
                    await status.edit_text(f"❌ {html.escape(str(e))}", parse_mode=ParseMode.HTML)
                    return

            try: await status.edit_text(f"📄 بناء PDF من {len(images_bytes)} صورة...")
            except: pass

            with tempfile.TemporaryDirectory() as td:
                pdf_path = os.path.join(td, f"merged_{mid}.pdf")
                ok = await asyncio.get_event_loop().run_in_executor(
                    None, build_pdf_from_bytes, images_bytes, pdf_path
                )
                if not ok or not os.path.exists(pdf_path):
                    await status.edit_text("❌ فشل بناء PDF")
                    return

                size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
                if size_mb > 2000:
                    await status.edit_text(f"⚠️ {size_mb:.0f}MB > 2000MB — جرّب 📚 كل الفصول PDF بدلاً من الدمج")
                    return

                last = [0.0, -1]
                async def progress_cb(current, total_b):
                    now = time.time()
                    pct = int(current * 100 / total_b)
                    if now - last[0] > 3 or pct - last[1] >= 5 or pct == 100:
                        last[0], last[1] = now, pct
                        bar = "▓" * (pct // 5) + "░" * (20 - pct // 5)
                        try:
                            await status.edit_text(
                                f"📤 رفع PDF ({size_mb:.0f}MB)\n"
                                f"[{bar}] {pct}%\n"
                                f"{current/(1024*1024):.0f}/{total_b/(1024*1024):.0f} MB")
                        except: pass

                try:
                    await c.send_document(
                        chat_id, pdf_path,
                        caption=f"🔀 <b>كل الفصول</b> • {len(images_bytes)} صورة • {size_mb:.0f}MB",
                        file_name=f"merged_{mid}.pdf",
                        parse_mode=ParseMode.HTML,
                        progress=progress_cb,
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🔙", callback_data=f"d:{mid}")
                        ]]),
                    )
                    try: await status.delete()
                    except: pass
                except Exception as e:
                    log.error(f"send merge: {e}")
                    await status.edit_text(f"❌ {html.escape(str(e))[:200]}", parse_mode=ParseMode.HTML)
        finally:
            PDF_LOCKS.pop(mid, None)
        return

    # ========== قائمة PDF للكل ==========
    if d.startswith("pdfmenu:"):
        mid = int(d.split(":")[1])
        murl = get_url(mid)
        if not murl: await q.answer("❌", show_alert=True); return
        total = count_chapters(murl)
        if not total: await q.answer("❌ لا فصول", show_alert=True); return

        btns = []
        for n in (10, 30, 50, 100):
            if n < total:
                btns.append([InlineKeyboardButton(f"📄 أول {n} فصل", callback_data=f"pdfall:{mid}:{n}")])
        btns.append([InlineKeyboardButton(f"📚 الكل ({total} فصل)", callback_data=f"pdfall:{mid}:{total}")])
        btns.append([InlineKeyboardButton("🔙", callback_data=f"d:{mid}")])

        await q.answer()
        try:
            await q.message.reply_text(
                "📄 <b>اختر عدد الفصول</b>\n\n"
                "⏱️ الوقت المتوقع تقريباً:\n"
                "• 10 فصول ≈ 3 دقائق\n"
                "• 30 فصل ≈ 10 دقائق\n"
                "• 50 فصل ≈ 15 دقيقة\n"
                "• 100 فصل ≈ 30 دقيقة",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(btns),
            )
        except Exception as e:
            log.warning(f"pdfmenu: {e}")
        return

    # ========== PDF لعدة فصول (streaming — ذاكرة منخفضة) ==========
    if d.startswith("pdfall:"):
        _, mid_s, limit_s = d.split(":")
        mid, limit = int(mid_s), int(limit_s)
        murl = get_url(mid)
        if not murl: await q.answer("❌", show_alert=True); return
        if PDF_LOCKS.get(mid):
            await q.answer("⏳ يبني حالياً...", show_alert=True); return

        total = count_chapters(murl)
        if not total: await q.answer("❌", show_alert=True); return
        if limit <= 0 or limit > total: limit = total

        await q.answer(f"📄 {limit} فصل...")
        PDF_LOCKS[mid] = True
        chat_id = q.message.chat.id
        status = await q.message.reply_text(f"⏳ بدء العمل على {limit} فصل...")

        try:
            chapter_urls = []
            for i in range(limit):
                ch = get_chapter(murl, i)
                if ch: chapter_urls.append((i, ch[0], ch[1]))

            if not chapter_urls:
                await status.edit_text("❌ لا فصول")
                return

            doc = fitz.open()
            total_added = 0
            skipped = 0

            async with aiohttp.ClientSession() as s:
                for j, (idx, ch_title, ch_url_val) in enumerate(chapter_urls, 1):
                    try:
                        dd = await api_convert(s, src, ch_url_val)
                        if not dd:
                            log.warning(f"skip ch {idx}: convert failed")
                            skipped += 1
                            continue
                        images = dd.get("images", [])
                        try:
                            bytes_list = await download_converted_images(s, images, strict=True)
                        except Exception as e:
                            log.warning(f"ch {idx}: {e}")
                            skipped += 1
                            continue

                        added_here = await asyncio.get_event_loop().run_in_executor(
                            None, _append_all_images, doc, bytes_list
                        )
                        total_added += added_here
                        del bytes_list

                        if j % 2 == 0 or j == len(chapter_urls):
                            try:
                                await status.edit_text(
                                    f"🔍 <b>{j}/{len(chapter_urls)}</b> فصل\n"
                                    f"📸 {total_added} صورة | ❌ {skipped} فشل",
                                    parse_mode=ParseMode.HTML)
                            except: pass
                    except Exception as e:
                        log.error(f"ch {idx}: {e}")
                        skipped += 1

            if total_added == 0:
                doc.close()
                await status.edit_text("❌ لا صور")
                return

            try: await status.edit_text(f"📄 بناء PDF نهائي من {total_added} صورة...")
            except: pass

            with tempfile.TemporaryDirectory() as td:
                pdf_path = os.path.join(td, f"manga_{mid}.pdf")
                try:
                    await asyncio.get_event_loop().run_in_executor(
                        None, lambda: doc.save(pdf_path, deflate=True, garbage=3)
                    )
                except Exception as e:
                    doc.close()
                    await status.edit_text(f"❌ {html.escape(str(e))[:200]}", parse_mode=ParseMode.HTML)
                    return
                doc.close()

                if not os.path.exists(pdf_path):
                    await status.edit_text("❌ فشل بناء PDF")
                    return

                size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
                if size_mb > 2000:
                    await status.edit_text(f"⚠️ {size_mb:.0f}MB > 2000MB — جرّب عدداً أقل.")
                    return

                last = [0.0, -1]
                async def progress_cb(current, total_b):
                    now = time.time()
                    pct = int(current * 100 / total_b)
                    if now - last[0] > 3 or pct - last[1] >= 5 or pct == 100:
                        last[0], last[1] = now, pct
                        bar = "▓" * (pct // 5) + "░" * (20 - pct // 5)
                        try:
                            await status.edit_text(
                                f"📤 رفع PDF ({size_mb:.0f}MB)\n"
                                f"[{bar}] {pct}%\n"
                                f"{current/(1024*1024):.0f}/{total_b/(1024*1024):.0f} MB")
                        except: pass

                caption = f"📚 <b>{limit} فصل</b> • {total_added} صورة • {size_mb:.0f}MB"
                if skipped:
                    caption += f"\n⚠️ فشل {skipped} فصل"

                try:
                    await c.send_document(
                        chat_id, pdf_path,
                        caption=caption,
                        file_name=f"manga_{mid}_{limit}ch.pdf",
                        parse_mode=ParseMode.HTML,
                        progress=progress_cb,
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🔙", callback_data=f"d:{mid}")
                        ]]),
                    )
                    try: await status.delete()
                    except: pass
                except Exception as e:
                    log.error(f"send: {e}")
                    await status.edit_text(f"❌ {html.escape(str(e))[:200]}", parse_mode=ParseMode.HTML)
        finally:
            PDF_LOCKS.pop(mid, None)
        return

    await q.answer()

if __name__ == "__main__":
    log.info("🚀 Bot starting...")
    app.run()
