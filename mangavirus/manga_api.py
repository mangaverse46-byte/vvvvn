import asyncio
import json
import random
import urllib.parse
import urllib.request
import urllib.error

class MangaAPI:
    def __init__(self, endpoint: str):
        self.endpoint = endpoint.rstrip("/")

    def _request_sync(self, action, params=None, payload=None):
        headers = {"User-Agent": "Mozilla/5.0 MangaVirus/2.0", "Accept": "application/json"}
        if payload is None:
            query = {"action": action, **(params or {})}
            url = self.endpoint + "?" + urllib.parse.urlencode(query)
            data = None
        else:
            url = self.endpoint
            data = json.dumps({"action": action, **payload}).encode()
            headers["Content-Type"] = "application/json"
        last_error = None
        for attempt in range(4):
            req = urllib.request.Request(url, data=data, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=35) as response:
                    raw = response.read()
                obj = json.loads(raw.decode("utf-8"))
                if isinstance(obj, dict) and obj.get("error"):
                    raise RuntimeError(str(obj["error"])[:250])
                return obj
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 3:
                    raise RuntimeError(f"Manga API HTTP {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last_error = exc
                if attempt == 3:
                    raise RuntimeError(f"Manga API connection failed: {exc}") from exc
            import time
            time.sleep(min(2 ** attempt, 8) + random.random() * .3)
        raise RuntimeError(str(last_error))

    async def request(self, action, params=None, payload=None):
        return await asyncio.to_thread(self._request_sync, action, params, payload)

    @staticmethod
    def items(obj, keys=("results", "items", "mangas", "chapters", "sources")):
        if isinstance(obj, list):
            return obj
        if not isinstance(obj, dict):
            return []
        for key in keys:
            if isinstance(obj.get(key), list):
                return obj[key]
        data = obj.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return MangaAPI.items(data, keys)
        return []

    @staticmethod
    def normalize_manga(item):
        if not isinstance(item, dict):
            return {}
        url = item.get("url") or item.get("manga_url") or item.get("link") or item.get("href")
        return {
            **item,
            "id": str(item.get("id") or item.get("slug") or url or ""),
            "title": str(item.get("title") or item.get("name") or "مانجا بدون اسم"),
            "url": url,
            "cover_url": item.get("cover_url") or item.get("cover") or item.get("image"),
        }

    async def sources(self):
        raw = await self.request("sources")
        return [x for x in self.items(raw) if isinstance(x, dict) and x.get("id") and x.get("enabled", True)]

    async def search(self, source, query, page=1):
        raw = await self.request("search", {"source": source, "q": query, "page": page})
        return [self.normalize_manga(x) for x in self.items(raw) if isinstance(x, dict)]

    async def latest(self, source, page=1):
        raw = await self.request("latest", {"source": source, "page": page})
        return [self.normalize_manga(x) for x in self.items(raw) if isinstance(x, dict)]

    async def details(self, source, manga_url):
        raw = await self.request("details", {"source": source, "url": manga_url})
        info = raw.get("manga", raw) if isinstance(raw, dict) else {}
        if not isinstance(info, dict):
            raise RuntimeError("رد تفاصيل المانجا غير صالح")
        chapters = info.get("chapters") or (raw.get("chapters", []) if isinstance(raw, dict) else [])
        normalized = []
        for index, chapter in enumerate(chapters or []):
            if isinstance(chapter, str):
                chapter = {"url": chapter, "title": f"الفصل {index + 1}"}
            if not isinstance(chapter, dict):
                continue
            url = chapter.get("url") or chapter.get("chapter_url") or chapter.get("link") or chapter.get("href")
            if url:
                normalized.append({**chapter, "url": url,
                    "title": str(chapter.get("title") or chapter.get("name") or chapter.get("chapter") or f"الفصل {index + 1}")})
        return {
            **info,
            "title": info.get("title") or info.get("name") or "مانجا",
            "description": info.get("description") or info.get("story") or "",
            "cover_url": info.get("cover_url") or info.get("cover") or info.get("image"),
            "chapters": normalized,
        }

    async def chapter_images(self, source, chapter_url):
        raw = await self.request("convert", payload={"source": source, "chapter_url": chapter_url})
        images = raw.get("images", []) if isinstance(raw, dict) else []
        urls = [x.get("url") for x in images if isinstance(x, dict) and x.get("ok") and x.get("url")]
        if not urls:
            raise RuntimeError("لم يستخرج مصدر المانجا صوراً صالحة")
        return urls
