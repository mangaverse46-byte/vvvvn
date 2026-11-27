#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare aiohttp and optional curl_cffi for downloading the same image URL list.

Usage:
  python benchmark_downloaders.py --url-file image_urls.txt
  python benchmark_downloaders.py --url https://... --url https://...
  python benchmark_downloaders.py --url-file image_urls.txt --referer https://source.example/
"""
import argparse
import asyncio
import statistics
import time

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
    "Chrome/139.0.0.0 Mobile Safari/537.36"
)
ACCEPT = "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"


def read_urls(args):
    urls = list(args.url or [])
    if args.url_file:
        with open(args.url_file, "r", encoding="utf-8") as handle:
            urls.extend(line.strip() for line in handle if line.strip() and not line.lstrip().startswith("#"))
    # Preserve order while removing duplicates.
    return list(dict.fromkeys(urls))


async def benchmark_aiohttp(urls, concurrency, timeout_seconds, headers):
    import aiohttp

    timeout = aiohttp.ClientTimeout(total=timeout_seconds, connect=min(15, timeout_seconds))
    connector = aiohttp.TCPConnector(
        limit=max(concurrency, 1),
        limit_per_host=max(concurrency, 1),
        ttl_dns_cache=600,
        keepalive_timeout=60,
        enable_cleanup_closed=True,
    )
    semaphore = asyncio.Semaphore(concurrency)
    sizes = [0] * len(urls)
    errors = [None] * len(urls)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector, headers=headers) as session:
        async def fetch(i, url):
            async with semaphore:
                try:
                    async with session.get(url, allow_redirects=True) as response:
                        if response.status != 200:
                            errors[i] = "HTTP " + str(response.status)
                            return
                        body = await response.read()
                        if len(body) < 200:
                            errors[i] = "response too small"
                            return
                        sizes[i] = len(body)
                except Exception as exc:
                    errors[i] = type(exc).__name__ + ": " + str(exc)[:140]

        started = time.perf_counter()
        await asyncio.gather(*(fetch(i, url) for i, url in enumerate(urls)))
        elapsed = time.perf_counter() - started

    return summarize("aiohttp", sizes, errors, elapsed)


async def benchmark_curl_cffi(urls, concurrency, timeout_seconds, headers):
    try:
        from curl_cffi.requests import AsyncSession
    except ImportError:
        return {"name": "curl_cffi", "available": False,
                "install": "python -m pip install 'curl_cffi>=0.7,<1'"}

    semaphore = asyncio.Semaphore(concurrency)
    sizes = [0] * len(urls)
    errors = [None] * len(urls)

    async with AsyncSession(
        impersonate="chrome",
        headers=headers,
        max_clients=concurrency,
        timeout=timeout_seconds,
    ) as session:
        async def fetch(i, url):
            async with semaphore:
                try:
                    response = await session.get(url, allow_redirects=True)
                    if response.status_code != 200:
                        errors[i] = "HTTP " + str(response.status_code)
                        return
                    body = response.content
                    if len(body) < 200:
                        errors[i] = "response too small"
                        return
                    sizes[i] = len(body)
                except Exception as exc:
                    errors[i] = type(exc).__name__ + ": " + str(exc)[:140]

        started = time.perf_counter()
        await asyncio.gather(*(fetch(i, url) for i, url in enumerate(urls)))
        elapsed = time.perf_counter() - started

    return summarize("curl_cffi", sizes, errors, elapsed)


def summarize(name, sizes, errors, elapsed):
    success = sum(size > 0 for size in sizes)
    total = sum(sizes)
    return {
        "name": name,
        "available": True,
        "success": success,
        "failed": len(sizes) - success,
        "bytes": total,
        "seconds": round(elapsed, 3),
        "mb_per_second": round(total / 1024 / 1024 / elapsed, 3) if elapsed else 0,
        "errors": [error for error in errors if error][:5],
    }


async def main():
    parser = argparse.ArgumentParser(description="Compare image download speeds without touching the bot/PDF pipeline.")
    parser.add_argument("--url", action="append", help="Image URL; can be supplied multiple times.")
    parser.add_argument("--url-file", help="UTF-8 text file with one image URL per line.")
    parser.add_argument("--referer", help="Optional Referer header used for both clients.")
    parser.add_argument("--concurrency", type=int, default=8, help="Concurrent downloads (default: 8, same as bot).")
    parser.add_argument("--timeout", type=int, default=45, help="Per-request timeout in seconds.")
    args = parser.parse_args()

    if args.concurrency < 1 or args.timeout < 1:
        parser.error("--concurrency and --timeout must be positive")
    urls = read_urls(args)
    if not urls:
        parser.error("Provide --url or --url-file with at least one URL")

    headers = {"User-Agent": USER_AGENT, "Accept": ACCEPT}
    if args.referer:
        headers["Referer"] = args.referer

    print("Image downloader benchmark")
    print("URLs:", len(urls), "| concurrency:", args.concurrency)
    print("Both clients receive the same URLs and headers; no files are saved.")
    results = []
    for runner in (benchmark_aiohttp, benchmark_curl_cffi):
        try:
            result = await runner(urls, args.concurrency, args.timeout, headers)
        except ImportError as exc:
            result = {"name": runner.__name__, "available": False, "error": str(exc)}
        results.append(result)
        if not result.get("available"):
            print(f"\n{result['name']}: unavailable - {result.get('install') or result.get('error')}")
            continue
        print(f"\n{result['name']}: {result['success']}/{len(urls)} succeeded, "
              f"{result['bytes'] / 1024 / 1024:.2f} MiB, {result['seconds']:.3f}s, "
              f"{result['mb_per_second']:.2f} MiB/s")
        if result["errors"]:
            print("Sample errors:", " | ".join(result["errors"]))

    available = [r for r in results if r.get("available") and r.get("success", 0)]
    if len(available) == 2:
        a, b = available
        if a["success"] != b["success"]:
            print("\nNote: success counts differ; compare reliability before speed.")
        elif a["seconds"] and b["seconds"]:
            faster = min(available, key=lambda r: r["seconds"])
            slower = max(available, key=lambda r: r["seconds"])
            print(f"\nFaster in this run: {faster['name']} "
                  f"({slower['seconds'] / faster['seconds']:.2f}x).")
    print("\nRun the test more than once with the same chapter URL list for a fair comparison.")


if __name__ == "__main__":
    asyncio.run(main())
