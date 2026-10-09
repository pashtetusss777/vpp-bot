"""Minecraft chat bridge for a Telegram forum topic.

The behavior follows the Paper side of tgbridge (https://github.com/vanutp/tgbridge):
chat, join, leave, death, advancements, start/stop, message merge, leave/join
merge, prefixes, silent events, /list and /tps. Fabric, Forge and third-party
mod integrations are outside this server.
"""

from __future__ import annotations

import asyncio
import html
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

log = logging.getLogger(__name__)

MEDIA_LABELS = {
    "animation": "[GIF]",
    "document": "[Файл]",
    "photo": "[Фото]",
    "audio": "[Аудио]",
    "sticker": "[Стикер]",
    "video": "[Видео]",
    "video_note": "[Кружок]",
    "voice": "[Голосовое сообщение]",
    "poll": "[Опрос]",
}


class ServerLink(Protocol):
    async def poll_chat_events(self, after: int) -> tuple[str, list[dict[str, Any]]]: ...

    async def broadcast_chat(
        self,
        sender: str,
        text: str,
        reply: str | None,
        message_format: str | None = None,
        reply_format: str | None = None,
    ) -> None: ...

    async def get_tps(self) -> dict[str, Any]: ...

    async def get_online(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ChatBridgeSettings:
    enabled: bool
    forum_chat_id: int
    status_topic_id: int | None
    chat_topic_id: int | None
    merge_window: int
    leave_join_merge_window: int
    require_prefix_minecraft: str | None
    require_prefix_telegram: str | None
    keep_prefix: bool
    use_real_username: bool
    silent_events: frozenset[str]
    join_messages: str
    leave_messages: bool
    death_messages: bool
    start_messages: bool
    stop_messages: bool
    advancement_messages: bool
    advancement_task: bool
    advancement_goal: bool
    advancement_challenge: bool
    advancement_description: bool
    formats: dict[str, str] = field(default_factory=dict)
    minecraft_message_format: str | None = None
    minecraft_reply_format: str | None = None
    minecraft_reply_enabled: bool = True
    minecraft_edit_prefix: str = "✎ "

    def fmt(self, key: str) -> str:
        return self.formats.get(key, DEFAULT_FORMATS[key])


DEFAULT_FORMATS: dict[str, str] = {
    "SERVER_START": "✅ Сервер запущен!",
    "SERVER_STOP": "❌ Сервер остановлен!",
    "JOIN": "🥳 {name} зашёл на сервер",
    "FIRST_JOIN": "🥳 {name} в первый раз зашёл на сервер",
    "LEAVE": "😕 {name} покинул сервер",
    "DEATH": "☠️ {text}",
    "DEATH_UNKNOWN": "☠️ {name} погиб",
    "ADVANCEMENT_TASK": "😼 {name} получил достижение <b>{title}</b>",
    "ADVANCEMENT_GOAL": "🎯 {name} достиг цели <b>{title}</b>",
    "ADVANCEMENT_CHALLENGE": "🏅 {name} завершил испытание <b>{title}</b>",
    "ADVANCEMENT_DESCRIPTION": "\n<i>{description}</i>",
    "CHAT": "<b>{name}</b>: {text}",
    "LIST": "📝 Онлайн {count}: {players}",
    "LIST_EMPTY": "📝 Сейчас никто не играет",
    "TPS": "📊 TPS: <code>{tps}</code>\n⏱️ MSPT: <code>{mspt}</code>",
    "SERVER_UNAVAILABLE": "Сервер недоступен: {error}",
}


class _KeepMissing(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render(template: str, **values: Any) -> str:
    """Fill {placeholders}. Values are HTML-escaped, the template itself may contain HTML."""
    escaped = _KeepMissing({key: html.escape(str(value)) for key, value in values.items()})
    try:
        return template.format_map(escaped)
    except (ValueError, IndexError):
        log.warning("Неверный шаблон CHAT_BRIDGE.FORMAT: %r", template)
        return template


def load_chat_bridge_settings(raw: dict[str, Any], forum_chat_id: int) -> ChatBridgeSettings:
    section = raw.get("CHAT_BRIDGE") or {}
    events = section.get("EVENTS") or {}
    silent = section.get("SILENT_EVENTS") or []
    minecraft = section.get("MINECRAFT_FORMAT") or {}
    fallback = _optional_topic(section.get("TOPIC_ID"))
    status_topic = (
        _optional_topic(section.get("STATUS_TOPIC_ID"))
        if "STATUS_TOPIC_ID" in section
        else fallback
    )
    chat_topic = (
        _optional_topic(section.get("CHAT_TOPIC_ID"))
        if "CHAT_TOPIC_ID" in section
        else fallback
    )
    return ChatBridgeSettings(
        enabled=bool(section.get("ENABLED", True)),
        forum_chat_id=forum_chat_id,
        status_topic_id=status_topic,
        chat_topic_id=chat_topic,
        merge_window=int(section.get("MERGE_WINDOW", 0)),
        leave_join_merge_window=int(section.get("LEAVE_JOIN_MERGE_WINDOW", 0)),
        require_prefix_minecraft=_optional_prefix(section.get("REQUIRE_PREFIX_MINECRAFT")),
        require_prefix_telegram=_optional_prefix(section.get("REQUIRE_PREFIX_TELEGRAM")),
        keep_prefix=bool(section.get("KEEP_PREFIX", False)),
        use_real_username=bool(section.get("USE_REAL_USERNAME", False)),
        silent_events=frozenset(str(item).upper() for item in silent),
        join_messages=str(events.get("JOIN", "true")).lower(),
        leave_messages=bool(events.get("LEAVE", True)),
        death_messages=bool(events.get("DEATH", True)),
        start_messages=bool(events.get("START", True)),
        stop_messages=bool(events.get("STOP", True)),
        advancement_messages=bool(events.get("ADVANCEMENT", True)),
        advancement_task=bool(events.get("ADVANCEMENT_TASK", True)),
        advancement_goal=bool(events.get("ADVANCEMENT_GOAL", True)),
        advancement_challenge=bool(events.get("ADVANCEMENT_CHALLENGE", True)),
        advancement_description=bool(events.get("ADVANCEMENT_DESCRIPTION", True)),
        formats=_load_formats(section.get("FORMAT")),
        minecraft_message_format=_optional_prefix(minecraft.get("MESSAGE")),
        minecraft_reply_format=_optional_prefix(minecraft.get("REPLY")),
        minecraft_reply_enabled=_reply_enabled(minecraft),
        minecraft_edit_prefix=str(minecraft.get("EDIT_PREFIX", "✎ ") or ""),
    )


def _reply_enabled(minecraft: dict[str, Any]) -> bool:
    if "REPLY" not in minecraft:
        return True
    value = minecraft.get("REPLY")
    if value is None or value is False:
        return False
    return str(value).strip().lower() not in {"", "false", "off", "no", "null", "none"}


def _load_formats(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    formats: dict[str, str] = {}
    for key, template in value.items():
        name = str(key).upper()
        if name not in DEFAULT_FORMATS:
            log.warning("Неизвестный ключ CHAT_BRIDGE.FORMAT.%s пропущен", key)
            continue
        formats[name] = "" if template is None else str(template)
    return formats


def _optional_topic(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if text in {"", "null", "None"}:
        return None
    number = int(text)
    if number <= 0:
        log.warning(
            "Число %s — это id чата, а не темы. Напишите /topic внутри нужной темы форума.",
            number,
        )
        return None
    return number


def take_new_events(
    events: list[dict[str, Any]], cursor: int, primed: bool, since_ms: int = 0
) -> tuple[int, bool, list[dict[str, Any]]]:
    """On the first poll, events queued before the bot started (older than since_ms) are skipped."""
    fresh: list[dict[str, Any]] = []
    for event in events:
        event_id = int(event.get("id") or 0)
        if event_id <= cursor:
            continue
        cursor = event_id
        if primed or int(event.get("at") or 0) >= since_ms:
            fresh.append(event)
    return cursor, True, fresh


STATUS_EVENTS = frozenset({"server_start", "server_stop"})


def topic_for_event(kind: str, settings: ChatBridgeSettings) -> int | None:
    if kind in STATUS_EVENTS:
        return settings.status_topic_id
    return settings.chat_topic_id


def _optional_prefix(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    if text.strip() in {"", "null", "None"}:
        return None
    return text


def apply_prefix(text: str, prefix: str | None, keep: bool) -> str | None:
    if not prefix:
        return text
    if not text.startswith(prefix):
        return None
    if keep:
        return text
    return text[len(prefix) :].lstrip()


def minecraft_name(event: dict[str, Any], use_real_username: bool) -> str:
    if use_real_username:
        return str(event.get("username") or event.get("display") or "игрок")
    return str(event.get("display") or event.get("username") or "игрок")


def format_server_event(event: dict[str, Any], settings: ChatBridgeSettings) -> str | None:
    text = _format_event(event, settings)
    if text is None or not text.strip():
        return None
    return text


def _format_event(event: dict[str, Any], settings: ChatBridgeSettings) -> str | None:
    kind = str(event.get("type") or "")
    name = minecraft_name(event, settings.use_real_username)
    if kind == "server_start":
        return settings.fmt("SERVER_START") if settings.start_messages else None
    if kind == "server_stop":
        return settings.fmt("SERVER_STOP") if settings.stop_messages else None
    if kind == "join":
        mode = settings.join_messages
        if mode in {"false", "0", "no"}:
            return None
        if mode in {"first_join_only", "first"} and not event.get("first_join"):
            return None
        key = "FIRST_JOIN" if event.get("first_join") else "JOIN"
        return render(settings.fmt(key), name=name)
    if kind == "leave":
        return render(settings.fmt("LEAVE"), name=name) if settings.leave_messages else None
    if kind == "death":
        if not settings.death_messages:
            return None
        text = str(event.get("text") or "").strip()
        if not text or text.startswith("death."):
            return render(settings.fmt("DEATH_UNKNOWN"), name=name)
        return render(settings.fmt("DEATH"), name=name, text=text)
    if kind == "advancement":
        return _format_advancement(event, settings, name)
    if kind == "chat":
        text = apply_prefix(
            str(event.get("text") or ""),
            settings.require_prefix_minecraft,
            settings.keep_prefix,
        )
        if text is None:
            return None
        return render(settings.fmt("CHAT"), name=name, text=text)
    if kind == "custom":
        return _format_custom(event)
    return None


def _format_advancement(
    event: dict[str, Any], settings: ChatBridgeSettings, name: str
) -> str | None:
    if not settings.advancement_messages:
        return None
    kind = str(event.get("advancement_type") or "task")
    allowed = {
        "task": settings.advancement_task,
        "goal": settings.advancement_goal,
        "challenge": settings.advancement_challenge,
    }
    if not allowed.get(kind, settings.advancement_task):
        return None
    key = {"goal": "ADVANCEMENT_GOAL", "challenge": "ADVANCEMENT_CHALLENGE"}.get(
        kind, "ADVANCEMENT_TASK"
    )
    title = str(event.get("title") or "достижение")
    description = str(event.get("description") or "")
    line = render(settings.fmt(key), name=name, title=title, description=description)
    if settings.advancement_description and description:
        line += render(settings.fmt("ADVANCEMENT_DESCRIPTION"), description=description)
    return line


def _format_custom(event: dict[str, Any]) -> str:
    text = str(event.get("text") or "")
    fmt = str(event.get("format") or "plain")
    if fmt == "html":
        return text
    if fmt == "mm":
        return html.escape(_strip_minimessage(text))
    if fmt == "json":
        return html.escape(_strip_json_text(text))
    return html.escape(text)


def _strip_minimessage(text: str) -> str:
    result = []
    index = 0
    while index < len(text):
        if text[index] == "<":
            end = text.find(">", index)
            if end == -1:
                result.append(text[index:])
                break
            index = end + 1
            continue
        result.append(text[index])
        index += 1
    return "".join(result)


def _strip_json_text(text: str) -> str:
    try:
        import json

        parsed = json.loads(text)
    except (ValueError, TypeError):
        return text
    return _collect_json_text(parsed)


def _collect_json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_collect_json_text(item) for item in value)
    if isinstance(value, dict):
        parts = []
        if "text" in value:
            parts.append(str(value.get("text") or ""))
        if "extra" in value:
            parts.append(_collect_json_text(value.get("extra")))
        return "".join(parts)
    return ""


def silent_event_name(kind: str) -> str:
    return {
        "server_start": "SERVER_STARTUP",
        "server_stop": "SERVER_SHUTDOWN",
        "chat": "CHAT",
        "death": "DEATH",
        "join": "JOIN",
        "leave": "LEAVE",
        "advancement": "ADVANCEMENT",
    }.get(kind, kind.upper())


def in_topic(message: Message, topic_id: int | None) -> bool:
    if topic_id is None:
        return True
    thread_id = message.message_thread_id
    if topic_id == 1:
        return thread_id in (None, 1)
    return thread_id == topic_id


def telegram_plain_text(message: Message) -> str:
    text = message.text or message.caption or ""
    label = _media_label(message)
    if label and text:
        return f"{label} {text}"
    if label:
        poll = getattr(message, "poll", None)
        if poll is not None and getattr(poll, "question", None):
            return f"{label} {poll.question}"
        return label
    return text


def _media_label(message: Message) -> str | None:
    if message.animation:
        return MEDIA_LABELS["animation"]
    if message.photo:
        return MEDIA_LABELS["photo"]
    if message.video:
        return MEDIA_LABELS["video"]
    if message.video_note:
        return MEDIA_LABELS["video_note"]
    if message.voice:
        return MEDIA_LABELS["voice"]
    if message.audio:
        return MEDIA_LABELS["audio"]
    if message.document:
        return MEDIA_LABELS["document"]
    if message.sticker:
        return MEDIA_LABELS["sticker"]
    if message.poll:
        return MEDIA_LABELS["poll"]
    return None


def reply_excerpt(message: Message) -> str | None:
    reply = message.reply_to_message
    if reply is None:
        return None
    excerpt = (reply.text or reply.caption or _media_label(reply) or "").strip()
    if not excerpt:
        return None
    excerpt = " ".join(excerpt.split())
    if len(excerpt) > 80:
        excerpt = excerpt[:77] + "..."
    return excerpt


def sender_name(message: Message) -> str:
    user = message.from_user
    if user is None:
        return "Telegram"
    if user.username:
        return user.username
    return user.full_name or str(user.id)


class ForumChatBridge:
    def __init__(self, settings: ChatBridgeSettings, server: ServerLink) -> None:
        self.settings = settings
        self.server = server
        self._missing_topics: set[int] = set()
        self.router = Router()
        self._cursor = 0
        self._primed = False
        self._session = ""
        self._started_ms = int(time.time() * 1000) - 5000
        self._seen_server = False
        self._misses = 0
        self._stop_sent = False
        self._last_chat: dict[str, tuple[float, int, str]] = {}
        self._last_leave: dict[str, tuple[float, int]] = {}
        self.router.message(F.chat.id == settings.forum_chat_id)(self.on_forum_message)
        self.router.edited_message(F.chat.id == settings.forum_chat_id)(self.on_forum_edit)

    async def run(self, bot: Bot) -> None:
        if not self.settings.enabled:
            return
        if self.settings.status_topic_id is None or self.settings.chat_topic_id is None:
            log.warning(
                "Темы моста не заданы. Напишите /topic в теме статуса и в теме чата, "
                "затем вставьте номера в STATUS_TOPIC_ID и CHAT_TOPIC_ID."
            )
        while True:
            try:
                session, events = await self.server.poll_chat_events(self._cursor)
                if self._misses >= 3:
                    log.info("Сервер Minecraft снова на связи")
                self._misses = 0
                self._seen_server = True
                if session != self._session:
                    restarted = bool(self._session)
                    self._session = session
                    if restarted or self._cursor:
                        # The plugin numbers events from 1 after each server start.
                        self._cursor = 0
                        self._primed = True
                        continue
                self._cursor, self._primed, fresh = take_new_events(
                    events, self._cursor, self._primed, self._started_ms
                )
                for event in fresh:
                    await self._publish(bot, event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._misses += 1
                if self._seen_server and self._misses == 3 and not self._stop_sent:
                    self._stop_sent = True
                    text = format_server_event({"type": "server_stop"}, self.settings)
                    if text is not None:
                        await self._send(bot, text, "server_stop")
                if self._misses == 1:
                    log.warning("Сервер Minecraft не отвечает: %s", exc)
            await asyncio.sleep(1)

    def _accepts_chat(self, message: Message) -> bool:
        if self.settings.chat_topic_id is None:
            if self.settings.status_topic_id is None:
                return True
            return not in_topic(message, self.settings.status_topic_id)
        return in_topic(message, self.settings.chat_topic_id)

    def _accepts_command(self, message: Message) -> bool:
        if self._accepts_chat(message):
            return True
        return self.settings.status_topic_id is not None and in_topic(
            message, self.settings.status_topic_id
        )

    async def on_forum_message(self, message: Message) -> None:
        if not self.settings.enabled:
            return
        if message.from_user is not None and message.from_user.is_bot:
            return
        text = (message.text or "").strip()
        command = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
        if command in {"/list", "/tps"}:
            if not self._accepts_command(message):
                return
            if command == "/list":
                await self._reply_list(message)
            else:
                await self._reply_tps(message)
            return
        if command.startswith("/") or not self._accepts_chat(message):
            return
        body = apply_prefix(
            telegram_plain_text(message),
            self.settings.require_prefix_telegram,
            self.settings.keep_prefix,
        )
        if not body or not body.strip():
            return
        try:
            await self.server.broadcast_chat(
                sender_name(message),
                body,
                reply_excerpt(message) if self.settings.minecraft_reply_enabled else None,
                self.settings.minecraft_message_format,
                self.settings.minecraft_reply_format,
            )
        except Exception as exc:
            log.warning("Could not forward Telegram message: %s", exc)

    async def on_forum_edit(self, message: Message) -> None:
        if not self.settings.enabled or not self._accepts_chat(message):
            return
        if message.from_user is not None and message.from_user.is_bot:
            return
        body = telegram_plain_text(message).strip()
        if not body:
            return
        try:
            await self.server.broadcast_chat(
                sender_name(message),
                f"{self.settings.minecraft_edit_prefix}{body}",
                None,
                self.settings.minecraft_message_format,
                self.settings.minecraft_reply_format,
            )
        except Exception as exc:
            log.warning("Could not forward edited Telegram message: %s", exc)

    async def _reply_list(self, message: Message) -> None:
        try:
            online = await self.server.get_online()
        except Exception as exc:
            await message.answer(render(self.settings.fmt("SERVER_UNAVAILABLE"), error=exc))
            return
        players = online.get("players") or []
        if not isinstance(players, list) or not players:
            await message.answer(self.settings.fmt("LIST_EMPTY"))
            return
        await message.answer(
            render(
                self.settings.fmt("LIST"),
                count=len(players),
                players=", ".join(str(player) for player in players),
            )
        )

    async def _reply_tps(self, message: Message) -> None:
        try:
            tps = await self.server.get_tps()
        except Exception as exc:
            await message.answer(render(self.settings.fmt("SERVER_UNAVAILABLE"), error=exc))
            return
        await message.answer(
            render(
                self.settings.fmt("TPS"),
                tps=f"{float(tps.get('tps1m', 0)):.1f}",
                tps5m=f"{float(tps.get('tps5m', 0)):.1f}",
                tps15m=f"{float(tps.get('tps15m', 0)):.1f}",
                mspt=f"{float(tps.get('mspt', 0)):.1f}",
            )
        )

    async def _publish(self, bot: Bot, event: dict[str, Any]) -> None:
        kind = str(event.get("type") or "")
        if kind == "server_start":
            self._stop_sent = False
        if kind == "server_stop":
            if self._stop_sent:
                return
            self._stop_sent = True
        if kind == "leave" and self.settings.leave_join_merge_window > 0:
            text = format_server_event(event, self.settings)
            if text is None:
                return
            sent = await self._send(bot, text, kind)
            if sent is not None:
                self._last_leave[str(event.get("username"))] = (time.monotonic(), sent.message_id)
            return
        if kind == "join" and await self._merged_rejoin(bot, event):
            return
        if kind == "chat" and await self._merged_chat(bot, event):
            return
        text = format_server_event(event, self.settings)
        if text is None:
            return
        await self._send(bot, text, kind)

    async def _merged_rejoin(self, bot: Bot, event: dict[str, Any]) -> bool:
        window = self.settings.leave_join_merge_window
        if window <= 0 or not self.settings.leave_messages or self.settings.join_messages in {
            "false",
            "0",
            "no",
        }:
            return False
        previous = self._last_leave.get(str(event.get("username")))
        if previous is None:
            return False
        sent_at, message_id = previous
        if time.monotonic() - sent_at > window:
            return False
        try:
            await bot.delete_message(self.settings.forum_chat_id, message_id)
        except Exception:
            log.debug("Could not delete merged leave message", exc_info=True)
        self._last_leave.pop(str(event.get("username")), None)
        return True

    async def _merged_chat(self, bot: Bot, event: dict[str, Any]) -> bool:
        window = self.settings.merge_window
        if window <= 0:
            return False
        text = format_server_event(event, self.settings)
        if text is None:
            return True
        key = str(event.get("username") or "")
        previous = self._last_chat.get(key)
        now = time.monotonic()
        if previous is None or now - previous[0] > window:
            sent = await self._send(bot, text, "chat")
            if sent is not None:
                self._last_chat[key] = (now, sent.message_id, text)
            return True
        _, message_id, old = previous
        body = apply_prefix(
            str(event.get("text") or ""),
            self.settings.require_prefix_minecraft,
            self.settings.keep_prefix,
        )
        merged = old + "\n" + html.escape(body or "")
        try:
            await bot.edit_message_text(
                merged,
                chat_id=self.settings.forum_chat_id,
                message_id=message_id,
            )
            self._last_chat[key] = (previous[0], message_id, merged)
        except Exception:
            sent = await self._send(bot, text, "chat")
            if sent is not None:
                self._last_chat[key] = (now, sent.message_id, text)
        return True

    async def _send(self, bot: Bot, text: str, kind: str) -> Message | None:
        topic_id = topic_for_event(kind, self.settings)
        if topic_id in self._missing_topics:
            return None
        try:
            return await self._send_once(bot, text, kind, topic_id)
        except TelegramBadRequest as exc:
            if topic_id is not None and "message thread not found" in exc.message.lower():
                self._missing_topics.add(topic_id)
                log.warning(
                    "Тема %s не найдена. Напишите /topic в нужной теме и укажите STATUS_TOPIC_ID или CHAT_TOPIC_ID.",
                    topic_id,
                )
                return None
            log.warning("Не удалось отправить сообщение моста: %s", exc.message)
            return None

    async def _send_once(
        self, bot: Bot, text: str, kind: str, topic_id: int | None
    ) -> Message:
        return await bot.send_message(
            self.settings.forum_chat_id,
            text,
            message_thread_id=topic_id,
            disable_notification=silent_event_name(kind) in self.settings.silent_events,
        )
