import asyncio
import io
import json
import urllib.request
import urllib.error
import aiohttp

class PDFEngine:
    def __init__(self, api_url: str):
        self.api_url = api_url.rstrip("/")

    async def create(self, image_urls):
        if not image_urls:
            raise ValueError("لا توجد صور لإنشاء PDF")
        timeout = aiohttp.ClientTimeout(total=180, connect=25)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(self.api_url, json={"urls": image_urls}) as response:
                body = await response.text()
                if response.status != 200:
                    raise RuntimeError(f"PDF API HTTP {response.status}: {body[:250]}")
                data = json.loads(body)
        pdf_url = data.get("pdf_url")
        if not pdf_url:
            raise RuntimeError("محرك PDF لم يرجع رابط الملف")
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(pdf_url) as response:
                if response.status != 200:
                    raise RuntimeError(f"تعذر تنزيل PDF: HTTP {response.status}")
                content = await response.read()
        if not content.startswith(b"%PDF"):
            raise RuntimeError("الملف المستلم ليس PDF صالحاً")
        file = io.BytesIO(content)
        file.name = "MangaVirus.pdf"
        file.seek(0)
        return file, data
