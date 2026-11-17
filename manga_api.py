# -*- coding: utf-8 -*-
"""Compatibility layer for MangaVerse public manga API."""
import asyncio
import json
import re
import urllib.parse
import urllib.request

API = "https://pixelflow-callback-harbor.lovable.app/api/public/manga"
API_IMAGE = "https://pixelflow-callback-harbor.lovable.app/api/public/image"
WORKERS = 15

def _request(action, params=None, payload=None):
    if payload is None:
        q = {"action": action}
        q.update(params or {})
        url = API + "?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    else:
        body = dict(action=action)
        body.update(payload)
        req = urllib.request.Request(API, data=json.dumps(body).encode(), headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=55) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8"))

def _data(obj):
    if isinstance(obj, dict):
        return obj.get("data", obj.get("result", obj))
    return obj

def _items(obj, keys):
    d = _data(obj)
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        for key in keys:
            if isinstance(d.get(key), list):
                return d[key]
        for key in ("items", "results", "list"):
            if isinstance(d.get(key), list):
                return d[key]
    return []

def _manga(x):
    if isinstance(x, (list, tuple)):
        a = list(x) + ["", "", ""]
        return {"title": a[0], "url": a[1], "id": a[2]}
    if not isinstance(x, dict):
        return {}
    title = x.get("title") or x.get("name") or x.get("manga_name") or "Manga"
    url = x.get("url") or x.get("manga_url") or x.get("link") or x.get("href")
    ident = x.get("id") or x.get("slug") or x.get("manga_id") or url
    return dict(x, title=str(title), url=url, id=str(ident or url or title),
                cover_url=x.get("cover_url") or x.get("cover") or x.get("image") or x.get("thumbnail"))

def _chapter(x, i):
    if isinstance(x, str):
        x = {"url": x, "title": "Chapter " + str(i + 1)}
    if not isinstance(x, dict):
        return None
    title = str(x.get("title") or x.get("name") or x.get("chapter") or x.get("number") or ("Chapter " + str(i + 1)))
    number = x.get("number") or x.get("chapter_number") or x.get("num")
    if number is None:
        m = re.search(r"(\d+(?:\.\d+)?)", title)
        number = m.group(1) if m else ""
    return dict(x, url=x.get("url") or x.get("chapter_url") or x.get("link") or x.get("href"),
                id=str(x.get("id") or x.get("chapter_id") or x.get("url") or i),
                title=title, number=str(number), num_str=str(number),
                is_numeric=bool(re.fullmatch(r"\d+(?:\.\d+)?", str(number))))

def _search(source, query):
    raw = _request("search", {"source": source, "q": query, "page": 1})
    return [_manga(x) for x in _items(raw, ("mangas", "results", "items"))]

def _latest(source):
    raw = _request("latest", {"source": source, "page": 1})
    return [_manga(x) for x in _items(raw, ("mangas", "results", "items", "chapters"))]

def _genres(source):
    raw = _request("genres", {"source": source})
    out = []
    for x in _items(raw, ("genres", "items")):
        if isinstance(x, str):
            out.append((x, x))
        elif isinstance(x, dict):
            name = x.get("name") or x.get("title") or x.get("genre")
            slug = x.get("url") or x.get("genre_url") or x.get("slug") or x.get("id")
            if name and slug:
                out.append((str(name), str(slug)))
    return out

def _by_genre(source, slug, page=1):
    raw = _request("genre-manga", {"source": source, "genre_url": slug, "page": page})
    return [_manga(x) for x in _items(raw, ("mangas", "results", "items"))]

def _details(source, manga_url):
    raw = _request("details", {"source": source, "url": manga_url})
    d = _data(raw)
    if not isinstance(d, dict):
        return None
    info = d.get("manga") if isinstance(d.get("manga"), dict) else d
    chapters = d.get("chapters") or info.get("chapters") or []
    info = dict(info)
    info["chapters"] = [c for i, x in enumerate(chapters) if (c := _chapter(x, i))]
    info["name"] = info.get("name") or info.get("title") or "Manga"
    info["cover_url"] = info.get("cover_url") or info.get("cover") or info.get("image")
    info["description"] = info.get("description") or info.get("story") or ""
    info["genres"] = info.get("genres") or []
    return info

def _image_urls(raw):
    d = _data(raw)
    if isinstance(d, dict):
        for key in ("images", "pages", "urls", "converted", "files"):
            if isinstance(d.get(key), list):
                d = d[key]
                break
    out = []
    if isinstance(d, list):
        for x in d:
            if isinstance(x, str):
                out.append(x)
            elif isinstance(x, dict):
                u = x.get("url") or x.get("image_url") or x.get("src") or x.get("download_url")
                if u:
                    out.append(u)
    return out

def _chapter_images(source, chapter):
    url = chapter.get("url") if isinstance(chapter, dict) else str(chapter)
    raw = _request("convert", payload={"source": source, "chapter_url": url})
    urls = _image_urls(raw)
    if not urls:
        raise RuntimeError("No images returned from Manga API")
    return urls

async def create_pdf_from_images(urls, client=None, headers=None):
    import aiohttp
    import fitz
    sem = asyncio.Semaphore(WORKERS)
    timeout = aiohttp.ClientTimeout(total=50, connect=15)
    async with aiohttp.ClientSession(timeout=timeout, headers=headers or {"User-Agent": "Mozilla/5.0"}) as session:
        async def fetch(url):
            async with sem:
                for attempt in range(4):
                    try:
                        async with session.get(url, allow_redirects=True) as r:
                            if r.status == 429:
                                await asyncio.sleep(min(10, int(r.headers.get("Retry-After", "2") or 2)))
                                continue
                            if r.status == 200:
                                b = await r.read()
                                if len(b) > 100:
                                    return b
                    except Exception:
                        if attempt < 3:
                            await asyncio.sleep(0.4 * (attempt + 1))
                return None
        blobs = await asyncio.gather(*(fetch(u) for u in urls))
    doc = fitz.open()
    page_w, page_h = 595.0, 842.0
    for blob in blobs:
        if not blob:
            continue
        try:
            pix = fitz.Pixmap(blob)
            iw, ih = pix.width, pix.height
            if iw <= 0 or ih <= 0:
                continue
            scale = min(page_w / iw, page_h / ih)
            w, h = iw * scale, ih * scale
            page = doc.new_page(width=page_w, height=page_h)
            rect = fitz.Rect((page_w-w)/2, (page_h-h)/2, (page_w+w)/2, (page_h+h)/2)
            page.insert_image(rect, stream=blob, keep_proportion=True)
        except Exception:
            try:
                page = doc.new_page(width=page_w, height=page_h)
                page.insert_image(page.rect, stream=blob, keep_proportion=True)
            except Exception:
                pass
    if not doc.page_count:
        doc.close()
        return None
    result = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    from io import BytesIO
    buf = BytesIO(result)
    buf.name = "manga.pdf"
    buf.seek(0)
    return buf

async def download_images_parallel(urls, client=None, headers=None):
    return await create_pdf_from_images(urls, client=client, headers=headers)

class _Source:
    SOURCE = "mangalik"
    BASE = "https://mangalik.net"
    H = {"User-Agent": "Mozilla/5.0"}
    @classmethod
    def search(cls, query):
        return _search(cls.SOURCE, query)
    @classmethod
    def get_latest_updates(cls):
        return [(x["title"], x.get("url") or "", x.get("id") or "") for x in _latest(cls.SOURCE)]
    @classmethod
    def get_genres(cls):
        return _genres(cls.SOURCE)
    @classmethod
    def get_manga_by_genre(cls, slug, page=1):
        return [(x["title"], x.get("url") or "", x.get("id") or "") for x in _by_genre(cls.SOURCE, slug, page)]
    @classmethod
    def get_details(cls, manga_url):
        return _details(cls.SOURCE, manga_url)
    @classmethod
    def get_chapters(cls, manga_url):
        d = _details(cls.SOURCE, manga_url)
        return (d or {}).get("chapters", [])
    @classmethod
    def get_chapter_images(cls, chapter):
        return _chapter_images(cls.SOURCE, chapter)
    @classmethod
    async def create_pdf_from_images(cls, urls, client=None):
        return await create_pdf_from_images(urls, client=client)
    @classmethod
    def get_cover_image(cls, info):
        return (info or {}).get("cover_url")

class StarzManga(_Source):
    SOURCE = "mangalik"
    BASE = "https://mangalik.net"

class MeshManga(_Source):
    SOURCE = "mesh"
    BASE = "https://meshmanga.com"
    @classmethod
    def get_details(cls, ident):
        return _details(cls.SOURCE, str(ident))
    @classmethod
    def get_chapters(cls, ident):
        d = cls.get_details(ident)
        return (d or {}).get("chapters", [])
    @classmethod
    def get_chapter_images(cls, chapter):
        return _chapter_images(cls.SOURCE, chapter)
    @classmethod
    def get_cover_image(cls, info):
        return (info or {}).get("cover_url")

class AzoraFly(_Source):
    SOURCE = "azora"
    BASE = "https://azorafly.com"
    @classmethod
    def get_chapter_images(cls, chapter):
        return _chapter_images(cls.SOURCE, chapter)

class LavaScans(_Source):
    SOURCE = "lava"
    BASE = "https://lavascans.com/"
    @classmethod
    def get_chapter_images(cls, chapter):
        return _chapter_images(cls.SOURCE, chapter)
