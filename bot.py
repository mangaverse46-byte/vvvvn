#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🤖 بوت مانجا — SQLite + img2pdf + روابط هدايا + مشاركة (نهائي)"""

import sys, subprocess, importlib.util, json, os, re, io, math, time, sqlite3, secrets, base64, zlib, hashlib
import asyncio, aiohttp
import zipfile, threading, tempfile
from datetime import datetime
from urllib.parse import quote, urljoin, unquote
from aiogram3_runtime import LegacyFilters as filters, make_legacy_app, make_inline_keyboard, create_bot, as_input_file
import signal
from aiogram.types import InlineKeyboardButton as _TelegramInlineKeyboardButton
from telethon import TelegramClient
InlineKeyboardMarkup = make_inline_keyboard

# Add a clear icon to any inline button label that does not already contain one.
def InlineKeyboardButton(text, *args, **kwargs):
    label = str(text).strip()
    callback = str(kwargs.get("callback_data") or "")
    # Give icon-only controls an action word so buttons are never emoji-only.
    if label in ("🔙", "⬅️", "➡️", "❌", "✅", "📋", "🔄", "⚙️", "🖼️", "📭"):
        label = {"🔙":"⬅️ رجوع", "⬅️":"⬅️ السابق", "➡️":"➡️ التالي", "❌":"❌ إغلاق",
                 "✅":"✅ تأكيد", "📋":"📋 عرض القائمة", "🔄":"🔄 تحديث",
                 "⚙️":"⚙️ إدارة", "🖼️":"🖼️ الصور", "📭":"📭 لا توجد عناصر"}[label]
    # Other emoji-only labels (for example 💰 or ⏰) receive a verb based on their action.
    if not any(ch.isalnum() or "\u0600" <= ch <= "\u06FF" for ch in label):
        if "close" in callback: action = "إغلاق"
        elif "back" in callback or "panel" in callback: action = "رجوع"
        elif "del" in callback or "remove" in callback: action = "حذف"
        elif "edit" in callback or "set" in callback: action = "تعديل"
        elif "add" in callback: action = "إضافة"
        elif "list" in callback: action = "عرض القائمة"
        elif "stats" in callback: action = "الإحصائيات"
        elif "refresh" in callback: action = "تحديث"
        elif "share" in callback: action = "مشاركة"
        elif "vip" in callback: action = "إدارة VIP"
        elif "gift" in callback: action = "إدارة الهدية"
        elif "reward" in callback: action = "المكافآت"
        else: action = "فتح"
        label = f"{label} {action}"
    has_icon = any(ord(ch) >= 0x1F000 or ord(ch) in (0x2190, 0x2192, 0x21A9, 0x21AA, 0x23F0, 0x23F3, 0x25B6, 0x25C0, 0x2600, 0x2601, 0x2611, 0x2620, 0x263A, 0x2640, 0x2642, 0x2665, 0x267B, 0x2699, 0x26A0, 0x2705, 0x2709, 0x2714, 0x274C, 0x274E, 0x2753, 0x2754, 0x2755, 0x2757, 0x2795, 0x2796, 0x2797, 0x27A1, 0x27B0, 0x27BF) for ch in label)
    if not has_icon:
        lower = label.casefold()
        icon = "🔙" if any(x in lower for x in ("رجوع", "السابق", "عودة")) else "🏠" if any(x in lower for x in ("الرئيسية", "الرئيس", "home")) else "🔍" if any(x in lower for x in ("بحث", "search")) else "📚" if any(x in lower for x in ("مانجا", "فصول", "مصادر", "manga", "chapter")) else "⚙️" if any(x in lower for x in ("إعداد", "ادمن", "إدارة", "admin")) else "📌"
        label = f"{icon} {label}"
    # aiogram 3 uses keyword-only Pydantic model fields; the legacy
    # wrapper accepts Pyrogram-style positional callback_data/url arguments.
    if args:
        if len(args) > 2:
            raise TypeError("InlineKeyboardButton accepts at most text, callback_data, url")
        if len(args) >= 1:
            kwargs.setdefault("callback_data", args[0])
        if len(args) == 2:
            kwargs.setdefault("url", args[1])
    return _TelegramInlineKeyboardButton(text=label, **kwargs)

from aiogram.enums import ParseMode, ChatMemberStatus

import gc

# ===== BEGIN MERGED MANGA API MODULE =====
# -*- coding: utf-8 -*-
"""Client for the PixelFlow Manga Engine API + local PDF assembly."""
import asyncio
import json
import re
import urllib.parse
import urllib.request
import urllib.error
import random
from io import BytesIO

API = "https://pixelflow-callback-harbor.lovable.app/api/public/manga"
API_IMAGE = "https://pixelflow-callback-harbor.lovable.app/api/public/image"
_SOURCE_CACHE = []
_SOURCE_CODES = {"mangalik": "m", "mesh": "e", "azora": "a", "lavascans": "l"}

# Successful GET responses are cached by action + complete URL.
_API_RESPONSE_CACHE = {}
_API_CACHE_LOCK = threading.RLock()
_API_CACHE_TTL = {
    "sources": 3600, "latest": 300, "search": 90,
    "genres": 3600, "genre-manga": 300, "details": 1800,
}
_API_CACHE_MAX_ITEMS = 1500

def _api_cache_get(key):
    now = time.time()
    with _API_CACHE_LOCK:
        entry = _API_RESPONSE_CACHE.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if expires_at <= now:
            _API_RESPONSE_CACHE.pop(key, None)
            return None
        return json.loads(json.dumps(value, ensure_ascii=False))

def _api_cache_set(key, value, ttl):
    if not ttl:
        return
    now = time.time()
    with _API_CACHE_LOCK:
        for old_key in [k for k, (expiry, _) in _API_RESPONSE_CACHE.items() if expiry <= now]:
            _API_RESPONSE_CACHE.pop(old_key, None)
        if len(_API_RESPONSE_CACHE) >= _API_CACHE_MAX_ITEMS:
            oldest = min(_API_RESPONSE_CACHE, key=lambda k: _API_RESPONSE_CACHE[k][0])
            _API_RESPONSE_CACHE.pop(oldest, None)
        _API_RESPONSE_CACHE[key] = (
            now + ttl, json.loads(json.dumps(value, ensure_ascii=False))
        )

def clear_api_cache(action=None):
    with _API_CACHE_LOCK:
        if action is None:
            _API_RESPONSE_CACHE.clear()
        else:
            prefix = str(action) + "|"
            for key in list(_API_RESPONSE_CACHE):
                if key.startswith(prefix):
                    _API_RESPONSE_CACHE.pop(key, None)

def _request(action, params=None, payload=None, use_cache=True):
    if payload is None:
        q = {"action": action}
        q.update(params or {})
        url = API + "?" + urllib.parse.urlencode(q)
        data = None
        headers = {"User-Agent": "Mozilla/5.0 MangaVirus", "Accept": "application/json"}
        cache_key = str(action) + "|" + url
        ttl = _API_CACHE_TTL.get(str(action), 0)
        if use_cache and ttl:
            cached = _api_cache_get(cache_key)
            if cached is not None:
                return cached
    else:
        cache_key = None
        ttl = 0
        body = {"action": action}
        body.update(payload)
        url = API
        data = json.dumps(body).encode("utf-8")
        headers = {"User-Agent": "Mozilla/5.0 MangaVirus", "Content-Type": "application/json", "Accept": "application/json"}

    # Retry only temporary gateway/rate-limit/network failures. Do not hide permanent 4xx errors.
    last_error = None
    for attempt in range(4):
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                raw = response.read()
            result = json.loads(raw.decode("utf-8"))
            if isinstance(result, dict) and result.get("error"):
                raise RuntimeError(str(result.get("error"))[:250])
            if cache_key is not None and use_cache and ttl:
                _api_cache_set(cache_key, result, ttl)
            return result
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = exc
            if attempt == 3:
                raise
        time.sleep(min(2 ** attempt, 8) + random.uniform(0, 0.5))
    raise RuntimeError(f"API request failed: {last_error}")

def get_sources(force=False):
    global _SOURCE_CACHE
    raw = _request("sources", use_cache=not force)
    items = raw.get("sources", []) if isinstance(raw, dict) else []
    _SOURCE_CACHE = [dict(x) for x in items if isinstance(x, dict) and x.get("enabled") is True and x.get("id")]
    return [dict(x) for x in _SOURCE_CACHE]

def source_code(source_id):
    source_id = str(source_id)
    if source_id in _SOURCE_CODES:
        return _SOURCE_CODES[source_id]
    used = set(_SOURCE_CODES.values())
    alphabet = "bcdfghjknopqrstuvwxyz0123456789"
    for code in alphabet:
        if code not in used:
            _SOURCE_CODES[source_id] = code
            return code
    # Callback payloads stay short even if the registry grows unusually large.
    return str(abs(hash(source_id)) % 10)

def source_from_code(code):
    for source_id in get_source_ids():
        if source_code(source_id) == str(code):
            return source_id
    return None

def get_source_ids():
    return [str(x["id"]) for x in get_sources()]

def _items(obj, keys=("results", "items", "mangas", "chapters")):
    if not isinstance(obj, dict):
        return obj if isinstance(obj, list) else []
    for key in keys:
        value = obj.get(key)
        if isinstance(value, list):
            return value
    data = obj.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return _items(data, keys)
    return []

def _cover_value(value):
    """Normalize cover values returned as URLs or nested image objects."""
    if isinstance(value, dict):
        for key in ("url", "src", "href", "original", "large", "full", "image", "cover"):
            candidate = value.get(key)
            if candidate:
                found = _cover_value(candidate)
                if found:
                    return found
        return None
    if isinstance(value, str):
        value = value.strip()
        if value.startswith(("https://", "http://", "//")):
            return "https:" + value if value.startswith("//") else value
    return None

def _extract_cover_url(*objects):
    keys = ("cover_url", "coverUrl", "cover_sd_url", "cover_image_url", "cover_image",
            "cover", "image_url", "image", "thumbnail_url", "thumbnail", "thumb",
            "poster", "featured_image", "manga_cover")
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        for key in keys:
            candidate = _cover_value(obj.get(key))
            if candidate:
                return candidate
        for nested_key in ("manga", "data", "metadata", "images", "media"):
            nested = obj.get(nested_key)
            if isinstance(nested, dict):
                candidate = _extract_cover_url(nested)
                if candidate:
                    return candidate
    return None

def _manga(item):
    if isinstance(item, (list, tuple)):
        vals = list(item) + ["", ""]
        return {"title": str(vals[0]), "url": vals[1], "id": str(vals[2] or vals[1] or vals[0])}
    if not isinstance(item, dict):
        return {}
    url = item.get("url") or item.get("manga_url") or item.get("link") or item.get("href")
    ident = item.get("id") or item.get("slug") or url
    return dict(item, title=str(item.get("title") or item.get("name") or "Manga"),
        url=url, id=str(ident or url or ""), cover_url=_extract_cover_url(item))

def _chapter(item, index):
    if isinstance(item, str):
        item = {"url": item, "title": f"Chapter {index + 1}"}
    if not isinstance(item, dict):
        return None
    url = item.get("url") or item.get("chapter_url") or item.get("link") or item.get("href")
    title = str(item.get("title") or item.get("name") or item.get("chapter") or item.get("number") or f"Chapter {index + 1}")
    number = str(item.get("number") or item.get("chapter_number") or item.get("num") or "")
    if not re.fullmatch(r"\d+(?:\.\d+)?", number):
        # Do not mistake relative publish times (e.g. "1 hour ago" / "ساعة واحدة")
        # for chapter numbers.
        time_label = re.search(
            r"\b(?:ago|hour|hours|minute|minutes|day|days|week|weeks|month|months|year|years)\b|"
            r"(?:منذ|ساعة|ساعات|دقيقة|دقائق|يوم|أيام|اسبوع|أسبوع|شهر|سنة)",
            title, re.IGNORECASE
        )
        match = re.search(r"(\d+(?:\.\d+)?)", title) if not time_label else None
        number = match.group(1) if match else ""
    return dict(item, url=url, id=str(item.get("id") or item.get("chapter_id") or url or index),
        title=title, number=number, num_str=number, display_text=number or title,
        is_numeric=bool(re.fullmatch(r"\d+(?:\.\d+)?", number)))

class MangaSource:
    def __init__(self, source_id):
        self.SOURCE = str(source_id)
        meta = next((x for x in get_sources() if str(x.get("id")) == self.SOURCE), None)
        if not meta:
            raise ValueError(f"مصدر غير متاح: {source_id}")
        self.NAME = str(meta.get("name") or self.SOURCE)
        self.BASE = str(meta.get("base_url") or "")
        self.H = {"User-Agent": "Mozilla/5.0"}

    def search(self, query, page=1):
        raw = _request("search", {"source": self.SOURCE, "q": query, "page": page})
        return [_manga(x) for x in _items(raw)]

    def get_latest_updates(self, page=1, force=False):
        raw = _request("latest", {"source": self.SOURCE, "page": page}, use_cache=not force)
        return [_manga(x) for x in _items(raw)]

    def get_genres(self):
        raw = _request("genres", {"source": self.SOURCE})
        out = []
        for x in _items(raw, ("results", "genres", "categories")):
            if isinstance(x, str):
                out.append((x, x))
            elif isinstance(x, dict):
                name = x.get("name") or x.get("title") or x.get("genre")
                slug = x.get("url") or x.get("genre_url") or x.get("slug") or x.get("id")
                if name and slug:
                    out.append((str(name), str(slug)))
        return out

    def get_manga_by_genre(self, slug, page=1):
        raw = _request("genre-manga", {"source": self.SOURCE, "genre_url": slug, "page": page})
        return [_manga(x) for x in _items(raw)]

    def get_details(self, manga_url):
        raw = _request("details", {"source": self.SOURCE, "url": str(manga_url)})
        info = raw.get("manga", raw) if isinstance(raw, dict) else {}
        if not isinstance(info, dict):
            return None
        chapters = info.get("chapters") or raw.get("chapters", []) if isinstance(raw, dict) else []
        info = dict(info)
        info["name"] = info.get("name") or info.get("title") or "Manga"
        info["title"] = info.get("title") or info["name"]
        info["cover_url"] = _extract_cover_url(info, raw)
        if info["cover_url"] and not info["cover_url"].startswith(("http://", "https://")):
            info["cover_url"] = urljoin(str(info.get("url") or manga_url), info["cover_url"])
        info["description"] = info.get("description") or info.get("story") or ""
        info["genres"] = info.get("genres") or []
        info["url"] = info.get("url") or str(manga_url)
        info["chapters"] = [c for i, x in enumerate(chapters or []) if (c := _chapter(x, i)) and c.get("url")]

        # MangaLik may expose its page's "إلغاء الرد" control as if it were a chapter.
        # Remove that UI artifact only for MangaLik; keep every real chapter intact.
        if self.SOURCE.lower() == "mangalik":
            def _is_reply_cancel_item(chapter):
                label = str(
                    chapter.get("title") or chapter.get("name")
                    or chapter.get("display_text") or ""
                ).strip().casefold()
                compact = re.sub(r"[\sـ]+", "", label)
                return compact in {
                    "إلغاءالرد", "الغاءالرد", "إلغاءرد", "الغاءرد",
                    "cancelreply", "cancelresponse",
                }
            info["chapters"] = [
                chapter for chapter in info["chapters"]
                if not _is_reply_cancel_item(chapter)
            ]
        return info

    def get_chapters(self, manga_url):
        info = self.get_details(manga_url)
        return (info or {}).get("chapters", [])

    def get_chapter_images(self, chapter):
        if isinstance(chapter, dict):
            chapter_url = chapter.get("url") or chapter.get("chapter_url")
        else:
            chapter_url = str(chapter)
        if not chapter_url or not chapter_url.startswith(("http://", "https://")):
            raise ValueError("رابط الفصل غير موجود")
        # The engine extracts the complete chapter, resizes/compresses it,
        # and returns ordered JPEG endpoint URLs. The bot only downloads them.
        raw = _request("convert", payload={"source": self.SOURCE, "chapter_url": chapter_url})
        images = raw.get("images", []) if isinstance(raw, dict) else []
        # The engine returns the processed image endpoint in "url".
        urls = [
            x.get("url")
            for x in images
            if isinstance(x, dict) and x.get("ok") and x.get("url")
        ]
        if not urls:
            errors = [x.get("error") for x in images if isinstance(x, dict) and x.get("error")]
            raise RuntimeError("لم يستخرج المحرك صوراً صالحة" + (": " + "; ".join(errors[:2]) if errors else ""))
        return urls

    def get_cover_image(self, info):
        return (info or {}).get("cover_url")

async def _get_cached_bdf_cover(client):
    """Cache only the configured BDF cover on disk to avoid downloading it repeatedly."""
    file_id = settings.get("bdf_image") if isinstance(settings, dict) else None
    if not file_id or client is None:
        return None

    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    os.makedirs(cache_dir, exist_ok=True)
    cache_name = "bdf_cover_" + hashlib.sha256(str(file_id).encode("utf-8")).hexdigest()[:20] + ".img"
    cache_path = os.path.join(cache_dir, cache_name)

    try:
        if os.path.isfile(cache_path) and os.path.getsize(cache_path) > 100:
            with open(cache_path, "rb") as cached:
                return cached.read()

        downloaded = await client.download_media(file_id, in_memory=True)
        if not downloaded:
            return None
        if hasattr(downloaded, "getvalue"):
            blob = downloaded.getvalue()
        elif hasattr(downloaded, "read"):
            blob = downloaded.read()
        else:
            blob = b""
        if not blob or len(blob) <= 100:
            return None

        with open(cache_path, "wb") as cached:
            cached.write(blob)

        # Keep only the currently configured BDF cover cached.
        for name in os.listdir(cache_dir):
            if name.startswith("bdf_cover_") and name.endswith(".img") and name != cache_name:
                try:
                    os.remove(os.path.join(cache_dir, name))
                except OSError:
                    pass
        return blob
    except Exception:
        return None

async def create_pdf_from_images(urls, client=None, headers=None):
    """Download images concurrently and assemble them with img2pdf only."""
    import aiohttp
    import img2pdf

    if urls and isinstance(urls[0], (list, tuple)):
        chapter_groups = [list(group) for group in urls if group]
    else:
        chapter_groups = [list(urls or [])]

    indexed_urls = [
        (chapter_index, image_index, url)
        for chapter_index, group in enumerate(chapter_groups)
        for image_index, url in enumerate(group)
        if url
    ]
    if not indexed_urls:
        return None

    timeout = aiohttp.ClientTimeout(total=90, connect=15, sock_read=60)
    request_headers = headers or {"User-Agent": "Mozilla/5.0 MangaVirus"}

    # Keep a single reusable HTTP session, but avoid opening an unlimited
    # number of simultaneous sockets (which can slow CDNs and cause timeouts).
    # 48 active downloads is a conservative starting point for chapter images.
    connector = aiohttp.TCPConnector(
        limit=64, limit_per_host=48, ttl_dns_cache=600,
        keepalive_timeout=60, enable_cleanup_closed=True,
    )
    download_sem = asyncio.Semaphore(48)
    downloaded = [None] * len(indexed_urls)

    async with aiohttp.ClientSession(
        timeout=timeout, connector=connector, headers=request_headers
    ) as session:
        async def fetch(position, url):
            async with download_sem:
                for attempt in range(4):
                    try:
                        async with session.get(url, allow_redirects=True) as response:
                            if response.status == 200:
                                data = await response.read()
                                if data and len(data) > 100:
                                    downloaded[position] = data
                                    return
                            elif response.status == 429 or response.status in (408, 425, 500, 502, 503, 504):
                                retry = response.headers.get("Retry-After", "2")
                                try:
                                    delay = min(20.0, max(0.5, float(retry)))
                                except (TypeError, ValueError):
                                    delay = min(8.0, 0.5 * (2 ** attempt))
                                if attempt < 3:
                                    await asyncio.sleep(delay)
                                    continue
                            else:
                                # Permanent HTTP errors should not be retried.
                                return
                    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
                        if attempt == 3:
                            return
                    if attempt < 3:
                        await asyncio.sleep(0.25 * (attempt + 1))

        await asyncio.gather(
            *(fetch(position, url) for position, (_, _, url) in enumerate(indexed_urls))
        )

    # Manga engine image URLs are expected to be JPEG. img2pdf also supports
    # PNG, JPEG2000 and selected TIFF/CCITT inputs. No image re-encoding.
    candidates = []
    for position, blob in enumerate(downloaded):
        if not blob:
            continue
        supported = (
            blob.startswith(b"\xff\xd8\xff")
            or blob.startswith(b"\x89PNG\r\n\x1a\n")
            or blob.startswith((b"\x00\x00\x00\x0cjP  ", b"\xffO\xffQ"))
            or blob.startswith((b"II*\x00", b"MM\x00*"))
        )
        if supported:
            candidates.append((position, blob))
        else:
            pass

    if not candidates:
        return None

    # Validate each candidate separately; a corrupt page will not cancel the chapter.
    valid = []
    for position, blob in candidates:
        try:
            img2pdf.convert(BytesIO(blob))
            valid.append(blob)
        except Exception as exc:
            pass

    # Use the server-cached BDF cover as the first PDF page.
    cover_blob = await _get_cached_bdf_cover(client)
    if cover_blob:
        try:
            if (
                cover_blob.startswith(b"\xff\xd8\xff")
                or cover_blob.startswith(b"\x89PNG\r\n\x1a\n")
                or cover_blob.startswith((b"\x00\x00\x00\x0cjP  ", b"\xffO\xffQ"))
                or cover_blob.startswith((b"II*\x00", b"MM\x00*"))
            ):
                img2pdf.convert(BytesIO(cover_blob))
                valid.insert(0, cover_blob)
        except Exception:
            pass

    if not valid:
        return None

    result = img2pdf.convert(
        *(BytesIO(blob) for blob in valid),
        title="Manga Virus",
        author="Manga Virus Bot",
        creator="Manga Virus",
        producer="Manga Virus PDF Engine",
        subject="MANGA_VIRUS_ORIGINAL_V1",
        keywords=["MANGA_VIRUS_ORIGINAL_V1", "Manga Virus"],
    )

    # PDF is built: release the source image byte buffers immediately.
    valid.clear()
    candidates.clear()
    downloaded.clear()
    cover_blob = None

    buf = BytesIO(result)
    result = None
    buf.name = "manga.pdf"
    buf.seek(0)
    return buf

async def download_images_parallel(urls, client=None, headers=None):
    return await create_pdf_from_images(urls, client=client, headers=headers)

def get_source(source_id):
    """Return the API-backed adapter for one enabled manga source."""
    return MangaSource(source_id)


LATEST_PER_SOURCE = 10

def get_all_latest():
    """Return at most the 10 newest manga from each enabled source."""
    rows = []
    sources = get_sources()
    for source in sources:
        source_id = str(source.get("id") or "")
        if not source_id:
            continue
        try:
            api = MangaSource(source_id)
            # Source latest endpoints are already ordered newest-first.
            items = api.get_latest_updates(page=1)[:LATEST_PER_SOURCE]
            source_rows = []
            for item in items:
                title = str(item.get("title") or item.get("name") or "Manga")
                url = item.get("url") or item.get("manga_url") or item.get("link")
                if not url:
                    continue
                ident = str(item.get("id") or url)
                latest_chapter = (
                    item.get("latest_chapter")
                    or item.get("last_chapter")
                    or item.get("chapter")
                    or ""
                )
                source_rows.append((title, str(url), ident, str(latest_chapter), source_id))
            rows.extend(source_rows[:LATEST_PER_SOURCE])
        except Exception:
            # A failing source must not prevent other sources from returning results.
            continue
    return rows


# Backward-compatible class names; source discovery remains API-driven.
class StarzManga(MangaSource):
    def __init__(self): super().__init__("mangalik")
class MeshManga(MangaSource):
    def __init__(self): super().__init__("mesh")
class AzoraFly(MangaSource):
    def __init__(self): super().__init__("azora")
class LavaScans(MangaSource):
    def __init__(self): super().__init__("lava")
# ===== END MERGED MANGA API MODULE =====
PDF_MAX_CHAPTERS = 10

def install_package(p):
    try: subprocess.check_call([sys.executable,"-m","pip","install",p,"--quiet"]); return True
    except: return False
def ensure_installed(p):
    if importlib.util.find_spec(p) is None:
        install_package(p)
for pkg in ["aiogram","aiohttp","img2pdf","cloudscraper","python-dotenv"]:
    ensure_installed(pkg)

from dotenv import load_dotenv
load_dotenv()

# Credentials are read from the local .env file; never commit real secrets.
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
if not BOT_TOKEN or not OWNER_ID:
    raise RuntimeError("Missing BOT_TOKEN or OWNER_ID in .env")

# Telethon MTProto uploader: direct Telegram uploads up to the bot-account limit.
API_ID = int(os.getenv("API_ID", "0") or 0)
API_HASH = os.getenv("API_HASH", "").strip()
_mtproto_client = None
_mtproto_lock = asyncio.Lock()


async def send_pdf_direct(chat_id, document, file_name, caption="", progress_message=None):
    """Upload a PDF directly through MTProto and show throttled upload progress."""
    global _mtproto_client
    if not API_ID or not API_HASH:
        raise RuntimeError(
            "إعدادات الرفع المباشر ناقصة: أضف API_ID و API_HASH إلى ملف .env"
        )
    async with _mtproto_lock:
        if _mtproto_client is None:
            _mtproto_client = TelegramClient(
                "manga_virus_mtproto", API_ID, API_HASH,
                connection_retries=5, retry_delay=2,
                auto_reconnect=True, receive_updates=False,
            )
        if not _mtproto_client.is_connected():
            await _mtproto_client.connect()
        if not await _mtproto_client.is_user_authorized():
            await _mtproto_client.start(bot_token=BOT_TOKEN)

    if hasattr(document, "seek"):
        document.seek(0)
    try:
        document.name = file_name
    except Exception:
        pass

    loop = asyncio.get_running_loop()
    last_update = [0.0]

    async def update_progress(current, total):
        if not progress_message or not total:
            return
        percent = min(100, int(current * 100 / total))
        try:
            await progress_message.edit_text(
                f"📤 **جاري رفع PDF مباشرة عبر MTProto...**\\n"
                f"📊 التقدم: `{percent}%`\\n"
                f"📦 `{current / (1024 * 1024):.1f}` / `{total / (1024 * 1024):.1f}` MB"
            )
        except Exception:
            pass

    def progress_callback(current, total):
        if not progress_message or not total:
            return
        now = time.monotonic()
        percent = min(100, int(current * 100 / total))
        if percent < 5 or (percent < 100 and now - last_update[0] < 3):
            return
        last_update[0] = now
        loop.call_soon_threadsafe(
            lambda: asyncio.create_task(update_progress(current, total))
        )

    return await _mtproto_client.send_file(
        entity=int(chat_id),
        file=document,
        caption=caption,
        force_document=True,
        file_name=file_name,
        parse_mode=None,
        progress_callback=progress_callback,
    )


async def close_mtproto_uploader():
    global _mtproto_client
    if _mtproto_client is not None and _mtproto_client.is_connected():
        await _mtproto_client.disconnect()
    _mtproto_client = None

ADMINS = [OWNER_ID]; OWNER_IDS = [OWNER_ID]
MAX_WORKERS = 15
CHECK_INTERVAL = 15*60
BACKUP_INTERVAL = 24*3600
VIP_PLANS = {"weekly":7*24*3600,"monthly":30*24*3600,"yearly":365*24*3600}
VIP_PLAN_NAMES = {"weekly":"أسبوعي","monthly":"شهري","yearly":"سنوي"}

BACKUP_DIR="backups"; os.makedirs(BACKUP_DIR,exist_ok=True)
user_data={}; BOT_USERNAME=None; latest_manga_cache=[]
active_downloads = set(); active_downloads_lock = threading.Lock()
def try_lock_download(uid):
    with active_downloads_lock:
        if uid in active_downloads: return False
        active_downloads.add(uid); return True
def unlock_download(uid):
    with active_downloads_lock: active_downloads.discard(uid)
def is_downloading(uid):
    with active_downloads_lock: return uid in active_downloads

class FakeCallback:
    def __init__(self, user, message, data):
        self.from_user = user; self.message = message; self.data = data
        self.id = ""; self.chat_instance = ""
    async def answer(self, *args, **kwargs): return None

async def _reopen_admin_page(client, uid, msg, cb_data):
    fake = FakeCallback(type('U',(),{'id':uid,'username':None,'first_name':'','last_name':''})(), msg, cb_data)
    try: await unified_callback(client, fake)
    except Exception as e:  pass

# ============ SQLite ============
DB_PATH = "bot.db"; _local = threading.local(); _write_lock = threading.Lock()
def _conn():
    if not hasattr(_local, "conn"):
        c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
        c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA synchronous=NORMAL")
        c.execute("PRAGMA busy_timeout=30000"); c.row_factory = sqlite3.Row
        _local.conn = c
    return _local.conn
def _execute(sql, params=()):
    for attempt in range(3):
        try:
            with _write_lock:
                c = _conn(); cur = c.execute(sql, params); c.commit(); return cur
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < 2: time.sleep(0.5)
            else: raise

def _init_db():
    c = _conn()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (uid INTEGER PRIMARY KEY, joined REAL NOT NULL, downloads INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS favorites (uid INTEGER NOT NULL, identifier TEXT NOT NULL, source TEXT NOT NULL, title TEXT NOT NULL, manga_url TEXT NOT NULL, cover TEXT, last_chapter TEXT, notify INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (uid, identifier, source));
    CREATE TABLE IF NOT EXISTS fav_settings (uid INTEGER PRIMARY KEY, notifications_enabled INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS daily_usage (uid INTEGER PRIMARY KEY, last_reset REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0, bonus INTEGER NOT NULL DEFAULT 0, reset_expires REAL NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS vip_users (uid INTEGER PRIMARY KEY, plan TEXT NOT NULL, started REAL NOT NULL, expires REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS referrals (owner_id INTEGER NOT NULL, referred_id INTEGER NOT NULL, ts REAL NOT NULL, rewarded INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (owner_id, referred_id));
    CREATE TABLE IF NOT EXISTS manga_share_links (code TEXT PRIMARY KEY, source TEXT NOT NULL, identifier TEXT NOT NULL, created_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS bots (bid TEXT PRIMARY KEY, token TEXT NOT NULL, name TEXT NOT NULL, target_id INTEGER, added REAL NOT NULL, added_by INTEGER, last_sent REAL NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS admins (uid INTEGER PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS banned (uid INTEGER PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS complaints (id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER NOT NULL, username TEXT, first_name TEXT, text TEXT NOT NULL, ts REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS download_stats (id INTEGER PRIMARY KEY CHECK (id = 1), total_downloads INTEGER NOT NULL DEFAULT 0);
    INSERT OR IGNORE INTO download_stats (id, total_downloads) VALUES (1, 0);
    """)
    cols = [r["name"] for r in c.execute("PRAGMA table_info(daily_usage)").fetchall()]
    if "merge_used" not in cols: c.execute("ALTER TABLE daily_usage ADD COLUMN merge_used INTEGER NOT NULL DEFAULT 0")
    if "merge_bonus" not in cols: c.execute("ALTER TABLE daily_usage ADD COLUMN merge_bonus INTEGER NOT NULL DEFAULT 0")
    if "single_reset_at" not in cols: c.execute("ALTER TABLE daily_usage ADD COLUMN single_reset_at REAL NOT NULL DEFAULT 0")
    if "merge_reset_at" not in cols: c.execute("ALTER TABLE daily_usage ADD COLUMN merge_reset_at REAL NOT NULL DEFAULT 0")
    c.execute("""CREATE TABLE IF NOT EXISTS gift_links (
        code TEXT PRIMARY KEY, single_amount INTEGER NOT NULL, merge_amount INTEGER NOT NULL,
        max_users INTEGER NOT NULL, used_count INTEGER NOT NULL DEFAULT 0,
        created_by INTEGER NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL,
        active INTEGER NOT NULL DEFAULT 1)""")
    c.execute("""CREATE TABLE IF NOT EXISTS gift_claims (
        code TEXT NOT NULL, uid INTEGER NOT NULL, claimed_at REAL NOT NULL,
        PRIMARY KEY (code, uid))""")
    c.commit()
    gift_cols = [r["name"] for r in c.execute("PRAGMA table_info(gift_links)").fetchall()]
    for col, ddl in [("allowed_users","TEXT DEFAULT NULL"),("channel_id","TEXT DEFAULT NULL"),
                     ("channel_message_id","INTEGER DEFAULT NULL"),("post_enabled","INTEGER DEFAULT 0"),
                     ("post_interval_hours","INTEGER DEFAULT 2"),("next_post_at","REAL DEFAULT 0"),
                     ("delete_scheduled_at","REAL DEFAULT 0"),("post_mode","TEXT DEFAULT 'auto'")]:
        if col not in gift_cols: c.execute(f"ALTER TABLE gift_links ADD COLUMN {col} {ddl}")
    c.commit()
_init_db()

REQUIRED_TABLES = {'users','settings','favorites','daily_usage','vip_users','referrals','bots','admins','banned','complaints','download_stats','fav_settings','gift_links','gift_claims'}
def _validate_db_file(path):
    if not os.path.exists(path): return False, "الملف غير موجود"
    if os.path.getsize(path) < 4096: return False, "الملف تالف"
    try:
        c = sqlite3.connect(path)
        try: tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        finally: c.close()
        missing = REQUIRED_TABLES - tables
        if missing: return False, f"ناقصة: {', '.join(sorted(missing))}"
        return True, None
    except Exception as e: return False, f"تالف: {e}"

# ============ Settings ============
DEFAULTS = {
    "welcome_message":"🌟 **مرحباً بك في بوت المانجا** 🌟\n\n📖 اختر من الأزرار أدناه:",
    "bdf_image":None,"welcome_image":None,"favorites_image":None,"results_image":None,"sources_image":None,
    "force_sub_channels":[],"force_sub_message":"⚠️ **يجب الاشتراك في القنوات أولاً**\n\nاشترك ثم اضغط تحقق ✅",
    "force_sub_image":None,"force_sub_buttons":{},
    "daily_reward_amount":100,"daily_reward_interval":86400,"merge_daily_limit":50,"merge_max_per_file":10,
    "single_caption":"**[ Ch {chapter} ] {title}**\n@T7T0K_bot",
    "vip_contact_second":None,"allow_parallel_downloads":False,
    "referral_bonus_single":50,"referral_bonus_merge":20,"maintenance_mode": False,
}
def load_settings():
    s = dict(DEFAULTS)
    for row in _conn().execute("SELECT key, value FROM settings").fetchall():
        try: s[row["key"]] = json.loads(row["value"])
        except: pass
    return s
def save_settings():
    with _write_lock:
        c = _conn()
        for k, v in settings.items():
            c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, json.dumps(v, ensure_ascii=False)))
        c.commit()
settings = load_settings()
for k, v in DEFAULTS.items():
    if k not in settings: settings[k] = v
save_settings()
NEW_SINGLE_CAPTION = DEFAULTS["single_caption"]

# ============ Users ============
def add_user(uid):
    try: u = int(uid)
    except: return False
    with _write_lock:
        c = _conn()
        if c.execute("SELECT 1 FROM users WHERE uid=?", (u,)).fetchone(): return False
        c.execute("INSERT INTO users (uid, joined, downloads) VALUES (?,?,0)", (u, time.time())); c.commit(); return True
def get_users_count(): return _conn().execute("SELECT COUNT(*) FROM users").fetchone()[0]
def get_all_user_ids(): return [r["uid"] for r in _conn().execute("SELECT uid FROM users").fetchall()]
def get_user_downloads(uid):
    try: u = int(uid)
    except: return 0
    row = _conn().execute("SELECT downloads FROM users WHERE uid=?", (u,)).fetchone()
    return row["downloads"] if row else 0
def get_user_joined(uid):
    try: u = int(uid)
    except: return time.time()
    row = _conn().execute("SELECT joined FROM users WHERE uid=?", (u,)).fetchone()
    return row["joined"] if row else time.time()
def increment_user_downloads(uid):
    try: u = int(uid)
    except: return
    with _write_lock:
        c = _conn()
        c.execute("INSERT OR IGNORE INTO users (uid, joined, downloads) VALUES (?,?,0)", (u, time.time()))
        c.execute("UPDATE users SET downloads = downloads + 1 WHERE uid=?", (u,)); c.commit()
def increment_download_count(uid=None):
    _execute("UPDATE download_stats SET total_downloads = total_downloads + 1 WHERE id = 1")
    if uid is not None: increment_user_downloads(uid)
def get_download_count():
    row = _conn().execute("SELECT total_downloads FROM download_stats WHERE id=1").fetchone()
    return row["total_downloads"] if row else 0

# ============ Favorites ============
def get_user_favs(uid):
    try: u = int(uid)
    except: return {"items": [], "notifications_enabled": True}
    c = _conn()
    nr = c.execute("SELECT notifications_enabled FROM fav_settings WHERE uid=?", (u,)).fetchone()
    if nr is None:
        _execute("INSERT OR IGNORE INTO fav_settings (uid, notifications_enabled) VALUES (?,1)", (u,)); notif = True
    else: notif = bool(nr["notifications_enabled"])
    items = []
    for r in c.execute("SELECT * FROM favorites WHERE uid=? ORDER BY rowid", (u,)).fetchall():
        items.append({"identifier": r["identifier"], "source": r["source"], "title": r["title"], "manga_url": r["manga_url"], "cover": r["cover"], "last_chapter": r["last_chapter"], "notify": bool(r["notify"])})
    return {"items": items, "notifications_enabled": notif}
def get_fav_items(uid): return get_user_favs(uid).get("items", [])
def get_favorites(uid): return get_fav_items(uid)
def set_notifications_enabled(uid, enabled):
    try: u = int(uid)
    except: return
    _execute("INSERT OR REPLACE INTO fav_settings (uid, notifications_enabled) VALUES (?,?)", (u, 1 if enabled else 0))
def is_notifications_enabled(uid):
    try: u = int(uid)
    except: return True
    row = _conn().execute("SELECT notifications_enabled FROM fav_settings WHERE uid=?", (u,)).fetchone()
    return bool(row["notifications_enabled"]) if row else True
def add_to_favorites(uid, title, ident, source, murl, cover, lch=None):
    try: u = int(uid)
    except: return False
    title = clean_manga_title(title, ident)
    with _write_lock:
        c = _conn()
        if c.execute("SELECT 1 FROM favorites WHERE uid=? AND identifier=? AND source=?", (u, ident, source)).fetchone(): return False
        c.execute("""INSERT INTO favorites (uid, identifier, source, title, manga_url, cover, last_chapter, notify) VALUES (?,?,?,?,?,?,?,1)""", (u, ident, source, title, murl, cover, lch))
        c.commit(); return True
def remove_from_favorites(uid, ident, source):
    try: u = int(uid)
    except: return False
    with _write_lock:
        c = _conn(); cur = c.execute("DELETE FROM favorites WHERE uid=? AND identifier=? AND source=?", (u, ident, source)); c.commit(); return cur.rowcount > 0
def is_favorite(uid, ident, source):
    try: u = int(uid)
    except: return False
    return _conn().execute("SELECT 1 FROM favorites WHERE uid=? AND identifier=? AND source=?", (u, ident, source)).fetchone() is not None
def set_fav_notify(uid, ident, source, notify):
    try: u = int(uid)
    except: return False
    with _write_lock:
        c = _conn(); cur = c.execute("UPDATE favorites SET notify=? WHERE uid=? AND identifier=? AND source=?", (1 if notify else 0, u, ident, source)); c.commit(); return cur.rowcount > 0
def get_fav_notify(uid, ident, source):
    try: u = int(uid)
    except: return True
    row = _conn().execute("SELECT notify FROM favorites WHERE uid=? AND identifier=? AND source=?", (u, ident, source)).fetchone()
    return bool(row["notify"]) if row else True
def set_fav_last_chapter(uid, ident, source, lch):
    try: u = int(uid)
    except: return
    _execute("UPDATE favorites SET last_chapter=? WHERE uid=? AND identifier=? AND source=?", (lch, u, ident, source))
def cleanup_empty_favorites():
    with _write_lock:
        c = _conn(); cur = c.execute("DELETE FROM fav_settings WHERE uid NOT IN (SELECT DISTINCT uid FROM favorites)"); c.commit(); return cur.rowcount
def count_total_favorites(): return _conn().execute("SELECT COUNT(*) FROM favorites").fetchone()[0]

# ============ Daily Usage ============
def get_daily_usage(uid):
    try: u = int(uid)
    except: return {"last_reset": time.time(), "used": 0, "bonus": 0, "reset_expires": 0, "merge_used": 0, "merge_bonus": 0, "single_reset_at": 0, "merge_reset_at": 0}
    now = time.time(); c = _conn()
    row = c.execute("SELECT * FROM daily_usage WHERE uid=?", (u,)).fetchone()
    if not row:
        _execute("INSERT INTO daily_usage (uid, last_reset, used, bonus, reset_expires, merge_used, merge_bonus, single_reset_at, merge_reset_at) VALUES (?,?,0,0,0,0,0,0,0)", (u, now))
        return {"last_reset": now, "used": 0, "bonus": 0, "reset_expires": 0, "merge_used": 0, "merge_bonus": 0, "single_reset_at": 0, "merge_reset_at": 0}
    if row["reset_expires"] and now >= row["reset_expires"]:
        _execute("UPDATE daily_usage SET last_reset=?, used=0, bonus=0, reset_expires=0, merge_used=0, merge_bonus=0, single_reset_at=0, merge_reset_at=0 WHERE uid=?", (now, u))
        _trigger_notify(u, "both"); row = c.execute("SELECT * FROM daily_usage WHERE uid=?", (u,)).fetchone()
    if row["single_reset_at"] and now >= row["single_reset_at"]:
        base = settings.get("daily_reward_amount", 100)
        new_used = max(0, int(row["used"]) - base)
        _execute("UPDATE daily_usage SET used=?, single_reset_at=0 WHERE uid=?", (new_used, u))
        _trigger_notify(u, "single"); row = c.execute("SELECT * FROM daily_usage WHERE uid=?", (u,)).fetchone()
    if row["merge_reset_at"] and now >= row["merge_reset_at"]:
        mbase = settings.get("merge_daily_limit", 50)
        new_used = max(0, int(row["merge_used"]) - mbase)
        _execute("UPDATE daily_usage SET merge_used=?, merge_reset_at=0 WHERE uid=?", (new_used, u))
        _trigger_notify(u, "merge"); row = c.execute("SELECT * FROM daily_usage WHERE uid=?", (u,)).fetchone()
    if (not row["merge_reset_at"]) and (not row["reset_expires"] or row["reset_expires"] <= now):
        mbase_chk = settings.get("merge_daily_limit", 50); mbonus_chk = int(row["merge_bonus"])
        merge_remaining = (mbase_chk + mbonus_chk) - int(row["merge_used"])
        if mbase_chk > 0 and 0 <= merge_remaining < 2:
            interval = settings.get("daily_reward_interval", 86400)
            _execute("UPDATE daily_usage SET merge_reset_at=? WHERE uid=?", (now + interval, u))
            row = c.execute("SELECT * FROM daily_usage WHERE uid=?", (u,)).fetchone()
    if (not row["single_reset_at"]) and (not row["reset_expires"] or row["reset_expires"] <= now):
        base_chk = settings.get("daily_reward_amount", 100); bonus_chk = int(row["bonus"])
        single_remaining = (base_chk + bonus_chk) - int(row["used"])
        if base_chk > 0 and 0 <= single_remaining < 1:
            interval = settings.get("daily_reward_interval", 86400)
            _execute("UPDATE daily_usage SET single_reset_at=? WHERE uid=?", (now + interval, u))
            row = c.execute("SELECT * FROM daily_usage WHERE uid=?", (u,)).fetchone()
    return {"last_reset": row["last_reset"], "used": row["used"], "bonus": row["bonus"], "reset_expires": row["reset_expires"], "merge_used": row["merge_used"], "merge_bonus": row["merge_bonus"], "single_reset_at": row["single_reset_at"], "merge_reset_at": row["merge_reset_at"]}
def get_user_base(uid):
    rec = get_daily_usage(uid)
    if rec.get("reset_expires", 0) > time.time(): return 0
    return settings.get("daily_reward_amount", 100)
def get_daily_remaining(uid):
    if is_vip(uid): return float("inf")
    rec = get_daily_usage(uid)
    return max(0, (get_user_base(uid) + int(rec.get("bonus", 0))) - int(rec.get("used", 0)))
def add_bonus(uid, amount):
    try: u = int(uid)
    except: return
    get_daily_usage(u); _execute("UPDATE daily_usage SET bonus = bonus + ? WHERE uid=?", (amount, u))
def refund_chapter(uid):
    if is_vip(uid): return
    try: u = int(uid)
    except: return
    get_daily_usage(u); _execute("UPDATE daily_usage SET used = MAX(0, used - 1) WHERE uid=?", (u,))
def try_deduct_chapter(uid, count=1):
    if is_vip(uid): return True, -1
    rec = get_daily_usage(uid)
    base = 0 if rec.get("reset_expires", 0) > time.time() else settings.get("daily_reward_amount", 100)
    bonus = int(rec.get("bonus", 0)); total = base + bonus
    remaining = total - int(rec.get("used", 0))
    if remaining < count: return False, remaining
    new_used = int(rec.get("used", 0)) + count
    if base > 0 and new_used >= base and not rec.get("single_reset_at"):
        interval = settings.get("daily_reward_interval", 86400)
        _execute("UPDATE daily_usage SET used = ?, single_reset_at = ? WHERE uid=?", (new_used, time.time() + interval, int(uid)))
    else:
        _execute("UPDATE daily_usage SET used = ? WHERE uid=?", (new_used, int(uid)))
    return True, remaining - count
def get_merge_base(uid):
    rec = get_daily_usage(uid)
    if rec.get("reset_expires", 0) > time.time(): return 0
    return settings.get("merge_daily_limit", 50)
def get_merge_remaining(uid):
    if is_vip(uid): return float("inf")
    rec = get_daily_usage(uid)
    return max(0, (get_merge_base(uid) + int(rec.get("merge_bonus", 0))) - int(rec.get("merge_used", 0)))
def add_merge_bonus(uid, amount):
    try: u = int(uid)
    except: return
    get_daily_usage(u); _execute("UPDATE daily_usage SET merge_bonus = merge_bonus + ? WHERE uid=?", (amount, u))
def refund_merge(uid, count):
    if is_vip(uid): return
    try: u = int(uid)
    except: return
    get_daily_usage(u); _execute("UPDATE daily_usage SET merge_used = MAX(0, merge_used - ?) WHERE uid=?", (count, u))
def try_deduct_merge(uid, count=1):
    if is_vip(uid): return True, -1
    rec = get_daily_usage(uid)
    mbase = 0 if rec.get("reset_expires", 0) > time.time() else settings.get("merge_daily_limit", 50)
    mbonus = int(rec.get("merge_bonus", 0)); total = mbase + mbonus
    remaining = total - int(rec.get("merge_used", 0))
    if remaining < count: return False, remaining
    new_used = int(rec.get("merge_used", 0)) + count
    new_remaining = total - new_used
    should_start = ((mbase > 0 and new_used >= mbase) or (new_remaining < 2))
    if should_start and not rec.get("merge_reset_at"):
        interval = settings.get("daily_reward_interval", 86400)
        _execute("UPDATE daily_usage SET merge_used = ?, merge_reset_at = ? WHERE uid=?", (new_used, time.time() + interval, int(uid)))
    else:
        _execute("UPDATE daily_usage SET merge_used = ? WHERE uid=?", (new_used, int(uid)))
    return True, new_remaining
def reset_user_balance(uid):
    try: u = int(uid)
    except: return
    interval = settings.get("daily_reward_interval", 86400); now = time.time()
    _execute("""INSERT OR REPLACE INTO daily_usage (uid, last_reset, used, bonus, reset_expires, merge_used, merge_bonus, single_reset_at, merge_reset_at) VALUES (?,?,0,0,?,0,0,0,0)""", (u, now, now + interval))
def reset_all_balances():
    interval = settings.get("daily_reward_interval", 86400); now = time.time()
    with _write_lock:
        c = _conn(); count = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        c.execute("""INSERT OR REPLACE INTO daily_usage (uid, last_reset, used, bonus, reset_expires, merge_used, merge_bonus, single_reset_at, merge_reset_at) SELECT uid, ?, 0, 0, ?, 0, 0, 0, 0 FROM users""", (now, now + interval))
        c.commit(); return count
def get_time_until_reset(uid=None, kind="single"):
    interval = settings.get("daily_reward_interval", 86400); now = time.time()
    if uid:
        rec = get_daily_usage(uid)
        if kind == "single":
            t_target = rec.get("single_reset_at", 0)
            if not t_target or t_target <= now: return 0, 0, 0
        elif kind == "merge":
            t_target = rec.get("merge_reset_at", 0)
            if not t_target or t_target <= now: return 0, 0, 0
        else:
            re_ = rec.get("reset_expires", 0)
            t_target = re_ if (re_ and re_ > now) else (rec.get("last_reset", now) + interval)
        end = t_target
    else: end = now + interval
    delta = max(0, end - now); t = int(delta)
    h, rem = divmod(t, 3600); m, s = divmod(rem, 60); return h, m, s

# ============ VIP ============
def is_vip(uid):
    try: u = int(uid)
    except: return False
    row = _conn().execute("SELECT expires FROM vip_users WHERE uid=?", (u,)).fetchone()
    return bool(row and row["expires"] >= time.time())
def get_vip_info(uid):
    try: u = int(uid)
    except: return None
    row = _conn().execute("SELECT plan, started, expires FROM vip_users WHERE uid=?", (u,)).fetchone()
    return {"plan": row["plan"], "started": row["started"], "expires": row["expires"]} if row else None
def add_vip(uid, plan):
    if plan not in VIP_PLANS: return False
    try: u = int(uid)
    except: return False
    now = time.time()
    existing = _conn().execute("SELECT expires FROM vip_users WHERE uid=?", (u,)).fetchone()
    base = existing["expires"] if existing and existing["expires"] > now else now
    _execute("INSERT OR REPLACE INTO vip_users (uid, plan, started, expires) VALUES (?,?,?,?)", (u, plan, now, base + VIP_PLANS[plan])); return True
def remove_vip(uid):
    try: u = int(uid)
    except: return False
    with _write_lock:
        c = _conn(); cur = c.execute("DELETE FROM vip_users WHERE uid=?", (u,)); c.commit(); return cur.rowcount > 0
def get_all_vips(): return [str(r["uid"]) for r in _conn().execute("SELECT uid FROM vip_users").fetchall()]
def get_expired_vips(): return [r["uid"] for r in _conn().execute("SELECT uid FROM vip_users WHERE expires < ?", (time.time(),)).fetchall()]
def extend_all_vips(seconds):
    now = time.time()
    with _write_lock:
        c = _conn(); users = c.execute("SELECT uid FROM users").fetchall(); count = 0
        for row in users:
            uid = row["uid"]
            existing = c.execute("SELECT expires FROM vip_users WHERE uid=?", (uid,)).fetchone()
            if existing and existing["expires"] > now:
                c.execute("UPDATE vip_users SET expires = expires + ? WHERE uid=?", (seconds, uid))
            else:
                c.execute("INSERT OR REPLACE INTO vip_users (uid, plan, started, expires) VALUES (?,?,?,?)", (uid, "weekly", now, now + seconds))
            count += 1
        c.commit(); return count

# ============ Referrals ============
def already_referred(nid):
    try: n = int(nid)
    except: return None
    row = _conn().execute("SELECT owner_id FROM referrals WHERE referred_id=?", (n,)).fetchone()
    return str(row["owner_id"]) if row else None
def add_referral(oid, nid):
    try: o, n = int(oid), int(nid)
    except: return
    _execute("INSERT OR IGNORE INTO referrals (owner_id, referred_id, ts, rewarded) VALUES (?,?,?,0)", (o, n, time.time()))
def mark_rewarded(oid, nid):
    try: o, n = int(oid), int(nid)
    except: return False
    with _write_lock:
        c = _conn(); cur = c.execute("UPDATE referrals SET rewarded=1 WHERE owner_id=? AND referred_id=? AND rewarded=0", (o, n)); c.commit(); return cur.rowcount > 0
def get_referral_link(uid):
    return f"https://t.me/{BOT_USERNAME}?start=ref_{uid}" if BOT_USERNAME else f"https://t.me/?start=ref_{uid}"

# ============ Bots ============
def add_bot_token(token, name, by, target_id=None):
    if not re.match(r'^\d{8,12}:[A-Za-z0-9_-]{30,50}$', token): return False, "صيغة خاطئة", None
    c = _conn()
    existing = c.execute("SELECT name FROM bots WHERE token=?", (token,)).fetchone()
    if existing: return False, f"موجود: {existing['name']}", None
    bid = token.split(":")[0]
    _execute("""INSERT INTO bots (bid, token, name, target_id, added, added_by, last_sent) VALUES (?,?,?,?,?,?,0)""", (bid, token, name, target_id, time.time(), by))
    return True, "تم", bid
def remove_bot_token(bid):
    with _write_lock:
        c = _conn(); row = c.execute("SELECT * FROM bots WHERE bid=?", (bid,)).fetchone()
        if not row: return False, None
        c.execute("DELETE FROM bots WHERE bid=?", (bid,)); c.commit(); return True, dict(row)
def get_all_bots():
    return {r["bid"]: {"token": r["token"], "name": r["name"], "target_id": r["target_id"], "added": r["added"], "added_by": r["added_by"], "last_sent": r["last_sent"]} for r in _conn().execute("SELECT * FROM bots").fetchall()}
def update_bot_last_sent(bid, ts): _execute("UPDATE bots SET last_sent=? WHERE bid=?", (ts, bid))

# ============ Admins ============
def add_added_admin(uid):
    try: u = int(uid)
    except: return False, "معرّف خاطئ"
    if u in ADMINS: return False, "أدمن أساسي"
    with _write_lock:
        c = _conn()
        if c.execute("SELECT 1 FROM admins WHERE uid=?", (u,)).fetchone(): return False, "موجود"
        c.execute("INSERT INTO admins (uid) VALUES (?)", (u,)); c.commit(); return True, "تم"
def remove_added_admin(uid):
    try: u = int(uid)
    except: return False
    with _write_lock:
        c = _conn(); cur = c.execute("DELETE FROM admins WHERE uid=?", (u,)); c.commit(); return cur.rowcount > 0
def get_all_added_admins(): return [r["uid"] for r in _conn().execute("SELECT uid FROM admins").fetchall()]
def is_added_admin(uid):
    try: u = int(uid)
    except: return False
    return _conn().execute("SELECT 1 FROM admins WHERE uid=?", (u,)).fetchone() is not None
def is_main_admin(uid): return uid in ADMINS
def is_admin_any(uid): return uid in ADMINS or is_added_admin(uid)

# ============ Banned ============
def is_banned(uid):
    try: u = int(uid)
    except: return False
    return _conn().execute("SELECT 1 FROM banned WHERE uid=?", (u,)).fetchone() is not None
def ban_user(uid):
    try: u = int(uid)
    except: return False
    with _write_lock:
        c = _conn()
        if c.execute("SELECT 1 FROM banned WHERE uid=?", (u,)).fetchone(): return False
        c.execute("INSERT INTO banned (uid) VALUES (?)", (u,)); c.commit(); return True
def unban_user(uid):
    try: u = int(uid)
    except: return False
    with _write_lock:
        c = _conn(); cur = c.execute("DELETE FROM banned WHERE uid=?", (u,)); c.commit(); return cur.rowcount > 0
def get_all_banned(): return [r["uid"] for r in _conn().execute("SELECT uid FROM banned").fetchall()]

# ============ Complaints ============
def add_complaint(uid, username, first_name, text):
    try: u = int(uid)
    except: return
    _execute("INSERT INTO complaints (uid, username, first_name, text, ts) VALUES (?,?,?,?,?)", (u, username or "", first_name or "", text, time.time()))
def get_all_complaints():
    return [{"uid": r["uid"], "username": r["username"], "first_name": r["first_name"], "text": r["text"], "ts": r["ts"]} for r in _conn().execute("SELECT * FROM complaints ORDER BY id").fetchall()]
def count_complaints(): return _conn().execute("SELECT COUNT(*) FROM complaints").fetchone()[0]
def clear_complaints():
    with _write_lock:
        c = _conn(); n = c.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]
        c.execute("DELETE FROM complaints"); c.commit(); return n

# ============ Backup ============
def backup_to(target_path):
    if os.path.exists(target_path):
        try: os.remove(target_path)
        except: pass
    src = _conn(); dst = sqlite3.connect(target_path)
    try:
        with dst: src.backup(dst)
    finally: dst.close()
    ok, err = _validate_db_file(target_path)
    if not ok:
        try: os.remove(target_path)
        except: pass
        raise RuntimeError(f"فشل: {err}")
def restore_from(src_path):
    ok, err = _validate_db_file(src_path)
    if not ok: raise RuntimeError(f"غير صالح: {err}")
    if hasattr(_local, "conn"):
        try: _local.conn.close()
        except: pass
        try: del _local.conn
        except: pass
    src = sqlite3.connect(src_path); dst = sqlite3.connect(DB_PATH)
    try:
        with dst: src.backup(dst)
    finally: src.close(); dst.close()
    _conn(); _init_db()

# ============ Gift Links ============
def create_gift_link(single, merge, max_users, expires_at, created_by, mode='auto'):
    code = secrets.token_urlsafe(9).replace("-","").replace("_","")[:10]
    _execute("""INSERT INTO gift_links (code, single_amount, merge_amount, max_users, used_count, created_by, created_at, expires_at, active, post_mode) VALUES (?,?,?,?,0,?,?,?,1,?)""",
             (code, single, merge, max_users, created_by, time.time(), expires_at, mode))
    return code
def get_gift_link(code):
    row = _conn().execute("SELECT * FROM gift_links WHERE code=? AND active=1", (code,)).fetchone()
    return dict(row) if row else None
def get_all_gift_links():
    return [dict(r) for r in _conn().execute("SELECT * FROM gift_links WHERE active=1 ORDER BY created_at DESC").fetchall()]
def delete_gift_link(code):
    with _write_lock:
        c = _conn(); cur = c.execute("UPDATE gift_links SET active=0 WHERE code=?", (code,)); c.commit(); return cur.rowcount > 0
def has_claimed_gift(code, uid):
    return _conn().execute("SELECT 1 FROM gift_claims WHERE code=? AND uid=?", (code, uid)).fetchone() is not None
def set_gift_allowed_users(code, uids):
    _execute("UPDATE gift_links SET allowed_users=? WHERE code=?", (json.dumps(uids) if uids else None, code))
def get_gift_allowed_users(code):
    row = _conn().execute("SELECT allowed_users FROM gift_links WHERE code=?", (code,)).fetchone()
    if not row or not row["allowed_users"]: return []
    try: return json.loads(row["allowed_users"])
    except: return []
def clear_gift_allowed_users(code):
    _execute("UPDATE gift_links SET allowed_users=NULL WHERE code=?", (code,))
def set_gift_channel(code, channel_id):
    _execute("UPDATE gift_links SET channel_id=?, channel_message_id=NULL, next_post_at=0, post_enabled=0 WHERE code=?", (channel_id, code))
def toggle_gift_post(code):
    row = _conn().execute("SELECT post_enabled, channel_id, post_mode FROM gift_links WHERE code=?", (code,)).fetchone()
    if not row: return None
    mode = row["post_mode"] or 'auto'
    if mode == 'auto' and not row["channel_id"]: return None
    new_val = 0 if row["post_enabled"] else 1
    _execute("UPDATE gift_links SET post_enabled=?, next_post_at=0 WHERE code=?", (new_val, code)); return new_val
def set_gift_interval(code, hours):
    _execute("UPDATE gift_links SET post_interval_hours=?, next_post_at=0 WHERE code=?", (hours, code))
def set_gift_post_mode(code, mode):
    if mode not in ('auto', 'manual'): return False
    _execute("UPDATE gift_links SET post_mode=?, next_post_at=0 WHERE code=?", (mode, code)); return True
def claim_gift(code, uid):
    link = get_gift_link(code)
    if not link: return 'not_found', None
    if link.get('allowed_users'):
        try:
            if uid not in json.loads(link['allowed_users']): return 'not_allowed', link
        except: pass
    if has_claimed_gift(code, uid): return 'already', link
    if time.time() > link['expires_at']: return 'expired', link
    if link['used_count'] >= link['max_users']: return 'limit', link
    if link['single_amount'] > 0: add_bonus(uid, link['single_amount'])
    if link['merge_amount'] > 0: add_merge_bonus(uid, link['merge_amount'])
    with _write_lock:
        c = _conn()
        c.execute("INSERT OR IGNORE INTO gift_claims (code, uid, claimed_at) VALUES (?,?,?)", (code, uid, time.time()))
        c.execute("UPDATE gift_links SET used_count = used_count + 1 WHERE code=?", (code,)); c.commit()
    link = get_gift_link(code); return 'ok', link

async def delete_gift_channel_msg(client, channel_id, message_id):
    if not channel_id or not message_id: return
    try: await client.delete_messages(channel_id, message_id)
    except Exception as e:  pass

async def _delayed_gift_delete(client, code, delay=60):
    _execute("UPDATE gift_links SET delete_scheduled_at=? WHERE code=?", (time.time() + delay, code))
    await asyncio.sleep(delay)
    try:
        row = _conn().execute("SELECT channel_id, channel_message_id FROM gift_links WHERE code=?", (code,)).fetchone()
        if not row: return
        if row["channel_message_id"]:
            await delete_gift_channel_msg(client, row["channel_id"], row["channel_message_id"])
            _execute("UPDATE gift_links SET channel_message_id=NULL, delete_scheduled_at=0 WHERE code=?", (code,))
    except Exception as e:  pass

async def publish_gift_now(client, admin_uid, code):
    link = get_gift_link(code)
    if not link: return False, '⚠️ الرابط غير موجود', None
    if link['expires_at'] <= time.time(): return False, '⏰ انتهت الصلاحية', None
    mode = link.get('post_mode') or 'auto'
    old_code = link['code']; old_mid = link.get('channel_message_id'); old_channel = link.get('channel_id')
    new_code = secrets.token_urlsafe(9).replace("-","").replace("_","")[:10]
    _execute("""INSERT INTO gift_links 
        (code, single_amount, merge_amount, max_users, used_count, created_by, created_at, expires_at, active,
         allowed_users, channel_id, channel_message_id, post_enabled, post_interval_hours, next_post_at, post_mode)
        VALUES (?,?,?,?,0,?,?,?,1,?,?,?,?,?,?,?)""",
        (new_code, link['single_amount'], link['merge_amount'], link['max_users'],
         link['created_by'], time.time(), link['expires_at'],
         link.get('allowed_users'), old_channel, None,
         1 if link.get('post_enabled') else 0,
         link.get('post_interval_hours') or 2, 0, mode))
    _execute("DELETE FROM gift_links WHERE code=?", (old_code,))
    _execute("DELETE FROM gift_claims WHERE code=?", (old_code,))
    if old_mid and old_channel:
        try: await client.delete_messages(old_channel, old_mid)
        except: pass
    bot_user = BOT_USERNAME or "bot"
    url = f"https://t.me/{bot_user}?start=gift_{new_code}"
    interval = link.get('post_interval_hours') or 2
    if mode == 'manual':
        try:
            await client.send_message(admin_uid,
                f"🎁 **رابط هدية جديد**\n\n🔗 `{url}`\n\n"
                f"📖 فردي: `{link['single_amount']}`\n🧩 دمج: `{link['merge_amount']}`\n"
                f"👥 حد: `{link['max_users']}`\n"
                f"⏰ ينتهي: `{time.strftime('%Y-%m-%d %H:%M', time.localtime(link['expires_at']))}`\n\n"
                f"💡 انسخ الرابط وانشره:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📤 مشاركة", url=f"https://t.me/share/url?url={quote(url)}&text={quote('🎁 هدية!')}")],
                    [InlineKeyboardButton("⚙️ إدارة", callback_data=f"admin_gift_manage_{new_code}")],
                    [InlineKeyboardButton("❌ إغلاق", callback_data="close_list")]]),
                parse_mode=ParseMode.MARKDOWN)
            return True, None, new_code
        except Exception as e:
            return False, f'فشل: {e}', None
    if not old_channel:
        _execute("DELETE FROM gift_links WHERE code=?", (new_code,))
        return False, '📢 لم تحدد قناة', None
    parts = ["🎁 **هدية فصول مجانية!**\n"]
    if link["single_amount"] > 0: parts.append(f"📖 فصول مفردة: **{link['single_amount']}**")
    if link["merge_amount"] > 0: parts.append(f"🧩 فصول مدمجة: **{link['merge_amount']}**")
    parts.append(f"\n👥 متبقٍ: `{link['max_users']}`")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎁 استلم الآن", url=url)]])
    try:
        m = await client.send_message(old_channel, "\n".join(parts), reply_markup=kb,
                                      parse_mode=ParseMode.MARKDOWN, disable_notification=True)
    except Exception as e:
        pass
        _execute("DELETE FROM gift_links WHERE code=?", (new_code,))
        return False, f'فشل النشر: {e}', None
    _execute("UPDATE gift_links SET channel_message_id=?, next_post_at=? WHERE code=?", (m.id, time.time() + interval * 3600, new_code))
    return True, None, new_code

async def _process_gift_claim(client, cid, uid, code):
    status, link = claim_gift(code, uid)
    if status == 'ok':
        parts = ["🎉 **مبروك! حصلت على هدية**\n\n"]
        if link['single_amount'] > 0: parts.append(f"📖 فصول مفردة: +`{link['single_amount']}`\n")
        if link['merge_amount'] > 0: parts.append(f"🧩 فصول مدمجة: +`{link['merge_amount']}`\n")
        await client.send_message(cid, "".join(parts), parse_mode=ParseMode.MARKDOWN)
        admin_id = link.get('created_by')
        if admin_id:
            try:
                u = await client.get_chat(uid); uname = f"@{u.username}" if u.username else (u.first_name or str(uid))
                await client.send_message(admin_id,
                    f"🔔 **دخل شخص عبر رابط الهدية**\n\n🔗 `{link['code']}`\n👤 {uname} (`{uid}`)\n"
                    f"📊 `{link['used_count']}/{link['max_users']}`",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ إدارة", callback_data=f"admin_gift_manage_{link['code']}")]]),
                    parse_mode=ParseMode.MARKDOWN)
            except: pass
        if link['used_count'] >= link['max_users'] and link.get('channel_message_id'):
            asyncio.create_task(_delayed_gift_delete(client, code, 60))
    elif status == 'not_found': await client.send_message(cid, "❌ **رابط غير موجود أو محذوف**", parse_mode=ParseMode.MARKDOWN)
    elif status == 'not_allowed': await client.send_message(cid, "🔒 **مخصص لمستخدمين معينين**", parse_mode=ParseMode.MARKDOWN)
    elif status == 'expired':
        await client.send_message(cid, "⏰ **انتهت مدة الرابط، اسف**", parse_mode=ParseMode.MARKDOWN)
        if link and link.get('channel_message_id'): asyncio.create_task(_delayed_gift_delete(client, code, 60))
    elif status == 'limit':
        await client.send_message(cid, "⚠️ **وصل للحد الأقصى، اسف**", parse_mode=ParseMode.MARKDOWN)
        if link and link.get('channel_message_id'): asyncio.create_task(_delayed_gift_delete(client, code, 60))
    elif status == 'already': await client.send_message(cid, "ℹ️ **استلمت من هذا الرابط مسبقاً**", parse_mode=ParseMode.MARKDOWN)

# ============ أدوات ============
def clean_url(s):
    if not s: return s
    return re.sub(r'\s+','',s).replace('\\','')
def sort_urls_by_number(urls):
    def k(u_):
        fn=u_.split("?")[0].rstrip("/").split("/")[-1]; m=re.search(r'(\d+)',fn); return int(m.group(1)) if m else 999999999
    seen=set(); uniq=[]
    for u in urls:
        if u not in seen: seen.add(u); uniq.append(u)
    uniq.sort(key=k); return uniq
def clean_manga_title(title,identifier):
    if not title: return identifier.replace("-"," ").title()
    t=title.strip()
    if t.lower() in ["access denied", "just a moment...", "attention required!", "forbidden", "404 not found", "غير معروف", "lava scans", "lavascans"]:
        return identifier.replace("-"," ").title()
    t=re.sub(r'^\s*مانجا\s+','',t); t=re.sub(r'^\s*مانها\s+','',t); t=re.sub(r'^\s*مانهوا\s+','',t)
    t=re.sub(r'\s+مترجمة\s*$','',t); t=re.sub(r'\s+مترجم\s*$','',t)
    for p in [r'مانجا\s*(?:اون|ون)\s*لاين',r'(?:اون|ون)\s*لاين',r'اونلاين',r'ونلاين',r'Team-?[Xx]',r'تيم\s*اكس',r'غير معروف', r'lava\s*scans']:
        t=re.sub(r'\s*[-|•]\s*'+p+r'.*$','',t,flags=re.I).strip(); t=re.sub(p,'',t,flags=re.I).strip()
    t=re.sub(r'^[\s\-|:•]+','',t); t=re.sub(r'[\s\-|:•]+$','',t)
    return t.strip() or identifier.replace("-"," ").title()
def make_quote(text):
    if not text: return text
    out=[]
    for line in text.split("\n"):
        s=line.rstrip()
        if not s: out.append(""); continue
        if s.startswith(">"): out.append(s)
        else: out.append(f"> {s}")
    return "\n".join(out)
def build_caption(template_key,**kwargs):
    try:
        template=settings.get(template_key,"")
        kwargs.update({"date":time.strftime("%Y-%m-%d"),"time":time.strftime("%H:%M")})
        return template.format(**kwargs)
    except Exception as e: return ""
def _chapter_tracking_value(chapter):
    if not isinstance(chapter, dict):
        return str(chapter or "")
    # Keep title/number first to remain compatible with checkpoints saved by older bot versions.
    return str(
        chapter.get("title")
        or chapter.get("number")
        or chapter.get("chapter_number")
        or chapter.get("id")
        or chapter.get("url")
        or ""
    )

def _chapter_display_value(chapter):
    if not isinstance(chapter, dict):
        return str(chapter or "فصل جديد")
    return str(
        chapter.get("title")
        or chapter.get("number")
        or chapter.get("chapter_number")
        or chapter.get("name")
        or "فصل جديد"
    )

def get_latest_chapter_info(source, ident, murl):
    """Read the newest chapter from the active Manga Engine source adapter."""
    api = get_source(source)
    info = api.get_details(murl or ident)
    chapters = (info or {}).get("chapters") or []
    return _chapter_tracking_value(chapters[0]) if chapters else "0"

def get_latest_chapter_number(source, ident, murl):
    api = get_source(source)
    info = api.get_details(murl or ident)
    chapters = (info or {}).get("chapters") or []
    if not chapters:
        return 0
    display = _chapter_display_value(chapters[0])
    match = re.search(r"(\d+(?:\.\d+)?)", display)
    return float(match.group(1)) if match else 0

_notify_callback = None
def set_notify_callback(cb):
    global _notify_callback; _notify_callback = cb
def _trigger_notify(uid, kind="both"):
    if not _notify_callback: return
    try: asyncio.get_running_loop().create_task(_notify_callback(uid, kind))
    except RuntimeError: pass
async def _send_renewal_notify(uid, kind="both"):
    try:
        parts = ["🎁 **تم تجديد رصيدك!**\n\n"]
        if kind in ("single", "both"): parts.append(f"📖 فصول مفردة: `{settings.get('daily_reward_amount',100)}`\n")
        if kind in ("merge", "both"): parts.append(f"🧩 فصول مدمجة: `{settings.get('merge_daily_limit',50)}`\n")
        if len(parts) > 1: await app.send_message(uid, "".join(parts), parse_mode=ParseMode.MARKDOWN)
    except: pass
set_notify_callback(_send_renewal_notify)

# تم حذف محرك تحويل الصور وواجهات PDF الخارجية.

# ============ المصادر ============
def create_chapters_markup(chs,page=0,ident=None,src="mangalik",uid=None):
    # Always expose the complete chapter list, including when opened from latest updates.
    latest_mode = bool(uid is not None and user_data.get(uid,{}).get("latest_mode"))
    per = 10
    total = max(1, math.ceil(len(chs) / per))
    page = max(0, min(int(page or 0), total - 1))
    s = page * per
    cur = chs[s:s + per]

    kb, row = [], []
    src_short = source_code(src)
    for i, ch in enumerate(cur):
        idx = s + i
        d = str(ch.get("display_text") or ch.get("number") or ch.get("num_str") or ch.get("title") or "?")[:12]
        row.append(InlineKeyboardButton(f"📖 {d}", callback_data=f"ch_{src_short}_{idx}"))
        if len(row) == 4:
            kb.append(row)
            row = []
    if row:
        kb.append(row)

    # Navigation is available in every mode: previous/next and first/last.
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"pg_{src_short}_{page-1}"))
    if page < total - 1:
        nav.append(InlineKeyboardButton("التالي ➡️", callback_data=f"pg_{src_short}_{page+1}"))
    if nav:
        kb.append(nav)

    ends = []
    if page > 0:
        ends.append(InlineKeyboardButton("⏮ أول فصل", callback_data=f"f_{src_short}"))
    if page < total - 1:
        ends.append(InlineKeyboardButton("آخر فصل ⏭", callback_data=f"l_{src_short}"))
    if ends:
        kb.append(ends)

    if uid is not None and is_vip(uid):
        if is_favorite(uid, ident, src):
            kb.append([InlineKeyboardButton("🗑️ إزالة من المفضلة", callback_data=f"fav_remove_{src_short}")])
            kb.append([InlineKeyboardButton("🔔 الإشعارات مفعلة" if get_fav_notify(uid, ident, src) else "🔕 الإشعارات معطلة", callback_data=f"toggle_notify_{src_short}")])
        else:
            kb.append([InlineKeyboardButton("⭐ إضافة للمفضلة", callback_data=f"fav_add_{src_short}")])

    kb.append([InlineKeyboardButton("🧩 دمج الفصول", callback_data=f"mrg_{src_short}")])
    if ident and BOT_USERNAME:
        kb.append([InlineKeyboardButton("🔗 مشاركة المانجا", callback_data=f"share_manga_{src_short}")])
    if latest_mode:
        latest_source = str(user_data.get(uid, {}).get("latest_source_id") or src)
        kb.append([InlineKeyboardButton("⬅️ مصادر أحدث الفصول", callback_data=f"latest_src_{latest_source}")])
        kb.append([InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="latest_home")])
    kb.append([InlineKeyboardButton("🔄 تحديث", callback_data=f"rf_{src_short}"), InlineKeyboardButton("❌ إغلاق", callback_data="close_list")])
    return InlineKeyboardMarkup(kb), page, total

def pack_share_url(url):
    raw = zlib.compress(str(url).encode("utf-8"), 9)
    return "z" + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

def unpack_share_url(token):
    if str(token).startswith("z"):
        value = str(token)[1:]
        value += "=" * (-len(value) % 4)
        try:
            return zlib.decompress(base64.urlsafe_b64decode(value.encode("ascii"))).decode("utf-8")
        except Exception:
            pass
    return unquote(str(token))

def create_manga_share_code(source, identifier):
    """Create a compact, persistent deep-link code for sharing one manga."""
    for _ in range(8):
        code = secrets.token_urlsafe(6).rstrip("=")
        try:
            _execute(
                "INSERT INTO manga_share_links (code, source, identifier, created_at) VALUES (?, ?, ?, ?)",
                (code, str(source), str(identifier), time.time())
            )
            return code
        except sqlite3.IntegrityError:
            continue
    raise RuntimeError("تعذر إنشاء رابط مشاركة قصير")

def get_manga_share(code):
    row = _execute(
        "SELECT source, identifier FROM manga_share_links WHERE code=?",
        (str(code),)
    ).fetchone()
    return dict(row) if row else None

def create_fav_list_markup(uid):
    favs=get_favorites(uid); n=is_notifications_enabled(uid)
    tt="🔔 الإشعارات مفعلة" if n else "🔕 الإشعارات معطلة"
    if not favs:
        return InlineKeyboardMarkup([[InlineKeyboardButton(tt,callback_data="toggle_notifications"), InlineKeyboardButton("❌ إغلاق",callback_data="close_list")]]),"مفعلة" if n else "معطلة",0
    kb=[]
    for i, f in enumerate(favs):
        kb.append([InlineKeyboardButton(f"📖 {clean_manga_title(f.get('title',''),f.get('identifier',''))[:35]}",callback_data=f"fav_open_{i}")])
    kb.append([InlineKeyboardButton(tt,callback_data="toggle_notifications"), InlineKeyboardButton("❌ إغلاق",callback_data="close_list")])
    return InlineKeyboardMarkup(kb),"مفعلة" if n else "معطلة",len(favs)

async def download_image_bytesio(url,referer=None):
    if not url: return None
    url=clean_url(url)
    base_h={"User-Agent":"Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 Chrome/139.0.0.0 Mobile Safari/537.36", "Accept":"image/avif,image/webp,image/apng,image/*,*/*;q=0.8"}
    for ref in [referer,None]:
        hh=dict(base_h)
        if ref: hh["Referer"]=ref
        try:
            async with aiohttp.ClientSession(headers=hh) as s:
                async with s.get(url,timeout=15,allow_redirects=True) as r:
                    if r.status!=200: continue
                    d=await r.read()
                    if d and len(d)>=200: return io.BytesIO(d)
        except: pass
    try:
        cs=cloudscraper.create_scraper(); hd=dict(base_h)
        if referer: hd["Referer"]=referer
        cs.headers.update(hd)
        r=cs.get(url,timeout=20,allow_redirects=True)
        if r.status_code==200 and len(r.content)>=200: return io.BytesIO(r.content)
    except: pass
    return None

async def send_cover_message(msg,cover,text,markup,referer=None):
    if cover:
        for rf in [referer,None]:
            try:
                cb=await download_image_bytesio(cover,referer=rf)
                if cb: return await msg.reply_photo(photo=cb,caption=text,reply_markup=markup,parse_mode=ParseMode.MARKDOWN)
            except: pass
    return await msg.reply_text(text,reply_markup=markup,parse_mode=ParseMode.MARKDOWN)

async def safe_edit_fresh_text(client, msg, chat_id, text, markup=None):
    """Show a text-only screen; never leave an old manga cover behind a list."""
    if msg.photo or msg.video or msg.document or msg.animation:
        try:
            await msg.delete()
        except Exception:
            pass
        return await client.send_message(chat_id=chat_id, text=text, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
    return await safe_edit(msg, text, markup)


async def safe_edit(msg,text,markup=None):
    if msg.photo or msg.video or msg.document or msg.animation:
        try: return await msg.edit_caption(caption=text,reply_markup=markup,parse_mode=ParseMode.MARKDOWN)
        except: pass
    try: return await msg.edit_text(text=text,reply_markup=markup,parse_mode=ParseMode.MARKDOWN)
    except: pass
    try: await msg.delete()
    except: pass
    try: return await msg.reply_text(text=text,reply_markup=markup,parse_mode=ParseMode.MARKDOWN)
    except: return None

async def is_user_subscribed(client,uid):
    if uid in OWNER_IDS: return True,None
    chs=settings.get("force_sub_channels",[])
    if not chs: return True,None
    unsub=[]
    for ch in chs:
        try:
            m=await client.get_chat_member(chat_id=ch,user_id=uid)
            if m.status in [ChatMemberStatus.LEFT,ChatMemberStatus.KICKED]: unsub.append(ch)
        except Exception as e:
            if "user_not_participant" in str(e).lower(): unsub.append(ch)
    return (len(unsub)==0),(unsub if unsub else None)

async def send_subscription_prompt(client,uid,cid,pending=None):
    chs=settings.get("force_sub_channels",[]); text=settings.get("force_sub_message","⚠️ اشترك أولاً.")
    img=settings.get("force_sub_image"); bc=settings.get("force_sub_buttons",{})
    kb=[]
    for ch in chs:
        kb.append([InlineKeyboardButton(bc.get(ch) or f"📢 اشترك في {ch}", url=f"https://t.me/{ch[1:]}" if ch.startswith("@") else f"https://t.me/c/{str(ch).replace('-100','')}")])
    if pending: user_data[uid]={'pending_action':pending}
    kb.append([InlineKeyboardButton("✅ تحقق من الاشتراك",callback_data="check_sub")])
    markup=InlineKeyboardMarkup(kb)
    if img:
        try: await client.send_photo(chat_id=cid,photo=img,caption=text,reply_markup=markup,parse_mode=ParseMode.MARKDOWN); return
        except: pass
    await client.send_message(chat_id=cid,text=text,reply_markup=markup,parse_mode=ParseMode.MARKDOWN)

async def check_subscription_and_continue(client,cb,pending=None):
    uid=cb.from_user.id; cid=cb.message.chat.id; msg=cb.message
    is_sub,_=await is_user_subscribed(client,uid)
    if is_sub:
        await cb.answer("✅ تم التحقق!")
        try: await msg.delete()
        except: pass
        await _try_reward_referral(client,uid)
        if pending:
            at=pending.get('type')
            class FM:
                """Small Bot-API message facade for replaying a pending command."""
                def __init__(s, c, ci, ui, t=""):
                    s.chat = type("C", (), {"id": ci, "type": "private"})()
                    s.from_user = type(
                        "U", (),
                        {"id": ui, "username": None, "first_name": "", "last_name": ""},
                    )()
                    s.text = t
                    s.message_id = 0
                    s.reply_to_message = None

                async def reply_text(s, t, *a, **k):
                    return await client.send_message(s.chat.id, t, *a, **k)
            fm=FM(client,cid,uid,"")
            if at=='search': fm.text=f"/search {pending.get('query','')}"; await search_cmd(client,fm)
            elif at=='check': await check_cmd(client,fm)
            elif at=='start':
                if pending.get('gift_code'): await _process_gift_claim(client, cid, uid, pending['gift_code'])
                if pending.get('show_data'):
                    sd = pending['show_data']
                    await _show_manga_by_deeplink(client, cid, uid, sd['src'], sd['ident'])
                fm.text=""; await start_cmd(client,fm)
    else:
        await cb.answer("⚠️ اشترك في جميع القنوات أولاً",show_alert=True)
        await send_subscription_prompt(client,uid,cid,pending)

app=make_legacy_app(BOT_TOKEN)

async def _send_shared_manga_card(client, cid, info, caption, markup):
    """Send the shared manga cover when available, with URL and downloaded-file fallbacks."""
    cover = _extract_cover_url(info)
    if not cover:
        return await client.send_message(
            cid, caption, reply_markup=markup, parse_mode=ParseMode.MARKDOWN
        )
    cover = urljoin(str(info.get("url") or ""), cover)
    # First let Telegram fetch the image directly; this is fastest for public image URLs.
    try:
        return await client.send_photo(
            chat_id=cid, photo=cover, caption=caption,
            reply_markup=markup, parse_mode=ParseMode.MARKDOWN
        )
    except Exception as direct_error:
        pass
    # Some manga CDNs block Telegram's fetcher. Download with browser-like headers instead.
    try:
        timeout = aiohttp.ClientTimeout(total=25, connect=10)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
            "Referer": str(info.get("url") or ""),
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(cover, allow_redirects=True) as response:
                if response.status == 200:
                    data = await response.read()
                    content_type = response.headers.get("Content-Type", "").lower()
                    is_image = content_type.startswith("image/") or data.startswith(
                        (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a", b"RIFF")
                    )
                    if data and len(data) > 100 and is_image:
                        photo = io.BytesIO(data)
                        photo.name = "manga_cover.jpg"
                        photo.seek(0)
                        return await client.send_photo(
                            chat_id=cid, photo=photo, caption=caption,
                            reply_markup=markup, parse_mode=ParseMode.MARKDOWN
                        )
                else:
                    pass
    except Exception as exc:
        pass
    # Keep the manga usable even if its source has no accessible cover.
    return await client.send_message(
        cid, caption, reply_markup=markup, parse_mode=ParseMode.MARKDOWN
    )

async def _show_manga_by_deeplink(client, cid, uid, src_short, ident):
    src = source_from_code(src_short)
    if not src:
        await client.send_message(cid, "⚠️ هذا المصدر لم يعد متاحاً.")
        return
    try:
        api = await asyncio.to_thread(get_source, src)
        manga_url = str(ident)
        info = await asyncio.to_thread(api.get_details, manga_url)
        if not info:
            await client.send_message(cid, "❌ تعذر جلب معلومات المانجا."); return
        chapters = list(reversed(info.get("chapters", [])))
        if not chapters:
            await client.send_message(cid, "❌ لا توجد فصول."); return
        title = clean_manga_title(info.get("name") or info.get("title") or "Manga", manga_url)
        async def pdf(ch, progress=None):
            urls = await asyncio.to_thread(api.get_chapter_images, ch)
            if progress:
                await progress("extract", len(urls))
            result = await download_images_parallel(urls, client=client)
            if progress:
                await progress("pdf", len(urls))
            return result
        cover_url = _extract_cover_url(info)
        if cover_url:
            cover_url = urljoin(str(info.get("url") or manga_url), cover_url)
        user_data[uid] = {"chapters": chapters, "title": title, "identifier": info.get("id") or manga_url,
            "page": 0, "source": src, "create_pdf_func": pdf, "manga_url": manga_url,
            "cover_url": cover_url, "genres": info.get("genres", []), "kind": info.get("kind", "")}
        cap = f"**{title}**\n\n{(info.get('description') or '')[:300]}\n\n📖 **{len(chapters)} فصل**"
        user_data[uid]["base_caption"] = cap
        markup,_,_ = create_chapters_markup(chapters, 0, user_data[uid]["identifier"], src, uid)
        await _send_shared_manga_card(client, cid, info, cap, markup)
    except Exception as e:
        await client.send_message(cid, f"❌ تعذر فتح المانجا: {str(e)[:180]}")

async def send_message_with_image(client,cid,text,key,markup=None):
    img=settings.get(key)
    if img:
        try: return await client.send_photo(chat_id=cid,photo=img,caption=text, reply_markup=markup,parse_mode=ParseMode.MARKDOWN)
        except: pass
    return await client.send_message(chat_id=cid,text=text,reply_markup=markup,parse_mode=ParseMode.MARKDOWN)

async def build_main_keyboard(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 بحث عن مانجا", callback_data="main_search")],
        [InlineKeyboardButton("👤 حسابي", callback_data="my_account"), InlineKeyboardButton("🔥 أحدث المانجا", callback_data="latest_manga_list")],
        [InlineKeyboardButton("🏷️ التصنيفات", callback_data="main_categories"), InlineKeyboardButton("❓ مساعدة", callback_data="help_full")],
        [InlineKeyboardButton("⭐ مفضلاتي", callback_data="fav_list")],
        [InlineKeyboardButton("📩 تقديم شكوى", callback_data="complaint_start")],
    ])

def _account_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 رصيدي",callback_data="acc_chapters"), InlineKeyboardButton("🔗 مشاركة",callback_data="acc_share")],
        [InlineKeyboardButton("⏰ وقت التجديد",callback_data="acc_daily_timer"), InlineKeyboardButton("👑 ترقية VIP",callback_data="acc_upgrade")],
        [InlineKeyboardButton("💎 تفاصيل VIP",callback_data="acc_vip_details"), InlineKeyboardButton("🔄 تحديث",callback_data="my_account_refresh")],
        [InlineKeyboardButton("❌ إغلاق",callback_data="close_list")],
    ])

async def _show_my_account(client,msg,uid,edit=False):
    if is_vip(uid): type_line="👑 **عضو VIP** — تحميل غير محدود"
    else: type_line=f"👤 **عضو عادي**\n📖 فردي: `{int(get_daily_remaining(uid))}`\n🧩 دمج: `{int(get_merge_remaining(uid))}`"
    joined=time.strftime("%Y-%m-%d",time.localtime(get_user_joined(uid)))
    try:
        u=await client.get_chat(uid); un=f"@{u.username}" if u.username else "—"
    except: un="—"
    text=(f"👤 **حسابي**\n\n{type_line}\n\n🆔 **المعرّف:** `{uid}`\n📝 **اليوزر:** {un}\n"
          f"📅 **مسجل:** `{joined}`\n⬇️ **التحميلات:** `{get_user_downloads(uid)}`")
    if edit: await safe_edit(msg, text, _account_keyboard())
    else:
        try: await msg.delete()
        except: pass
        await msg.reply_text(text,reply_markup=_account_keyboard(),parse_mode=ParseMode.MARKDOWN)

async def _show_chapters_balance(client,msg,uid):
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إغلاق",callback_data="close_list")]])
    if is_vip(uid):
        info=get_vip_info(uid); days=max(0,int((info["expires"]-time.time())//86400))
        await msg.reply_text(f"📊 **رصيد الفصول**\n\n👑 **أنت VIP!**\n\n📅 {VIP_PLAN_NAMES.get(info['plan'],'?')}\n⏳ {days} يوم\n\n✨ تحميل غير محدود", reply_markup=kb,parse_mode=ParseMode.MARKDOWN); return
    rec=get_daily_usage(uid); base=get_user_base(uid); bonus=int(rec.get("bonus",0))
    used=int(rec.get("used",0)); total=base+bonus; rem=max(0,total-used)
    mbase=get_merge_base(uid); mbonus=int(rec.get("merge_bonus",0)); mused=int(rec.get("merge_used",0))
    mtotal=mbase+mbonus; mrem=max(0,mtotal-mused)
    single_note=""; merge_note=""; forced_note=""
    if rec.get("single_reset_at", 0) > time.time():
        h,m,s=get_time_until_reset(uid, "single"); single_note=f"\n⏰ تجديد: `{h:02d}:{m:02d}:{s:02d}`"
    if rec.get("merge_reset_at", 0) > time.time():
        h,m,s=get_time_until_reset(uid, "merge"); merge_note=f"\n⏰ تجديد: `{h:02d}:{m:02d}:{s:02d}`"
    if rec.get("reset_expires", 0) > time.time():
        h,m,s=get_time_until_reset(uid, "forced"); forced_note=f"\n⚡ تصفير: `{h:02d}:{m:02d}:{s:02d}`"
    pct=int((rem/total)*10) if total>0 else 0; bar="█"*pct+"░"*(10-pct)
    mpct=int((mrem/mtotal)*10) if mtotal>0 else 0; mbar="█"*mpct+"░"*(10-mpct)
    await msg.reply_text(
        f"📊 **رصيدي**\n\n"
        f"📖 **فردي**\n├ 🎯 `{base}`\n├ 🎁 `{bonus}`\n├ 📦 `{total}`\n├ ✅ `{used}`\n└ 🔋 **`{rem}`**\n`[{bar}]`{single_note}\n\n"
        f"🧩 **دمج**\n├ 🎯 `{mbase}`\n├ 🎁 `{mbonus}`\n├ 📦 `{mtotal}`\n├ ✅ `{mused}`\n└ 🔋 **`{mrem}`**\n`[{mbar}]`{merge_note}{forced_note}",
        reply_markup=kb,parse_mode=ParseMode.MARKDOWN)

async def _show_share_link(client,msg,uid):
    link=get_referral_link(uid)
    text=(f"🔗 **مشاركة البوت**\n\nاحصل على مكافآت لكل صديق:\n\n"
          f"📖 فردي: +`{settings.get('referral_bonus_single',50)}`\n"
          f"🧩 دمج: +`{settings.get('referral_bonus_merge',20)}`\n\n"
          f"**رابطك:**\n`{link}`")
    kb=InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 مشاركة",url=f"https://t.me/share/url?url={quote(link)}&text={quote('🎁 جرب هذا البوت!')}")],
        [InlineKeyboardButton("❌ إغلاق",callback_data="close_list")]])
    await msg.reply_text(text,reply_markup=kb,parse_mode=ParseMode.MARKDOWN)

async def _show_vip_upgrade(client,msg):
    au=None
    try: o=await client.get_chat(OWNER_ID); au=o.username
    except: pass
    cu=f"https://t.me/{au}" if au else f"tg://user?id={OWNER_ID}"
    second=settings.get("vip_contact_second"); cu2=f"https://t.me/{str(second)[1:]}" if second and str(second).startswith("@") else None
    rows=[[InlineKeyboardButton("👤 تواصل مع الأدمن",url=cu)]]
    if cu2: rows.append([InlineKeyboardButton("👥 تواصل بديل",url=cu2)])
    rows.append([InlineKeyboardButton("❌ إغلاق",callback_data="close_list")])
    await msg.reply_text(
        f"👑 **ترقية VIP**\n\n"
        f"✨ **المميزات:**\n"
        f"├ ♾️ تحميل غير محدود\n"
        f"├ ⭐ المفضلة\n"
        f"├ 🧩 دمج غير محدود\n"
        f"└ ⚡ أولوية في الدعم\n\n"
        f"💰 أسبوعي / شهري / سنوي\n\n"
        f"💬 تواصل:",
        reply_markup=InlineKeyboardMarkup(rows),parse_mode=ParseMode.MARKDOWN)

async def _show_vip_details(client,msg,uid):
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إغلاق",callback_data="close_list")]])
    if is_vip(uid):
        info=get_vip_info(uid); days=max(0,int((info["expires"]-time.time())//86400))
        exp=time.strftime("%Y-%m-%d %H:%M",time.localtime(info["expires"]))
        await msg.reply_text(f"💎 **تفاصيل VIP**\n\n✅ **أنت VIP**\n\n📅 {VIP_PLAN_NAMES.get(info['plan'],'?')}\n⏳ {days} يوم\n📆 `{exp}`", reply_markup=kb,parse_mode=ParseMode.MARKDOWN)
    else: await msg.reply_text("💎 **VIP**\n\n❌ لست VIP\n\n💡 يمكنك الترقية", reply_markup=kb,parse_mode=ParseMode.MARKDOWN)

async def _show_daily_timer(client,msg,uid):
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إغلاق",callback_data="close_list")]])
    if is_vip(uid): await msg.reply_text("⏰ **VIP — بلا انتظار**",reply_markup=kb,parse_mode=ParseMode.MARKDOWN); return
    rec=get_daily_usage(uid); base=get_user_base(uid); bonus=int(rec.get("bonus",0))
    rem=max(0,(base+bonus)-int(rec.get("used",0)))
    mbase=get_merge_base(uid); mbonus=int(rec.get("merge_bonus",0)); mrem=max(0,(mbase+mbonus)-int(rec.get("merge_used",0)))
    if rec.get("single_reset_at",0)>time.time(): h,m,s=get_time_until_reset(uid,"single"); single_timer=f"⏳ `{h:02d}:{m:02d}:{s:02d}`"
    else: single_timer="✅ جاهز"
    if rec.get("merge_reset_at",0)>time.time(): h,m,s=get_time_until_reset(uid,"merge"); merge_timer=f"⏳ `{h:02d}:{m:02d}:{s:02d}`"
    else: merge_timer="✅ جاهز"
    await msg.reply_text(
        f"⏰ **الوقت**\n\n"
        f"📖 **فردي**\n├ 🔋 `{rem}`\n└ {single_timer}\n\n"
        f"🧩 **دمج**\n├ 🔋 `{mrem}`\n└ {merge_timer}\n\n"
        f"⏱️ مدة التجديد: `{settings.get('daily_reward_interval',86400)//3600}` ساعة",
        reply_markup=kb,parse_mode=ParseMode.MARKDOWN)

def create_backup_with_custom_token(tk,bn):
    ts=datetime.now().strftime("%Y%m%d_%H%M%S"); safe=re.sub(r'[^A-Za-z0-9_-]','_',bn)[:30]
    zn=f"bot_{safe}_{ts}.zip"; zp=os.path.join(BACKUP_DIR,zn); tmp_db=zp+".db"
    backup_to(tmp_db)
    cfg={"bot_token":tk,"bot_name":bn,"admins":ADMINS,"owner_ids":OWNER_IDS,"backup_date":ts}
    install='#!/usr/bin/env python3\nimport os, shutil\nBASE=os.path.dirname(os.path.abspath(__file__))\nd=os.path.join(BASE,"data")\nif os.path.isdir(d):\n    for f in os.listdir(d): shutil.copy2(os.path.join(d,f),os.path.join(os.getcwd(),f))\n'
    with zipfile.ZipFile(zp,'w',zipfile.ZIP_DEFLATED) as z:
        z.write(tmp_db, "data/bot.db")
        z.writestr("config/bot_config.json",json.dumps(cfg,ensure_ascii=False,indent=2))
        z.writestr("install.py",install)
    try: os.remove(tmp_db)
    except: pass
    return zp,zn

def restore_from_zip(zp):
    global settings
    try:
        with zipfile.ZipFile(zp,'r') as z:
            if "data/bot.db" not in z.namelist(): return False,[],"❌ ZIP لا يحتوي data/bot.db"
            tmp=tempfile.mktemp(suffix=".db")
            with open(tmp,'wb') as f: f.write(z.read("data/bot.db"))
            ok, err = _validate_db_file(tmp)
            if not ok:
                try: os.remove(tmp)
                except: pass
                return False,[],f"❌ bot.db غير صالح: {err}"
            restore_from(tmp)
            try: os.remove(tmp)
            except: pass
            new_s=load_settings(); settings.clear(); settings.update(new_s); return True,["bot.db"],None
    except Exception as e: return False,[],f"❌ {e}"

def cleanup_old_backups(keep=10):
    try:
        fs=sorted([f for f in os.listdir(BACKUP_DIR) if f.endswith(".zip")], key=lambda x: os.path.getmtime(os.path.join(BACKUP_DIR,x)),reverse=True)
        for o in fs[keep:]: os.remove(os.path.join(BACKUP_DIR,o))
    except: pass

async def send_zip_via_added_bots(manual=False):
    bots=get_all_bots()
    if not bots: return 0,0,"🤖 **لا توجد بوتات نسخ مسجلة حالياً.**\n\nيمكنك إضافة بوت جديد من زر الإضافة."
    title="يدوية" if manual else "تلقائية"; success=failed=0
    for bid,info in list(bots.items()):
        try:
            token=info.get("token"); target_id=info.get("target_id"); name=info.get("name","?")
            if not token or not target_id: failed+=1; continue
            zp,zn=create_backup_with_custom_token(token,name); sz=os.path.getsize(zp)/1024
            cap=(f"💾 **{title} - {name}**\n\n📅 `{time.strftime('%Y-%m-%d %H:%M')}`\n👥 `{get_users_count()}`\n👑 VIP: `{len(get_all_vips())}`\n📥 `{get_download_count()}`\n📦 `{sz:.1f} KB`")
            temp_bot=create_bot(token)
            try:
                await temp_bot.send_document(chat_id=target_id,document=as_input_file(zp, filename=zn),caption=cap)
                success+=1
                if not manual: update_bot_last_sent(bid, time.time())
            except Exception:
                failed+=1
            finally:
                try: await temp_bot.session.close()
                except: pass
            try: os.remove(zp)
            except: pass
        except: failed+=1
    cleanup_old_backups(); return success,failed,None

async def auto_backup_task():
    await asyncio.sleep(60)
    while True:
        try:
            bots=get_all_bots()
            if not bots: await asyncio.sleep(3600); continue
            now=time.time(); need=any((now-info.get("last_sent",0))>=BACKUP_INTERVAL for info in bots.values())
            if need: await send_zip_via_added_bots(manual=False)
        except: pass
        await asyncio.sleep(600)

async def latest_manga_refresh_task():
    global latest_manga_cache
    while True:
        try:
            fresh_latest = await asyncio.to_thread(get_all_latest)
            # Keep the last good cache if the API temporarily returns an empty/failed result.
            if fresh_latest:
                latest_manga_cache = fresh_latest
                pass
            else:
                pass
        except Exception as e:
            pass
        await asyncio.sleep(CHECK_INTERVAL)

async def gift_channel_publisher_task():
    await asyncio.sleep(90)
    while True:
        try:
            rows = _conn().execute("SELECT * FROM gift_links WHERE active=1 AND post_enabled=1 AND post_mode='auto' AND channel_id IS NOT NULL").fetchall()
            now = time.time()
            for row in rows:
                link = dict(row); code = link['code']
                if link['expires_at'] <= now:
                    sched = link.get('delete_scheduled_at', 0) or 0
                    if sched > now: continue
                    if link.get('channel_message_id'):
                        await delete_gift_channel_msg(app, link['channel_id'], link['channel_message_id'])
                    _execute("UPDATE gift_links SET channel_message_id=NULL, post_enabled=0, delete_scheduled_at=0 WHERE code=?", (code,))
                    continue
                if link['next_post_at'] <= now:
                    ok, err, new_code = await publish_gift_now(app, link['created_by'], code)
                    if not ok:  pass
        except Exception as e:  pass
        await asyncio.sleep(60)

def get_admin_panel_kb():
    status = "🔓 إيقاف الصيانة" if settings.get("maintenance_mode") else "🔒 وضع الصيانة"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 الإحصائيات والبث",callback_data="sec_broadcast_stats")],
        [InlineKeyboardButton("📬 صندوق الشكاوى",callback_data="admin_complaints")],
        [InlineKeyboardButton("🖼️ الصور",callback_data="admin_images_section"), InlineKeyboardButton("📝 الرسائل",callback_data="admin_messages_section")],
        [InlineKeyboardButton("📄 الأوصاف",callback_data="admin_captions_section"), InlineKeyboardButton("👑 VIP",callback_data="admin_vip_section")],
        [InlineKeyboardButton("💾 النسخ",callback_data="admin_backup_section"), InlineKeyboardButton("🤖 البوتات",callback_data="admin_bots_section")],
        [InlineKeyboardButton("⚙️ التحميل",callback_data="admin_download_settings")],
        [InlineKeyboardButton("👮 الأدمنز",callback_data="admin_manage_admins"), InlineKeyboardButton("🎁 المكافآت",callback_data="admin_rewards_section")],
        [InlineKeyboardButton("🎉 الهدايا",callback_data="admin_gifts_section"), InlineKeyboardButton("🔗 روابط الهدايا",callback_data="admin_gift_links")],
        [InlineKeyboardButton("♻️ تصفير الفصول",callback_data="admin_reset_section")],
        [InlineKeyboardButton("🧩 هدية دمج",callback_data="admin_merge_gifts")],
        [InlineKeyboardButton("🧮 عدادات الدمج",callback_data="admin_merge_counters")],
        [InlineKeyboardButton("🚫 الحظر",callback_data="admin_ban_section"), InlineKeyboardButton("📢 الاشتراك الإجباري",callback_data="admin_forcesub_section")],
        [InlineKeyboardButton(status, callback_data="admin_toggle_maintenance")],
        [InlineKeyboardButton("❌ إغلاق اللوحة",callback_data="close_list")]])

# ============ Handlers ============
async def _start_cmd_impl(client,message):
    uid=message.from_user.id
    if settings.get("maintenance_mode", False) and not is_admin_any(uid):
        await message.reply_text("⚠️ **البوت في وضع الصيانة**\n\nيرجى المحاولة لاحقاً", parse_mode=ParseMode.MARKDOWN); return
    if is_banned(uid) and uid not in OWNER_IDS:
        await message.reply_text("🚫 **أنت محظور**", parse_mode=ParseMode.MARKDOWN); return
    is_new=add_user(uid); ref_owner=None; gift_code=None; show_data=None
    if len(message.text.split())>1:
        pl=message.text.split()[1]
        if pl.startswith("ref_"):
            try:
                oid=int(pl[4:])
                if oid!=uid: ref_owner=oid
            except: pass
        elif pl.startswith("gift_"): gift_code = pl[5:]
        elif pl.startswith("show_"):
            parts = pl[5:].split("_", 1)
            if len(parts) == 2:
                show_data = {'src': parts[0], 'ident': unpack_share_url(parts[1])}
        elif pl.startswith("m_"):
            shared = get_manga_share(pl[2:])
            if shared:
                show_data = {'src': source_code(shared['source']), 'ident': shared['identifier']}
    if is_new and ref_owner and already_referred(uid) is None:
        add_referral(ref_owner,uid); user_data.setdefault(uid,{})["pending_referral_owner"]=ref_owner
    if is_new:
        try:
            un=message.from_user.username or "لا يوجد"
            await client.send_message(OWNER_ID,f"👤 **عضو جديد**\n\n👤 {message.from_user.first_name or ''}\n🆔 `{uid}`\n📝 @{un}",parse_mode=ParseMode.MARKDOWN)
        except: pass
    is_sub,_=await is_user_subscribed(client,uid)
    if not is_sub:
        pa={'type':'start'}
        if ref_owner: pa['referral_owner']=ref_owner
        if gift_code: pa['gift_code']=gift_code
        if show_data: pa['show_data']=show_data
        await send_subscription_prompt(client,uid,message.chat.id,pa); return
    await _try_reward_referral(client,uid)
    if gift_code: await _process_gift_claim(client, message.chat.id, uid, gift_code)
    if show_data:
        await _show_manga_by_deeplink(client, message.chat.id, uid, show_data['src'], show_data['ident'])
        return
    kb=await build_main_keyboard(uid); wt=settings.get("welcome_message","🌟 **مرحباً!**")
    if is_vip(uid): wt+="\n\n👑 **أنت VIP!**"
    await send_message_with_image(client,message.chat.id,wt,"welcome_image",kb)



@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    try:
        if not message.from_user:
            return
        await _start_cmd_impl(client, message)
    except Exception as exc:
        import traceback
        details = traceback.format_exc()
        pass
        try:
            await message.reply_text("⚠️ حدث خطأ أثناء تشغيل البوت. تم تسجيل الخطأ، حاول مرة أخرى بعد قليل.")
        except Exception as send_exc:
            pass
        try:
            await client.send_message(OWNER_ID, "❌ خطأ في أمر /start:\\n" + details[-3000:])
        except Exception:
            pass


async def _try_reward_referral(client,new_uid):
    po=user_data.get(new_uid,{}).get("pending_referral_owner")
    if not po: return
    if not mark_rewarded(po,new_uid): return
    add_bonus(po,settings.get("referral_bonus_single",50)); add_merge_bonus(po,settings.get("referral_bonus_merge",20))
    try:
        await client.send_message(po,f"🎉 **مبروك!**\n\nحصلت على:\n📖 +`{settings.get('referral_bonus_single',50)}`\n🧩 +`{settings.get('referral_bonus_merge',20)}`",parse_mode=ParseMode.MARKDOWN)
    except: pass
    user_data.get(new_uid,{}).pop("pending_referral_owner",None)

@app.on_message(filters.command("search"))
async def search_cmd(client,message):
    uid = message.from_user.id
    parts = message.text.split(maxsplit=1)
    query = parts[1].strip() if len(parts) > 1 else ""
    if not query:
        await message.reply_text("🔍 اكتب اسم المانجا بعد الأمر، مثال:\n/search Solo Leveling")
        return
    user_data.setdefault(uid, {})["search_query"] = query
    try:
        sources = await asyncio.to_thread(get_sources)
    except Exception as e:
        await message.reply_text(f"❌ تعذر الاتصال بمحرك المانجا: {str(e)[:160]}"); return
    rows = []
    for source in sources:
        sid = str(source["id"]); label = f"📚 {source.get('name') or sid}"[:60]
        rows.append([InlineKeyboardButton(label, callback_data=f"src_{sid}")])
    rows.append([InlineKeyboardButton("❌ إغلاق", callback_data="close_list")])
    if not sources:
        await message.reply_text("❌ لا توجد مصادر مفعلة داخل المحرك."); return
    await send_message_with_image(client, message.chat.id, "🔍 **اختر المصدر للبحث عن:**\n" + query, "sources_image", InlineKeyboardMarkup(rows))

@app.on_message(filters.command("check"))
async def check_cmd(client,message):
    if not is_admin_any(message.from_user.id):
        await message.reply_text("⛔ هذا الأمر للأدمن فقط."); return
    await message.reply_text("🔄 جاري فحص الفصول الجديدة...")
    await check_new_chapters()
    await message.reply_text("✅ انتهى فحص المفضلات.")

@app.on_message(filters.command("cancel") & filters.private)
async def cancel_cmd(client,message):
    uid=message.from_user.id
    if user_data.get(uid): user_data.pop(uid,None); await message.reply_text("❌ **ملغى**")
    else: await message.reply_text("ℹ️ **لا شيء قيد التنفيذ**")

@app.on_message(filters.command("admin") & filters.private)
async def admin_panel(client,message):
    uid=message.from_user.id
    if not is_admin_any(uid): await message.reply_text("⛔ **غير مصرح**"); return
    if is_added_admin(uid) and not is_main_admin(uid):
        kb=InlineKeyboardMarkup([
            [InlineKeyboardButton("👑 VIP",callback_data="admin_vip_section"), InlineKeyboardButton("🎁 المكافآت",callback_data="admin_rewards_section")],
            [InlineKeyboardButton("🎁 هدية للجميع",callback_data="admin_gift_all"), InlineKeyboardButton("🎯 لفرد",callback_data="admin_gift_one")],
            [InlineKeyboardButton("📬 الشكاوى",callback_data="admin_complaints")],
            [InlineKeyboardButton("❌ إغلاق",callback_data="close_list")]])
        await message.reply_text("🛠️ **لوحة الأدمن**",reply_markup=kb,parse_mode=ParseMode.MARKDOWN); return
    await message.reply_text("🛠️ **لوحة التحكم**\n\n👇 اختر:", reply_markup=get_admin_panel_kb(),parse_mode=ParseMode.MARKDOWN)

# ============ Unified Callback ============
@app.on_callback_query()
async def unified_callback(client,callback):
    data=callback.data; uid=callback.from_user.id
    cid=callback.message.chat.id; msg=callback.message

    if settings.get("maintenance_mode", False) and not is_admin_any(uid):
        await callback.answer("⚠️ صيانة", show_alert=True); return
    if data=="check_sub":
        await check_subscription_and_continue(client,callback,user_data.get(uid,{}).get('pending_action')); return
    if is_banned(uid) and uid not in OWNER_IDS: await callback.answer("🚫",show_alert=True); return
    if data!="check_sub":
        is_sub,_=await is_user_subscribed(client,uid)
        if not is_sub:
            await callback.answer("⚠️ اشترك أولاً",show_alert=True); await send_subscription_prompt(client,uid,cid); return
    if data=="close_list":
        try: await msg.delete()
        except: pass
        await callback.answer("✅"); return

    if data=="complaint_start":
        await callback.answer("📩"); user_data[uid]={"awaiting_complaint":True}
        await msg.reply_text("📩 **شكوى**\n\n✍️ اكتب:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء",callback_data="cancel_complaint")]]),parse_mode=ParseMode.MARKDOWN); return
    if data=="cancel_complaint":
        user_data.pop(uid,None)
        try: await msg.delete()
        except: pass
        await callback.answer("❌"); return
    if data in ("help_full","help"):
        await callback.answer("❓")
        await msg.reply_text(
            f"❓ **مساعدة**\n\n🔍 `/search الاسم`\n📚 4 مصادر\n\n"
            f"📖 فردي: `{settings.get('daily_reward_amount',100)}`\n🧩 دمج: `{settings.get('merge_daily_limit',50)}`\n"
            f"📎 حد الملف: `{PDF_MAX_CHAPTERS}`\n"
            f"🔗 إحالة: فردي +{settings.get('referral_bonus_single',50)} / دمج +{settings.get('referral_bonus_merge',20)}\n"
            f"👑 VIP: بلا حدود",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إغلاق",callback_data="close_list")]]),parse_mode=ParseMode.MARKDOWN); return
    if data=="main_search":
        await callback.answer("🔍")
        await msg.reply_text("🔍 **للبحث:**\n`/search اسم المانجا`",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إغلاق",callback_data="close_list")]]),parse_mode=ParseMode.MARKDOWN); return
    if data=="my_account": await callback.answer("👤"); await _show_my_account(client,msg,uid,edit=False); return
    if data=="my_account_refresh": await callback.answer("🔄"); await _show_my_account(client,msg,uid,edit=True); return
    if data=="acc_chapters": await callback.answer("📊"); await _show_chapters_balance(client,msg,uid); return
    if data=="acc_share": await callback.answer("🔗"); await _show_share_link(client,msg,uid); return
    if data=="acc_upgrade": await callback.answer("👑"); await _show_vip_upgrade(client,msg); return
    if data=="acc_vip_details": await callback.answer("💎"); await _show_vip_details(client,msg,uid); return
    if data=="acc_daily_timer": await callback.answer("⏰"); await _show_daily_timer(client,msg,uid); return
    if data=="share_referral": await callback.answer("🔗"); await _show_share_link(client,msg,uid); return
    if data=="vip_upgrade": await callback.answer("👑"); await _show_vip_upgrade(client,msg); return
    if data=="vip_info": await callback.answer("💎"); await _show_vip_details(client,msg,uid); return

    if data=="fav_list":
        if not is_vip(uid):
            await callback.answer("VIP فقط 👑", show_alert=True)
            try: await msg.delete()
            except: pass
            try:
                o=await client.get_chat(OWNER_ID); au=o.username
            except: au=None
            rows=[[InlineKeyboardButton("📞 تواصل", url=f"https://t.me/{au}" if au else f"tg://user?id={OWNER_ID}")],[InlineKeyboardButton("❌ إغلاق", callback_data="close_list")]]
            await msg.reply_text("🔒 **ميزة VIP**\n\n⭐ المفضلات لمشتركي VIP فقط", reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.MARKDOWN); return
        m,s,c=create_fav_list_markup(uid)
        try: await msg.delete()
        except: pass
        await send_message_with_image(client,cid,f"⭐ **المفضلات** ({c})\n⚙️ {s}\n\nاختر:","favorites_image",m)
        await callback.answer("⭐"); return

    if data=="toggle_notifications":
        if not is_vip(uid): await callback.answer("VIP فقط 👑",show_alert=True); return
        cur=is_notifications_enabled(uid); set_notifications_enabled(uid,not cur)
        m,s,c=create_fav_list_markup(uid)
        try: await msg.edit_text(f"⭐ **({c})**\n⚙️ {s}\n\nاختر:",reply_markup=m,parse_mode=ParseMode.MARKDOWN)
        except: pass
        await callback.answer("✅" if not cur else "❌"); return

    if data=="latest_manga_list":
        await callback.answer("📚")
        try:
            sources = await asyncio.to_thread(get_sources)
        except Exception as e:
            sources = []
        if not sources:
            await safe_edit(msg,"❌ تعذر تحميل قائمة المصادر")
            return
        kb=[]
        for source in sources:
            sid=str(source.get("id") or "")
            if not sid: continue
            name=str(source.get("name") or sid)
            kb.append([InlineKeyboardButton("📚 " + name[:45],callback_data=f"latest_src_{sid}")])
        kb.append([InlineKeyboardButton("🏠 القائمة الرئيسية",callback_data="latest_home")])
        try: await msg.delete()
        except: pass
        await send_message_with_image(client,cid,"📚 **اختر مصدر أحدث الفصول:**","sources_image",InlineKeyboardMarkup(kb)); return

    if data.startswith("latest_src_"):
        await callback.answer("⏳")
        src=data[len("latest_src_"):]
        global latest_manga_cache
        try:
            if not latest_manga_cache:
                latest_manga_cache = await asyncio.to_thread(get_all_latest)
            selected=[(i,item) for i,item in enumerate(latest_manga_cache)
                      if len(item)>4 and str(item[4])==src]
            if not selected:
                fresh = await asyncio.to_thread(get_source(src).get_latest_updates)
                refreshed=[]
                for item in fresh[:LATEST_PER_SOURCE]:
                    title=str(item.get("title") or item.get("name") or "Manga")
                    url=item.get("url") or item.get("manga_url") or item.get("link")
                    if not url: continue
                    ident=str(item.get("id") or url)
                    chapter=str(item.get("latest_chapter") or item.get("last_chapter") or item.get("chapter") or "")
                    refreshed.append((title,str(url),ident,chapter,src))
                latest_manga_cache=[x for x in latest_manga_cache if len(x)<=4 or str(x[4])!=src]+refreshed
                selected=[(i,item) for i,item in enumerate(latest_manga_cache)
                          if len(item)>4 and str(item[4])==src]
        except Exception as e:
            pass
            await safe_edit_fresh_text(client,msg,cid,"❌ تعذر تحميل أحدث الفصول من هذا المصدر")
            return
        if not selected:
            await safe_edit_fresh_text(client,msg,cid,"❌ لا توجد مانجا حديثة في هذا المصدر",
                InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ المصادر",callback_data="latest_manga_list")],
                                      [InlineKeyboardButton("🏠 القائمة الرئيسية",callback_data="latest_home")]]))
            return
        kb=[]
        for i,item in selected:
            title,url,ident=item[:3]
            chapter=item[3] if len(item)>3 else ""
            label=f"📖 {str(title)[:32]}" + (f" — {str(chapter)[:12]}" if chapter else "")
            kb.append([InlineKeyboardButton(label,callback_data=f"latest_{i}")])
        kb.append([InlineKeyboardButton("⬅️ المصادر",callback_data="latest_manga_list")])
        kb.append([InlineKeyboardButton("🏠 القائمة الرئيسية",callback_data="latest_home")])
        try: await msg.delete()
        except: pass
        await send_message_with_image(client,cid,"🔥 **أحدث الفصول في المصدر المحدد:**","results_image",InlineKeyboardMarkup(kb)); return

    if data=="latest_home":
        await callback.answer("🏠")
        welcome=settings.get("welcome_message","🌟 **مرحباً بك في بوت المانجا**")
        # A manga details message is a photo; editing its caption leaves the old cover visible.
        # Delete that media message and send the main menu as a clean text message instead.
        try:
            await msg.delete()
        except Exception:
            pass
        await client.send_message(
            chat_id=cid,
            text=welcome,
            reply_markup=await build_main_keyboard(uid),
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if data=="main_categories" or data.startswith("cat_pg_"):
        page=0 if data=="main_categories" else int(data.replace("cat_pg_",""))
        await callback.answer("⏳")
        genres=await asyncio.to_thread(get_source("mangalik").get_genres)
        if not genres: await safe_edit(msg,"❌"); return
        per=12; tp=math.ceil(len(genres)/per); cur=genres[page*per:(page+1)*per]; kb,row=[],[]
        for i,(n,s) in enumerate(cur):
            row.append(InlineKeyboardButton(f"{n}",callback_data=f"cat_g_{page*per+i}"))
            if len(row)==2: kb.append(row); row=[]
        if row: kb.append(row)
        nav=[]
        if page>0: nav.append(InlineKeyboardButton("⬅️",callback_data=f"cat_pg_{page-1}"))
        if page<tp-1: nav.append(InlineKeyboardButton("➡️",callback_data=f"cat_pg_{page+1}"))
        if nav: kb.append(nav)
        kb.append([InlineKeyboardButton("❌ إغلاق",callback_data="close_list")])
        await safe_edit(msg,f"🏷️ **التصنيفات ({page+1}/{tp})**",InlineKeyboardMarkup(kb)); return

    if data.startswith("cat_g_"):
        idx=int(data[6:]); genres=await asyncio.to_thread(get_source("mangalik").get_genres)
        if not genres or idx>=len(genres): await callback.answer("⚠️",show_alert=True); return
        slug,name=genres[idx][1],genres[idx][0]; await callback.answer("⏳")
        await safe_edit(msg,f"⏳ **{name}**")
        mangas=await asyncio.to_thread(get_source("mangalik").get_manga_by_genre, slug, 1)
        if not mangas: await safe_edit(msg,"❌",InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data=f"cat_pg_{idx//12}"), InlineKeyboardButton("❌",callback_data="close_list")]])); return
        kb=[[InlineKeyboardButton(f"📖 {item.get('title','Manga')[:40]}",callback_data=f"cat_sel_{idx}_{i}")] for i,item in enumerate(mangas)]
        kb.append([InlineKeyboardButton("🔙 رجوع",callback_data=f"cat_pg_{idx//12}"), InlineKeyboardButton("❌ إغلاق",callback_data="close_list")])
        await safe_edit(msg,f"🏷️ **{name}** ({len(mangas)})",InlineKeyboardMarkup(kb)); return

    if data.startswith("cat_sel_"):
        p=data.split("_"); idx=int(p[2]); i=int(p[3])
        genres=await asyncio.to_thread(get_source("mangalik").get_genres)
        if not genres or idx>=len(genres): return
        mangas=await asyncio.to_thread(get_source("mangalik").get_manga_by_genre, genres[idx][1], 1)
        if i>=len(mangas): return
        user_data.setdefault(uid,{})["search_results"]=[mangas[i]]
        user_data[uid]["source"]="mangalik"
        data="sel_mangalik_0"

    if data.startswith("sel_") or data.startswith("fav_open_") or data.startswith("latest_"):
        manga_url = None
        if data.startswith("sel_"):
            _, src, idx = data.split("_"); idx=int(idx)
            results=user_data.get(uid,{}).get("search_results",[])
            if idx>=len(results): return
            item=results[idx]
            manga_url=item.get("url") or item.get("manga_url")
            ident=str(item.get("id") or manga_url or "")
        elif data.startswith("fav_open_"):
            idx=int(data.split("_")[2]); favs=get_favorites(uid)
            if idx>=len(favs): return
            item=favs[idx]; src=str(item["source"]); ident=str(item["identifier"])
            manga_url=item.get("manga_url") or (ident if ident.startswith("http") else None)
        else:
            idx=int(data.split("_")[1])
            if idx>=len(latest_manga_cache): return
            item=latest_manga_cache[idx]
            src=str(item[4]) if len(item)>4 else "mangalik"
            manga_url=item[1]
            ident=str(item[2] or manga_url)
            user_data.setdefault(uid,{})["search_results"]=[{"title":item[0],"url":manga_url,"id":ident}]
        if not manga_url:
            await callback.answer("رابط المانجا غير متوفر",show_alert=True); return
        await callback.answer("⏳"); await safe_edit(msg,"⏳ **جاري تحميل معلومات المانجا...**")
        try:
            api=await asyncio.to_thread(get_source,src)
            info=await asyncio.to_thread(api.get_details,manga_url)
            if not info: await safe_edit(msg,"❌ تعذر جلب المعلومات"); return
            chs=list(reversed(info.get("chapters",[])))
            if not chs: await safe_edit(msg,"❌ لا توجد فصول"); return
            title=clean_manga_title(info.get("name") or info.get("title") or ident,ident)
            description=(info.get("description") or "")[:300]
            cover=info.get("cover_url")
            genres=info.get("genres") or []
            kind=info.get("kind") or ""
            async def pdf(ch,_api=api,_client=client,progress=None):
                image_urls=await asyncio.to_thread(_api.get_chapter_images,ch)
                if progress:
                    await progress("extract", len(image_urls))
                result=await download_images_parallel(image_urls,client=_client)
                if progress:
                    await progress("pdf", len(image_urls))
                return result
            user_data[uid]={"chapters":chs,"title":title,"identifier":ident,"page":0,"source":src,
                "create_pdf_func":pdf,"manga_url":manga_url,"cover_url":cover,"genres":genres,"kind":kind,
                "latest_mode":data.startswith("latest_"),"latest_source_id":src}
            parts=[f"**{title}**"]
            if kind: parts.append(f"📚 **{kind}**")
            if genres: parts.append("🏷️ " + " | ".join(map(str,genres[:8])))
            if description: parts.extend(["",description])
            parts.extend(["",f"📖 **{len(chs)} فصل**"])
            if chs:
                latest=chs[-1]
                label=latest.get("number") or latest.get("num_str") or latest.get("chapter_number") or ""
                if not label:
                    candidate=str(latest.get("title") or "").strip()
                    # Never show relative publication time as the chapter number.
                    time_label=re.search(
                        r"\b(?:ago|hour|hours|minute|minutes|day|days|week|weeks|month|months|year|years)\b|"
                        r"(?:منذ|ساعة|ساعات|دقيقة|دقائق|يوم|أيام|اسبوع|أسبوع|شهر|سنة)",
                        candidate, re.IGNORECASE
                    )
                    match=re.search(r"(?:chapter|ch\.?|فصل)\s*#?\s*(\d+(?:\.\d+)?)", candidate, re.IGNORECASE)
                    if match and not time_label:
                        label=match.group(1)
                if label: parts.append(f"📌 آخر فصل: `{label}`")
            cap="\n".join(parts); user_data[uid]["base_caption"]=cap
            markup,_,_=create_chapters_markup(chs,0,ident,src,uid)
            try: await msg.delete()
            except: pass
            await send_cover_message(msg,cover,cap,markup,referer=api.BASE)
        except Exception as e:
            pass
            await safe_edit(msg,f"❌ {str(e)[:180]}")
        return

    if data.startswith("share_manga_"):
        src_short = data.replace("share_manga_", "")
        info = user_data.get(uid, {})
        ident = info.get("manga_url") or info.get("identifier")
        title = info.get('title', 'مانجا')
        if not ident:
            await callback.answer("⚠️ لا توجد بيانات، افتح المانجا أولاً", show_alert=True)
            return
        source_id = source_from_code(src_short)
        if not source_id:
            await callback.answer("⚠️ مصدر المانجا غير متاح", show_alert=True)
            return
        share_code = create_manga_share_code(source_id, ident)
        share_url = f"https://t.me/{BOT_USERNAME}?start=m_{share_code}"
        txt = (
            f"🔗 **رابط مشاركة المانجا**\n\n"
            f"📚 **{title}**\n\n"
            f"`{share_url}`\n\n"
            f"💡 **انسخ الرابط وشاركه مع أصدقائك**\n"
            f"✨ عند فتحه يفتح البوت ويعرض المانجا تلقائياً"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ إغلاق", callback_data="close_list")]
        ])
        await msg.reply_text(txt, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        await callback.answer("🔗 الرابط جاهز — انسخه")
        return

    if data.startswith(("pg_","f_","l_")):
        try:
            if data.startswith("pg_"): p=data.split("_"); src_short,pg=p[1],int(p[2])
            elif data.startswith("f_"): p=data.split("_"); src_short=p[1]; pg=0
            else:
                p=data.split("_"); src_short=p[1]
                chs=user_data.get(uid,{}).get('chapters',[]); pg=max(0,math.ceil(len(chs)/10)-1)
        except: return
        src = source_from_code(src_short)
        if not src or uid not in user_data: await callback.answer("⚠️"); return
        chs=user_data[uid].get('chapters',[]); ident=user_data[uid].get('identifier')
        if not chs: return
        user_data[uid]['page']=pg; m,p2,tot=create_chapters_markup(chs,pg,ident,src,uid)
        base=user_data[uid].get('base_caption'); txt=(base+f"\n\n📄 **{p2+1}/{tot}**") if base else f"📄 {p2+1}/{tot}"
        try: await msg.edit_caption(caption=txt,reply_markup=m,parse_mode=ParseMode.MARKDOWN)
        except:
            try: await msg.delete()
            except: pass
        await callback.answer(f"{p2+1}"); return

    if data.startswith("rf_"):
        src_short=data.split("_")[1]; src=source_from_code(src_short)
        if not src: return
        ident=user_data.get(uid, {}).get('identifier')
        if not ident: await callback.answer("⚠️"); return
        await callback.answer("🔄"); await safe_edit(msg,"⏳")
        try:
            murl_k=user_data.get(uid,{}).get("manga_url")
            if not murl_k: await safe_edit(msg,"⚠️ رابط المانجا غير موجود"); return
            api=await asyncio.to_thread(get_source,src)
            info=await asyncio.to_thread(api.get_details,murl_k)
            if not info: await safe_edit(msg,"❌"); return
            chs=list(reversed(info.get("chapters",[])))
            if not chs: await safe_edit(msg,"❌ لا فصول"); return
            t=clean_manga_title(info.get("name") or info.get("title") or ident,ident)
            d=(info.get("description") or "")[:300]
            cover=info.get("cover_url")
            async def pdf(ch,_api=api,_c=client,progress=None):
                urls=await asyncio.to_thread(_api.get_chapter_images,ch)
                if progress:
                    await progress("extract", len(urls))
                result=await download_images_parallel(urls,client=_c)
                if progress:
                    await progress("pdf", len(urls))
                return result
            ref=api.BASE
        except Exception as e: await safe_edit(msg,f"❌ {e}"); return
        if not chs: await safe_edit(msg,"❌"); return
        user_data[uid]={'chapters':chs,'title':t,'identifier':ident,'page':0,'source':src,'create_pdf_func':pdf,'manga_url':murl_k,'cover_url':cover}
        cap=f"**{t}** (محدث) 🔄\n{d}\n📚 {len(chs)} فصل"
        user_data[uid]['base_caption']=cap
        m,_,_=create_chapters_markup(chs,0,ident,src,uid)
        try: await msg.delete()
        except: pass
        await send_cover_message(msg,cover,cap,m,referer=ref); return

    if data.startswith("ch_"):
        p=data.split("_")
        if len(p)<3: return
        src_short, idx_str = p[1], p[2]; idx=int(idx_str)
        src = source_from_code(src_short)
        if not src: await callback.answer("⚠️"); return
        if uid not in user_data: await callback.answer("⚠️",show_alert=True); return
        parallel_allowed = settings.get("allow_parallel_downloads", False); locked = False
        if not parallel_allowed:
            if is_downloading(uid): await callback.answer("⏳",show_alert=True); return
            if not try_lock_download(uid): await callback.answer("⏳",show_alert=True); return
            locked = True
        try:
            chs=user_data[uid].get('chapters',[])
            if idx>=len(chs): await callback.answer("❌"); return
            pdf_func=user_data[uid].get('create_pdf_func')
            if not pdf_func: await callback.answer("⚠️"); return
            target=chs[idx]; disp='?'
            disp=str(target.get("display_text") or target.get("number") or target.get("num_str") or target.get("title") or "?")[:30]
            disp=re.sub(r"_+", " ", disp).strip() or "?"
            success,rem=try_deduct_chapter(uid,1)
            if not success:
                await callback.answer("❌ لا رصيد",show_alert=True)
                kb=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 مشاركة",callback_data="share_referral"), InlineKeyboardButton("👑 VIP",callback_data="vip_upgrade")],[InlineKeyboardButton("❌ إغلاق",callback_data="close_list")]])
                await msg.reply_text("❌ **لا يوجد رصيد**\n\nادعُ صديقاً 🔗",reply_markup=kb,parse_mode=ParseMode.MARKDOWN); return
            await callback.answer("⏳")
            lt = f"⏳ **جاري تحميل الفصل {disp}...**"
            if rem>=0: lt += f"\n📊 المتبقي: `{rem}`"
            lm=await msg.reply_text(lt)
            stage_clock = {"started": time.perf_counter()}
            async def single_progress(stage, image_count):
                now = time.perf_counter()
                elapsed = now - stage_clock["started"]
                if stage == "extract":
                    status = (f"📖 **الفصل 1/1 — {disp}**\n"
                              f"🔗 تم استخراج `{image_count}` صورة "
                              f"خلال `{elapsed:.1f}` ثانية")
                else:
                    status = (f"📖 **الفصل 1/1 — {disp}**\n"
                              f"📦 تم تجهيز PDF من `{image_count}` صورة "
                              f"خلال `{elapsed:.1f}` ثانية")
                stage_clock["started"] = now
                await lm.edit_text(status)
            try:
                buf = await pdf_func(target, progress=single_progress)
            except Exception:
                buf = None
            if not buf:
                refund_chapter(uid)
                await lm.edit_text("❌ **فشل التحميل**")
                return
            increment_download_count(uid)
            upload_started = time.perf_counter()
            await lm.edit_text("📤 **جاري الرفع...**")
            try:
                title_for_caption=user_data.get(uid,{}).get('title','')
                caption_text=build_caption("single_caption",title=title_for_caption,chapter=disp)
                safe_title=re.sub(r"_+", " ", re.sub(r'[\\/:*?"<>|]', '', title_for_caption)).strip()[:60] or "manga"
                await send_pdf_direct(cid, document=buf, file_name=f"{disp} - {safe_title}.pdf", caption=caption_text, progress_message=lm)
                upload_elapsed = time.perf_counter() - upload_started

                await lm.delete()
            except Exception as e:
                await lm.edit_text(f"❌ {e}")
            try:
                buf.close()
            except Exception:
                pass
            del buf
            gc.collect()
            return
        finally:
            if locked: unlock_download(uid)

    if data.startswith(("fav_add_","fav_remove_","toggle_notify_")):
        if not is_vip(uid): await callback.answer("VIP فقط 👑",show_alert=True); return
        src_short = data.split("_")[-1] if data.startswith("toggle_notify_") else data.split("_")[2]
        src = source_from_code(src_short)
        ident=user_data.get(uid, {}).get('identifier')
        if not src or not ident: return
        if data.startswith("fav_add_"):
            info=user_data.get(uid,{})
            try:
                lc = await asyncio.to_thread(
                    get_latest_chapter_info, src, ident, info.get("manga_url", "")
                )
            except Exception:
                lc = "0"
            if add_to_favorites(uid,info.get('title','?'),ident,src,info.get('manga_url',''),info.get('cover_url',''),lc): await callback.answer("✅")
            else: await callback.answer("⚠️ موجود",show_alert=True)
        elif data.startswith("fav_remove_"):
            if remove_from_favorites(uid,ident,src): await callback.answer("✅")
            else: await callback.answer("⚠️",show_alert=True)
        else:
            cur=get_fav_notify(uid,ident,src); set_fav_notify(uid,ident,src,not cur)
            await callback.answer("✅" if not cur else "❌")
        info=user_data.get(uid,{})
        m,_,_=create_chapters_markup(info.get('chapters',[]),info.get('page',0),ident,src,uid)
        try: await msg.edit_caption(caption=msg.caption,reply_markup=m,parse_mode=ParseMode.MARKDOWN)
        except: pass
        return

    if data.startswith("mrg_"):
        src_short=data.split("_")[1]; src=source_from_code(src_short)
        if not src: await callback.answer("⚠️"); return
        if uid not in user_data: await callback.answer("⚠️", show_alert=True); return
        ident=user_data[uid].get('identifier'); chs=user_data[uid].get('chapters',[])
        if not chs: await callback.answer("لا فصول", show_alert=True); return
        user_data[uid]['awaiting_merge_range'] = {'src': src, 'ident': ident, 'chapters': chs}
        mr = '♾️ VIP' if is_vip(uid) else str(int(get_merge_remaining(uid)))
        mmax = PDF_MAX_CHAPTERS
        await msg.reply_text(f"🧩 **دمج الفصول**\n\n📚 `{len(chs)}` فصل\n🔢 `{mmax}` حد أقصى\n💳 رصيد: `{mr}`\n\n📝 أرسل: `البداية-النهاية`\nمثال: `1-{mmax}`\n\n/cancel", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إغلاق",callback_data="close_list")]]), parse_mode=ParseMode.MARKDOWN)
        await callback.answer("⏳"); return

    if data.startswith("src_"):
        src=data[4:]; q=user_data.get(uid,{}).get('search_query')
        if not q: await callback.answer("⚠️",show_alert=True); await safe_edit(msg,"`/search`"); return
        await callback.answer("⏳"); await safe_edit(msg,f"🔍 **{q}**")
        res=[]
        try:
            api=await asyncio.to_thread(get_source,src)
            res=await asyncio.to_thread(api.search,q)
        except Exception as e:  pass
        if not res:
            try: await msg.delete()
            except: pass
            await client.send_message(cid, f"❌ **لا نتائج أو المصدر غير متاح**\n`{q}`",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔍 بحث جديد",callback_data="main_search")],[InlineKeyboardButton("❌ إغلاق",callback_data="close_list")]]),
                parse_mode=ParseMode.MARKDOWN); return
        user_data[uid]["search_results"]=res; user_data[uid]["source"]=src
        kb=[]
        for i,item in enumerate(res):
            title=str(item.get("title") or "Manga")
            kb.append([InlineKeyboardButton(f"📖 {title[:45]}",callback_data=f"sel_{src}_{i}")])
        kb.append([InlineKeyboardButton("🔍 بحث جديد",callback_data="main_search"), InlineKeyboardButton("❌ إغلاق",callback_data="close_list")])
        try: await msg.delete()
        except: pass
        await send_message_with_image(client,cid,f"✅ **{len(res)} نتيجة**\n`{q}`","results_image",InlineKeyboardMarkup(kb)); return

    # ============ ADMIN ============
    if is_admin_any(uid):
        if data == "admin_toggle_maintenance":
            current = settings.get("maintenance_mode", False); settings["maintenance_mode"] = not current; save_settings()
            await callback.answer("🔒" if not current else "🔓", show_alert=True)
            try: await msg.edit_text("🛠️ **لوحة التحكم الرئيسية**", reply_markup=get_admin_panel_kb(), parse_mode=ParseMode.MARKDOWN)
            except: pass
            return
        if data=="admin_gift_links":
            links=get_all_gift_links()
            await msg.edit_text(f"🎁 **إدارة روابط الهدايا** ({len(links)})",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ إنشاء رابط", callback_data="admin_gift_link_create")],
                    [InlineKeyboardButton("📋 عرض/إدارة", callback_data="admin_gift_link_list")],
                    [InlineKeyboardButton("🗑️ حذف", callback_data="admin_gift_link_delete_menu")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel_back"), InlineKeyboardButton("❌ إغلاق", callback_data="close_list")]]),
                parse_mode=ParseMode.MARKDOWN)
            await callback.answer("🎁"); return
        if data.startswith("admin_gift_manage_"):
            code = data.replace("admin_gift_manage_", ""); link = get_gift_link(code)
            if not link: await callback.answer("⚠️", show_alert=True); return
            allowed = get_gift_allowed_users(code); allowed_txt = f"`{len(allowed)}` مستخدم" if allowed else "الجميع"
            ch = link.get('channel_id') or "غير محدد"; en = "✅" if link.get('post_enabled') else "❌"
            interval = link.get('post_interval_hours', 2); mode = link.get('post_mode') or 'auto'
            mode_txt = "🤖 تلقائي" if mode == 'auto' else "👤 يدوي"
            rem = max(0, int(link['expires_at'] - time.time())); h_rem = rem // 3600; m_rem = (rem % 3600) // 60
            bot_user = BOT_USERNAME or "bot"; current_url = f"https://t.me/{bot_user}?start=gift_{code}"
            txt = (f"⚙️ **إدارة الرابط** `{code}`\n\n🔗 `{current_url}`\n\n📖 `{link['single_amount']}`\n🧩 `{link['merge_amount']}`\n👥 `{link['used_count']}/{link['max_users']}`\n⏰ `{h_rem}س {m_rem}د`\n\n🛡️ {allowed_txt}\n📢 `{ch}`\n⏯ {en}\n📣 {mode_txt}\n🔄 كل `{interval}` ساعة")
            kb_rows = [
                [InlineKeyboardButton("📤 مشاركة الرابط", url=f"https://t.me/share/url?url={quote(current_url)}&text={quote('🎁 هدية!')}")],
                [InlineKeyboardButton("👥 مستخدمين", callback_data=f"admin_gift_users_{code}"), InlineKeyboardButton("📢 قناة", callback_data=f"admin_gift_setchannel_{code}")],
                [InlineKeyboardButton("⏯ تفعيل/تعطيل", callback_data=f"admin_gift_toggle_{code}")],
                [InlineKeyboardButton(f"📣 الوضع", callback_data=f"admin_gift_mode_{code}")],
                [InlineKeyboardButton("⏰ كل كم ساعة", callback_data=f"admin_gift_interval_{code}")],
            ]
            if mode == 'auto':
                if link.get('post_enabled') and link.get('channel_id'):
                    kb_rows.append([InlineKeyboardButton("📤 انشر الآن", callback_data=f"admin_gift_publish_{code}")])
            else:
                kb_rows.append([InlineKeyboardButton("🔄 توليد رابط جديد", callback_data=f"admin_gift_publish_{code}")])
            kb_rows.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_gift_links")])
            await msg.edit_text(txt, reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode=ParseMode.MARKDOWN)
            await callback.answer("⚙️"); return
        if data.startswith("admin_gift_users_set_"):
            code = data.replace("admin_gift_users_set_", ""); user_data[uid] = {"awaiting_gift_allowed_users": code}
            await msg.delete(); await msg.reply_text("👥 **أرسل المعرّفات** مفصولة بمسافة:\n`123456789 @user1`\n\n/cancel", parse_mode=ParseMode.MARKDOWN)
            await callback.answer("👥"); return
        if data.startswith("admin_gift_users_clear_"):
            code = data.replace("admin_gift_users_clear_", ""); clear_gift_allowed_users(code)
            await msg.edit_text("✅ **مفتوح للجميع**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data=f"admin_gift_manage_{code}")],[InlineKeyboardButton("❌", callback_data="close_list")]]))
            await callback.answer("✅"); return
        if data.startswith("admin_gift_users_"):
            code = data.replace("admin_gift_users_", ""); allowed = get_gift_allowed_users(code)
            if allowed: txt = f"👥 **المستخدمون المسموح لهم** ({len(allowed)})\n\n" + "\n".join(f"• `{u}`" for u in allowed[:30])
            else: txt = "👥 **مفتوح للجميع**"
            await msg.edit_text(txt, reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ إضافة", callback_data=f"admin_gift_users_set_{code}")],
                [InlineKeyboardButton("🗑️ مسح", callback_data=f"admin_gift_users_clear_{code}")],
                [InlineKeyboardButton("🔙 رجوع", callback_data=f"admin_gift_manage_{code}")]]), parse_mode=ParseMode.MARKDOWN)
            await callback.answer("👥"); return
        if data.startswith("admin_gift_setchannel_"):
            code = data.replace("admin_gift_setchannel_", ""); user_data[uid] = {"awaiting_gift_channel": code}
            await msg.delete(); await msg.reply_text("📢 **معرّف القناة:**\n`@channel` أو `-100...`\n\n⚠️ البوت أدمن\n\n/cancel", parse_mode=ParseMode.MARKDOWN)
            await callback.answer("📢"); return
        if data.startswith("admin_gift_toggle_"):
            code = data.replace("admin_gift_toggle_", ""); res = toggle_gift_post(code)
            if res is None: await callback.answer("⚠️ حدد قناة أولاً", show_alert=True); return
            await callback.answer("✅" if res else "❌", show_alert=True)
            await _reopen_admin_page(client, uid, msg, f"admin_gift_manage_{code}"); return
        if data.startswith("admin_gift_mode_"):
            code = data.replace("admin_gift_mode_", ""); link = get_gift_link(code)
            if not link: await callback.answer("⚠️", show_alert=True); return
            new_mode = 'manual' if (link.get('post_mode') or 'auto') == 'auto' else 'auto'
            set_gift_post_mode(code, new_mode)
            await callback.answer("👤 يدوي" if new_mode=='manual' else "🤖 تلقائي", show_alert=True)
            await _reopen_admin_page(client, uid, msg, f"admin_gift_manage_{code}"); return
        if data.startswith("admin_gift_publish_"):
            code = data.replace("admin_gift_publish_", ""); link = get_gift_link(code)
            if not link: await callback.answer("⚠️", show_alert=True); return
            mode = link.get('post_mode') or 'auto'
            ok, err, new_code = await publish_gift_now(client, uid, code)
            if ok: await callback.answer("✅ نُشر" if mode=='auto' else "✅ أُرسل لك", show_alert=True)
            else: await callback.answer(f"❌ {err}", show_alert=True)
            await _reopen_admin_page(client, uid, msg, "admin_gift_links"); return
        if data.startswith("admin_gift_interval_"):
            code = data.replace("admin_gift_interval_", ""); user_data[uid] = {"awaiting_gift_post_interval": code}
            await msg.delete(); await msg.reply_text("⏰ **كل كم ساعة؟** (1-24)\n\n/cancel", parse_mode=ParseMode.MARKDOWN)
            await callback.answer("⏰"); return
        if data=="admin_gift_link_create":
            user_data[uid]={"gift_link_step":"single"}; await msg.delete()
            await msg.reply_text("🎁 **إنشاء رابط**\n\n📖 **الفصول المفردة** لكل مستخدم؟\n(0 للتخطي)\n\n/cancel", parse_mode=ParseMode.MARKDOWN)
            await callback.answer("🎁"); return
        if data=="admin_gift_link_list":
            links=get_all_gift_links()
            if not links:
                await msg.edit_text("🎁 **لا توجد روابط هدايا حالياً**\n\nأنشئ رابطاً جديداً ليظهر هنا.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="admin_gift_links")],[InlineKeyboardButton("❌", callback_data="close_list")]]))
                await callback.answer("📭"); return
            kb=[]
            for l in links:
                rem=max(0, int(l['expires_at']-time.time())); h=rem//3600; m=(rem%3600)//60
                exp = "منتهي" if rem<=0 else f"{h}س{m}د"
                mode_icon = "🤖" if (l.get('post_mode') or 'auto') == 'auto' else "👤"
                kb.append([InlineKeyboardButton(f"{mode_icon} {l['code']} — {l['used_count']}/{l['max_users']} — {exp}", callback_data=f"admin_gift_manage_{l['code']}")])
            kb.append([InlineKeyboardButton("🔙", callback_data="admin_gift_links"), InlineKeyboardButton("❌", callback_data="close_list")])
            await msg.edit_text("📋 **اختر الرابط الذي تريد إدارته:**", reply_markup=InlineKeyboardMarkup(kb)); await callback.answer("📋"); return
        if data=="admin_gift_link_delete_menu":
            links=get_all_gift_links()
            if not links: await msg.edit_text("🎁 **لا توجد روابط هدايا لحذفها**\n\nأنشئ رابطاً أولاً قبل استخدام الحذف."); await callback.answer("📭"); return
            kb=[[InlineKeyboardButton(f"🗑️ {l['code']}", callback_data=f"admin_gift_link_del_{l['code']}")] for l in links]
            kb.append([InlineKeyboardButton("🔙", callback_data="admin_gift_links")])
            await msg.edit_text("🗑️ **اختر العنصر الذي تريد حذفه:**", reply_markup=InlineKeyboardMarkup(kb)); await callback.answer("🗑️"); return
        if data.startswith("admin_gift_link_del_"):
            code=data.replace("admin_gift_link_del_","")
            if delete_gift_link(code):
                await msg.edit_text(f"✅ حُذف `{code}`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="admin_gift_links")],[InlineKeyboardButton("❌", callback_data="close_list")]]), parse_mode=ParseMode.MARKDOWN)
            else: await msg.edit_text("⚠️ **تعذّر تنفيذ الطلب**\nراجع البيانات المطلوبة وحاول مجدداً.")
            await callback.answer("✅"); return
        if data=="gift_expiry_hours":
            if not user_data.get(uid,{}).get("gift_link_step"): await callback.answer("⚠️", show_alert=True); return
            user_data[uid]["gift_expiry_unit"]="hours"; user_data[uid]["gift_link_step"]="expiry_value"; await msg.delete()
            await msg.reply_text("⏰ **الساعات:**\nمثال: `24`\n\n/cancel", parse_mode=ParseMode.MARKDOWN); await callback.answer("⏰"); return
        if data=="gift_expiry_minutes":
            if not user_data.get(uid,{}).get("gift_link_step"): await callback.answer("⚠️", show_alert=True); return
            user_data[uid]["gift_expiry_unit"]="minutes"; user_data[uid]["gift_link_step"]="expiry_value"; await msg.delete()
            await msg.reply_text("⏱️ **الدقائق:**\nمثال: `30`\n\n/cancel", parse_mode=ParseMode.MARKDOWN); await callback.answer("⏱️"); return
        if data=="admin_merge_counters":
            await msg.edit_text(f"🧮 **إعدادات العدادات والحدود**\n\n📖 `{settings.get('daily_reward_amount',100)}`\n🧩 `{settings.get('merge_daily_limit',50)}`\n📎 `{PDF_MAX_CHAPTERS}`",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✏️ تعديل حد الدمج",callback_data="admin_edit_merge_limit")],[InlineKeyboardButton("✏️ تعديل حد الملف",callback_data="admin_edit_merge_max")],[InlineKeyboardButton("✏️ تعديل حد الفردي",callback_data="admin_edit_daily_amount")],[InlineKeyboardButton("🔙 رجوع",callback_data="admin_panel_back"), InlineKeyboardButton("❌ إغلاق",callback_data="close_list")]]),parse_mode=ParseMode.MARKDOWN)
            await callback.answer("🧮"); return
        if data=="admin_edit_merge_limit":
            await msg.delete(); await msg.reply_text(f"✏️ min 2\nالحالي: `{settings.get('merge_daily_limit',50)}`\n\n/cancel",parse_mode=ParseMode.MARKDOWN)
            user_data[uid]={"awaiting_merge_limit":True}; await callback.answer("✏️"); return
        if data=="admin_edit_merge_max":
            await msg.delete(); await msg.reply_text(f"✏️ min 2\nالحالي: `{PDF_MAX_CHAPTERS}`\n\n/cancel",parse_mode=ParseMode.MARKDOWN)
            user_data[uid]={"awaiting_merge_max":True}; await callback.answer("✏️"); return
        if data=="admin_edit_daily_amount":
            await msg.delete(); await msg.reply_text(f"✏️ الحالي: `{settings.get('daily_reward_amount',100)}`\n\n/cancel",parse_mode=ParseMode.MARKDOWN)
            user_data[uid]={"awaiting_daily_amount":True}; await callback.answer("✏️"); return
        if data=="admin_merge_gifts":
            await msg.edit_text("🧩 **هدية دمج الفصول**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎯 فرد",callback_data="admin_merge_gift_one"), InlineKeyboardButton("🎁 جميع",callback_data="admin_merge_gift_all")],[InlineKeyboardButton("🔙",callback_data="admin_panel_back"), InlineKeyboardButton("❌",callback_data="close_list")]]), parse_mode=ParseMode.MARKDOWN)
            await callback.answer("🧩"); return
        if data=="admin_merge_gift_one":
            await msg.delete(); await msg.reply_text("🎯 **إرسال هدية دمج إلى عضو**\nأرسل آيدي المستخدم أو @username.\n\nللإلغاء أرسل /cancel")
            user_data[uid]={"awaiting_merge_gift_one_id":True}; await callback.answer("🎯"); return
        if data=="admin_merge_gift_all":
            await msg.delete(); await msg.reply_text("🎁 **هدية دمج لجميع الأعضاء**\nأرسل عدد فصول الدمج التي تريد إضافتها لكل مستخدم.\n\nللإلغاء أرسل /cancel")
            user_data[uid]={"awaiting_merge_gift_all":True}; await callback.answer("🎁"); return
        if data=="admin_complaints":
            clist=get_all_complaints()
            if not clist:
                await msg.edit_text("📭 **صندوق الشكاوى فارغ**\n\nستظهر شكاوى المستخدمين هنا عند وصولها.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙",callback_data="admin_panel_back")],[InlineKeyboardButton("❌",callback_data="close_list")]]))
                await callback.answer("📭"); return
            txt=f"📬 **صندوق الشكاوى** ({len(clist)})\n\n"
            for i,c in enumerate(clist[-20:][::-1],1):
                un=f"@{c['username']}" if c.get('username') else "—"; dt=time.strftime("%Y-%m-%d %H:%M",time.localtime(c.get('ts',0)))
                txt+=f"{i}. {c.get('first_name','?')} | `{c['uid']}` | {un}\n🕐 {dt}\n💬 {c.get('text','')[:180]}\n\n"
            if len(txt)>3900: txt=txt[:3900]+"..."
            await msg.edit_text(txt,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗑️ مسح",callback_data="admin_clear_complaints")],[InlineKeyboardButton("🔄",callback_data="admin_complaints"), InlineKeyboardButton("🔙",callback_data="admin_panel_back")],[InlineKeyboardButton("❌",callback_data="close_list")]]),parse_mode=ParseMode.MARKDOWN)
            await callback.answer("📬"); return
        if data=="admin_clear_complaints":
            await msg.edit_text(f"🗑️ **تأكيد حذف الشكاوى**\nهل تريد حذف جميع الشكاوى وعددها `{count_complaints()}`؟", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅",callback_data="admin_clear_complaints_yes")],[InlineKeyboardButton("❌",callback_data="admin_complaints")]]))
            await callback.answer("⚠️"); return
        if data=="admin_clear_complaints_yes":
            n=clear_complaints(); await msg.edit_text(f"✅ {n}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌",callback_data="close_list")]]))
            await callback.answer("✅"); return
        if data=="admin_panel_back":
            try: await msg.delete()
            except: pass
            await msg.reply_text("🛠️ **لوحة التحكم الرئيسية**",reply_markup=get_admin_panel_kb(),parse_mode=ParseMode.MARKDOWN)
            await callback.answer("🔙"); return
        if data=="sec_broadcast_stats":
            await msg.edit_text(
                f"📊 **لوحة الإحصائيات العامة – Manga Virus** 🦠\n\n✨ **نظرة شاملة على نشاط البوت وأرقامه:**\n\n👥 **إجمالي المستخدمين:** `{get_users_count()}`\n📥 **عمليات التحميل:** `{get_download_count()}`\n👑 **أعضاء VIP:** `{len(get_all_vips())}`\n👮 **المشرفون المضافون:** `{len(get_all_added_admins())}`\n🚫 **المحظورون:** `{len(get_all_banned())}`\n🤖 **البوتات المسجلة:** `{len(get_all_bots())}`\n📬 **الشكاوى الواردة:** `{count_complaints()}`\n📖 **الحد اليومي لتحميل الفصول:** `{settings.get('daily_reward_amount',100)}`\n🧩 **حد دمج الفصول اليومي:** `{settings.get('merge_daily_limit',50)}`\n\n━━━━━━━━━━━━━━━━━━\n\n🚀 **Manga Virus في تطوّر مستمر!**\n\nكل رقم يمثل خطوة جديدة في رحلتنا لتوفير أفضل تجربة لعشاق المانجا والمانهوا.\n\n🖤 شكراً لكل من اختار Manga Virus، والقادم أفضل بإذن الله! 🦠",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📢 إعلان",callback_data="admin_broadcast"), InlineKeyboardButton("📊",callback_data="admin_stats")],[InlineKeyboardButton("🧹 تنظيف",callback_data="admin_cleanup")],[InlineKeyboardButton("❌",callback_data="close_list")]]),parse_mode=ParseMode.MARKDOWN)
            await callback.answer("📊"); return
        if data=="admin_broadcast":
            await msg.delete(); await msg.reply_text("📢 **إرسال إعلان للمستخدمين**\nأرسل نص الإعلان الذي تريد نشره للجميع.\n\nللإلغاء أرسل /cancel")
            user_data[uid]={'awaiting_broadcast':True}; await callback.answer("📢"); return
        if data=="admin_stats":
            await msg.edit_text(f"📊 **إحصائيات**\n👥 `{get_users_count()}`\n📥 `{get_download_count()}`\n⭐ `{count_total_favorites()}`\n👑 `{len(get_all_vips())}`\n🔄 `{time.strftime('%Y-%m-%d %H:%M:%S')}`",parse_mode=ParseMode.MARKDOWN)
            await callback.answer("📊"); return
        if data=="admin_reset_section":
            await msg.edit_text("♻️ **تصفير الفصول**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("♻️ الجميع",callback_data="admin_reset_all_confirm"), InlineKeyboardButton("👤 عضو",callback_data="admin_reset_one")],[InlineKeyboardButton("❌",callback_data="close_list")]]),parse_mode=ParseMode.MARKDOWN)
            await callback.answer("♻️"); return
        if data=="admin_reset_all_confirm":
            await msg.edit_text(f"♻️ **تأكيد تصفير الأرصدة**\nهل تريد تصفير أرصدة جميع المستخدمين وعددهم `{get_users_count()}`؟ لا يمكن التراجع عن هذه العملية.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅",callback_data="admin_reset_all_do")],[InlineKeyboardButton("❌",callback_data="admin_reset_section")]]),parse_mode=ParseMode.MARKDOWN)
            await callback.answer("⚠️"); return
        if data=="admin_reset_all_do":
            await callback.answer("⏳")
            try:
                count=reset_all_balances(); await msg.edit_text(f"✅ {count}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌",callback_data="close_list")]]))
            except Exception as e: await msg.edit_text(f"⚠️ **تعذّر حذف النسخ الاحتياطية:**\n{e}")
            return
        if data=="admin_reset_one":
            await msg.delete(); await msg.reply_text("👤 **تصفير رصيد مستخدم محدد**\nأرسل آيدي المستخدم أو @username.\n\nللإلغاء أرسل /cancel")
            user_data[uid]={"awaiting_reset_user":True}; await callback.answer("👤"); return
        if data=="admin_ban_section":
            await msg.edit_text(f"🚫 **إدارة المحظورين** ({len(get_all_banned())})", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 حظر",callback_data="admin_ban_user"), InlineKeyboardButton("✅ فك",callback_data="admin_unban_user")],[InlineKeyboardButton("📋",callback_data="admin_banned_list"), InlineKeyboardButton("❌",callback_data="close_list")]]),parse_mode=ParseMode.MARKDOWN)
            await callback.answer("🚫"); return
        if data=="admin_ban_user":
            await msg.delete(); await msg.reply_text("🚫 **حظر مستخدم**\nأرسل آيدي المستخدم أو @username الذي تريد حظره.\n\nللإلغاء أرسل /cancel")
            user_data[uid]={"awaiting_ban_user":True}; await callback.answer("🚫"); return
        if data=="admin_unban_user":
            await msg.delete(); await msg.reply_text("🔓 **رفع الحظر عن مستخدم**\nأرسل آيدي المستخدم أو @username.\n\nللإلغاء أرسل /cancel")
            user_data[uid]={"awaiting_unban_user":True}; await callback.answer("✅"); return
        if data=="admin_banned_list":
            blist=get_all_banned()
            if not blist:
                await msg.edit_text("🛡️ **قائمة الحظر فارغة**\n\nلا يوجد مستخدمون محظورون حالياً.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌",callback_data="close_list")]]))
                await callback.answer("📋"); return
            txt=f"📋 ({len(blist)})\n\n" + "\n".join(f"{i}. `{b}`" for i,b in enumerate(blist,1))
            await msg.edit_text(txt,parse_mode=ParseMode.MARKDOWN); await callback.answer("📋"); return
        if data=="admin_captions_section":
            await msg.edit_text(f"📄 **إدارة وصف ملفات الفصول**\n\nالوصف الحالي:\n{settings.get('single_caption','')[:200]}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✏️ تعديل الوصف",callback_data="admin_edit_single_caption")],[InlineKeyboardButton("♻️ استعادة الافتراضي",callback_data="admin_reset_captions")],[InlineKeyboardButton("❌ إغلاق",callback_data="close_list")]]),parse_mode=ParseMode.MARKDOWN)
            await callback.answer("📄"); return
        if data=="admin_edit_single_caption":
            await msg.delete(); await msg.reply_text("✏️ **تعديل وصف ملف الفصل**\nاستخدم `{chapter}` لرقم الفصل و`{title}` لاسم المانجا.\nأرسل نص الوصف الجديد.\n\nللإلغاء أرسل /cancel",parse_mode=ParseMode.MARKDOWN)
            user_data[uid]={"awaiting_single_caption":True}; await callback.answer("✏️"); return
        if data=="admin_reset_captions":
            settings["single_caption"]=NEW_SINGLE_CAPTION; save_settings()
            await msg.edit_text("♻️ **تمت استعادة وصف الفصل الافتراضي بنجاح.**",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌",callback_data="close_list")]]))
            await callback.answer("✅"); return
        if data=="admin_images_section":
            def st(k): return "✅" if settings.get(k) else "❌"
            await msg.edit_text(f"🖼️ **إدارة صور البوت**\n\nBDF:{st('bdf_image')} ترحيب:{st('welcome_image')} مفضلة:{st('favorites_image')}\nنتائج:{st('results_image')} مصادر:{st('sources_image')} اشتراك:{st('force_sub_image')}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🖼️ BDF",callback_data="img_menu_bdf"), InlineKeyboardButton("🖼️ ترحيب",callback_data="img_menu_welcome")],[InlineKeyboardButton("🖼️ مفضلة",callback_data="img_menu_favorites")],[InlineKeyboardButton("🖼️ نتائج",callback_data="img_menu_results"), InlineKeyboardButton("🖼️ مصادر",callback_data="img_menu_sources")],[InlineKeyboardButton("🖼️ اشتراك",callback_data="img_menu_sub")],[InlineKeyboardButton("❌ إغلاق",callback_data="close_list")]]),parse_mode=ParseMode.MARKDOWN)
            await callback.answer("🖼️"); return
        if data.startswith("img_menu_"):
            km={"bdf":("bdf_image","BDF","admin_add_bdf","admin_del_bdf"),"welcome":("welcome_image","ترحيب","admin_set_welcome_image","admin_del_welcome_image"),"favorites":("favorites_image","مفضلة","admin_set_favorites_image","admin_del_favorites_image"),"results":("results_image","نتائج","admin_set_results_image","admin_del_results_image"),"sources":("sources_image","مصادر","admin_set_sources_image","admin_del_sources_image"),"sub":("force_sub_image","اشتراك","admin_set_sub_image","admin_del_sub_image")}
            k=data.replace("img_menu_","")
            if k not in km: await callback.answer("⚠️"); return
            sk,ttl,scb,dcb=km[k]; has="✅" if settings.get(sk) else "❌"
            await msg.edit_text(f"🖼️ **{ttl}**: {has}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ رفع صورة",callback_data=scb), InlineKeyboardButton("🗑️ حذف الصورة",callback_data=dcb)],[InlineKeyboardButton("❌ إغلاق",callback_data="close_list")]]),parse_mode=ParseMode.MARKDOWN)
            await callback.answer("🖼️"); return
        if data=="admin_messages_section":
            await msg.edit_text("📝 **إدارة رسائل البوت**\n\nعدّل رسالة الترحيب أو رسالة الاشتراك الإجباري. اختر الرسالة التي تريد تغييرها.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📝 رسالة الترحيب",callback_data="admin_set_welcome"), InlineKeyboardButton("📢 رسالة الاشتراك",callback_data="admin_set_sub_message")],[InlineKeyboardButton("❌ إغلاق",callback_data="close_list")]]),parse_mode=ParseMode.MARKDOWN)
            await callback.answer("📝"); return
        if data=="admin_download_settings":
            parallel = settings.get("allow_parallel_downloads", False); status = "✅" if parallel else "❌"
            btn_text = "🔒 تعطيل" if parallel else "🔓 تفعيل"
            await msg.edit_text(f"⚙️ **التحميل**\n\nمتوازي: {status}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(btn_text, callback_data="admin_toggle_parallel")],[InlineKeyboardButton("🔙", callback_data="admin_panel_back"), InlineKeyboardButton("❌", callback_data="close_list")]]),parse_mode=ParseMode.MARKDOWN)
            await callback.answer("⚙️"); return
        if data=="admin_toggle_parallel":
            settings["allow_parallel_downloads"] = not settings.get("allow_parallel_downloads", False); save_settings()
            await callback.answer("✅" if settings["allow_parallel_downloads"] else "❌", show_alert=True)
            await _reopen_admin_page(client, uid, msg, "admin_download_settings"); return
        if data=="admin_vip_section":
            sc=settings.get("vip_contact_second")
            await msg.edit_text(f"👑 **إدارة الـ VIP** ({len(get_all_vips())})\nالزر الثاني: `{sc or 'غير محدد'}`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ إضافة عضو VIP",callback_data="admin_vip_add"), InlineKeyboardButton("🗑️ إزالة عضو VIP",callback_data="admin_vip_remove")],[InlineKeyboardButton("🎁 VIP مجاني للجميع",callback_data="admin_vip_all_1day")],[InlineKeyboardButton("👥 تعديل زر التواصل",callback_data="admin_set_vip_contact")],[InlineKeyboardButton("📋 قائمة المشتركين",callback_data="admin_vip_list"), InlineKeyboardButton("❌ إغلاق",callback_data="close_list")]]),parse_mode=ParseMode.MARKDOWN)
            await callback.answer("👑"); return
        if data=="admin_set_vip_contact":
            await msg.edit_text(f"👥 الحالي: `{settings.get('vip_contact_second') or 'غير محدد'}`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🗑️",callback_data="admin_del_vip_contact")],[InlineKeyboardButton("❌",callback_data="close_list")]]),parse_mode=ParseMode.MARKDOWN)
            user_data[uid]={"awaiting_vip_contact":True}; await callback.answer("👥"); return
        if data=="admin_del_vip_contact":
            settings["vip_contact_second"]=None; save_settings(); user_data.pop(uid,None)
            await msg.edit_text("👥 **تم حذف جهة التواصل الإضافية الخاصة بـ VIP.**",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌",callback_data="close_list")]]))
            await callback.answer("✅"); return
        if data=="admin_vip_all_1day":
            await msg.edit_text(f"منح VIP ليوم لـ {get_users_count()}؟", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅",callback_data="admin_vip_all_1day_yes")],[InlineKeyboardButton("❌",callback_data="close_list")]]),parse_mode=ParseMode.MARKDOWN)
            await callback.answer("⚠️"); return
        if data=="admin_vip_all_1day_yes":
            await callback.answer("⏳")
            success=extend_all_vips(24*3600)
            for u in get_all_user_ids():
                try:
                    await client.send_message(u,"🎉 **VIP ليوم** 👑",parse_mode=ParseMode.MARKDOWN); await asyncio.sleep(0.05)
                except: pass
            await msg.edit_text(f"✅ {success}",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌",callback_data="close_list")]])); return
        if data=="admin_vip_add":
            await msg.edit_text("👑 **اختر مدة اشتراك VIP التي تريد منحها:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📅 أسبوع",callback_data="vip_add_weekly"), InlineKeyboardButton("📆 شهر",callback_data="vip_add_monthly"), InlineKeyboardButton("🗓️ سنة",callback_data="vip_add_yearly")],[InlineKeyboardButton("❌",callback_data="close_list")]]))
            await callback.answer("👑"); return
        if data in ("vip_add_weekly","vip_add_monthly","vip_add_yearly"):
            plan=data.replace("vip_add_",""); user_data[uid]={"awaiting_vip_user":plan}
            await msg.delete(); await msg.reply_text(f"👑 **منح اشتراك VIP: {VIP_PLAN_NAMES[plan]}**\nأرسل آيدي المستخدم أو @username.\n\nللإلغاء أرسل /cancel")
            await callback.answer("👑"); return
        if data=="admin_vip_remove":
            await msg.delete(); await msg.reply_text("👑 **إزالة اشتراك VIP**\nأرسل آيدي المستخدم أو @username.\n\nللإلغاء أرسل /cancel")
            user_data[uid]={"awaiting_vip_remove":True}; await callback.answer("🗑️"); return
        if data=="admin_vip_list":
            vips=get_all_vips()
            if not vips: await msg.edit_text("👑 **لا يوجد أعضاء VIP حالياً.**\n\nيمكنك إضافة مشترك جديد من خيارات إدارة VIP."); await callback.answer("📋"); return
            txt="👑 **قائمة أعضاء VIP**\n\n🆔 آيدي العضو — الخطة — الأيام المتبقية\n\n"
            for v in vips:
                info=get_vip_info(v)
                if info: txt+=f"• `{v}` — {VIP_PLAN_NAMES.get(info['plan'],'?')} — {max(0,int((info['expires']-time.time())//86400))} يوم\n"
            await msg.edit_text(txt,parse_mode=ParseMode.MARKDOWN); await callback.answer("📋"); return
        if data=="admin_rewards_section":
            amt=settings.get("daily_reward_amount",100); iv=settings.get("daily_reward_interval",86400)//3600
            await msg.edit_text(f"🎁 **إعدادات المكافآت اليومية**\n\n💰 `{amt}`\n⏰ `{iv}` ساعة\n🔗 مفرد: `{settings.get('referral_bonus_single',50)}`\n🔗 دمج: `{settings.get('referral_bonus_merge',20)}`",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💰",callback_data="admin_edit_reward_amount"), InlineKeyboardButton("⏰",callback_data="admin_edit_reward_interval")],[InlineKeyboardButton("🔗 مفرد",callback_data="admin_edit_ref_single"), InlineKeyboardButton("🔗 دمج",callback_data="admin_edit_ref_merge")],[InlineKeyboardButton("❌",callback_data="close_list")]]),parse_mode=ParseMode.MARKDOWN)
            await callback.answer("🎁"); return
        if data=="admin_edit_reward_amount":
            await msg.delete(); await msg.reply_text(f"💰 **تعديل رصيد الفصول اليومي**\nالقيمة الحالية: `{settings.get('daily_reward_amount',100)}`\nأرسل القيمة الجديدة.\n\nللإلغاء أرسل /cancel")
            user_data[uid]={"awaiting_reward_amount":True}; await callback.answer("💰"); return
        if data=="admin_edit_reward_interval":
            await msg.delete(); await msg.reply_text(f"⏰ **تعديل مدة تجديد الرصيد**\nالمدة الحالية: `{settings.get('daily_reward_interval',86400)//3600}` ساعة.\nأرسل المدة الجديدة بالساعات.\n\nللإلغاء أرسل /cancel")
            user_data[uid]={"awaiting_reward_interval":True}; await callback.answer("⏰"); return
        if data=="admin_edit_ref_single":
            await msg.delete(); await msg.reply_text(f"🔗 **تعديل مكافأة إحالة التحميل الفردي**\nالقيمة الحالية: `{settings.get('referral_bonus_single',50)}` فصل.\nأرسل المكافأة الجديدة.\n\nللإلغاء أرسل /cancel")
            user_data[uid]={"awaiting_ref_single_amount":True}; await callback.answer("🔗"); return
        if data=="admin_edit_ref_merge":
            await msg.delete(); await msg.reply_text(f"🧩 **تعديل مكافأة إحالة الدمج**\nالقيمة الحالية: `{settings.get('referral_bonus_merge',20)}` فصل دمج.\nأرسل المكافأة الجديدة.\n\nللإلغاء أرسل /cancel")
            user_data[uid]={"awaiting_ref_merge_amount":True}; await callback.answer("🔗"); return
        if data=="admin_gifts_section":
            await msg.edit_text("🎉 **قسم هدايا الفصول**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎁 جميع",callback_data="admin_gift_all"), InlineKeyboardButton("🎯 فرد",callback_data="admin_gift_one")],[InlineKeyboardButton("❌",callback_data="close_list")]]),parse_mode=ParseMode.MARKDOWN)
            await callback.answer("🎉"); return
        if data=="admin_gift_all":
            await msg.delete(); await msg.reply_text("🎁 **هدية دمج لجميع الأعضاء**\nأرسل عدد فصول الدمج التي تريد إضافتها لكل مستخدم.\n\nللإلغاء أرسل /cancel")
            user_data[uid]={"awaiting_gift_all":True}; await callback.answer("🎁"); return
        if data=="admin_gift_one":
            await msg.delete(); await msg.reply_text("🎯 **إرسال هدية دمج إلى عضو**\nأرسل آيدي المستخدم أو @username.\n\nللإلغاء أرسل /cancel")
            user_data[uid]={"awaiting_gift_one_id":True}; await callback.answer("🎯"); return
        if data=="admin_manage_admins":
            await msg.edit_text(f"👮‍♂️ **الأدمنز** (رئيسي: {len(ADMINS)} | مضاف: {len(get_all_added_admins())})", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ إضافة أدمن",callback_data="admin_add_new"), InlineKeyboardButton("🗑️ حذف أدمن",callback_data="admin_remove_one")],[InlineKeyboardButton("📋 قائمة الأدمنز",callback_data="admin_list_admins"), InlineKeyboardButton("❌ إغلاق",callback_data="close_list")]]),parse_mode=ParseMode.MARKDOWN)
            await callback.answer("👮"); return
        if data=="admin_add_new":
            await msg.delete(); await msg.reply_text("👮 **إضافة أدمن جديد**\nأرسل آيدي المستخدم أو @username.\n\nللإلغاء أرسل /cancel")
            user_data[uid]={"awaiting_add_admin":True}; await callback.answer("➕"); return
        if data=="admin_remove_one":
            alist=get_all_added_admins()
            if not alist: await msg.edit_text("👮 **لا يوجد أدمنز مضافون حالياً.**"); await callback.answer("⚠️"); return
            kb=[[InlineKeyboardButton(f"🗑️ {a}",callback_data=f"adm_del_{a}")] for a in alist]
            kb.append([InlineKeyboardButton("❌",callback_data="close_list")])
            await msg.edit_text("🗑️ **اختر العنصر الذي تريد حذفه:**",reply_markup=InlineKeyboardMarkup(kb)); await callback.answer("🗑️"); return
        if data.startswith("adm_del_"):
            try:
                a=int(data[8:])
                if remove_added_admin(a):
                    await msg.edit_text(f"👮 **تم حذف الأدمن** `{a}` **من قائمة المشرفين.**")
                    try: await client.send_message(a,"👮 **تم إلغاء صلاحيات الأدمن الخاصة بك.**\nلم تعد قادراً على استخدام لوحة الإدارة.",parse_mode=ParseMode.MARKDOWN)
                    except: pass
                else: await msg.edit_text("⚠️ **تعذّر تنفيذ الطلب**\nراجع البيانات المطلوبة وحاول مجدداً.")
            except: pass
            await callback.answer("✅"); return
        if data=="admin_list_admins":
            txt="👮‍♂️ **قائمة الأدمنز المسجلين**\n\n"
            for a in ADMINS + get_all_added_admins(): txt+=f"• `{a}`\n"
            await msg.edit_text(txt,parse_mode=ParseMode.MARKDOWN); await callback.answer("📋"); return
        if data=="admin_backup_section":
            bc=len(get_all_bots()); cnt=len([f for f in os.listdir(BACKUP_DIR) if f.endswith(".zip")]) if os.path.exists(BACKUP_DIR) else 0
            await msg.edit_text(f"💾 **حالة النسخ الاحتياطي**\n\n📦 النسخ المحفوظة: `{cnt}`\n🤖 بوتات النسخ المتاحة: `{bc}`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f"📤 إنشاء وإرسال ({bc})",callback_data="backup_create_send")],[InlineKeyboardButton("📥 استعادة نسخة",callback_data="backup_restore")],[InlineKeyboardButton("🗑️ حذف كل النسخ",callback_data="backup_delete_all")],[InlineKeyboardButton("❌ إغلاق",callback_data="close_list")]]),parse_mode=ParseMode.MARKDOWN)
            await callback.answer("💾"); return
        if data=="backup_create_send":
            if not get_all_bots(): await callback.answer("⚠️",show_alert=True); return
            await callback.answer("⏳"); await msg.edit_text("⏳ **جارٍ تنفيذ العملية**\nيرجى الانتظار حتى يكتمل الطلب.")
            s,f,_=await send_zip_via_added_bots(manual=True)
            await msg.edit_text(f"📦 **انتهت عملية إنشاء وإرسال النسخ**\n✅ نجح الإرسال: `{s}`\n❌ فشل الإرسال: `{f}`"); return
        if data=="backup_restore":
            await msg.delete(); await msg.reply_text("📥 **استعادة نسخة احتياطية**\nأرسل ملف النسخة بصيغة ZIP.\n\nللإلغاء أرسل /cancel")
            user_data[uid]={"awaiting_backup_restore":True}; await callback.answer("📥"); return
        if data=="backup_delete_all":
            try:
                fs=[f for f in os.listdir(BACKUP_DIR) if f.endswith(".zip")]
                for f in fs: os.remove(os.path.join(BACKUP_DIR,f))
                await msg.edit_text(f"🗑️ **اكتمل حذف النسخ الاحتياطية**\nتم حذف `{len(fs)}` ملف ZIP.")
            except Exception as e: await msg.edit_text(f"❌ {e}")
            await callback.answer("✅"); return
        if data=="admin_bots_section":
            await msg.edit_text(f"🤖 **إدارة بوتات النسخ** ({len(get_all_bots())})", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ إضافة بوت",callback_data="bots_add_token"), InlineKeyboardButton("🗑️ حذف بوت",callback_data="bots_remove")],[InlineKeyboardButton("📋 قائمة البوتات",callback_data="bots_list"), InlineKeyboardButton("❌ إغلاق",callback_data="close_list")]]),parse_mode=ParseMode.MARKDOWN)
            await callback.answer("🤖"); return
        if data=="bots_add_token":
            await msg.delete(); await msg.reply_text("➕ `اسم | توكن | آيدي`\n\n/cancel",parse_mode=ParseMode.MARKDOWN)
            user_data[uid]={"awaiting_bot_token":True}; await callback.answer("➕"); return
        if data=="bots_remove":
            bots=get_all_bots()
            if not bots: await msg.edit_text("🤖 **لا توجد بوتات نسخ مسجلة حالياً.**\n\nيمكنك إضافة بوت جديد من زر الإضافة."); await callback.answer("⚠️"); return
            kb=[[InlineKeyboardButton(f"🗑️ {info.get('name','?')}",callback_data=f"bot_del_{bid}")] for bid,info in bots.items()]
            kb.append([InlineKeyboardButton("❌",callback_data="close_list")])
            await msg.edit_text("🗑️ **اختر العنصر الذي تريد حذفه:**",reply_markup=InlineKeyboardMarkup(kb)); await callback.answer("🗑️"); return
        if data.startswith("bot_del_"):
            bid=data[8:]; ok,info=remove_bot_token(bid)
            await msg.edit_text("🤖 **تم حذف البوت من قائمة النسخ.**" if ok else "⚠️ **تعذّر حذف البوت.**\nقد يكون غير موجود في القائمة."); await callback.answer("✅" if ok else "⚠️"); return
        if data=="bots_list":
            bots=get_all_bots()
            if not bots: await msg.edit_text("🤖 **لا توجد بوتات نسخ مسجلة حالياً.**\n\nيمكنك إضافة بوت جديد من زر الإضافة."); await callback.answer("📋"); return
            txt=f"🤖 **قائمة بوتات النسخ المسجلة**\n\n"
            for bid,info in bots.items(): txt+=f"🤖 **{info.get('name','?')}**\n🆔 `{bid}`\n📬 `{info.get('target_id','—')}`\n\n"
            await msg.edit_text(txt[:4000],parse_mode=ParseMode.MARKDOWN); await callback.answer("📋"); return
        if data=="admin_forcesub_section":
            chs=settings.get("force_sub_channels",[]); ch_list="\n".join(f"• `{ch}`" for ch in chs[:5]) or "_لا قنوات_"
            await msg.edit_text(f"📢 **الاشتراك الإجباري** ({len(chs)})\n\n{ch_list}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ إضافة قناة",callback_data="admin_add_sub_channel"), InlineKeyboardButton("🗑️ حذف قناة",callback_data="admin_del_sub_channel")],[InlineKeyboardButton("✏️ تعديل أسماء الأزرار",callback_data="admin_edit_sub_btns")],[InlineKeyboardButton("📝 نص رسالة الاشتراك",callback_data="admin_set_sub_message"), InlineKeyboardButton("🖼️ صورة الاشتراك",callback_data="admin_set_sub_image")],[InlineKeyboardButton("❌ إغلاق",callback_data="close_list")]]),parse_mode=ParseMode.MARKDOWN)
            await callback.answer("📢"); return
        if data=="admin_edit_sub_btns":
            chs=settings.get("force_sub_channels",[])
            if not chs: await callback.answer("⚠️", show_alert=True); return
            kb=[]
            for ch in chs:
                c_ch = ch[1:] if ch.startswith("@") else ch
                name = settings.get("force_sub_buttons", {}).get(ch, f"اشترك في {ch}")
                kb.append([InlineKeyboardButton(name, callback_data=f"edit_sub_btn_{c_ch}")])
            kb.append([InlineKeyboardButton("🔙",callback_data="admin_forcesub_section")])
            await msg.edit_text("🧭 **اختر القناة التي تريد تعديل اسم زرها:**", reply_markup=InlineKeyboardMarkup(kb)); await callback.answer("✏️"); return
        if data.startswith("edit_sub_btn_"):
            c_ch = data.replace("edit_sub_btn_", ""); ch = f"@{c_ch}"
            user_data[uid] = {"awaiting_sub_btn_name": ch}; await msg.delete()
            await msg.reply_text(f"🔘 **تعديل اسم زر قناة الاشتراك**\nالقناة: `{ch}`\nأرسل الاسم الجديد الذي سيظهر على الزر.\n\nللإلغاء أرسل /cancel"); await callback.answer("✏️"); return
        if data=="admin_add_sub_channel":
            await msg.delete(); await msg.reply_text("📢 **أرسل معرف القناة**\nمثال: `@my_channel`\nتأكد أن البوت مشرف في القناة.\n\nللإلغاء أرسل /cancel")
            user_data[uid]={"awaiting_sub_channel_add":True}; await callback.answer("➕"); return
        if data=="admin_del_sub_channel":
            chs=settings.get("force_sub_channels",[])
            if not chs: await msg.edit_text("📢 **لا توجد قنوات اشتراك إجباري**\n\nأضف قناة أولاً حتى تتمكن من إدارتها."); await callback.answer("⚠️"); return
            kb=[[InlineKeyboardButton(f"🗑️ {ch}",callback_data=f"del_sub_{ch}")] for ch in chs]
            kb.append([InlineKeyboardButton("❌",callback_data="close_list")])
            await msg.edit_text("🗑️ **اختر العنصر الذي تريد حذفه:**",reply_markup=InlineKeyboardMarkup(kb)); await callback.answer("🗑️"); return
        if data.startswith("del_sub_"):
            ch=data[8:]; chs=settings.get("force_sub_channels",[])
            if ch in chs:
                chs.remove(ch); settings["force_sub_channels"]=chs
                b=settings.get("force_sub_buttons",{}); b.pop(ch,None); settings["force_sub_buttons"]=b; save_settings()
                await msg.edit_text(f"✅ `{ch}`")
            else: await msg.edit_text("⚠️ **تعذّر تنفيذ الطلب**\nراجع البيانات المطلوبة وحاول مجدداً.")
            await callback.answer("✅"); return
        if data=="admin_set_sub_message":
            await msg.delete(); await msg.reply_text("📝 **إرسال نص الرسالة الجديدة**\nأرسل النص الذي تريد حفظه.\n\nللإلغاء أرسل /cancel")
            user_data[uid]={'awaiting_sub_message':True}; await callback.answer("📝"); return
        if data=="admin_set_sub_image":
            await msg.delete(); await msg.reply_text("🖼️ **إرسال صورة الآن**\nأرسل الصورة كصورة داخل تيليجرام حتى يتم حفظها في إعدادات البوت.\n\nللإلغاء أرسل /cancel")
            user_data[uid]={'awaiting_sub_image':True}; await callback.answer("🖼️"); return
        if data=="admin_add_bdf":
            await msg.delete(); await msg.reply_text("🖼️ **إرسال صورة الآن**\nأرسل الصورة كصورة داخل تيليجرام حتى يتم حفظها في إعدادات البوت.\n\nللإلغاء أرسل /cancel")
            user_data[uid]={'awaiting_bdf':True}; await callback.answer("🖼️"); return
        if data=="admin_del_bdf":
            settings["bdf_image"]=None; save_settings(); await msg.edit_text("🖼️ **تم حذف صورة BDF بنجاح.**"); await callback.answer("✅"); return
        if data=="admin_set_welcome_image":
            await msg.delete(); await msg.reply_text("🖼️ **إرسال صورة الآن**\nأرسل الصورة كصورة داخل تيليجرام حتى يتم حفظها في إعدادات البوت.\n\nللإلغاء أرسل /cancel")
            user_data[uid]={'awaiting_welcome_image':True}; await callback.answer("🖼️"); return
        if data=="admin_del_welcome_image":
            settings["welcome_image"]=None; save_settings(); await msg.edit_text("👋 **تم حذف صورة الترحيب بنجاح.**"); await callback.answer("✅"); return
        if data=="admin_set_favorites_image":
            await msg.delete(); await msg.reply_text("🖼️ **إرسال صورة الآن**\nأرسل الصورة كصورة داخل تيليجرام حتى يتم حفظها في إعدادات البوت.\n\nللإلغاء أرسل /cancel")
            user_data[uid]={'awaiting_favorites_image':True}; await callback.answer("🖼️"); return
        if data=="admin_del_favorites_image":
            settings["favorites_image"]=None; save_settings(); await msg.edit_text("⭐ **تم حذف صورة المفضلة بنجاح.**"); await callback.answer("✅"); return
        if data=="admin_set_results_image":
            await msg.delete(); await msg.reply_text("🖼️ **إرسال صورة الآن**\nأرسل الصورة كصورة داخل تيليجرام حتى يتم حفظها في إعدادات البوت.\n\nللإلغاء أرسل /cancel")
            user_data[uid]={'awaiting_results_image':True}; await callback.answer("🖼️"); return
        if data=="admin_del_results_image":
            settings["results_image"]=None; save_settings(); await msg.edit_text("🔍 **تم حذف صورة النتائج بنجاح.**"); await callback.answer("✅"); return
        if data=="admin_set_sources_image":
            await msg.delete(); await msg.reply_text("🖼️ **إرسال صورة الآن**\nأرسل الصورة كصورة داخل تيليجرام حتى يتم حفظها في إعدادات البوت.\n\nللإلغاء أرسل /cancel")
            user_data[uid]={'awaiting_sources_image':True}; await callback.answer("🖼️"); return
        if data=="admin_del_sources_image":
            settings["sources_image"]=None; save_settings(); await msg.edit_text("📚 **تم حذف صورة المصادر بنجاح.**"); await callback.answer("✅"); return
        if data=="admin_set_welcome":
            await msg.delete(); await msg.reply_text("📝 **إرسال نص الرسالة الجديدة**\nأرسل النص الذي تريد حفظه.\n\nللإلغاء أرسل /cancel")
            user_data[uid]={'awaiting_welcome':True}; await callback.answer("📝"); return
        if data=="admin_del_welcome":
            settings["welcome_message"]=DEFAULTS["welcome_message"]; save_settings(); await msg.edit_text("👋 **تمت استعادة رسالة الترحيب الافتراضية.**"); await callback.answer("✅"); return
        if data=="admin_cleanup":
            r=cleanup_empty_favorites(); await msg.edit_text(f"🧹 **اكتمل تنظيف قاعدة المفضلات**\nتمت إزالة `{r}` من السجلات الفارغة."); await callback.answer("✅"); return

    await callback.answer("⚠️", show_alert=True)

# ============ Text Handler ============
@app.on_message(filters.private & filters.text & ~filters.command(["admin","start","search","check","cancel"]))
async def handle_all_text(client,message):
    uid=message.from_user.id
    if settings.get("maintenance_mode", False) and not is_admin_any(uid): return

    if user_data.get(uid,{}).get("awaiting_complaint"):
        text=message.text.strip()
        if not text or len(text)<3: await message.reply_text("⚠️ **نص الشكوى قصير جداً**\nاكتب تفاصيل أكثر (3 أحرف على الأقل) حتى نتمكن من فهم المشكلة."); return
        add_complaint(uid,message.from_user.username or "",message.from_user.first_name or "",text)
        user_data.pop(uid,None); await message.reply_text("✅ **تم الإرسال**")
        try: await client.send_message(OWNER_ID,f"📬 `{uid}`\n💬 {text}",parse_mode=ParseMode.MARKDOWN)
        except: pass
        return

    if user_data.get(uid, {}).get('awaiting_merge_range'):
        m = re.match(r'^\s*(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*$', message.text.strip())
        if not m: await message.reply_text("🔢 **صيغة نطاق الفصول غير صحيحة.**\nأرسل رقم البداية ثم شرطة ثم رقم النهاية، مثال: `1-10`."); return
        start_num, end_num = float(m.group(1)), float(m.group(2))
        if start_num > end_num: start_num, end_num = end_num, start_num
        info = user_data[uid]['awaiting_merge_range']; src, ident, chs = info['src'], info['ident'], info['chapters']
        selected = []
        for ch in chs:
            num = None
            try:
                raw_num = str(ch.get("number") or ch.get("num_str") or ch.get("display_text") or ch.get("title") or "")
                m2 = re.search(r"(\d+(?:\.\d+)?)", raw_num)
                if m2: num = float(m2.group(1))
            except: pass
            if num is not None and start_num <= num <= end_num: selected.append(ch)
        if not selected: await message.reply_text("📚 **لم يتم العثور على فصول ضمن هذا النطاق.**\nتحقق من أرقام الفصول وأرسل نطاقاً آخر."); return
        count = len(selected); mmax = PDF_MAX_CHAPTERS
        if count > mmax: await message.reply_text(f"📄 **عدد الفصول يتجاوز الحد المسموح.**\nطلبت `{count}` فصلاً، والحد الأقصى لهذا الملف `{mmax}` فصول."); return
        if not is_vip(uid):
            remaining = get_merge_remaining(uid)
            if remaining < count: await message.reply_text(f"💳 **رصيد الدمج غير كافٍ.**\nالمطلوب: `{count}` فصل.\nالمتاح: `{int(remaining)}` فصل.\nيمكنك تجديد الرصيد أو ترقية حسابك إلى VIP."); return
        if not settings.get("allow_parallel_downloads", False):
            if is_downloading(uid) or not try_lock_download(uid): await message.reply_text("⏳ **يوجد تحميل آخر قيد التنفيذ.**\nانتظر حتى يكتمل ثم حاول مجدداً."); return
        locked = not settings.get("allow_parallel_downloads", False)
        try:
            success, rem = try_deduct_merge(uid, count)
            if not success: await message.reply_text("❌ **تعذّر بدء تحميل الفصل.**\nلم يتم خصم الرصيد؛ حاول مرة أخرى بعد قليل."); return
            user_data[uid].pop('awaiting_merge_range', None)
            title = user_data[uid].get('title', 'مانجا')
            lm = await message.reply_text(f"🧩 **بدأ تجهيز ملف دمج الفصول**\n📚 النطاق: `{start_num:g} → {end_num:g}`\n🔢 عدد الفصول: `{count}`\n⏳ يرجى الانتظار...")
            chapter_groups = []
            total_images = 0
            api = await asyncio.to_thread(get_source,src)

            # Extract chapter image lists concurrently, while showing completed chapter counts.
            extract_sem = asyncio.Semaphore(4)
            progress_lock = asyncio.Lock()
            progress = {"done": 0, "ok": 0, "images": 0}

            async def extract_chapter(index, chapter):
                urls = None
                async with extract_sem:
                    try:
                        urls = await asyncio.to_thread(api.get_chapter_images, chapter)
                    except Exception as exc:
                        pass
                async with progress_lock:
                    progress["done"] += 1
                    if urls:
                        progress["ok"] += 1
                        progress["images"] += len(urls)
                    await lm.edit_text(
                        f"🧩 **استخراج الفصول**\n"
                        f"📚 المكتمل: `{progress['done']}/{count}`\n"
                        f"✅ الناجح: `{progress['ok']}`\n"
                        f"🖼️ الصور المستخرجة: `{progress['images']}`"
                    )
                return index, urls or None

            await lm.edit_text(
                f"🧩 **استخراج الفصول**\n📚 المكتمل: `0/{count}`\n"
                f"✅ الناجح: `0`\n🖼️ الصور المستخرجة: `0`"
            )
            extracted = await asyncio.gather(
                *(extract_chapter(i, ch) for i, ch in enumerate(selected))
            )
            # Rebuild groups in the original selected-chapter order.
            for _, urls in sorted(extracted, key=lambda item: item[0]):
                if urls:
                    chapter_groups.append(urls)
                    total_images += len(urls)

            if not chapter_groups:
                refund_merge(uid,count)
                await lm.edit_text("❌ لم يستخرج المحرك صور الفصول")
                return
            await lm.edit_text(f"🖼️ **تم استخراج الصور بنجاح.**\n📥 جارٍ تنزيل `{total_images}` صورة بالتوازي وتجهيز ملف PDF...")
            # One shared HTTP session; all chapter image requests run concurrently.
            buf = await download_images_parallel(chapter_groups,client=client)
            if not buf: refund_merge(uid, count); await lm.edit_text("❌ **فشل تجهيز ملف دمج الفصول.**\nتمت إعادة الرصيد إلى حسابك."); return
            await lm.edit_text("📤 **اكتمل تجهيز الملف.**\nجارٍ رفع ملف PDF إلى تيليجرام...")
            safe_title = re.sub(r"_+", " ", re.sub(r'[\\/:*?"<>|]', '', title)).strip()[:50] or "manga"
            try:
                await send_pdf_direct(chat_id=message.chat.id, document=buf, file_name=f"Merge {start_num:g}-{end_num:g} - {safe_title}.pdf",
                    caption=f"🧩 ملف مدمج\n\n📚 {title}\n📖 {start_num:g} → {end_num:g}\n📄 {total_images}")
                increment_download_count(uid)
            except Exception as upload_error:
                refund_merge(uid, count)
                print(f"[MTProto upload] {type(upload_error).__name__}: {upload_error}", flush=True)
                await lm.edit_text(
                    "❌ **تعذّر رفع ملف PDF إلى تيليجرام.**\\n"
                    "تم إرجاع رصيد الدمج إلى حسابك؛ حاول مرة أخرى لاحقاً."
                )
                return
            finally:
                try: buf.close()
                except Exception: pass
                del buf
                gc.collect()
            try: await lm.delete()
            except: pass
        finally:
            if locked: unlock_download(uid)
        return

    gs = user_data.get(uid, {}).get("gift_link_step")
    if gs:
        try:
            val = int(message.text.strip())
            if val < 0: raise ValueError
        except: await message.reply_text("🔢 **المدخل غير صحيح**\nأرسل رقماً صحيحاً فقط، ثم حاول مجدداً."); return
        if gs == "single":
            user_data[uid]["gift_link_single"] = val; user_data[uid]["gift_link_step"] = "merge"
            await message.reply_text(f"✅ فردي: `{val}`\n\n🧩 **المدمجة**؟\n(0 للتخطي)\n\n/cancel", parse_mode=ParseMode.MARKDOWN); return
        if gs == "merge":
            user_data[uid]["gift_link_merge"] = val; user_data[uid]["gift_link_step"] = "max"
            await message.reply_text(f"✅ دمج: `{val}`\n\n👥 **الحد الأقصى**؟\n(>0)\n\n/cancel", parse_mode=ParseMode.MARKDOWN); return
        if gs == "max":
            if val <= 0: await message.reply_text("👥 **عدد المستخدمين يجب أن يكون أكبر من صفر.** أرسل رقماً موجباً."); return
            user_data[uid]["gift_link_max"] = val; user_data[uid]["gift_link_step"] = "expiry"
            await message.reply_text(f"✅ `{val}`\n\n⏰ الوحدة:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏰ ساعة", callback_data="gift_expiry_hours"), InlineKeyboardButton("⏱️ دقيقة", callback_data="gift_expiry_minutes")],[InlineKeyboardButton("❌ إغلاق", callback_data="close_list")]]), parse_mode=ParseMode.MARKDOWN); return
        if gs == "expiry_value":
            if val <= 0: await message.reply_text("⏳ **مدة صلاحية الرابط يجب أن تكون أكبر من صفر.** أرسل قيمة موجبة."); return
            unit = user_data[uid].get("gift_expiry_unit", "hours"); seconds = val * 3600 if unit == "hours" else val * 60
            expires_at = time.time() + seconds
            single = user_data[uid]["gift_link_single"]; merge = user_data[uid]["gift_link_merge"]; max_users = user_data[uid]["gift_link_max"]
            code = create_gift_link(single, merge, max_users, expires_at, uid)
            bot = BOT_USERNAME or "bot"; link = f"https://t.me/{bot}?start=gift_{code}"
            unit_name = "ساعة" if unit == "hours" else "دقيقة"
            await message.reply_text(
                f"✅ **تم إنشاء الرابط**\n\n🔗 `{link}`\n\n📖 `{single}`\n🧩 `{merge}`\n👥 `{max_users}`\n⏰ `{val}` {unit_name}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📤 مشاركة", url=f"https://t.me/share/url?url={quote(link)}&text={quote('🎁 هدية!')}")],[InlineKeyboardButton("⚙️ إدارة", callback_data=f"admin_gift_manage_{code}")],[InlineKeyboardButton("❌ إغلاق", callback_data="close_list")]]), parse_mode=ParseMode.MARKDOWN)
            user_data.pop(uid, None); return

    if user_data.get(uid, {}).get("awaiting_gift_allowed_users"):
        code = user_data[uid]["awaiting_gift_allowed_users"]; ids = []
        for tok in re.split(r'[\s,]+', message.text.strip()):
            if not tok: continue
            try:
                if tok.startswith("@"): continue
                user_id = int(tok)
                if user_id > 0: ids.append(user_id)
            except: pass
        if not ids: await message.reply_text("⚠️ **لم أتعرف على أي مستخدم.**\nأرسل آيديات تيليجرام الرقمية فقط، مفصولة بمسافة أو فاصلة."); return
        set_gift_allowed_users(code, ids); user_data.pop(uid, None)
        await message.reply_text(f"✅ `{len(ids)}` مستخدم", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️", callback_data=f"admin_gift_manage_{code}")],[InlineKeyboardButton("❌", callback_data="close_list")]]), parse_mode=ParseMode.MARKDOWN); return
    if user_data.get(uid, {}).get("awaiting_gift_channel"):
        code = user_data[uid]["awaiting_gift_channel"]; ch = message.text.strip()
        if not (ch.startswith("@") or ch.startswith("-100")): await message.reply_text("📢 **معرّف القناة غير صحيح.**\nأرسل @username أو آيدي القناة الذي يبدأ بـ -100."); return
        try:
            await client.get_chat(ch); test = await client.send_message(ch, "✅"); await client.delete_messages(ch, test.id)
        except Exception as e: await message.reply_text(f"❌ {e}"); return
        set_gift_channel(code, ch); user_data.pop(uid, None)
        await message.reply_text(f"✅ `{ch}`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️", callback_data=f"admin_gift_manage_{code}")],[InlineKeyboardButton("❌", callback_data="close_list")]]), parse_mode=ParseMode.MARKDOWN); return
    if user_data.get(uid, {}).get("awaiting_gift_post_interval"):
        code = user_data[uid]["awaiting_gift_post_interval"]
        try:
            h = int(message.text.strip())
            if h < 1 or h > 24: raise ValueError
        except: await message.reply_text("⏰ **الفترة غير صحيحة.** أرسل عدداً من 1 إلى 24 ساعة."); return
        set_gift_interval(code, h); user_data.pop(uid, None)
        await message.reply_text(f"✅ كل `{h}` ساعة", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⚙️", callback_data=f"admin_gift_manage_{code}")],[InlineKeyboardButton("❌", callback_data="close_list")]]), parse_mode=ParseMode.MARKDOWN); return

    if not is_admin_any(uid): return

    if user_data.get(uid,{}).get("awaiting_merge_limit"):
        try:
            v=int(message.text.strip())
            if v<2: await message.reply_text("🧩 **حد الدمج يجب أن يكون 2 على الأقل.** أرسل قيمة أكبر أو تساوي 2."); return
            settings["merge_daily_limit"]=v; save_settings(); user_data.pop(uid,None)
            await message.reply_text(f"✅ `{v}`")
        except: await message.reply_text("🔢 **قيمة حد الدمج غير صالحة.** أرسل رقماً صحيحاً لا يقل عن 2.")
        return
    if user_data.get(uid,{}).get("awaiting_merge_max"):
        try:
            v=int(message.text.strip())
            if v<2 or v>PDF_MAX_CHAPTERS:
                await message.reply_text("⚠️ الحد المسموح من 2 إلى 10"); return
            settings["merge_max_per_file"]=v; save_settings(); user_data.pop(uid,None)
            await message.reply_text(f"✅ الحد لكل ملف: `{v}`")
        except: await message.reply_text("🔢 **قيمة حد الفصول في الملف غير صالحة.** أرسل رقماً ضمن الحد المسموح.")
        return
    if user_data.get(uid,{}).get("awaiting_daily_amount"):
        try:
            v=int(message.text.strip())
            if v<=0: raise ValueError
            settings["daily_reward_amount"]=v; save_settings(); user_data.pop(uid,None)
            await message.reply_text(f"✅ `{v}`")
        except: await message.reply_text("🔢 **عدد الفصول اليومي غير صالح.** أرسل رقماً أكبر من صفر.")
        return
    if user_data.get(uid,{}).get("awaiting_ref_single_amount"):
        try: settings["referral_bonus_single"]=int(message.text.strip()); save_settings(); user_data.pop(uid,None); await message.reply_text("🔗 **تم تحديث مكافأة الإحالة للفصول الفردية بنجاح.**")
        except: await message.reply_text("🔢 **قيمة مكافأة الإحالة الفردية غير صحيحة.** أرسل رقماً صحيحاً.")
        return
    if user_data.get(uid,{}).get("awaiting_ref_merge_amount"):
        try: settings["referral_bonus_merge"]=int(message.text.strip()); save_settings(); user_data.pop(uid,None); await message.reply_text("🧩 **تم تحديث مكافأة الإحالة للفصول المدمجة بنجاح.**")
        except: await message.reply_text("🔢 **قيمة مكافأة الإحالة للدمج غير صحيحة.** أرسل رقماً صحيحاً.")
        return
    if user_data.get(uid,{}).get("awaiting_merge_gift_one_id"):
        t=message.text.strip(); tid=None
        try: tid=int(t)
        except: await message.reply_text("👤 **لم أتمكن من العثور على المستخدم.** أرسل آيدي تيليجرام الرقمي فقط."); return
        user_data[uid]={"awaiting_merge_gift_one_amount":tid}; await message.reply_text(f"👤 **تم تحديد المستخدم** `{tid}`\n🎁 أرسل عدد فصول الدمج التي تريد إضافتها له:"); return
    if user_data.get(uid,{}).get("awaiting_merge_gift_one_amount"):
        try: a=int(message.text.strip())
        except: await message.reply_text("🔢 **عدد فصول الدمج غير صالح.** أرسل رقماً صحيحاً."); return
        tid=user_data[uid]["awaiting_merge_gift_one_amount"]; add_merge_bonus(tid,a)
        await message.reply_text(f"🧩 **تمت إضافة {a} من فصول الدمج إلى المستخدم** `{tid}`.")
        try: await client.send_message(tid,f"🧩 +{a} دمج",parse_mode=ParseMode.MARKDOWN)
        except: pass
        user_data.pop(uid,None); return
    if user_data.get(uid,{}).get("awaiting_merge_gift_all"):
        try: a=int(message.text.strip())
        except: await message.reply_text("🔢 **عدد الهدية غير صالح.** أرسل رقماً صحيحاً."); return
        await message.reply_text(f"🎁 **جارٍ توزيع {a} من فصول الدمج على جميع المستخدمين...**\nيرجى الانتظار حتى تظهر نتيجة الإرسال.")
        s=f=0
        for u in get_all_user_ids():
            try:
                add_merge_bonus(u,a)
                try: await client.send_message(u,f"🧩 +{a} دمج",parse_mode=ParseMode.MARKDOWN); s+=1
                except: f+=1
                await asyncio.sleep(0.05)
            except: f+=1
        user_data.pop(uid,None); await message.reply_text(f"🎉 **اكتمل توزيع هدية الدمج**\n✅ وصل إلى: `{s}` مستخدم\n❌ تعذّر الإرسال إلى: `{f}` مستخدم"); return
    if user_data.get(uid,{}).get("awaiting_vip_contact"):
        t=message.text.strip()
        if t.startswith("@") and len(t)>=4: settings["vip_contact_second"]=t; save_settings(); user_data.pop(uid,None); await message.reply_text(f"✅ `{t}`"); return
        await message.reply_text("👤 **اسم المستخدم غير صحيح.** أرسل معرفاً يبدأ بـ @ مثل @username."); return
    if user_data.get(uid,{}).get('awaiting_broadcast'):
        t=message.text; await message.reply_text("📢 **بدأ إرسال الإعلان إلى المستخدمين.**\nسأعرض لك عدد الرسائل الناجحة والفاشلة بعد الانتهاء.")
        s=f=0
        for u in get_all_user_ids():
            try: await client.send_message(u,f"📢 **إعلان**\n\n{t}",parse_mode=ParseMode.MARKDOWN); s+=1; await asyncio.sleep(0.05)
            except: f+=1
        user_data.pop(uid,None); await message.reply_text(f"📢 **اكتمل إرسال الإعلان**\n✅ تم الإرسال إلى: `{s}` مستخدم\n❌ تعذّر الإرسال إلى: `{f}` مستخدم"); return
    for k in ['awaiting_bdf','awaiting_welcome_image','awaiting_favorites_image','awaiting_results_image','awaiting_sources_image','awaiting_sub_image']:
        if user_data.get(uid,{}).get(k): await message.reply_text("🖼️ **مطلوب إرسال صورة**\nأرسل الصورة كصورة داخل تيليجرام، وليس كنص.\n\nللإلغاء أرسل /cancel"); return
    if user_data.get(uid,{}).get('awaiting_welcome'):
        settings["welcome_message"]=message.text; save_settings(); user_data.pop(uid,None); await message.reply_text("👋 **تم حفظ رسالة الترحيب الجديدة بنجاح.**"); return
    if user_data.get(uid,{}).get('awaiting_sub_channel_add'):
        ch=message.text.strip(); ch=ch[1:] if ch.startswith("@") else ch; c2="@"+ch
        chs=settings.get("force_sub_channels",[])
        if c2 not in chs: chs.append(c2); settings["force_sub_channels"]=chs; save_settings()
        user_data.pop(uid,None); await message.reply_text(f"📢 **تمت إضافة قناة الاشتراك الإجباري** `{c2}` بنجاح."); return
    if user_data.get(uid,{}).get("awaiting_sub_btn_name"):
        ch=user_data[uid]["awaiting_sub_btn_name"]; b=settings.get("force_sub_buttons",{}); b[ch]=message.text.strip()
        settings["force_sub_buttons"]=b; save_settings(); user_data.pop(uid,None); await message.reply_text("🔘 **تم تحديث اسم زر الاشتراك بنجاح.**"); return
    if user_data.get(uid,{}).get('awaiting_sub_message'):
        settings["force_sub_message"]=message.text; save_settings(); user_data.pop(uid,None); await message.reply_text("📢 **تم حفظ رسالة الاشتراك الإجباري بنجاح.**"); return
    if user_data.get(uid,{}).get("awaiting_single_caption"):
        txt=message.text
        if "{chapter}" not in txt and "{title}" not in txt: await message.reply_text("⚠️ {chapter}/{title}"); return
        settings["single_caption"]=make_quote(txt); save_settings(); user_data.pop(uid,None); await message.reply_text("📄 **تم حفظ وصف ملف الفصل الجديد.**"); return
    if user_data.get(uid,{}).get("awaiting_reward_amount"):
        try: settings["daily_reward_amount"]=int(message.text.strip()); save_settings(); user_data.pop(uid,None); await message.reply_text("💰 **تم تحديث مكافأة الفصول اليومية بنجاح.**")
        except: await message.reply_text("🔢 **قيمة المكافأة اليومية غير صحيحة.** أرسل رقماً صحيحاً.")
        return
    if user_data.get(uid,{}).get("awaiting_reward_interval"):
        try:
            h=int(message.text.strip()); settings["daily_reward_interval"]=h*3600; save_settings(); user_data.pop(uid,None)
            await message.reply_text(f"✅ {h} ساعة")
        except: await message.reply_text("⏰ **مدة التجديد غير صحيحة.** أرسل عدد ساعات صحيحاً.")
        return
    if user_data.get(uid,{}).get("awaiting_gift_all"):
        try: a=int(message.text.strip())
        except: await message.reply_text("🔢 **عدد الفصول المجانية غير صالح.** أرسل رقماً صحيحاً."); return
        await message.reply_text(f"🎁 **جارٍ توزيع {a} من الفصول المجانية على المستخدمين...**\nيرجى الانتظار حتى يكتمل التوزيع.")
        s=f=0
        for u in get_all_user_ids():
            try:
                add_bonus(u,a)
                try: await client.send_message(u,f"🎁 +{a}",parse_mode=ParseMode.MARKDOWN); s+=1
                except: f+=1
                await asyncio.sleep(0.05)
            except: f+=1
        user_data.pop(uid,None); await message.reply_text(f"🎁 **اكتمل توزيع الفصول المجانية**\n✅ وصل إلى: `{s}` مستخدم\n❌ تعذّر الإرسال إلى: `{f}` مستخدم"); return
    if user_data.get(uid,{}).get("awaiting_gift_one_id"):
        t=message.text.strip(); tid=None
        try: tid=int(t)
        except: await message.reply_text("👤 **لم أتمكن من العثور على المستخدم.** أرسل آيدي تيليجرام الرقمي فقط."); return
        user_data[uid]={"awaiting_gift_one_amount":tid}; await message.reply_text(f"👤 **تم تحديد المستخدم** `{tid}`\n🎁 أرسل عدد الفصول المجانية التي تريد إضافتها له:"); return
    if user_data.get(uid,{}).get("awaiting_gift_one_amount"):
        try: a=int(message.text.strip())
        except: await message.reply_text("🔢 **عدد الفصول المجانية غير صالح.** أرسل رقماً صحيحاً."); return
        tid=user_data[uid]["awaiting_gift_one_amount"]; add_bonus(tid,a)
        await message.reply_text(f"🎁 **تمت إضافة {a} من الفصول المجانية إلى المستخدم** `{tid}`.")
        try: await client.send_message(tid,f"🎁 +{a}",parse_mode=ParseMode.MARKDOWN)
        except: pass
        user_data.pop(uid,None); return
    if user_data.get(uid,{}).get("awaiting_reset_user"):
        t=message.text.strip(); tid=None
        try: tid=int(t)
        except: await message.reply_text("👤 **لم أتمكن من العثور على المستخدم.** أرسل آيدي تيليجرام الرقمي فقط."); return
        reset_user_balance(tid); await message.reply_text(f"♻️ **تم تصفير رصيد المستخدم** `{tid}` بنجاح."); user_data.pop(uid,None); return
    if user_data.get(uid,{}).get("awaiting_ban_user"):
        t=message.text.strip(); tid=None
        try: tid=int(t)
        except: await message.reply_text("👤 **لم أتمكن من العثور على المستخدم.** أرسل آيدي تيليجرام الرقمي فقط."); return
        if tid in OWNER_IDS or tid in ADMINS: await message.reply_text("🛡️ **لا يمكن حظر أدمن أو مالك البوت.**"); user_data.pop(uid,None); return
        if ban_user(tid): await message.reply_text(f"🚫 **تم حظر المستخدم** `{tid}` بنجاح.")
        else: await message.reply_text("⚠️ **لم يتم حظر المستخدم.** ربما هو محظور مسبقاً أو آيديه غير صحيح.")
        user_data.pop(uid,None); return
    if user_data.get(uid,{}).get("awaiting_unban_user"):
        t=message.text.strip(); tid=None
        try: tid=int(t)
        except: await message.reply_text("👤 **لم أتمكن من العثور على المستخدم.** أرسل آيدي تيليجرام الرقمي فقط."); return
        if unban_user(tid): await message.reply_text(f"🔓 **تم رفع الحظر عن المستخدم** `{tid}` بنجاح.")
        else: await message.reply_text("⚠️ **لم يتم رفع الحظر.** تأكد من أن المستخدم موجود في قائمة المحظورين.")
        user_data.pop(uid,None); return
    if user_data.get(uid,{}).get("awaiting_add_admin"):
        t=message.text.strip(); tid=None
        try: tid=int(t)
        except: await message.reply_text("👤 **لم أتمكن من العثور على المستخدم.** أرسل آيدي تيليجرام الرقمي فقط."); return
        ok,m=add_added_admin(tid)
        if ok:
            await message.reply_text(f"👮 **تمت إضافة المستخدم** `{tid}` **كمشرف بنجاح.**")
            try: await client.send_message(tid,"👮 **تمت إضافتك إلى فريق إدارة البوت.**\nيمكنك استخدام /admin لعرض لوحة الأدمن المتاحة لك.",parse_mode=ParseMode.MARKDOWN)
            except: pass
        else: await message.reply_text(f"⚠️ **تعذرت إضافة الأدمن:** {m}")
        user_data.pop(uid,None); return
    plan=user_data.get(uid,{}).get("awaiting_vip_user")
    if plan:
        t=message.text.strip(); tid=None
        try: tid=int(t)
        except: await message.reply_text("👤 **لم أتمكن من العثور على المستخدم.** أرسل آيدي تيليجرام الرقمي فقط."); return
        if add_vip(tid,plan):
            info=get_vip_info(tid); dy=max(0,int((info["expires"]-time.time())//86400))
            await message.reply_text(f"👑 **تم تفعيل VIP للمستخدم** `{tid}`\n📅 الخطة: {VIP_PLAN_NAMES[plan]}\n⏳ المدة المتبقية: `{dy}` يوم")
            try: await client.send_message(tid,f"🎉 **تم تفعيل اشتراك VIP لك!**\n👑 الخطة: {VIP_PLAN_NAMES[plan]}",parse_mode=ParseMode.MARKDOWN)
            except: pass
        else: await message.reply_text("⚠️ **تعذّر تفعيل VIP.** تحقق من آيدي المستخدم وحالة اشتراكه.")
        user_data.pop(uid,None); return
    if user_data.get(uid,{}).get("awaiting_vip_remove"):
        t=message.text.strip(); tid=None
        try: tid=int(t)
        except: await message.reply_text("👤 **لم أتمكن من العثور على المستخدم.** أرسل آيدي تيليجرام الرقمي فقط."); return
        if remove_vip(tid): await message.reply_text(f"👑 **تم إلغاء اشتراك VIP للمستخدم** `{tid}`.")
        else: await message.reply_text("⚠️ **لم يتم إلغاء VIP.** قد لا يكون المستخدم مشتركاً حالياً.")
        user_data.pop(uid,None); return
    if user_data.get(uid,{}).get("awaiting_bot_token"):
        parts=[p.strip() for p in message.text.strip().split("|")]
        if len(parts)!=3: await message.reply_text("🤖 **صيغة إضافة البوت غير صحيحة.** أرسل البيانات بهذا الترتيب:\n`اسم البوت | التوكن | آيدي الهدف`"); return
        bn,tk,tid_s=parts
        try: target_id=int(tid_s)
        except: await message.reply_text("🆔 **آيدي الهدف غير صحيح.** أرسل آيدياً رقمياً."); return
        await message.reply_text("🔎 **جارٍ التحقق من توكن البوت عبر تيليجرام...**\nيرجى الانتظار.")
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"https://api.telegram.org/bot{tk}/getMe",timeout=10) as r:
                    d=await r.json()
                    if not d.get("ok"): await message.reply_text("🤖 **التوكن غير صالح أو لم يقبله تيليجرام.**"); user_data.pop(uid,None); return
                    ru=d["result"].get("username","?")
        except: await message.reply_text("🌐 **تعذّر الاتصال بواجهة تيليجرام للتحقق من التوكن.** حاول مرة أخرى."); user_data.pop(uid,None); return
        ok,m,bid=add_bot_token(tk,bn,uid,target_id=target_id)
        if ok: await message.reply_text(f"✅ @{ru}")
        else: await message.reply_text(f"⚠️ {m}")
        user_data.pop(uid,None); return
    if user_data.get(uid,{}).get("awaiting_backup_restore"):
        await message.reply_text("📦 **الملف غير صالح**\nأرسل نسخة احتياطية بصيغة ZIP."); return

@app.on_message(filters.photo & filters.private)
async def handle_images(client,message):
    uid=message.from_user.id
    if not is_admin_any(uid): return
    mapping={'awaiting_bdf':('bdf_image','BDF'),'awaiting_welcome_image':('welcome_image','ترحيب'),
             'awaiting_favorites_image':('favorites_image','مفضلة'),'awaiting_results_image':('results_image','نتائج'),
             'awaiting_sources_image':('sources_image','مصادر'),'awaiting_sub_image':('force_sub_image','اشتراك')}
    for key,(field,label) in mapping.items():
        if user_data.get(uid,{}).get(key):
            settings[field]=message.photo[-1].file_id; save_settings(); user_data.pop(uid,None)
            await message.reply_text(f"✅ {label}"); return

@app.on_message(filters.document & filters.private)
async def handle_documents(client,message):
    uid=message.from_user.id
    if not is_admin_any(uid): return
    fn = message.document.file_name or ""
    if not fn.lower().endswith(".zip"):
        if user_data.get(uid,{}).get("awaiting_backup_restore"): await message.reply_text("📦 **صيغة الملف غير مدعومة**\nيجب أن تكون النسخة الاحتياطية بامتداد ZIP.")
        return
    await message.reply_text("📥 **بدأ تنزيل النسخة الاحتياطية.**\nيرجى الانتظار حتى يكتمل الفحص والاستعادة.")
    try:
        tp = await message.download(); ok, r, err = restore_from_zip(tp)
        try: os.remove(tp)
        except: pass
        if ok: await message.reply_text(f"✅ {len(r)}")
        else: await message.reply_text(f"❌ {err}")
    except Exception as e: await message.reply_text(f"❌ {e}")
    user_data.pop(uid, None)

async def check_new_chapters():
    """Poll the Manga Engine for the newest chapter of VIP members' favorites."""
    for uid in get_all_user_ids():
        # Favorites and chapter notifications are a VIP-only feature.
        if not is_vip(uid) or not is_notifications_enabled(uid):
            continue

        for fav in get_fav_items(uid):
            if not fav.get("notify", True):
                continue

            try:
                source = fav.get("source")
                manga_url = fav.get("manga_url") or fav.get("identifier")
                api = await asyncio.to_thread(get_source, source)
                info = await asyncio.to_thread(api.get_details, manga_url)
                chapters = (info or {}).get("chapters") or []
                if not chapters:
                    continue

                newest = chapters[0]
                latest = _chapter_tracking_value(newest)
                previous = str(fav.get("last_chapter") or "")
                if not latest:
                    continue

                # First successful check establishes a baseline without a false alert.
                if not previous or previous == "0":
                    set_fav_last_chapter(uid, fav["identifier"], source, latest)
                    continue

                if latest == previous:
                    continue

                chapter_title = _chapter_display_value(newest)
                chapter_url = newest.get("url") if isinstance(newest, dict) else None
                notification = (
                    "🆕 فصل جديد متوفر!\n\n"
                    + "📚 " + str(fav.get("title") or "مانجا") + "\n"
                    + "📖 " + chapter_title
                )
                if chapter_url:
                    notification += "\n🔗 " + str(chapter_url)

                # Advance the saved chapter only after Telegram confirms delivery.
                await app.send_message(uid, notification, disable_web_page_preview=True)
                set_fav_last_chapter(uid, fav["identifier"], source, latest)

            except Exception:
                # Keep the previous checkpoint so a failed fetch/send is retried next cycle.
                continue

async def check_vip_expiry():
    for u in get_expired_vips():
        try: await app.send_message(int(u),"⚠️ **انتهى VIP**",parse_mode=ParseMode.MARKDOWN)
        except: pass
        remove_vip(u)

async def periodic_check():
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        await check_new_chapters(); await check_vip_expiry()

if __name__ == "__main__":
    async def _bootstrap():
        global BOT_USERNAME
        background_tasks = []
        started = False
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()
        installed_signals = []

        def request_shutdown():
            stop_event.set()

        try:
            # Handle Ctrl+C explicitly in the active asyncio loop.
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, request_shutdown)
                    installed_signals.append(sig)
                except (NotImplementedError, RuntimeError):
                    pass

            await app.start()
            started = True

            me = None
            for attempt in range(1, 4):
                try:
                    me = await app.get_me()
                    break
                except Exception:
                    if attempt == 3:
                        raise
                    await asyncio.sleep(2)

            BOT_USERNAME = me.username

            background_tasks = [
                asyncio.create_task(periodic_check(), name="periodic_check"),
                asyncio.create_task(auto_backup_task(), name="auto_backup_task"),
                asyncio.create_task(latest_manga_refresh_task(), name="latest_manga_refresh_task"),
            ]

            print("✅ البوت يعمل عبر aiogram 3. لإيقافه اضغط Ctrl+C", flush=True)
            polling_task = asyncio.create_task(
                app.dispatcher.start_polling(app.bot, handle_signals=False),
                name="telegram_polling",
            )
            stop_task = asyncio.create_task(stop_event.wait(), name="shutdown_signal")
            try:
                done, _ = await asyncio.wait(
                    (polling_task, stop_task),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                # Surface polling failures instead of leaving the process hanging.
                if polling_task in done:
                    await polling_task
            finally:
                for task in (polling_task, stop_task):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(polling_task, stop_task, return_exceptions=True)

        finally:
            # Remove custom signal handlers before closing the event loop.
            for sig in installed_signals:
                try:
                    loop.remove_signal_handler(sig)
                except Exception:
                    pass

            # Cancel and await all background jobs before disconnecting Telegram.
            for task in background_tasks:
                if not task.done():
                    task.cancel()
            if background_tasks:
                await asyncio.gather(*background_tasks, return_exceptions=True)

            if started and app.is_connected:
                try:
                    await app.stop()
                except Exception:
                    pass
            try:
                await close_mtproto_uploader()
            except Exception:
                pass

    try:
        app.run(_bootstrap())
    except KeyboardInterrupt:
        # A fallback for interrupts received before the async handlers are ready.
        print("\n🛑 تم إيقاف البوت.", flush=True)
