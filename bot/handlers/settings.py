from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from .. import db
from ..keyboards import settings_keyboard

router = Router()


def _settings_text(profile: db.UserProfile) -> str:
    status = "включены ✅" if profile.notify_enabled else "выключены ❌"
    deadline_status = "включены ✅" if profile.deadline_reminder_enabled else "выключены ❌"
    return (
        "⚙️ <b>Настройки уведомлений</b>\n\n"
        f"Часовой пояс: <b>{profile.timezone}</b>\n"
        f"Время ежедневного уведомления: <b>{profile.notify_time}</b>\n"
        f"Ежедневные уведомления: {status}\n\n"
        f"⏰ Напоминания по дедлайну: {deadline_status}\n"
        f"За сколько часов до дедлайна: <b>{profile.deadline_reminder_hours} ч</b>\n"
        "Дедлайн задаётся тегом [ЧЧ:ММ] в тексте задания, например "
        "«Сделать презентацию [18:00]».\n\n"
        "Выбери время, часовой пояс или настройки дедлайнов на кнопках ниже:"
    )


def _settings_keyboard_for(profile: db.UserProfile):
    return settings_keyboard(
        profile.notify_enabled, profile.deadline_reminder_enabled, profile.deadline_reminder_hours
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message) -> None:
    profile = db.get_or_create_user(message.chat.id)
    await message.answer(_settings_text(profile), reply_markup=_settings_keyboard_for(profile))


@router.callback_query(F.data.startswith("settime:"))
async def cb_set_time(callback: CallbackQuery) -> None:
    notify_time = callback.data.split(":", 1)[1]
    db.set_notify_time(callback.message.chat.id, notify_time)
    profile = db.get_or_create_user(callback.message.chat.id)
    await callback.message.edit_text(_settings_text(profile), reply_markup=_settings_keyboard_for(profile))
    await callback.answer(f"Время уведомления: {notify_time}")


@router.callback_query(F.data.startswith("settz:"))
async def cb_set_tz(callback: CallbackQuery) -> None:
    timezone = callback.data.split(":", 1)[1]
    db.set_timezone(callback.message.chat.id, timezone)
    profile = db.get_or_create_user(callback.message.chat.id)
    await callback.message.edit_text(_settings_text(profile), reply_markup=_settings_keyboard_for(profile))
    await callback.answer(f"Часовой пояс: {timezone}")


@router.callback_query(F.data == "togglenotify")
async def cb_toggle(callback: CallbackQuery) -> None:
    profile = db.get_or_create_user(callback.message.chat.id)
    db.set_notify_enabled(callback.message.chat.id, not profile.notify_enabled)
    profile = db.get_or_create_user(callback.message.chat.id)
    await callback.message.edit_text(_settings_text(profile), reply_markup=_settings_keyboard_for(profile))
    await callback.answer("Готово")


@router.callback_query(F.data == "toggledeadline")
async def cb_toggle_deadline(callback: CallbackQuery) -> None:
    profile = db.get_or_create_user(callback.message.chat.id)
    db.set_deadline_reminder_enabled(callback.message.chat.id, not profile.deadline_reminder_enabled)
    profile = db.get_or_create_user(callback.message.chat.id)
    await callback.message.edit_text(_settings_text(profile), reply_markup=_settings_keyboard_for(profile))
    await callback.answer("Готово")


@router.callback_query(F.data.startswith("deadlinehours:"))
async def cb_set_deadline_hours(callback: CallbackQuery) -> None:
    try:
        hours = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Некорректное значение", show_alert=False)
        return
    db.set_deadline_reminder_hours(callback.message.chat.id, hours)
    profile = db.get_or_create_user(callback.message.chat.id)
    await callback.message.edit_text(_settings_text(profile), reply_markup=_settings_keyboard_for(profile))
    await callback.answer(f"Напоминание за {hours} ч до дедлайна")
