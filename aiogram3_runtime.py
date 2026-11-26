"""Aiogram 3 migration foundation for Manga Virus.

This module is deliberately isolated from bot.py until the handler migration is
complete. It provides the Bot/Dispatcher setup and compatibility primitives;
it does NOT make the existing Pyrogram handlers runnable by itself.
"""
from __future__ import annotations

import io
from typing import Any, Iterable

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    InlineKeyboardButton as AioInlineKeyboardButton,
    InlineKeyboardMarkup as AioInlineKeyboardMarkup,
    BufferedInputFile,
    FSInputFile,
    URLInputFile,
)


def create_bot(token: str) -> Bot:
    """Create an aiogram 3 bot with Markdown as the legacy default."""
    if not token or not token.strip():
        raise ValueError("BOT_TOKEN is required")
    return Bot(
        token=token.strip(),
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )


def create_dispatcher() -> Dispatcher:
    """Return a fresh dispatcher; routers are attached during handler migration."""
    return Dispatcher()


def make_inline_keyboard(rows: Iterable[Iterable[Any]]) -> AioInlineKeyboardMarkup:
    """Convert legacy row-based keyboard definitions to aiogram 3 markup."""
    converted: list[list[AioInlineKeyboardButton]] = []
    for row in rows:
        converted_row: list[AioInlineKeyboardButton] = []
        for button in row:
            if isinstance(button, AioInlineKeyboardButton):
                converted_row.append(button)
                continue
            text = getattr(button, "text", None)
            if not text:
                raise TypeError("Keyboard button must have a non-empty text")
            kwargs: dict[str, Any] = {"text": str(text)}
            for field in (
                "url", "callback_data", "web_app", "login_url", "switch_inline_query",
                "switch_inline_query_current_chat", "callback_game", "pay",
            ):
                value = getattr(button, field, None)
                if value is not None:
                    kwargs[field] = value
            converted_row.append(AioInlineKeyboardButton(**kwargs))
        if converted_row:
            converted.append(converted_row)
    return AioInlineKeyboardMarkup(inline_keyboard=converted)


def as_input_file(value: Any, filename: str | None = None) -> Any:
    """Convert common Pyrogram-era media values to aiogram-compatible inputs."""
    if isinstance(value, (str, URLInputFile, FSInputFile, BufferedInputFile)):
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return URLInputFile(value)
        if isinstance(value, str):
            return FSInputFile(value)
        return value
    if isinstance(value, io.BytesIO):
        data = value.getvalue()
        name = filename or getattr(value, "name", None) or "upload.bin"
        return BufferedInputFile(data, filename=str(name))
    if isinstance(value, (bytes, bytearray)):
        return BufferedInputFile(bytes(value), filename=filename or "upload.bin")
    # Telegram file_id strings are handled above as strings only when the caller
    # identifies them as IDs; callers should pass file_id directly to Bot methods.
    return value


async def download_telegram_file(bot: Bot, file_id: str) -> bytes:
    """Download a Telegram file using Bot API get_file + download_file."""
    if not file_id:
        raise ValueError("file_id is required")
    info = await bot.get_file(file_id)
    if not info.file_path:
        raise RuntimeError("Telegram did not return a file path")
    target = io.BytesIO()
    await bot.download_file(info.file_path, destination=target)
    return target.getvalue()
