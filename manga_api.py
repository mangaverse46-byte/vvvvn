# -*- coding: utf-8 -*-
"""Client for the PixelFlow Manga Engine API + local PDF assembly."""
import asyncio
import json
import re
import urllib.parse
import urllib.request
from io import BytesIO

API = "https://pixelflow-callback-harbor.lovable.app/api/public/manga"
API_IMAGE = "https://pixelflow-callback-harbor.lovable.app/api/public/image"
WORKERS = 24
_SOURCE_CACHE = []
_SOURCE_CODES = {"mangalik": "m", "mesh": "e", "azora": "a", "lavascans": "l"}

def _request(action, params=None, payload=None):
    if payload is None:
        q = {"action": action}
        q.update(params or {})
        url = API + "?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 MangaVirus"})
    else:
        body = {"action": action}
        body.update(payload)
        req = urllib.request.Request(API, data=json.dumps(body).encode("utf-8"),
            headers={"User-Agent": "Mozilla/5.0 MangaVirus", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as response:
        raw = response.read()
    result = json.loads(raw.decode("utf-8"))
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(str(result.get("error"))[:250])
    return result

def get_sources(force=False):
    global _SOURCE_CACHE
    raw = _request("sources")
    items = raw.get("sources", []) if isinstance(raw, dict) else []
    _SOURCE_CACHE = [dict(x) for x in items if isinstance(x, dict) and x.get("enabled") is True and x.get("id")]
    return list(_SOURCE_CACHE)

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

def _manga(item):
    if isinstance(item, (list, tuple)):
        vals = list(item) + ["", ""]
        return {"title": str(vals[0]), "url": vals[1], "id": str(vals[2] or vals[1] or vals[0])}
    if not isinstance(item, dict):
        return {}
    url = item.get("url") or item.get("manga_url") or item.get("link") or item.get("href")
    ident = item.get("id") or item.get("slug") or url
    return dict(item, title=str(item.get("title") or item.get("name") or "Manga"),
        url=url, id=str(ident or url or ""), cover_url=item.get("cover_url") or item.get("cover") or item.get("image"))

def _chapter(item, index):
    if isinstance(item, str):
        item = {"url": item, "title": f"Chapter {index + 1}"}
    if not isinstance(item, dict):
        return None
    url = item.get("url") or item.get("chapter_url") or item.get("link") or item.get("href")
    title = str(item.get("title") or item.get("name") or item.get("chapter") or item.get("number") or f"Chapter {index + 1}")
    number = str(item.get("number") or item.get("chapter_number") or item.get("num") or "")
    if not re.fullmatch(r"\d+(?:\.\d+)?", number):
        match = re.search(r"(\d+(?:\.\d+)?)", title)
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

    def get_latest_updates(self, page=1):
        raw = _request("latest", {"source": self.SOURCE, "page": page})
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
        info["cover_url"] = info.get("cover_url") or info.get("cover") or info.get("image")
        info["description"] = info.get("description") or info.get("story") or ""
        info["genres"] = info.get("genres") or []
        info["url"] = info.get("url") or str(manga_url)
        info["chapters"] = [c for i, x in enumerate(chapters or []) if (c := _chapter(x, i)) and c.get("url")]
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
        urls = [x.get("url") for x in images if isinstance(x, dict) and x.get("ok") and x.get("url")]
        if not urls:
            errors = [x.get("error") for x in images if isinstance(x, dict) and x.get("error")]
            raise RuntimeError("لم يستخرج المحرك صوراً صالحة" + (": " + "; ".join(errors[:2]) if errors else ""))
        return urls

    def get_cover_image(self, info):
        return (info or {}).get("cover_url")

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

    timeout = aiohttp.ClientTimeout(total=90, connect=20)
    request_headers = headers or {"User-Agent": "Mozilla/5.0 MangaVirus"}
    connector = aiohttp.TCPConnector(
        limit=WORKERS, limit_per_host=WORKERS, ttl_dns_cache=300,
        keepalive_timeout=30, enable_cleanup_closed=True,
    )
    semaphore = asyncio.Semaphore(WORKERS)
    downloaded = [None] * len(indexed_urls)

    async with aiohttp.ClientSession(
        timeout=timeout, connector=connector, headers=request_headers
    ) as session:
        async def fetch(position, url):
            async with semaphore:
                for attempt in range(4):
                    try:
                        async with session.get(url, allow_redirects=True) as response:
                            if response.status == 429:
                                retry = response.headers.get("Retry-After", "2")
                                try:
                                    delay = min(20, max(1, int(retry)))
                                except (TypeError, ValueError):
                                    delay = 2
                                if attempt < 3:
                                    await asyncio.sleep(delay)
                                    continue
                            if response.status == 200:
                                data = await response.read()
                                if data and len(data) > 100:
                                    downloaded[position] = data
                                    return
                    except Exception as exc:
                        if attempt == 3:
                            print(f"⚠️ image download failed ({position + 1}): {exc}")
                    if attempt < 3:
                        await asyncio.sleep(0.5 * (attempt + 1))

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
            print(f"⚠️ skipped unsupported image format {position + 1}")

    if not candidates:
        return None

    # Validate each candidate separately; a corrupt page will not cancel the chapter.
    valid = []
    for position, blob in candidates:
        try:
            img2pdf.convert(BytesIO(blob))
            valid.append(blob)
        except Exception as exc:
            print(f"⚠️ skipped invalid image {position + 1}: {exc}")

    if not valid:
        return None

    result = img2pdf.convert(*(BytesIO(blob) for blob in valid))
    buf = BytesIO(result)
    buf.name = "manga.pdf"
    buf.seek(0)
    return buf

async def download_images_parallel(urls, client=None, headers=None):
    return await create_pdf_from_images(urls, client=client, headers=headers)

def get_source(source_id):
    """Return the API-backed adapter for one enabled manga source."""
    return MangaSource(source_id)


def get_all_latest():
    """Return latest manga rows in the tuple format expected by bot.py."""
    rows = []
    for source in get_sources():
        source_id = str(source.get("id") or "")
        if not source_id:
            continue
        try:
            api = MangaSource(source_id)
            for item in api.get_latest_updates():
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
                rows.append((title, str(url), ident, str(latest_chapter), source_id))
        except Exception as exc:
            print(f"⚠️ latest source {source_id}: {exc}")
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
