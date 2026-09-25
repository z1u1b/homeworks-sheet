"""Диалог «➕ Добавить ДЗ» (шаг 5 плана): предмет → дата → текст →
подтверждение → запись в Google-таблицу.

Запись идёт от имени пользователя через OAuth (bot/oauth.py), а не через
сервис-аккаунт (тот расшарен только на чтение). Из-за scope drive.file писать
можно только в таблицы, созданные через /create_sheet; для таблиц из
/connect_sheet бот отвечает понятным сообщением (проверка — в самом начале
диалога, чтобы не заставлять вводить текст зря).
"""
import asyncio
import logging
from html import escape
from datetime import date, timedelta
from typing import Any, Callable, List

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import config, db, oauth, sheets
from ..keyboards import (
    ADD_CALENDAR_DAYS,
    BTN_ADD,
    MENU_BUTTONS,
    add_confirm_keyboard,
    add_dates_keyboard,
    add_subjects_keyboard,
)
from ..utils import cell_to_html, format_date_ru, is_empty_cell
from .homework import NO_SHEET_TEXT, NO_SUBJECTS_TEXT
from .subject_manage import NO_WRITE_ACCESS_TEXT, try_add_subject

router = Router()
logger = logging.getLogger(__name__)


class AddHomework(StatesGroup):
    subject = State()
    new_subject = State()  # ввод названия для "➕ Новый предмет" (шаг 5б)
    date = State()
    text = State()
    confirm = State()


async def _run(func: Callable[..., Any], *args: Any) -> Any:
    """Блокирующие вызовы gspread/OAuth — в потоке, чтобы не вешать бота
    (asyncio.to_thread не используем: на сервере Python 3.8)."""
    return await asyncio.get_running_loop().run_in_executor(None, func, *args)


def _sheet_of(chat_id: int):
    profile = db.get_or_create_user(chat_id)
    if not profile.sheet_id:
        return None, None
    return profile.sheet_id, profile.sheet_name or config.GOOGLE_SHEET_NAME


async def _subjects(chat_id: int) -> List[str]:
    sheet_id, sheet_name = _sheet_of(chat_id)
    return await _run(sheets.get_subjects, sheet_id, sheet_name)


# ---------- запуск диалога ----------


async def _start_dialog(message: Message, state: FSMContext) -> None:
    await state.clear()
    chat_id = message.chat.id
    sheet_id, sheet_name = _sheet_of(chat_id)
    if not sheet_id:
        await message.answer(NO_SHEET_TEXT)
        return
    if not config.GOOGLE_OAUTH_CLIENT_ID or not config.GOOGLE_OAUTH_CLIENT_SECRET:
        await message.answer("Добавление ДЗ через бота пока не настроено администратором.")
        return

    try:
        client = await _run(oauth.get_client_for_user, chat_id)
    except LookupError:
        await message.answer(
            "Чтобы бот мог записывать в вашу таблицу, один раз авторизуйтесь "
            "через Google по ссылке, потом снова нажмите «➕ Добавить ДЗ»:\n"
            + oauth.build_auth_url(chat_id)
        )
        return
    except Exception:
        logger.exception("Не удалось получить OAuth-клиент для chat_id=%s", chat_id)
        await message.answer(
            "Не получилось обновить доступ к вашему Google-аккаунту. "
            "Попробуйте авторизоваться заново — пришлите /create_sheet ещё раз."
        )
        return

    try:
        await _run(sheets.open_worksheet_for_write, client, sheet_id, sheet_name)
        subjects = await _run(sheets.get_subjects, sheet_id, sheet_name)
    except sheets.WriteAccessError:
        await message.answer(NO_WRITE_ACCESS_TEXT)
        return
    except Exception:
        logger.exception("Не удалось открыть таблицу для записи (chat_id=%s)", chat_id)
        await message.answer("Не получилось открыть таблицу. Попробуйте позже.")
        return

    if not subjects:
        await message.answer(NO_SUBJECTS_TEXT)
        return

    await state.set_state(AddHomework.subject)
    await message.answer("➕ Новое ДЗ. Выберите предмет:", reply_markup=add_subjects_keyboard(subjects))


@router.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext) -> None:
    await _start_dialog(message, state)


@router.message(F.text == BTN_ADD)
async def btn_add(message: Message, state: FSMContext) -> None:
    await _start_dialog(message, state)


# ---------- отмена ----------


@router.message(Command("cancel"), StateFilter(AddHomework))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Добавление отменено.")


@router.callback_query(F.data == "add:cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Добавление отменено.")
    await callback.answer()


# ---------- шаги диалога ----------


@router.callback_query(AddHomework.subject, F.data.startswith("add:s:"))
async def cb_subject(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        idx = int(callback.data.split(":")[2])
        subjects = await _subjects(callback.message.chat.id)
        subject = subjects[idx]
    except (ValueError, IndexError):
        await callback.answer("Кнопка устарела", show_alert=False)
        return
    await state.update_data(subject_idx=idx, subject=subject)
    await state.set_state(AddHomework.date)
    await callback.message.edit_text(
        f"📚 Предмет: <b>{escape(subject)}</b>\n\nВыберите дату:",
        reply_markup=add_dates_keyboard(date.today()),
    )
    await callback.answer()


# ---------- "➕ Новый предмет" внутри диалога (шаг 5б) ----------


@router.callback_query(AddHomework.subject, F.data == "add:newsubj")
async def cb_new_subject_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddHomework.new_subject)
    await callback.message.edit_text(
        "Введите название нового предмета одним сообщением.\nОтмена — /cancel"
    )
    await callback.answer()


@router.message(AddHomework.new_subject, F.text, ~F.text.startswith("/"), ~F.text.in_(MENU_BUTTONS))
async def msg_new_subject_name(message: Message, state: FSMContext) -> None:
    result = await try_add_subject(message.chat.id, message.text)
    await message.answer(result.message)
    if not result.ok:
        if not result.retryable:
            # неисправимо в рамках диалога (нет доступа, лимит колонок,
            # OAuth не настроен/нужна повторная авторизация и т.п.)
            await state.clear()
        # иначе (пустое название / дубликат) остаёмся в AddHomework.new_subject
        # и даём попробовать ещё раз
        return

    await state.update_data(subject=result.subject)
    await state.set_state(AddHomework.date)
    await message.answer(
        f"📚 Предмет: <b>{escape(result.subject)}</b>\n\nВыберите дату:",
        reply_markup=add_dates_keyboard(date.today()),
    )


@router.callback_query(AddHomework.date, F.data.startswith("add:d:"))
async def cb_date(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        target = date.fromisoformat(callback.data.split(":", 2)[2])
    except ValueError:
        await callback.answer("Кнопка устарела", show_alert=False)
        return
    today = date.today()
    if not today <= target <= today + timedelta(days=ADD_CALENDAR_DAYS):
        await callback.answer("Эта дата уже недоступна, выберите другую", show_alert=True)
        return
    data = await state.update_data(date=target.isoformat())
    await state.set_state(AddHomework.text)
    await callback.message.edit_text(
        f"📚 <b>{escape(data['subject'])}</b> · 📅 <b>{format_date_ru(target)}</b>\n\n"
        "Отправьте текст задания одним сообщением (ссылки можно вставлять прямо в текст).\n"
        "Отмена — /cancel"
    )
    await callback.answer()


def _is_command_or_button(message: Message) -> bool:
    text = message.text or ""
    return text.startswith("/") or text in MENU_BUTTONS


@router.message(AddHomework.text, F.text, ~F.text.startswith("/"), ~F.text.in_(MENU_BUTTONS))
async def msg_text(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not text or is_empty_cell(text):
        await message.answer("Текст задания пустой — отправьте ещё раз или /cancel.")
        return
    data = await state.update_data(text=text)
    target = date.fromisoformat(data["date"])

    sheet_id, sheet_name = _sheet_of(message.chat.id)
    existing = None
    try:
        day = await _run(sheets.get_day, sheet_id, sheet_name, target)
        existing = (day or {}).get(data["subject"])
    except Exception:
        logger.exception("Не удалось проверить занятость ячейки (chat_id=%s)", message.chat.id)
    occupied = bool(existing) and not is_empty_cell(existing)

    preview = (
        "Проверьте задание:\n\n"
        f"📅 <b>{format_date_ru(target)}</b>\n"
        f"📚 <b>{escape(data['subject'])}</b>\n\n"
        f"{cell_to_html(text)}"
    )
    if occupied:
        preview += (
            "\n\n⚠️ В этой ячейке уже есть задание:\n"
            f"<blockquote>{cell_to_html(existing)}</blockquote>\n"
            "Дописать новое под ним или заменить?"
        )
    await state.set_state(AddHomework.confirm)
    await message.answer(preview, reply_markup=add_confirm_keyboard(occupied))


@router.callback_query(AddHomework.confirm, F.data.in_({"add:ok", "add:append", "add:replace"}))
async def cb_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    chat_id = callback.message.chat.id
    sheet_id, sheet_name = _sheet_of(chat_id)
    if not sheet_id or not {"subject", "date", "text"} <= set(data):
        await state.clear()
        await callback.message.edit_text("Диалог устарел, начните заново: «➕ Добавить ДЗ».")
        await callback.answer()
        return

    target = date.fromisoformat(data["date"])
    replace = callback.data == "add:replace"
    await callback.answer("Сохраняю…")
    try:
        client = await _run(oauth.get_client_for_user, chat_id)
        created = await _run(
            sheets.write_homework, client, sheet_id, sheet_name, target,
            data["subject"], data["text"], replace,
        )
    except sheets.WriteAccessError:
        await state.clear()
        await callback.message.edit_text(NO_WRITE_ACCESS_TEXT)
        return
    except LookupError as exc:
        await state.clear()
        await callback.message.edit_text(f"Не получилось записать: {exc}. Начните заново.")
        return
    except Exception:
        logger.exception("Не удалось записать ДЗ (chat_id=%s)", chat_id)
        await state.clear()
        await callback.message.edit_text("Не получилось записать в таблицу. Попробуйте позже.")
        return

    await state.clear()
    note = "\n(добавлена новая строка с датой)" if created else ""
    await callback.message.edit_text(
        "✅ Добавлено в таблицу:\n\n"
        f"📅 <b>{format_date_ru(target)}</b>\n"
        f"📚 <b>{escape(data['subject'])}</b>\n\n"
        f"{cell_to_html(data['text'])}{note}"
    )


# ---------- «запасные» обработчики внутри диалога ----------


@router.message(StateFilter(AddHomework), F.text, F.func(_is_command_or_button))
async def msg_interrupt(message: Message, state: FSMContext) -> None:
    """Команда или кнопка меню посреди диалога — отменяем диалог, иначе
    следующее обычное сообщение ушло бы в текст задания."""
    await state.clear()
    await message.answer("Добавление отменено. Повторите нужное действие ещё раз.")


@router.message(StateFilter(AddHomework))
async def msg_hint(message: Message) -> None:
    await message.answer("Выберите вариант на кнопках выше или отправьте /cancel.")


@router.callback_query(F.data.startswith("add:"))
async def cb_stale(callback: CallbackQuery) -> None:
    # Без ответа у пользователя вечно крутится «загрузка».
    await callback.answer("Диалог устарел — начните заново: «➕ Добавить ДЗ»", show_alert=False)
