import logging
from datetime import date, datetime, timedelta

try:  # Python 3.9+: zoneinfo is in the stdlib
    from zoneinfo import ZoneInfo
except ImportError:  # older Python on some servers (< 3.9)
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from . import config, db, oauth, sheets
from .utils import cell_to_html, format_date_ru, parse_deadline_time

logger = logging.getLogger(__name__)


def _format_reminder(target: date, homework: dict, subjects: list) -> str:
    lines = [f"🔔 Напоминание о домашнем задании на {format_date_ru(target)}"]
    for subject in subjects:
        if subject in homework:
            lines.append(f"• <b>{subject}:</b> {cell_to_html(homework[subject])}")
    return "\n".join(lines)


async def _check_and_notify(bot: Bot) -> None:
    for profile in db.get_all_users():
        if not profile.notify_enabled:
            continue
        if not profile.sheet_id:
            # Пользователь ещё не подключил таблицу — напоминать нечем.
            continue

        try:
            tz = ZoneInfo(profile.timezone)
        except Exception:
            logger.warning("Неизвестный часовой пояс %s у чата %s", profile.timezone, profile.chat_id)
            continue

        now = datetime.now(tz)
        if now.strftime("%H:%M") != profile.notify_time:
            continue

        target = now.date() + timedelta(days=1)
        target_str = target.isoformat()
        if db.was_notified(profile.chat_id, target_str):
            continue

        # Помечаем сразу, чтобы при ошибке ниже не пытаться отправить повторно
        # в течение той же минуты/дня.
        db.mark_notified(profile.chat_id, target_str)

        sheet_name = profile.sheet_name or config.GOOGLE_SHEET_NAME
        try:
            homework = sheets.get_day(profile.sheet_id, sheet_name, target)
            subjects = sheets.get_subjects(profile.sheet_id, sheet_name)
        except Exception:
            logger.exception(
                "Не удалось получить домашние задания для напоминания (chat_id=%s)", profile.chat_id
            )
            continue

        if not homework or not any(s in homework for s in subjects):
            continue

        try:
            await bot.send_message(profile.chat_id, _format_reminder(target, homework, subjects))
        except Exception:
            logger.exception("Не удалось отправить напоминание чату %s", profile.chat_id)


def _format_deadline_reminder(target: date, subject: str, text: str, hours: int) -> str:
    return (
        f"⏰ Через {hours} ч дедлайн по предмету <b>{subject}</b> "
        f"({format_date_ru(target)}):\n{cell_to_html(text)}"
    )


async def _check_deadline_reminders(bot: Bot) -> None:
    """Точечные напоминания по дедлайну. Дедлайн — тег [ЧЧ:ММ] в
    тексте ячейки ДЗ (см. utils.parse_deadline_time), время всегда в
    пределах дня, на который заведена строка. Проверяем сегодняшнюю И
    завтрашнюю дату: если дедлайн, например, в 01:00, а напоминание должно
    прийти за 3 часа, момент напоминания (22:00) приходится на предыдущий
    календарный день."""
    for profile in db.get_all_users():
        if not profile.deadline_reminder_enabled or not profile.sheet_id:
            continue

        try:
            tz = ZoneInfo(profile.timezone)
        except Exception:
            logger.warning("Неизвестный часовой пояс %s у чата %s", profile.timezone, profile.chat_id)
            continue

        now = datetime.now(tz)
        sheet_name = profile.sheet_name or config.GOOGLE_SHEET_NAME

        for offset in (0, 1):
            hw_date = now.date() + timedelta(days=offset)
            try:
                homework = sheets.get_day(profile.sheet_id, sheet_name, hw_date)
            except Exception:
                logger.exception(
                    "Не удалось получить ДЗ для проверки дедлайнов (chat_id=%s)", profile.chat_id
                )
                continue
            if not homework:
                continue

            for subject, text in homework.items():
                deadline_time = parse_deadline_time(text)
                if deadline_time is None:
                    continue

                deadline_dt = datetime.combine(hw_date, deadline_time, tzinfo=tz)
                remind_at = deadline_dt - timedelta(hours=profile.deadline_reminder_hours)
                if remind_at.date() != now.date() or remind_at.strftime("%H:%M") != now.strftime("%H:%M"):
                    continue

                hw_date_str = hw_date.isoformat()
                if db.was_deadline_notified(profile.chat_id, profile.sheet_id, hw_date_str, subject):
                    continue
                # Помечаем сразу, чтобы при ошибке отправки ниже не долбить повторно.
                db.mark_deadline_notified(profile.chat_id, profile.sheet_id, hw_date_str, subject)

                try:
                    await bot.send_message(
                        profile.chat_id,
                        _format_deadline_reminder(hw_date, subject, text, profile.deadline_reminder_hours),
                    )
                except Exception:
                    logger.exception("Не удалось отправить напоминание о дедлайне чату %s", profile.chat_id)


async def _check_and_reformat_sheets(bot: Bot) -> None:
    """Раз в день (config.REFORMAT_CHECK_TIME, по часовому поясу
    пользователя) проверяет, не выросла ли таблица за пределы последнего
    оформления — например, предмет или дата были дописаны руками прямо в
    Google Sheets, а не через бота. Если да, тихо перенакатывает формат.

    Работает только там, где у бота есть доступ на запись через OAuth
    (таблицы из /create_sheet); для /connect_sheet и для тех, кто вообще не
    проходил OAuth, просто пропускает — без сообщений пользователю, чтобы
    не дёргать их авторизоваться ради фонового форматирования."""
    today_str = date.today().isoformat()

    for profile in db.get_all_users():
        if not profile.sheet_id:
            continue

        try:
            tz = ZoneInfo(profile.timezone)
        except Exception:
            continue

        now = datetime.now(tz)
        if now.strftime("%H:%M") != config.REFORMAT_CHECK_TIME:
            continue
        if db.was_reformat_checked(profile.chat_id, today_str):
            continue
        db.mark_reformat_checked(profile.chat_id, today_str)

        sheet_name = profile.sheet_name or config.GOOGLE_SHEET_NAME
        try:
            client = oauth.get_client_for_user(profile.chat_id)
            reformatted = sheets.ensure_formatted(client, profile.sheet_id, sheet_name)
        except (LookupError, sheets.WriteAccessError):
            continue  # нет OAuth-авторизации или нет доступа на запись — тихо пропускаем
        except Exception:
            logger.exception("Не удалось проверить/докатить оформление (chat_id=%s)", profile.chat_id)
            continue

        if reformatted:
            logger.info("Автоматически докатил оформление таблицы (chat_id=%s)", profile.chat_id)


def create_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(_check_and_notify, "cron", minute="*", args=(bot,), id="homework_reminders")
    scheduler.add_job(_check_deadline_reminders, "cron", minute="*", args=(bot,), id="deadline_reminders")
    scheduler.add_job(_check_and_reformat_sheets, "cron", minute="*", args=(bot,), id="sheet_reformat")
    return scheduler
