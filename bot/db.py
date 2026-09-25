import sqlite3
import threading
from dataclasses import dataclass
from typing import List, Optional

from . import config

_lock = threading.Lock()
_conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
_conn.execute("PRAGMA journal_mode=WAL")

# Колонки, которых могло не быть в базе, созданной до перехода на
# мультипользовательскую схему. init_db() добавляет их автоматически,
# если их ещё нет — специально, чтобы не нужно было руками трогать
# homeworks.db на сервере: достаточно git pull + перезапуск бота.
_MIGRATIONS = {
    "sheet_id": "TEXT",
    "sheet_name": "TEXT",
    # Для /create_sheet (OAuth пользователя, не сервис-аккаунт): refresh_token
    # для повторного создания access-токена и email — только для справки/whoami.
    "google_refresh_token": "TEXT",
    "google_email": "TEXT",
    # Точечные напоминания по дедлайну (тег [ЧЧ:ММ] в тексте ячейки).
    # Выключено по умолчанию, чтобы не менять поведение уже существующих
    # пользователей.
    "deadline_reminder_enabled": "INTEGER NOT NULL DEFAULT 0",
    "deadline_reminder_hours": "INTEGER NOT NULL DEFAULT 3",
}


@dataclass
class UserProfile:
    chat_id: int
    timezone: str
    notify_time: str
    notify_enabled: bool
    sheet_id: Optional[str]
    sheet_name: Optional[str]
    deadline_reminder_enabled: bool = False
    deadline_reminder_hours: int = 3


def init_db() -> None:
    with _lock:
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY,
                timezone TEXT NOT NULL DEFAULT 'Europe/Moscow',
                notify_time TEXT NOT NULL DEFAULT '20:00',
                notify_enabled INTEGER NOT NULL DEFAULT 1,
                sheet_id TEXT,
                sheet_name TEXT
            )
            """
        )
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sent_notifications (
                chat_id INTEGER NOT NULL,
                target_date TEXT NOT NULL,
                PRIMARY KEY (chat_id, target_date)
            )
            """
        )

        # Отметки «выполнено» (шаг 4 плана). Живут только в SQLite, саму
        # Google-таблицу не трогают. Строка есть => ДЗ выполнено; снятие
        # отметки удаляет строку. Новая таблица (не колонка), поэтому
        # CREATE IF NOT EXISTS достаточно — git pull + рестарт.
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS homework_status (
                chat_id INTEGER NOT NULL,
                sheet_id TEXT NOT NULL,
                hw_date TEXT NOT NULL,
                subject TEXT NOT NULL,
                PRIMARY KEY (chat_id, sheet_id, hw_date, subject)
            )
            """
        )

        # Дедуп напоминаний по дедлайну (шаг 6) — своя таблица по тому же
        # принципу, что и homework_status/sent_notifications: чтобы при
        # перезапуске бота или повторном тике APScheduler не отправить одно
        # и то же напоминание дважды.
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sent_deadline_reminders (
                chat_id INTEGER NOT NULL,
                sheet_id TEXT NOT NULL,
                hw_date TEXT NOT NULL,
                subject TEXT NOT NULL,
                PRIMARY KEY (chat_id, sheet_id, hw_date, subject)
            )
            """
        )

        # Дедуп ежедневной проверки "не выросла ли таблица за пределы формата"
        # (автоподгонка оформления, bot/scheduler.py: _check_and_reformat_sheets).
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sheet_reformat_checks (
                chat_id INTEGER NOT NULL,
                check_date TEXT NOT NULL,
                PRIMARY KEY (chat_id, check_date)
            )
            """
        )

        existing_columns = {row[1] for row in _conn.execute("PRAGMA table_info(users)").fetchall()}
        for column, col_type in _MIGRATIONS.items():
            if column not in existing_columns:
                _conn.execute(f"ALTER TABLE users ADD COLUMN {column} {col_type}")

        _conn.commit()


def get_or_create_user(chat_id: int) -> UserProfile:
    with _lock:
        cur = _conn.execute(
            "SELECT chat_id, timezone, notify_time, notify_enabled, sheet_id, sheet_name, "
            "deadline_reminder_enabled, deadline_reminder_hours "
            "FROM users WHERE chat_id=?",
            (chat_id,),
        )
        row = cur.fetchone()
        if row is None:
            _conn.execute(
                "INSERT INTO users (chat_id, timezone, notify_time, notify_enabled, "
                "deadline_reminder_hours) VALUES (?, ?, ?, 1, ?)",
                (chat_id, config.DEFAULT_TIMEZONE, config.DEFAULT_NOTIFY_TIME, config.DEFAULT_DEADLINE_HOURS),
            )
            _conn.commit()
            return UserProfile(
                chat_id=chat_id,
                timezone=config.DEFAULT_TIMEZONE,
                notify_time=config.DEFAULT_NOTIFY_TIME,
                notify_enabled=True,
                sheet_id=None,
                sheet_name=None,
                deadline_reminder_enabled=False,
                deadline_reminder_hours=config.DEFAULT_DEADLINE_HOURS,
            )
        cid, timezone, notify_time, notify_enabled, sheet_id, sheet_name, dl_enabled, dl_hours = row
        return UserProfile(
            cid, timezone, notify_time, bool(notify_enabled), sheet_id, sheet_name,
            bool(dl_enabled), dl_hours,
        )


def set_timezone(chat_id: int, timezone: str) -> None:
    with _lock:
        _conn.execute("UPDATE users SET timezone=? WHERE chat_id=?", (timezone, chat_id))
        _conn.commit()


def set_notify_time(chat_id: int, notify_time: str) -> None:
    with _lock:
        _conn.execute(
            "UPDATE users SET notify_time=? WHERE chat_id=?", (notify_time, chat_id)
        )
        _conn.commit()


def set_notify_enabled(chat_id: int, enabled: bool) -> None:
    with _lock:
        _conn.execute(
            "UPDATE users SET notify_enabled=? WHERE chat_id=?", (int(enabled), chat_id)
        )
        _conn.commit()


def set_sheet(chat_id: int, sheet_id: str, sheet_name: str) -> None:
    """Привязывает конкретную Google-таблицу (лист) к пользователю."""
    with _lock:
        _conn.execute(
            "UPDATE users SET sheet_id=?, sheet_name=? WHERE chat_id=?",
            (sheet_id, sheet_name, chat_id),
        )
        _conn.commit()


def set_google_auth(chat_id: int, refresh_token: str, email: Optional[str] = None) -> None:
    """Сохраняет refresh_token пользователя, полученный через OAuth-флоу
    (bot/oauth.py), для последующего /create_sheet."""
    with _lock:
        _conn.execute(
            "UPDATE users SET google_refresh_token=?, google_email=? WHERE chat_id=?",
            (refresh_token, email, chat_id),
        )
        _conn.commit()


def get_google_refresh_token(chat_id: int) -> Optional[str]:
    with _lock:
        cur = _conn.execute(
            "SELECT google_refresh_token FROM users WHERE chat_id=?", (chat_id,)
        )
        row = cur.fetchone()
        return row[0] if row else None


def set_deadline_reminder_enabled(chat_id: int, enabled: bool) -> None:
    with _lock:
        _conn.execute(
            "UPDATE users SET deadline_reminder_enabled=? WHERE chat_id=?", (int(enabled), chat_id)
        )
        _conn.commit()


def set_deadline_reminder_hours(chat_id: int, hours: int) -> None:
    with _lock:
        _conn.execute(
            "UPDATE users SET deadline_reminder_hours=? WHERE chat_id=?", (hours, chat_id)
        )
        _conn.commit()


def get_all_users() -> List[UserProfile]:
    with _lock:
        cur = _conn.execute(
            "SELECT chat_id, timezone, notify_time, notify_enabled, sheet_id, sheet_name, "
            "deadline_reminder_enabled, deadline_reminder_hours FROM users"
        )
        return [
            UserProfile(cid, tz, nt, bool(en), sid, sname, bool(dl_en), dl_hours)
            for cid, tz, nt, en, sid, sname, dl_en, dl_hours in cur.fetchall()
        ]


def was_notified(chat_id: int, target_date: str) -> bool:
    with _lock:
        cur = _conn.execute(
            "SELECT 1 FROM sent_notifications WHERE chat_id=? AND target_date=?",
            (chat_id, target_date),
        )
        return cur.fetchone() is not None


def mark_notified(chat_id: int, target_date: str) -> None:
    with _lock:
        _conn.execute(
            "INSERT OR IGNORE INTO sent_notifications (chat_id, target_date) VALUES (?, ?)",
            (chat_id, target_date),
        )
        _conn.commit()


def is_homework_done(chat_id: int, sheet_id: str, hw_date: str, subject: str) -> bool:
    with _lock:
        cur = _conn.execute(
            "SELECT 1 FROM homework_status "
            "WHERE chat_id=? AND sheet_id=? AND hw_date=? AND subject=?",
            (chat_id, sheet_id, hw_date, subject),
        )
        return cur.fetchone() is not None


def set_homework_done(chat_id: int, sheet_id: str, hw_date: str, subject: str, done: bool) -> None:
    """Ставит/снимает отметку «выполнено». hw_date — ISO (YYYY-MM-DD)."""
    with _lock:
        if done:
            _conn.execute(
                "INSERT OR IGNORE INTO homework_status (chat_id, sheet_id, hw_date, subject) "
                "VALUES (?, ?, ?, ?)",
                (chat_id, sheet_id, hw_date, subject),
            )
        else:
            _conn.execute(
                "DELETE FROM homework_status "
                "WHERE chat_id=? AND sheet_id=? AND hw_date=? AND subject=?",
                (chat_id, sheet_id, hw_date, subject),
            )
        _conn.commit()


def was_deadline_notified(chat_id: int, sheet_id: str, hw_date: str, subject: str) -> bool:
    with _lock:
        cur = _conn.execute(
            "SELECT 1 FROM sent_deadline_reminders WHERE chat_id=? AND sheet_id=? AND hw_date=? AND subject=?",
            (chat_id, sheet_id, hw_date, subject),
        )
        return cur.fetchone() is not None


def mark_deadline_notified(chat_id: int, sheet_id: str, hw_date: str, subject: str) -> None:
    with _lock:
        _conn.execute(
            "INSERT OR IGNORE INTO sent_deadline_reminders (chat_id, sheet_id, hw_date, subject) "
            "VALUES (?, ?, ?, ?)",
            (chat_id, sheet_id, hw_date, subject),
        )
        _conn.commit()


def was_reformat_checked(chat_id: int, check_date: str) -> bool:
    with _lock:
        cur = _conn.execute(
            "SELECT 1 FROM sheet_reformat_checks WHERE chat_id=? AND check_date=?",
            (chat_id, check_date),
        )
        return cur.fetchone() is not None


def mark_reformat_checked(chat_id: int, check_date: str) -> None:
    with _lock:
        _conn.execute(
            "INSERT OR IGNORE INTO sheet_reformat_checks (chat_id, check_date) VALUES (?, ?)",
            (chat_id, check_date),
        )
        _conn.commit()
