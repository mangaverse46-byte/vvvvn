import asyncio
import os
import random
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import img2pdf

from config import MAX_DOWNLOAD_CONCURRENCY, MAX_PDF_PAGES

def _retry_delay(value, attempt):
    try:
        return min(30, max(0.5, float(value)))
    except (TypeError, ValueError):
        return min(20, (2 ** attempt) + random.random())

async def build_pdf(image_urls: list[str], caption="manga"):
    urls = [x.get("url") if isinstance(x, dict) else x for x in image_urls]
    urls = [u for u in urls if isinstance(u, str) and u.startswith(("http://", "https://"))]
    if not urls:
        raise RuntimeError("لم يرجع API أي روابط صور صالحة")
    if len(urls) > MAX_PDF_PAGES:
        raise RuntimeError(f"عدد الصور {len(urls)} يتجاوز الحد الحالي {MAX_PDF_PAGES}")
    semaphore = asyncio.Semaphore(MAX_DOWNLOAD_CONCURRENCY)
    temp = tempfile.TemporaryDirectory(prefix="mangavirus_")
    paths = [None] * len(urls)
    timeout = aiohttp.ClientTimeout(total=90, connect=20)

    async def fetch(index, url, session):
        async with semaphore:
            for attempt in range(5):
                try:
                    async with session.get(url) as response:
                        if response.status == 429 or response.status >= 500:
                            if attempt == 4:
                                response.raise_for_status()
                            await asyncio.sleep(_retry_delay(response.headers.get("Retry-After"), attempt))
                            continue
                        response.raise_for_status()
                        data = await response.read()
                        if not data:
                            raise RuntimeError("صورة فارغة")
                        suffix = os.path.splitext(urlparse(url).path)[1].lower()
                        if suffix not in (".jpg", ".jpeg", ".png", ".jp2"):
                            suffix = ".img"
                        path = os.path.join(temp.name, f"{index:06d}{suffix}")
                        with open(path, "wb") as f:
                            f.write(data)
                        paths[index] = path
                        return
                except Exception:
                    if attempt == 4:
                        raise
                    await asyncio.sleep(_retry_delay(None, attempt))

    try:
        connector = aiohttp.TCPConnector(limit=MAX_DOWNLOAD_CONCURRENCY * 2, ttl_dns_cache=300)
        async with aiohttp.ClientSession(timeout=timeout, connector=connector,
                                         headers={"User-Agent": "Mozilla/5.0 MangaVirus/1.0"}) as session:
            await asyncio.gather(*(fetch(i, url, session) for i, url in enumerate(urls)))
        pdf_path = os.path.join(temp.name, "chapter.pdf")
        with open(pdf_path, "wb") as output:
            output.write(img2pdf.convert(paths))
        # Return bytes before temporary directory is removed.
        return Path(pdf_path).read_bytes(), len(paths)
    finally:
        temp.cleanup()
