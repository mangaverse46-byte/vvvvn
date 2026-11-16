import aiohttp
from urllib.parse import urlencode

class MangaAPI:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.session = None

    async def start(self):
        timeout = aiohttp.ClientTimeout(total=45, connect=15)
        self.session = aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": "MangaVirusBot/1.0"})

    async def close(self):
        if self.session:
            await self.session.close()

    async def _request(self, method: str, params=None, payload=None):
        if not self.session:
            await self.start()
        url = self.base_url
        async with self.session.request(method, url, params=params, json=payload) as response:
            raw = await response.text()
            if response.status >= 400:
                raise RuntimeError(f"API HTTP {response.status}: {raw[:350]}")
            try:
                import json
                data = json.loads(raw)
            except Exception:
                raise RuntimeError("استجابة API ليست JSON صالحاً")
            if not isinstance(data, dict):
                raise RuntimeError("تنسيق استجابة API غير متوقع")
            return data

    async def get(self, action: str, **params):
        return await self._request("GET", {"action": action, **params})

    async def post(self, payload: dict):
        return await self._request("POST", payload=payload)

    async def sources(self):
        data = await self.get("sources")
        items = data.get("sources", [])
        return [s for s in items if isinstance(s, dict) and s.get("enabled", True)]

    async def latest(self, source: str, page=1):
        return await self.get("latest", source=source, page=page)

    async def search(self, source: str, query: str, page=1):
        return await self.get("search", source=source, q=query, page=page)

    async def details(self, source: str, url: str):
        return await self.get("details", source=source, url=url)

    async def pages(self, source: str, chapter_id: str):
        return await self.get("pages", source=source, id=chapter_id)

    async def merge(self, source: str, chapter_urls: list[str]):
        return await self.post({"action": "merge", "source": source, "chapter_urls": chapter_urls})
