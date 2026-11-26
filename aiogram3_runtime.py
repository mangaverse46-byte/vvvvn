"""Aiogram 3 migration foundation for Manga Virus.

This module is deliberately isolated from bot.py until handler registration and
all legacy call sites have been migrated. It is not a drop-in Pyrogram runtime.
"""
from __future__ import annotations

import io
import os
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
    if not token or not token.strip():
        raise ValueError("BOT_TOKEN is required")
    return Bot(token=token.strip(), default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))


def create_dispatcher() -> Dispatcher:
    return Dispatcher()


def make_inline_keyboard(rows: Iterable[Iterable[Any]]) -> AioInlineKeyboardMarkup:
    converted: list[list[AioInlineKeyboardButton]] = []
    for row in rows:
        converted_row: list[AioInlineKeyboardButton] = []
        for button in row:
            if isinstance(button, AioInlineKeyboardButton):
                converted_row.append(button)
                continue
            label = getattr(button, "text", None)
            if not label:
                raise TypeError("Keyboard button must have a non-empty text")
            kwargs: dict[str, Any] = {"text": str(label)}
            for field in ("url", "callback_data", "web_app", "login_url",
                          "switch_inline_query", "switch_inline_query_current_chat",
                          "callback_game", "pay"):
                value = getattr(button, field, None)
                if value is not None:
                    kwargs[field] = value
            converted_row.append(AioInlineKeyboardButton(**kwargs))
        if converted_row:
            converted.append(converted_row)
    return AioInlineKeyboardMarkup(inline_keyboard=converted)


def as_input_file(value: Any, filename: str | None = None) -> Any:
    """Convert URLs, existing paths and byte streams; preserve Telegram file IDs."""
    if isinstance(value, (URLInputFile, FSInputFile, BufferedInputFile)):
        return value
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            return URLInputFile(value)
        if os.path.isfile(value):
            return FSInputFile(value)
        return value
    if isinstance(value, io.BytesIO):
        name = filename or getattr(value, "name", None) or "upload.bin"
        return BufferedInputFile(value.getvalue(), filename=str(name))
    if isinstance(value, (bytes, bytearray)):
        return BufferedInputFile(bytes(value), filename=filename or "upload.bin")
    return value


class MessageCompat:
    """Bridge common Pyrogram Message methods to aiogram Message methods."""
    def __init__(self, bot: Bot, message: Any):
        self._bot, self._message = bot, message

    def __getattr__(self, name: str) -> Any:
        return getattr(self._message, name)

    async def reply_text(self, text: str, *args: Any, **kwargs: Any) -> Any:
        kwargs.pop("parse_mode", None)
        return await self._message.answer(text, *args, **kwargs)

    async def reply_photo(self, photo: Any, *args: Any, **kwargs: Any) -> Any:
        kwargs.pop("parse_mode", None)
        return await self._message.answer_photo(as_input_file(photo), *args, **kwargs)

    async def download(self, destination: str | None = None) -> str:
        media = self._message.document
        if media is None and self._message.photo:
            media = self._message.photo[-1]
        if media is None:
            raise ValueError("Message does not contain downloadable media")
        info = await self._bot.get_file(media.file_id)
        if not info.file_path:
            raise RuntimeError("Telegram did not return a file path")
        if destination is None:
            import tempfile
            suffix = os.path.splitext(getattr(media, "file_name", "") or "")[1]
            fd, destination = tempfile.mkstemp(suffix=suffix)
            os.close(fd)
        await self._bot.download_file(info.file_path, destination=destination)
        return destination


class BotClientCompat:
    """Bridge common Pyrogram client calls. Arbitrary @username lookup is unsupported."""
    def __init__(self, bot: Bot):
        self.bot = bot

    async def send_message(self, chat_id: Any, text: str, *args: Any, **kwargs: Any) -> Any:
        kwargs.pop("parse_mode", None)
        return await self.bot.send_message(chat_id=chat_id, text=text, *args, **kwargs)

    async def send_photo(self, chat_id: Any, photo: Any, *args: Any, **kwargs: Any) -> Any:
        kwargs.pop("parse_mode", None)
        return await self.bot.send_photo(chat_id=chat_id, photo=as_input_file(photo), *args, **kwargs)

    async def send_document(self, chat_id: Any, document: Any, *args: Any, **kwargs: Any) -> Any:
        kwargs.pop("parse_mode", None)
        return await self.bot.send_document(chat_id=chat_id, document=as_input_file(document), *args, **kwargs)

    async def get_chat_member(self, chat_id: Any, user_id: int) -> Any:
        return await self.bot.get_chat_member(chat_id=chat_id, user_id=user_id)

    async def get_chat(self, chat_id: Any) -> Any:
        return await self.bot.get_chat(chat_id)

    async def get_me(self) -> Any:
        return await self.bot.get_me()

    async def get_users(self, user_id: Any) -> Any:
        if isinstance(user_id, str) and user_id.startswith("@"):
            raise NotImplementedError(
                "Telegram Bot API cannot resolve arbitrary @usernames; use a numeric ID."
            )
        return await self.bot.get_chat(int(user_id))

    async def delete_messages(self, chat_id: Any, message_ids: Any) -> None:
        ids = message_ids if isinstance(message_ids, (list, tuple)) else [message_ids]
        for message_id in ids:
            await self.bot.delete_message(chat_id=chat_id, message_id=int(message_id))

    async def download_media(self, file_id: str, in_memory: bool = False) -> Any:
        info = await self.bot.get_file(file_id)
        if not info.file_path:
            raise RuntimeError("Telegram did not return a file path")
        target = io.BytesIO() if in_memory else None
        return await self.bot.download_file(info.file_path, destination=target)
