"""Manga API adapter.

The upstream API's exact response contract must be confirmed before enabling
search/chapter parsing. This module deliberately reports upstream responses
rather than guessing field names or silently dropping results.
"""
import httpx
from config import MANGA_API_BASE, MANGA_API_KEY

class MangaAPIError(RuntimeError):
    pass

async def request_json(path: str, params=None):
    if not MANGA_API_BASE:
        raise MangaAPIError('لم يتم ضبط رابط Manga API في ملف .env')
    headers = {"Accept": "application/json", "User-Agent": "MangaVirus/1.0"}
    if MANGA_API_KEY:
        headers["Authorization"] = f"Bearer {MANGA_API_KEY}"
    url = f"{MANGA_API_BASE}/{path.lstrip('/')}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=10.0), follow_redirects=True) as client:
        response = await client.get(url, params=params or {}, headers=headers)
        if response.status_code == 429:
            retry = response.headers.get('Retry-After', 'غير محدد')
            raise MangaAPIError(f'المصدر يطلب تهدئة الطلبات (429). Retry-After: {retry}')
        response.raise_for_status()
        try:
            return response.json()
        except ValueError as exc:
            raise MangaAPIError('الـ API لم يرجع JSON صالحاً') from exc

async def search_manga(query: str):
    # Endpoint/query mapping intentionally awaits the confirmed API contract.
    raise MangaAPIError('ربط البحث متوقف مؤقتاً حتى نثبت مسار البحث وشكل JSON من MangaTek؛ لم يتم تخمينه.')
