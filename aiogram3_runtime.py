"""Aiogram 3 migration foundation and compatibility layer for Manga Virus.

The legacy handler body is being migrated in stages. This module adapts the
old decorator/signature conventions to aiogram 3; it does not emulate MTProto.
"""
from __future__ import annotations

import io
import os
from typing import Any, Callable, Iterable

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import BaseFilter
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    InlineKeyboardButton as AioInlineKeyboardButton,
    InlineKeyboardMarkup as AioInlineKeyboardMarkup,
    BufferedInputFile,
    FSInputFile,
    URLInputFile,
    LinkPreviewOptions,
)


def _is_entity_parse_error(error: Exception) -> bool:
    message = str(error).lower()
    return "can't parse entities" in message or "cannot parse entities" in message


async def _call_with_plain_text_fallback(method: Any, *args: Any, **kwargs: Any) -> Any:
    """Retry only Telegram entity-formatting failures without parse mode."""
    try:
        return await method(*args, **kwargs)
    except TelegramBadRequest as error:
        if not _is_entity_parse_error(error):
            raise
        plain_kwargs = dict(kwargs)
        plain_kwargs["parse_mode"] = None
        return await method(*args, **plain_kwargs)


def create_bot(token: str) -> Bot:
    if not token or not token.strip():
        raise ValueError("BOT_TOKEN is required")
    return Bot(token=token.strip(), default=DefaultBotProperties(parse_mode=None))


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
            for field in ("style", "url", "callback_data", "web_app", "login_url",
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
    def __init__(self, bot: Bot, message: Any):
        self._bot, self._message = bot, message

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._message, name)
        if name == "edit_text" and callable(attribute):
            async def safe_edit_text(*args: Any, **kwargs: Any) -> Any:
                return await _call_with_plain_text_fallback(attribute, *args, **kwargs)
            return safe_edit_text
        return attribute

    async def reply_text(self, text: str, *args: Any, **kwargs: Any) -> Any:
        kwargs.pop("parse_mode", None)
        return await _call_with_plain_text_fallback(self._message.answer, text, *args, **kwargs)

    async def reply_photo(self, photo: Any, *args: Any, **kwargs: Any) -> Any:
        kwargs.pop("parse_mode", None)
        return await _call_with_plain_text_fallback(
            self._message.answer_photo, as_input_file(photo), *args, **kwargs
        )

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


class CallbackCompat:
    def __init__(self, bot: Bot, callback: Any):
        self._callback = callback
        self.message = MessageCompat(bot, callback.message) if callback.message else None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._callback, name)

    async def answer(self, *args: Any, **kwargs: Any) -> Any:
        return await self._callback.answer(*args, **kwargs)


class BotClientCompat:
    """Common Pyrogram client method names backed by Telegram Bot API."""
    def __init__(self, bot: Bot):
        self.bot = bot

    async def send_message(self, chat_id: Any, text: str, *args: Any, **kwargs: Any) -> Any:
        kwargs.pop("parse_mode", None)
        if kwargs.pop("disable_web_page_preview", False):
            kwargs.setdefault("link_preview_options", LinkPreviewOptions(is_disabled=True))
        return await _call_with_plain_text_fallback(
            self.bot.send_message, chat_id=chat_id, text=text, *args, **kwargs
        )

    async def send_photo(self, chat_id: Any, photo: Any, *args: Any, **kwargs: Any) -> Any:
        kwargs.pop("parse_mode", None)
        return await _call_with_plain_text_fallback(
            self.bot.send_photo, chat_id=chat_id, photo=as_input_file(photo), *args, **kwargs
        )

    async def send_document(self, chat_id: Any, document: Any, *args: Any, **kwargs: Any) -> Any:
        kwargs.pop("parse_mode", None)
        filename = kwargs.pop("file_name", None)
        return await _call_with_plain_text_fallback(
            self.bot.send_document,
            chat_id=chat_id,
            document=as_input_file(document, filename=filename),
            *args,
            **kwargs,
        )

    async def copy_message(
        self, chat_id: Any, from_chat_id: Any, message_id: int, **kwargs: Any
    ) -> Any:
        """Copy a post from an accessible Telegram chat to another chat."""
        return await self.bot.copy_message(
            chat_id=chat_id,
            from_chat_id=from_chat_id,
            message_id=message_id,
            **kwargs,
        )

    async def get_chat_member(self, chat_id: Any, user_id: int) -> Any:
        return await self.bot.get_chat_member(chat_id=chat_id, user_id=user_id)

    async def get_chat(self, chat_id: Any) -> Any:
        return await self.bot.get_chat(chat_id)

    async def get_me(self) -> Any:
        return await self.bot.get_me()

    async def get_users(self, user_id: Any) -> Any:
        if isinstance(user_id, str) and user_id.startswith("@"):
            raise NotImplementedError("Bot API cannot resolve arbitrary @usernames; use a stored numeric ID.")
        return await self.bot.get_chat(int(user_id))

    async def delete_messages(self, chat_id: Any, message_ids: Any) -> None:
        ids = message_ids if isinstance(message_ids, (list, tuple)) else [message_ids]
        for message_id in ids:
            await self.bot.delete_message(chat_id=chat_id, message_id=int(message_id))

    async def download_media(self, file_id: str, in_memory: bool = False) -> Any:
        """Download a Telegram file, returning BytesIO in memory or a local path."""
        info = await self.bot.get_file(file_id)
        if not info.file_path:
            raise RuntimeError("Telegram did not return a file path")

        if in_memory:
            target = io.BytesIO()
            downloaded = await self.bot.download_file(info.file_path, destination=target)
            result = downloaded if downloaded is not None else target
            if hasattr(result, "seek"):
                result.seek(0)
            return result

        import tempfile
        fd, destination = tempfile.mkstemp(
            prefix="manga_telegram_",
            suffix=os.path.splitext(info.file_path)[1] or ".bin",
        )
        os.close(fd)
        try:
            await self.bot.download_file(info.file_path, destination=destination)
            return destination
        except Exception:
            try:
                os.remove(destination)
            except OSError:
                pass
            raise


class LegacyPredicateFilter(BaseFilter):
    def __init__(self, predicate: Callable[[Any], bool]):
        self.predicate = predicate

    async def __call__(self, event: Any) -> bool:
        try:
            return bool(self.predicate(event))
        except Exception:
            return False


class LegacyFilter:
    def __init__(self, predicate: Callable[[Any], bool]):
        self.predicate = predicate

    def __and__(self, other: "LegacyFilter") -> "LegacyFilter":
        return LegacyFilter(lambda event: self.predicate(event) and other.predicate(event))

    def __invert__(self) -> "LegacyFilter":
        return LegacyFilter(lambda event: not self.predicate(event))


class LegacyFilters:
    private = LegacyFilter(lambda m: bool(getattr(getattr(m, "chat", None), "type", None) == "private"))
    text = LegacyFilter(lambda m: getattr(m, "text", None) is not None)
    photo = LegacyFilter(lambda m: bool(getattr(m, "photo", None)))
    document = LegacyFilter(lambda m: getattr(m, "document", None) is not None)

    @staticmethod
    def command(commands: Any) -> LegacyFilter:
        allowed = {commands} if isinstance(commands, str) else set(commands)
        def match(message: Any) -> bool:
            value = getattr(message, "text", None) or ""
            if not value.startswith("/"):
                return False
            first = value.split(maxsplit=1)[0][1:].split("@", 1)[0]
            return first in allowed
        return LegacyFilter(match)


class LegacyApp:
    """Supports the old @app.on_message/@app.on_callback_query registration style."""
    def __init__(self, bot: Bot):
        self.bot = bot
        self.client = BotClientCompat(bot)
        self.router = Router()
        self.dispatcher = Dispatcher()
        self.dispatcher.include_router(self.router)
        self.is_connected = False

    def on_message(self, legacy_filter: LegacyFilter | None = None):
        def decorator(handler: Callable[..., Any]):
            async def wrapped(message: Any):
                return await handler(self.client, MessageCompat(self.bot, message))
            self.router.message(LegacyPredicateFilter((legacy_filter or LegacyFilter(lambda _: True)).predicate))(wrapped)
            return handler
        return decorator

    def on_callback_query(self):
        def decorator(handler: Callable[..., Any]):
            async def wrapped(callback: Any):
                return await handler(self.client, CallbackCompat(self.bot, callback))
            self.router.callback_query()(wrapped)
            return handler
        return decorator

    async def start(self) -> None:
        # Retained only for staged migration of the old startup sequence.
        await self.bot.get_me()
        self.is_connected = True

    async def stop(self) -> None:
        await self.bot.session.close()
        self.is_connected = False

    async def get_me(self) -> Any:
        return await self.bot.get_me()

    async def send_message(self, *args: Any, **kwargs: Any) -> Any:
        return await self.client.send_message(*args, **kwargs)

    def run(self, coroutine: Any = None) -> None:
        import asyncio
        async def runner() -> None:
            if coroutine is not None:
                await coroutine
            else:
                await self.dispatcher.start_polling(self.bot)
        asyncio.run(runner())


def make_legacy_app(token: str) -> LegacyApp:
    return LegacyApp(create_bot(token))
