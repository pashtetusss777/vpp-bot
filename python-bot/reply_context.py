"""Makes every bot message sent while handling a user message a reply to that message."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.client.session.middlewares.base import (
    BaseRequestMiddleware,
    NextRequestMiddlewareType,
)
from aiogram.methods import TelegramMethod
from aiogram.methods.base import Response, TelegramType
from aiogram.types import Message, ReplyParameters, TelegramObject

_current: ContextVar[tuple[int, int] | None] = ContextVar("reply_target", default=None)


class RememberIncomingMessage(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)
        token = _current.set((event.chat.id, event.message_id))
        try:
            return await handler(event, data)
        finally:
            _current.reset(token)


class ReplyToIncoming(BaseRequestMiddleware):
    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        target = _current.get()
        if target is not None and _should_reply(method, target[0]):
            method.reply_parameters = ReplyParameters(
                message_id=target[1],
                allow_sending_without_reply=True,
            )
        return await make_request(bot, method)


def _should_reply(method: Any, chat_id: int) -> bool:
    if "reply_parameters" not in type(method).model_fields:
        return False
    if getattr(method, "reply_parameters", None) is not None:
        return False
    if getattr(method, "reply_to_message_id", None) is not None:
        return False
    try:
        return int(getattr(method, "chat_id")) == chat_id
    except (TypeError, ValueError):
        return False
