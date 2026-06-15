import asyncio
import html
import re
import shutil
from urllib.parse import quote
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

import aiohttp
import aiosqlite
import yaml
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from PIL import Image, ImageDraw, ImageFont
from strings import Strings


NICKNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")


@dataclass(frozen=True)
class BridgeConfig:
    base_url: str
    token: str
    timeout_seconds: int


@dataclass(frozen=True)
class BotMessages:
    enter_nickname: str
    form_start: str
    rules: str
    form_complete: str
    already_applied: str
    application_accepted: str
    application_rejected: str
    application_banned: str


@dataclass(frozen=True)
class AppConfig:
    bot_token: str
    bot_username: str
    admin_chat_id: int
    admins: set[int]
    bridge: BridgeConfig
    db_path: str
    db_backup_dir: str
    db_backup_keep_last: int
    questions: list[str]
    messages: BotMessages


@dataclass
class ApplicationSession:
    nickname: str | None = None
    answers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RejectionSession:
    application_id: int
    telegram_id: int
    nickname: str
    message_chat_id: int
    message_id: int


@dataclass(frozen=True)
class BroadcastSession:
    started_at: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class Application:
    id: int
    telegram_id: int
    username: str | None
    nickname: str
    answers: list[str]
    status: str
    created_at: str
    decided_by: int | None = None
    decided_at: str | None = None
    decided_by_name: str | None = None
    decision_reason: str | None = None


class ApplicationBlockedError(Exception):
    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


def load_config() -> AppConfig:
    config_path = Path(__file__).with_name("config.yml")
    if not config_path.exists():
        raise RuntimeError(
            "Не найден python-bot/config.yml. Скопируй config.example.yml и заполни значения."
        )

    raw: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    questions = list(raw["QUESTIONS"])
    if not questions:
        raise RuntimeError("В config.yml должен быть хотя бы один вопрос.")

    db_path = Path(raw.get("DATABASE", {}).get("PATH", "applications.db"))
    if not db_path.is_absolute():
        db_path = config_path.parent / db_path
    database = raw.get("DATABASE", {})
    db_backup_dir = Path(database.get("BACKUP_DIR", db_path.parent / "backups"))
    if not db_backup_dir.is_absolute():
        db_backup_dir = config_path.parent / db_backup_dir

    messages = raw["MESSAGES"]
    bridge = raw.get("BRIDGE", {})

    return AppConfig(
        bot_token=str(raw["BOT_TOKEN"]),
        bot_username=str(raw.get("BOT_USERNAME", "")),
        admin_chat_id=int(raw["ADMIN_CHAT_ID"]),
        admins={int(admin_id) for admin_id in raw.get("ADMINS", [])},
        bridge=BridgeConfig(
            base_url=str(bridge.get("BASE_URL", "http://127.0.0.1:8088")).rstrip("/"),
            token=str(bridge.get("TOKEN", "change-this-long-random-secret")),
            timeout_seconds=int(bridge.get("TIMEOUT_SECONDS", 5)),
        ),
        db_path=str(db_path),
        db_backup_dir=str(db_backup_dir),
        db_backup_keep_last=int(database.get("BACKUP_KEEP_LAST", 30)),
        questions=questions,
        messages=BotMessages(
            enter_nickname=str(messages["ENTER_NICKNAME"]),
            form_start=str(messages["FORM_START"]),
            rules=str(
                messages.get(
                    "RULES", "Нажмите кнопку ниже, когда ознакомитесь с правилами."
                )
            ),
            form_complete=str(messages["FORM_COMPLETE"]),
            already_applied=str(messages["ALREADY_APPLIED"]),
            application_accepted=str(messages["APPLICATION_ACCEPTED"]),
            application_rejected=str(messages["APPLICATION_REJECTED"]),
            application_banned=str(messages["APPLICATION_BANNED"]),
        ),
    )


class ApplicationStore:
    def __init__(
        self, db_path: str, backup_dir: str, backup_keep_last: int = 30
    ) -> None:
        self.db_path = Path(db_path)
        self.backup_dir = Path(backup_dir)
        self.backup_keep_last = max(1, backup_keep_last)

    async def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._restore_latest_backup_if_needed()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    username TEXT,
                    nickname TEXT NOT NULL,
                    answers TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    decided_by INTEGER,
                    decided_at TEXT
                )
                """
            )
            await self._ensure_column(db, "applications", "decided_by_name", "TEXT")
            await self._ensure_column(db, "applications", "decision_reason", "TEXT")
            await db.commit()
        self._backup_now("init")

    async def create(
        self, telegram_id: int, username: str | None, nickname: str, answers: list[str]
    ) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            gate_status = await self._get_gate_status(db, telegram_id)
            if gate_status:
                await db.rollback()
                raise ApplicationBlockedError(gate_status)

            cursor = await db.execute(
                """
                INSERT INTO applications (telegram_id, username, nickname, answers)
                VALUES (?, ?, ?, ?)
                """,
                (telegram_id, username, nickname, "\n".join(answers)),
            )
            await db.commit()
            self._backup_now("create")
            return int(cursor.lastrowid)

    async def get_latest_status(self, telegram_id: int) -> str | None:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT status FROM applications
                WHERE telegram_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (telegram_id,),
            )
            row = await cursor.fetchone()
            return str(row[0]) if row else None

    async def get_gate_status(self, telegram_id: int) -> str | None:
        async with aiosqlite.connect(self.db_path) as db:
            return await self._get_gate_status(db, telegram_id)

    @staticmethod
    async def _get_gate_status(
        db: aiosqlite.Connection, telegram_id: int
    ) -> str | None:
        cursor = await db.execute(
            """
            SELECT status FROM applications
            WHERE telegram_id = ? AND status IN ('banned', 'approved', 'pending')
            ORDER BY
                CASE status
                    WHEN 'banned' THEN 1
                    WHEN 'approved' THEN 2
                    WHEN 'pending' THEN 3
                    ELSE 4
                END,
                id DESC
            LIMIT 1
            """,
            (telegram_id,),
        )
        row = await cursor.fetchone()
        return str(row[0]) if row else None

    async def get_pending(self, application_id: int) -> tuple[int, str] | None:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT telegram_id, nickname FROM applications WHERE id = ? AND status = 'pending'",
                (application_id,),
            )
            row = await cursor.fetchone()
            return (int(row[0]), str(row[1])) if row else None

    async def get_by_id(self, application_id: int) -> Application | None:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT id, telegram_id, username, nickname, answers, status, created_at, decided_by, decided_at, decided_by_name, decision_reason
                FROM applications
                WHERE id = ?
                """,
                (application_id,),
            )
            row = await cursor.fetchone()
            return self._application_from_row(row) if row else None

    async def list_applications(
        self, status: str | None = None, limit: int = 10
    ) -> list[Application]:
        query = """
            SELECT id, telegram_id, username, nickname, answers, status, created_at, decided_by, decided_at, decided_by_name, decision_reason
            FROM applications
        """
        params: tuple[Any, ...] = ()
        if status:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY id DESC LIMIT ?"
        params += (limit,)

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(query, params)
            rows = await cursor.fetchall()
            return [self._application_from_row(row) for row in rows]

    async def search(self, query: str, limit: int = 10) -> list[Application]:
        clean = query.strip().lstrip("#")
        async with aiosqlite.connect(self.db_path) as db:
            if clean.isdigit():
                cursor = await db.execute(
                    """
                    SELECT id, telegram_id, username, nickname, answers, status, created_at, decided_by, decided_at, decided_by_name, decision_reason
                    FROM applications
                    WHERE id = ? OR telegram_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (int(clean), int(clean), limit),
                )
            else:
                like = f"%{clean}%"
                cursor = await db.execute(
                    """
                    SELECT id, telegram_id, username, nickname, answers, status, created_at, decided_by, decided_at, decided_by_name, decision_reason
                    FROM applications
                    WHERE nickname LIKE ? OR username LIKE ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (like, like, limit),
                )
            rows = await cursor.fetchall()
            return [self._application_from_row(row) for row in rows]

    async def counts_by_status(self) -> dict[str, int]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT status, COUNT(*) FROM applications GROUP BY status"
            )
            rows = await cursor.fetchall()
            return {str(status): int(count) for status, count in rows}

    async def daily_counts(self, days: int = 14) -> list[tuple[str, int]]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                SELECT DATE(created_at), COUNT(DISTINCT telegram_id)
                FROM applications
                WHERE created_at >= DATETIME('now', ?)
                GROUP BY DATE(created_at)
                ORDER BY DATE(created_at)
                """,
                (f"-{days - 1} days",),
            )
            rows = await cursor.fetchall()

        found = {str(day): int(count) for day, count in rows}
        today = datetime.now().date()
        start = today - timedelta(days=days - 1)
        return [
            (
                (start + timedelta(days=offset)).isoformat(),
                found.get((start + timedelta(days=offset)).isoformat(), 0),
            )
            for offset in range(days)
        ]

    async def user_count(self) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT COUNT(DISTINCT telegram_id) FROM applications"
            )
            row = await cursor.fetchone()
            return int(row[0]) if row else 0

    async def user_ids(self) -> list[int]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT DISTINCT telegram_id FROM applications ORDER BY telegram_id"
            )
            rows = await cursor.fetchall()
            return [int(row[0]) for row in rows]

    async def decide(
        self,
        application_id: int,
        status: str,
        admin_id: int,
        admin_name: str,
        reason: str | None = None,
    ) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE applications
                SET status = ?, decided_by = ?, decided_by_name = ?, decision_reason = ?, decided_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, admin_id, admin_name, reason, application_id),
            )
            await db.commit()
        self._backup_now("decide")

    async def unban_user(self, telegram_id: int, admin_id: int, admin_name: str) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                UPDATE applications
                SET status = 'rejected',
                    decided_by = ?,
                    decided_by_name = ?,
                    decision_reason = 'Разбанен администратором',
                    decided_at = CURRENT_TIMESTAMP
                WHERE telegram_id = ? AND status = 'banned'
                """,
                (admin_id, admin_name, telegram_id),
            )
            await db.commit()
            self._backup_now("unban")
            return cursor.rowcount

    def _restore_latest_backup_if_needed(self) -> None:
        if self.db_path.exists():
            return
        backups = sorted(self.backup_dir.glob(f"{self.db_path.stem}-*.db"))
        if backups:
            shutil.copy2(backups[-1], self.db_path)

    def _backup_now(self, reason: str) -> None:
        if not self.db_path.exists():
            return
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup_path = self.backup_dir / f"{self.db_path.stem}-{timestamp}-{reason}.db"
        shutil.copy2(self.db_path, backup_path)
        backups = sorted(self.backup_dir.glob(f"{self.db_path.stem}-*.db"))
        for old_backup in backups[: -self.backup_keep_last]:
            old_backup.unlink(missing_ok=True)

    @staticmethod
    async def _ensure_column(
        db: aiosqlite.Connection, table: str, column: str, column_type: str
    ) -> None:
        cursor = await db.execute(f"PRAGMA table_info({table})")
        columns = {str(row[1]) for row in await cursor.fetchall()}
        if column not in columns:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    @staticmethod
    def _application_from_row(row: tuple[Any, ...]) -> Application:
        return Application(
            id=int(row[0]),
            telegram_id=int(row[1]),
            username=str(row[2]) if row[2] else None,
            nickname=str(row[3]),
            answers=str(row[4]).splitlines(),
            status=str(row[5]),
            created_at=str(row[6]),
            decided_by=int(row[7]) if len(row) > 7 and row[7] is not None else None,
            decided_at=str(row[8]) if len(row) > 8 and row[8] else None,
            decided_by_name=str(row[9]) if len(row) > 9 and row[9] else None,
            decision_reason=str(row[10]) if len(row) > 10 and row[10] else None,
        )


class MinecraftBridge:
    def __init__(self, config: BridgeConfig) -> None:
        self.config = config

    async def get_status(self) -> dict[str, Any]:
        return await self._get_json("/server/status")

    async def get_online(self) -> dict[str, Any]:
        return await self._get_json("/server/online")

    async def get_player_info(self, nickname: str) -> dict[str, Any]:
        return await self._get_json(f"/player/info?name={quote(nickname)}")

    async def kick_player(self, nickname: str, reason: str = "Kicked by admin") -> str:
        return await self.exec_command(f"kick {nickname} {reason}")

    async def add_to_whitelist(self, nickname: str) -> None:
        timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
        headers = {"Authorization": f"Bearer {self.config.token}"}
        payload = {"nickname": nickname}

        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.post(
                f"{self.config.base_url}/whitelist/add", json=payload
            ) as response:
                body = await response.text()
                if response.status >= 400:
                    raise RuntimeError(
                        f"Bridge returned HTTP {response.status}: {body}"
                    )

    async def exec_command(self, command: str) -> str:
        """Send a console command to the bridge and return the raw response body."""
        timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
        headers = {"Authorization": f"Bearer {self.config.token}"}
        payload = {"command": command}

        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.post(
                f"{self.config.base_url}/console/exec", json=payload
            ) as response:
                body = await response.text()
                if response.status >= 400:
                    raise RuntimeError(
                        f"Bridge returned HTTP {response.status}: {body}"
                    )
                return body

    async def _get_json(self, endpoint: str) -> dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
        headers = {"Authorization": f"Bearer {self.config.token}"}

        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(f"{self.config.base_url}{endpoint}") as response:
                body = await response.text()
                if response.status >= 400:
                    raise RuntimeError(
                        f"Bridge returned HTTP {response.status}: {body}"
                    )
                try:
                    data = await response.json(content_type=None)
                except aiohttp.ContentTypeError as exc:
                    raise RuntimeError(f"Bridge returned invalid JSON: {body}") from exc
                if not isinstance(data, dict):
                    raise RuntimeError(f"Bridge returned unexpected JSON: {body}")
                return data


class ApplicationFlow:
    def __init__(
        self, config: AppConfig, store: ApplicationStore, bridge: MinecraftBridge
    ) -> None:
        self.config = config
        self.store = store
        self.bridge = bridge
        self.router = Router()
        self.sessions: dict[int, ApplicationSession] = {}
        self.admin_search_sessions: set[int] = set()
        self.console_sessions: set[int] = set()
        self.reject_sessions: dict[int, RejectionSession] = {}
        self.broadcast_sessions: dict[int, BroadcastSession] = {}
        self._register_handlers()

    def _register_handlers(self) -> None:
        self.router.message(Command("start", "panel"))(self.start)
        self.router.message(F.chat.id == self.config.admin_chat_id)(
            self.handle_admin_message
        )
        self.router.message(F.chat.type == "private")(self.answer_question)
        self.router.callback_query(F.data.startswith("flow:"))(self.handle_flow)
        self.router.callback_query(F.data.startswith("app:"))(self.handle_admin_action)
        self.router.callback_query(F.data.startswith("player:"))(
            self.handle_player_action
        )
        self.router.callback_query(F.data.startswith("panel:"))(self.handle_admin_panel)

    async def start(self, message: Message) -> None:
        if message.chat.type != "private":
            if message.chat.id == self.config.admin_chat_id and self._is_admin(
                message.from_user.id
            ):
                await message.answer(
                    Strings.ADMIN_PANEL, reply_markup=self._admin_panel_keyboard()
                )
            return

        if self._is_admin(message.from_user.id):
            await self._send_player_status(message, message.from_user.id)
            await message.answer(
                Strings.ADMIN_PANEL, reply_markup=self._admin_panel_keyboard()
            )
            return

        await self._send_player_menu(message, message.from_user.id)

    async def _send_player_status(self, message: Message, user_id: int) -> bool:
        latest_status = await self.store.get_gate_status(user_id)
        status_message = self._status_message(latest_status)
        if status_message:
            await message.answer(status_message)
            return True

        return False

    async def _send_player_menu(self, message: Message, user_id: int) -> None:
        if await self._send_player_status(message, user_id):
            return
        await message.answer(
            self.config.messages.form_start,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=Strings.BUTTON_START, callback_data="flow:start"
                        )
                    ]
                ]
            ),
        )

    async def handle_flow(self, callback: CallbackQuery) -> None:
        if callback.message.chat.type != "private":
            await self._safe_answer(
                callback, Strings.ONLY_PRIVATE_ALERT, show_alert=True
            )
            return

        action = callback.data.split(":", maxsplit=1)[1]
        user_id = callback.from_user.id
        latest_status = await self.store.get_gate_status(user_id)
        status_message = self._status_message(latest_status)
        if status_message:
            self.sessions.pop(user_id, None)
            await self._safe_answer(callback, status_message, show_alert=True)
            await self._safe_clear_reply_markup(callback.message)
            return

        if action == "start":
            if user_id in self.sessions:
                await self._safe_answer(
                    callback,
                    "Анкета уже начата. Ответьте на текущий вопрос.",
                    show_alert=True,
                )
                return
            await self._safe_answer(callback)
            await self._safe_clear_reply_markup(callback.message)
            await callback.message.answer(
                self.config.messages.rules,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text="Я ознакомлен", callback_data="flow:agree"
                            )
                        ]
                    ]
                ),
            )
            return

        if action == "agree":
            if user_id in self.sessions:
                await self._safe_answer(
                    callback,
                    "Анкета уже начата. Ответьте на текущий вопрос.",
                    show_alert=True,
                )
                return
            self.sessions[user_id] = ApplicationSession()
            await self._safe_answer(callback)
            await self._safe_clear_reply_markup(callback.message)
            await callback.message.answer(self.config.messages.enter_nickname)

    async def answer_question(self, message: Message, bot: Bot) -> None:
        user_id = message.from_user.id
        if await self._handle_admin_message(message, bot):
            return
        if user_id not in self.sessions:
            return

        latest_status = await self.store.get_gate_status(user_id)
        status_message = self._status_message(latest_status)
        if status_message:
            self.sessions.pop(user_id, None)
            await message.answer(status_message)
            return

        session = self.sessions[user_id]
        if message.text is None:
            await message.answer("Пожалуйста, отправьте ответ текстом.")
            return
        text = message.text.strip()

        if session.nickname is None:
            if not NICKNAME_RE.fullmatch(text):
                await message.answer(Strings.INVALID_NICKNAME)
                return

            session.nickname = text
            await message.answer(self.config.questions[0])
            return

        session.answers.append(text)

        if len(session.answers) < len(self.config.questions):
            await message.answer(self.config.questions[len(session.answers)])
            return

        latest_status = await self.store.get_gate_status(user_id)
        status_message = self._status_message(latest_status)
        if status_message:
            self.sessions.pop(user_id, None)
            await message.answer(status_message)
            return

        try:
            application_id = await self.store.create(
                telegram_id=user_id,
                username=message.from_user.username,
                nickname=session.nickname,
                answers=session.answers,
            )
        except ApplicationBlockedError as exc:
            self.sessions.pop(user_id, None)
            await message.answer(
                self._status_message(exc.status) or self.config.messages.already_applied
            )
            return
        self.sessions.pop(user_id, None)

        await bot.send_message(
            self.config.admin_chat_id,
            self._format_application(
                Application(
                    id=application_id,
                    telegram_id=user_id,
                    username=message.from_user.username,
                    nickname=session.nickname,
                    answers=session.answers,
                    status="pending",
                    created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    decided_by=None,
                    decided_at=None,
                    decided_by_name=None,
                    decision_reason=None,
                )
            ),
            reply_markup=self._application_keyboard(application_id),
        )
        await message.answer(self.config.messages.form_complete)

    async def handle_admin_action(self, callback: CallbackQuery, bot: Bot) -> None:
        if not await self._allow_admin_callback(callback):
            return

        _, action, raw_application_id = callback.data.split(":")
        application_id = int(raw_application_id)

        if action == "view":
            application = await self.store.get_by_id(application_id)
            if application is None:
                await self._safe_answer(
                    callback, Strings.APPLICATION_NOT_FOUND, show_alert=True
                )
                return

            await self._safe_answer(callback)
            reply_markup = (
                self._application_keyboard(application.id)
                if application.status == "pending"
                else None
            )
            if application.status == "banned":
                reply_markup = self._banned_application_keyboard(application.id)
            await callback.message.answer(
                self._format_application(application), reply_markup=reply_markup
            )
            return

        pending = await self.store.get_pending(application_id)

        if pending is None:
            application = await self.store.get_by_id(application_id)
            if (
                action == "unban"
                and application is not None
                and application.status == "banned"
            ):
                admin_id = callback.from_user.id
                admin_name = self._admin_display_name(callback.from_user)
                updated = await self.store.unban_user(
                    application.telegram_id, admin_id, admin_name
                )
                await self._safe_answer(
                    callback,
                    "Разбанено ✅" if updated else "Бан не найден",
                    show_alert=True,
                )
                await callback.message.answer(
                    f"♻️ Пользователь <code>{application.telegram_id}</code> разбанен ({html.escape(admin_name)})."
                )
                return
            await self._safe_answer(
                callback, Strings.APPLICATION_ALREADY_PROCESSED, show_alert=True
            )
            return

        telegram_id, nickname = pending
        admin_id = callback.from_user.id
        admin_name = self._admin_display_name(callback.from_user)

        if action == "approve":
            try:
                await self.bridge.add_to_whitelist(nickname)
            except Exception as exc:
                await self._safe_answer(
                    callback, Strings.WHITELIST_ADD_FAILED, show_alert=True
                )
                await callback.message.answer(
                    f"Ошибка bridge для заявки #{application_id}: {html.escape(str(exc))}"
                )
                return

            await self.store.decide(application_id, "approved", admin_id, admin_name)
            self.sessions.pop(telegram_id, None)
            await bot.send_message(
                telegram_id, self.config.messages.application_accepted
            )
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(
                self._format_decision_notice(
                    application_id, nickname, "ПРИНЯТА", admin_name, "✅"
                )
            )
            await self._safe_answer(callback, Strings.ACTION_ACCEPTED)
            return

        if action == "reject":
            self.reject_sessions[admin_id] = RejectionSession(
                application_id=application_id,
                telegram_id=telegram_id,
                nickname=nickname,
                message_chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
            )
            await self._safe_answer(callback)
            await callback.message.answer(
                f"Укажите причину отклонения заявки #{application_id} (<code>{html.escape(nickname)}</code>).\n"
                "Отправьте текст одним сообщением или <code>/cancel</code> для отмены."
            )
            return

        if action == "ban":
            await self.store.decide(application_id, "banned", admin_id, admin_name)
            self.sessions.pop(telegram_id, None)
            await bot.send_message(telegram_id, self.config.messages.application_banned)
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer(
                self._format_decision_notice(
                    application_id, nickname, "ЗАБАНЕНА", admin_name, "⛔"
                )
            )
            await self._safe_answer(callback, Strings.ACTION_BANNED)

    async def handle_player_action(self, callback: CallbackQuery) -> None:
        if not await self._allow_admin_callback(callback):
            return

        _, action, nickname = callback.data.split(":", maxsplit=2)
        await self._safe_answer(callback)

        if action == "menu":
            await callback.message.answer(
                f"<b>{html.escape(nickname)}</b>",
                reply_markup=self._player_action_keyboard(nickname),
            )
            return

        if action == "info":
            try:
                info = await self.bridge.get_player_info(nickname)
            except Exception as exc:
                await callback.message.answer(
                    f"Не удалось получить данные игрока: <code>{html.escape(str(exc))}</code>"
                )
                return

            ip = html.escape(str(info.get("ip") or "неизвестно"))
            online = "да" if info.get("online") else "нет"
            await callback.message.answer(
                f"<b>{html.escape(nickname)}</b>\n"
                f"Онлайн: <code>{online}</code>\n"
                f"IP: <code>{ip}</code>"
            )
            return

        if action == "kick":
            try:
                await self.bridge.kick_player(nickname)
            except Exception as exc:
                await callback.message.answer(
                    f"Не удалось кикнуть игрока: <code>{html.escape(str(exc))}</code>"
                )
                return
            await callback.message.answer(
                f"👢 Игрок <code>{html.escape(nickname)}</code> кикнут."
            )

    async def handle_admin_panel(self, callback: CallbackQuery, bot: Bot) -> None:
        if not await self._allow_admin_callback(callback):
            return

        _, section = callback.data.split(":", maxsplit=1)
        await self._safe_answer(callback)

        if section == "applications":
            await self._send_application_list(callback.message)
            return
        if section == "stats":
            await self._send_stats(callback.message, bot)
            return
        if section == "online":
            await self._send_server_online(callback.message)
            return
        if section == "server":
            await self._send_server_status(callback.message)
            return
        if section == "search":
            self.admin_search_sessions.add(callback.from_user.id)
            await callback.message.answer(
                "Отправьте ник, username, Telegram ID или номер заявки. Например: <code>#12</code>."
            )
            return
        if section == "users":
            user_count = await self.store.user_count()
            await callback.message.answer(
                f"<b>Пользователи бота</b>\nУникальных подавших заявки: <code>{user_count}</code>"
            )
            return
        if section == "info":
            counts = Counter(await self.store.counts_by_status())
            user_count = await self.store.user_count()
            await callback.message.answer(
                "<b>Информация</b>\n"
                f"Bridge: <code>{html.escape(self.config.bridge.base_url)}</code>\n"
                f"Пользователей: <code>{user_count}</code>\n"
                f"Заявок всего: <code>{sum(counts.values())}</code>\n"
                f"Ожидают: <code>{counts.get('pending', 0)}</code>"
            )
            return
        if section == "admins":
            admins = (
                "\n".join(
                    f"<code>{admin_id}</code>"
                    for admin_id in sorted(self.config.admins)
                )
                or "Все пользователи считаются админами."
            )
            await callback.message.answer(f"<b>Админы</b>\n{admins}")
            return
        if section == "broadcast":
            self.broadcast_sessions[callback.from_user.id] = BroadcastSession()
            await callback.message.answer(
                "<b>Рассылка</b>\n"
                "Отправьте сообщение для рассылки: текст, фото, видео, документ или стикер.\n"
                "Бот перешлет его всем пользователям, которые когда-либо подавали заявку.\n\n"
                "Отмена: <code>/cancel</code>"
            )
            return
        if section == "console":
            self.console_sessions.add(callback.from_user.id)
            await callback.message.answer(
                "<b>Консоль сервера</b>\n"
                "Отправляйте команды сообщениями. Можно с <code>/</code> или без него.\n"
                "Пример: <code>say Привет всем</code>\n\n"
                "Чтобы выйти из режима консоли: <code>/cancel</code>"
            )
            return
        if section == "player_menu":
            await self._send_player_menu(callback.message, callback.from_user.id)

    async def handle_admin_message(self, message: Message, bot: Bot) -> None:
        await self._handle_admin_message(message, bot)

    async def _handle_admin_message(self, message: Message, bot: Bot) -> bool:
        if not self._is_admin(message.from_user.id):
            return False
        message_text = message.text or ""
        if message.from_user.id in self.broadcast_sessions:
            text = (message.text or message.caption or "").strip()
            if text.lower() in {"/cancel", "cancel", "отмена"}:
                self.broadcast_sessions.pop(message.from_user.id, None)
                await message.answer("Рассылка отменена.")
                return True

            self.broadcast_sessions.pop(message.from_user.id, None)
            user_ids = await self.store.user_ids()
            sent = 0
            failed = 0
            for user_id in user_ids:
                try:
                    await bot.copy_message(user_id, message.chat.id, message.message_id)
                    sent += 1
                except Exception:
                    failed += 1
            await message.answer(
                f"📣 Рассылка завершена. Отправлено: <code>{sent}</code>, ошибок: <code>{failed}</code>."
            )
            return True

        if message.from_user.id in self.reject_sessions:
            reject_session = self.reject_sessions[message.from_user.id]
            reason = (message.text or message.caption or "").strip()
            if reason.lower() in {"/cancel", "cancel", "отмена"}:
                self.reject_sessions.pop(message.from_user.id, None)
                await message.answer("Отклонение заявки отменено.")
                return True
            if not reason:
                await message.answer(
                    "Причина не может быть пустой. Отправьте текст причины или <code>/cancel</code>."
                )
                return True

            pending = await self.store.get_pending(reject_session.application_id)
            if pending is None:
                self.reject_sessions.pop(message.from_user.id, None)
                await message.answer(Strings.APPLICATION_ALREADY_PROCESSED)
                return True

            admin_id = message.from_user.id
            admin_name = self._admin_display_name(message.from_user)
            await self.store.decide(
                reject_session.application_id, "rejected", admin_id, admin_name, reason
            )
            self.sessions.pop(reject_session.telegram_id, None)
            self.reject_sessions.pop(message.from_user.id, None)
            await bot.send_message(
                reject_session.telegram_id, self._format_rejection_message(reason)
            )
            try:
                await bot.edit_message_reply_markup(
                    chat_id=reject_session.message_chat_id,
                    message_id=reject_session.message_id,
                    reply_markup=None,
                )
            except TelegramBadRequest:
                pass
            await message.answer(
                self._format_decision_notice(
                    reject_session.application_id,
                    reject_session.nickname,
                    "ОТКЛОНЕНА",
                    admin_name,
                    "❌",
                )
            )
            return True

        # Console command session (admin)
        if message.from_user.id in self.console_sessions:
            command = message_text.strip()
            if command.lower() in {"/cancel", "cancel", "отмена"}:
                self.console_sessions.discard(message.from_user.id)
                await message.answer("Режим консоли выключен.")
                return True
            if command.startswith("/"):
                command = command[1:].lstrip()
            if not command:
                await message.answer(Strings.EMPTY_COMMAND)
                return True
            try:
                result = await self.bridge.exec_command(command)
                await message.answer(
                    "Команда отправлена в консоль.\n"
                    f"<code>{html.escape(result)}</code>\n\n"
                    "Следующая команда или <code>/cancel</code> для выхода."
                )
            except Exception as exc:
                await message.answer(
                    f"Ошибка при отправке команды: <code>{html.escape(str(exc))}</code>\n\n"
                    "Режим консоли остается включенным. <code>/cancel</code> для выхода."
                )
            return True
        if message_text.startswith("/"):
            return False
        if message.from_user.id not in self.admin_search_sessions:
            return False

        self.admin_search_sessions.discard(message.from_user.id)
        applications = await self.store.search(message_text)
        if not applications:
            await message.answer(Strings.NOTHING_FOUND)
            return True

        lines = ["<b>Результаты поиска</b>"]
        buttons = []
        for application in applications:
            username = (
                f"@{application.username}" if application.username else "без username"
            )
            lines.append(
                f"#{application.id} | <code>{html.escape(application.nickname)}</code> | {application.status} | {html.escape(username)}"
            )
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"Открыть #{application.id}",
                        callback_data=f"app:view:{application.id}",
                    )
                ]
            )

        await message.answer(
            "\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
        return True

    async def _send_application_list(self, message: Message) -> None:
        applications = await self.store.list_applications(status="pending", limit=10)
        if not applications:
            await message.answer(Strings.NO_PENDING_APPLICATIONS)
            return

        lines = ["<b>Ожидающие заявки</b>"]
        buttons = []
        for application in applications:
            username = (
                f"@{application.username}" if application.username else "без username"
            )
            lines.append(
                f"#{application.id} | <code>{html.escape(application.nickname)}</code> | {html.escape(username)}"
            )
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"Открыть #{application.id}",
                        callback_data=f"app:view:{application.id}",
                    )
                ]
            )

        await message.answer(
            "\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )

    async def _send_stats(self, message: Message, bot: Bot) -> None:
        counts = Counter(await self.store.counts_by_status())
        total = sum(counts.values())
        daily_counts = await self.store.daily_counts(days=14)
        text = (
            "<b>Статистика заявок</b>\n"
            f"Всего: <code>{total}</code>\n"
            f"Ожидают: <code>{counts.get('pending', 0)}</code>\n"
            f"Приняты: <code>{counts.get('approved', 0)}</code>\n"
            f"Отклонены: <code>{counts.get('rejected', 0)}</code>\n"
            f"Забанены: <code>{counts.get('banned', 0)}</code>"
        )
        await message.answer(text)

        png = self._build_stats_png(daily_counts)
        await bot.send_photo(
            message.chat.id,
            BufferedInputFile(png, filename="applications-stats.png"),
            caption="График заявок за последние 14 дней",
        )

    async def _send_server_status(self, message: Message) -> None:
        try:
            status = await self.bridge.get_status()
        except Exception as exc:
            await message.answer(
                f"<b>Панель сервера</b>\nBridge недоступен: <code>{html.escape(str(exc))}</code>"
            )
            return

        whitelist = "включен" if status.get("whitelist") else "выключен"
        console = "включена" if status.get("console_enabled") else "выключена"
        await message.answer(
            "<b>Панель сервера</b>\n"
            f"Bridge: <code>{html.escape(self.config.bridge.base_url)}</code>\n"
            f"Сервер: <code>{html.escape(str(status.get('name', 'unknown')))}</code>\n"
            f"Версия: <code>{html.escape(str(status.get('bukkit_version') or status.get('version') or 'unknown'))}</code>\n"
            f"Онлайн: <code>{status.get('online', 0)}/{status.get('max_players', 0)}</code>\n"
            f"Whitelist: <code>{whitelist}</code>\n"
            f"Консоль bridge: <code>{console}</code>"
        )

    async def _send_server_online(self, message: Message) -> None:
        try:
            online = await self.bridge.get_online()
        except Exception as exc:
            await message.answer(
                f"<b>Онлайн</b>\nBridge недоступен: <code>{html.escape(str(exc))}</code>"
            )
            return

        players = online.get("players", [])
        if not isinstance(players, list):
            players = []
        names = [html.escape(str(player)) for player in players]
        player_lines = (
            "\n".join(f"• <code>{name}</code>" for name in names)
            if names
            else "Игроков онлайн нет."
        )
        buttons = [
            [
                InlineKeyboardButton(
                    text=str(player), callback_data=f"player:menu:{player}"
                )
            ]
            for player in players[:20]
        ]
        await message.answer(
            "<b>Онлайн</b>\n"
            f"Игроков: <code>{online.get('online', len(names))}/{online.get('max_players', 0)}</code>\n\n"
            f"{player_lines}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            if buttons
            else None,
        )

    def _format_application(self, application: Application) -> str:
        username = (
            f"@{application.username}" if application.username else "без username"
        )
        lines = [
            f"<b>Заявка #{application.id}</b>",
            f"Статус: <code>{application.status}</code>",
            f"Создана: <code>{html.escape(application.created_at)}</code>",
            f"Telegram ID: <code>{application.telegram_id}</code>",
            f"Пользователь: {html.escape(username)}",
            f"Ник: <code>{html.escape(application.nickname)}</code>",
        ]

        if application.decided_by is not None:
            admin_name = html.escape(application.decided_by_name or "админ")
            decided = f"Решение: {admin_name} (<code>{application.decided_by}</code>)"
            if application.decided_at:
                decided += f" в <code>{html.escape(application.decided_at)}</code>"
            lines.append(decided)
            if application.decision_reason:
                lines.append(f"Причина: {html.escape(application.decision_reason)}")

        lines.append("")

        for question, answer in zip(
            self.config.questions, application.answers, strict=False
        ):
            lines.append(f"<b>{html.escape(question)}</b>")
            lines.append(html.escape(answer))
            lines.append("")

        return "\n".join(lines).strip()

    @staticmethod
    def _admin_display_name(user: Any) -> str:
        return str(user.full_name or user.username or user.id)

    @staticmethod
    def _format_decision_notice(
        application_id: int, nickname: str, status: str, admin_name: str, icon: str
    ) -> str:
        return f"{icon} Заявка #{application_id} ({html.escape(nickname)}) {status} ({html.escape(admin_name)})"

    def _format_rejection_message(self, reason: str) -> str:
        return f"{self.config.messages.application_rejected}\n\n<b>Причина:</b> {html.escape(reason)}"

    @staticmethod
    def _application_keyboard(application_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Принять", callback_data=f"app:approve:{application_id}"
                    ),
                    InlineKeyboardButton(
                        text="Отклонить", callback_data=f"app:reject:{application_id}"
                    ),
                    InlineKeyboardButton(
                        text="Бан", callback_data=f"app:ban:{application_id}"
                    ),
                ]
            ]
        )

    @staticmethod
    def _banned_application_keyboard(application_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="♻️ Разбанить", callback_data=f"app:unban:{application_id}"
                    )
                ]
            ]
        )

    @staticmethod
    def _player_action_keyboard(nickname: str) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="ℹ️ Инфо", callback_data=f"player:info:{nickname}"
                    ),
                    InlineKeyboardButton(
                        text="👢 Кик", callback_data=f"player:kick:{nickname}"
                    ),
                ]
            ]
        )

    @staticmethod
    def _admin_panel_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📝 Заявки", callback_data="panel:applications"
                    ),
                    InlineKeyboardButton(
                        text="📊 Статистика заявок", callback_data="panel:stats"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="🖥️ Панель сервера", callback_data="panel:server"
                    ),
                    InlineKeyboardButton(
                        text="👥 Онлайн", callback_data="panel:online"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="⌨️ Консоль", callback_data="panel:console"
                    ),
                    InlineKeyboardButton(text="🔍 Поиск", callback_data="panel:search"),
                ],
                [
                    InlineKeyboardButton(
                        text="ℹ️ Информация", callback_data="panel:info"
                    ),
                    InlineKeyboardButton(
                        text="📣 Рассылка", callback_data="panel:broadcast"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="В меню игрока", callback_data="panel:player_menu"
                    ),
                ],
            ]
        )

    def _build_stats_png(self, values: list[tuple[str, int]]) -> bytes:
        scale = 2
        width = 920
        height = 420
        image = Image.new("RGB", (width * scale, height * scale), "#17111a")
        draw = ImageDraw.Draw(image)

        def s(value: float) -> int:
            return round(value * scale)

        title_font = self._load_font(34 * scale, bold=True)
        value_font = self._load_font(22 * scale, bold=True)
        label_font = self._load_font(17 * scale)
        small_font = self._load_font(15 * scale)

        left = 66
        top = 74
        chart_width = width - 118
        chart_height = height - 156
        max_value = max([count for _, count in values] + [1])
        bar_gap = 10
        bar_width = max(20, (chart_width - bar_gap * (len(values) - 1)) / len(values))

        colors = {
            "panel": "#231722",
            "axis": "#6a4b61",
            "grid": "#3a2635",
            "bar": "#ff9fbc",
            "bar_top": "#ffd1dc",
            "text": "#fff4f8",
            "muted": "#d7a7b8",
        }

        draw.rounded_rectangle(
            [s(18), s(18), s(width - 18), s(height - 18)],
            radius=s(26),
            fill=colors["panel"],
        )
        draw.text(
            (s(42), s(34)),
            "Заявки за последние 14 дней",
            font=title_font,
            fill=colors["text"],
        )
        # Subtitle removed per user request (previously: "Розовая сакура")

        for step in range(5):
            y = top + chart_height - (chart_height / 4) * step
            draw.line(
                [s(left), s(y), s(left + chart_width), s(y)],
                fill=colors["axis"] if step == 0 else colors["grid"],
                width=s(2 if step == 0 else 1),
            )
        draw.line(
            [s(left), s(top), s(left), s(top + chart_height)],
            fill=colors["axis"],
            width=s(2),
        )

        for index, (day, count) in enumerate(values):
            x = left + index * (bar_width + bar_gap)
            bar_height = max(2, (count / max_value) * chart_height)
            y = top + chart_height - bar_height
            rect = [s(x), s(y), s(x + bar_width), s(top + chart_height)]
            draw.rounded_rectangle(rect, radius=s(10), fill=colors["bar"])
            draw.rounded_rectangle(
                [rect[0], rect[1], rect[2], min(rect[3], rect[1] + s(18))],
                radius=s(10),
                fill=colors["bar_top"],
            )

            count_text = str(count)
            count_box = draw.textbbox((0, 0), count_text, font=value_font)
            draw.text(
                (s(x + bar_width / 2) - (count_box[2] - count_box[0]) / 2, s(y - 30)),
                count_text,
                font=value_font,
                fill=colors["text"],
            )

            label = day[5:]
            label_box = draw.textbbox((0, 0), label, font=label_font)
            draw.text(
                (
                    s(x + bar_width / 2) - (label_box[2] - label_box[0]) / 2,
                    s(height - 58),
                ),
                label,
                font=label_font,
                fill=colors["muted"],
            )

        image = image.resize((width, height), Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, format="PNG", optimize=True)
        return output.getvalue()

    @staticmethod
    def _load_font(
        size: int, bold: bool = False
    ) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        bot_dir = Path(__file__).resolve().parent
        candidates: list[str] = []

        # Local fonts folder: prefer explicit Bold/Regular, then any TTF found there
        local_fonts = bot_dir / "fonts"
        if local_fonts.exists() and local_fonts.is_dir():
            explicit = local_fonts / (
                "Comfortaa-Bold.ttf" if bold else "Comfortaa-Regular.ttf"
            )
            if explicit.exists():
                candidates.append(str(explicit))
            # add any ttf in the fonts folder as fallback
            for p in sorted(local_fonts.glob("*.ttf")):
                candidates.append(str(p))

        # Prefer common Linux fonts (typical on VPS/Docker images)
        if bold:
            candidates += [
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ]
        else:
            candidates += [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            ]

        # Fallback to common Windows font paths if running on Windows
        if bold:
            candidates += [
                "C:/Windows/Fonts/segoeuib.ttf",
                "C:/Windows/Fonts/segoeuii.ttf",
                "C:/Windows/Fonts/seguisb.ttf",
                "C:/Windows/Fonts/SegoeUI-Semibold.ttf",
                "C:/Windows/Fonts/arialbd.ttf",
            ]
        else:
            candidates += [
                "C:/Windows/Fonts/segoeui.ttf",
                "C:/Windows/Fonts/Segoe UI.ttf",
                "C:/Windows/Fonts/arial.ttf",
                "C:/Windows/Fonts/Verdana.ttf",
                "C:/Windows/Fonts/Tahoma.ttf",
            ]

        # Try loading candidates
        for candidate in candidates:
            try:
                return ImageFont.truetype(candidate, size)
            except OSError, IOError:
                continue

        # As a last resort try to use a PIL bundled font by name (may fail on some installs)
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size)
        except Exception:
            return ImageFont.load_default()

    async def _allow_admin_callback(self, callback: CallbackQuery) -> bool:
        if not self._is_admin(callback.from_user.id):
            await self._safe_answer(callback, Strings.NO_ACCESS, show_alert=True)
            return False
        is_admin_chat = callback.message.chat.id == self.config.admin_chat_id
        is_private = callback.message.chat.type == "private"
        if not is_admin_chat and not is_private:
            await self._safe_answer(
                callback, Strings.ADMIN_ONLY_BUTTON, show_alert=True
            )
            return False
        return True

    async def _safe_answer(
        self, callback: CallbackQuery, text: str | None = None, show_alert: bool = False
    ) -> None:
        try:
            await callback.answer(text, show_alert=show_alert)
        except TelegramBadRequest:
            pass

    @staticmethod
    async def _safe_clear_reply_markup(message: Message) -> None:
        try:
            await message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass

    def _is_admin(self, telegram_id: int) -> bool:
        return not self.config.admins or telegram_id in self.config.admins

    def _status_message(self, status: str | None) -> str | None:
        if status == "banned":
            return self.config.messages.application_banned
        if status == "pending":
            return self.config.messages.already_applied
        if status == "approved":
            return self.config.messages.application_accepted
        return None


async def main() -> None:
    config = load_config()
    store = ApplicationStore(
        config.db_path, config.db_backup_dir, config.db_backup_keep_last
    )
    await store.init()

    bot = Bot(config.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    dispatcher = Dispatcher()
    flow = ApplicationFlow(config, store, MinecraftBridge(config.bridge))
    dispatcher.include_router(flow.router)

    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
