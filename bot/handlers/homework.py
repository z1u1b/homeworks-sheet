import logging
from datetime import date, timedelta
from html import escape
from typing import List, Tuple

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from .. import config, db, sheets
from ..keyboards import card_keyboard, subjects_keyboard
from ..utils import cell_to_html, daterange, format_date_ru

router = Router()
logger = logging.getLogger(__name__)

NO_SHEET_TEXT = (
    "📄 У вас ещё не подключена таблица с заданиями.\n\n"
    "Подключите её командой:\n"
    "/connect_sheet &lt;ID_ТАБЛИЦЫ&gt; [название листа]\n\n"
    "ID — это часть ссылки на таблицу между /d/ и /edit. Перед этим "
    "откройте доступ сервис-аккаунту бота к таблице (см. README)."
)

EMPTY_TEXT = {
    "d": "Заданий не найдено.",
    "w": "На ближайшую неделю домашних заданий не найдено.",
    "s": "По этому предмету заданий не найдено.",
}

# Одна карточка = одна ячейка таблицы: (дата, предмет, текст).
Card = Tuple[date, str, str]

# Сколько дней охватывает режим: "d" — один день, "w" — неделя.
# Режим "s" (по предмету) от дней не зависит: все даты начиная с сегодняшней.
_MODE_DAYS = {"d": 1, "w": 7}
_MODES = ("d", "w", "s")

SUBJECTS_TEXT = "📚 Выберите предмет:"
NO_SUBJECTS_TEXT = "В таблице не найдено ни одного предмета (проверьте шапку — первая строка)."


def _collect_subject_cards(sheet_id: str, sheet_name: str, subject_idx: int) -> List[Card]:
    """Ближайшие ДЗ по одному предмету: все даты от сегодня и позже."""
    data, subjects = sheets.fetch_homework(sheet_id, sheet_name)
    if not 0 <= subject_idx < len(subjects):
        return []
    subject = subjects[subject_idx]
    today = date.today()
    return [
        (day, subject, data[day][subject])
        for day in sorted(data)
        if day >= today and subject in data[day]
    ]


def _collect_cards(sheet_id: str, sheet_name: str, arg: str, mode: str) -> List[Card]:
    if mode == "s":
        return _collect_subject_cards(sheet_id, sheet_name, int(arg))
    start = date.fromisoformat(arg)
    subjects = sheets.get_subjects(sheet_id, sheet_name)
    cards: List[Card] = []
    for day in daterange(start, _MODE_DAYS[mode]):
        homework = sheets.get_day(sheet_id, sheet_name, day)
        if not homework:
            continue
        for subject in subjects:
            if subject in homework:
                cards.append((day, subject, homework[subject]))
    return cards


def render_card(card: Card, idx: int, total: int, done: bool = False) -> str:
    """Единый вид карточки ДЗ (дата, предмет, текст со ссылками, статус)."""
    day, subject, text = card
    result = (
        f"📅 <b>{format_date_ru(day)}</b>\n"
        f"📚 <b>{escape(subject)}</b>\n\n"
        f"{cell_to_html(text)}"
    )
    if done:
        result += "\n\n✔️ <b>Выполнено</b>"
    return result


def _build(chat_id: int, sheet_id: str, sheet_name: str, arg: str, mode: str, idx: int):
    """Возвращает (текст, клавиатура) карточки с индексом idx (с зажимом
    в допустимый диапазон — таблица могла измениться с прошлого показа)."""
    cards = _collect_cards(sheet_id, sheet_name, arg, mode)
    if not cards:
        # В режиме "s" оставляем кнопку возврата к списку предметов.
        return EMPTY_TEXT[mode], card_keyboard(mode, arg, 0, 0)
    idx = max(0, min(idx, len(cards) - 1))
    day, subject, _ = cards[idx]
    subjects = sheets.get_subjects(sheet_id, sheet_name)
    done = db.is_homework_done(chat_id, sheet_id, day.isoformat(), subject)
    toggle = f"{day.isoformat()}:{subjects.index(subject)}"
    return (
        render_card(cards[idx], idx, len(cards), done),
        card_keyboard(mode, arg, idx, len(cards), toggle, done),
    )


async def _show(message: Message, start: date, mode: str) -> None:
    profile = db.get_or_create_user(message.chat.id)
    if not profile.sheet_id:
        await message.answer(NO_SHEET_TEXT)
        return
    sheet_name = profile.sheet_name or config.GOOGLE_SHEET_NAME
    text, kb = _build(message.chat.id, profile.sheet_id, sheet_name, start.isoformat(), mode, 0)
    await message.answer(text, reply_markup=kb)


@router.message(Command("today"))
async def cmd_today(message: Message) -> None:
    await _show(message, date.today(), "d")


@router.message(Command("tomorrow"))
async def cmd_tomorrow(message: Message) -> None:
    await _show(message, date.today() + timedelta(days=1), "d")


@router.message(Command("week"))
async def cmd_week(message: Message) -> None:
    await _show(message, date.today(), "w")


@router.message(Command("subject"))
async def cmd_subject(message: Message) -> None:
    """Список предметов из шапки таблицы (кнопка «📚 По предмету»)."""
    profile = db.get_or_create_user(message.chat.id)
    if not profile.sheet_id:
        await message.answer(NO_SHEET_TEXT)
        return
    sheet_name = profile.sheet_name or config.GOOGLE_SHEET_NAME
    subjects = sheets.get_subjects(profile.sheet_id, sheet_name)
    if not subjects:
        await message.answer(NO_SUBJECTS_TEXT)
        return
    await message.answer(SUBJECTS_TEXT, reply_markup=subjects_keyboard(subjects))


@router.callback_query(F.data == "hw:subj")
async def cb_back_to_subjects(callback: CallbackQuery) -> None:
    profile = db.get_or_create_user(callback.message.chat.id)
    if not profile.sheet_id:
        await callback.answer("Таблица не подключена", show_alert=True)
        return
    sheet_name = profile.sheet_name or config.GOOGLE_SHEET_NAME
    subjects = sheets.get_subjects(profile.sheet_id, sheet_name)
    if not subjects:
        await callback.message.edit_text(NO_SUBJECTS_TEXT)
    else:
        await callback.message.edit_text(SUBJECTS_TEXT, reply_markup=subjects_keyboard(subjects))
    await callback.answer()


@router.callback_query(F.data == "hw:noop")
async def cb_card_noop(callback: CallbackQuery) -> None:
    await callback.answer()


async def _refresh_card(callback: CallbackQuery, mode: str, arg: str, idx: int) -> None:
    """Перерисовывает карточку в сообщении callback и отвечает на нажатие."""
    chat_id = callback.message.chat.id
    profile = db.get_or_create_user(chat_id)
    if not profile.sheet_id:
        await callback.answer("Таблица не подключена", show_alert=True)
        return
    sheet_name = profile.sheet_name or config.GOOGLE_SHEET_NAME
    try:
        text, kb = _build(chat_id, profile.sheet_id, sheet_name, arg, mode, idx)
        await callback.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as exc:
        # «message is not modified» — быстрый двойной клик, не ошибка.
        if "not modified" not in str(exc):
            logger.exception("Не удалось показать карточку (data=%s)", callback.data)
            await callback.answer("Не удалось показать задание, см. лог бота", show_alert=True)
            return
    except Exception:
        # Без callback.answer() у пользователя вечно крутится «загрузка».
        logger.exception("Ошибка при показе карточки (data=%s)", callback.data)
        await callback.answer("Ошибка при загрузке заданий, попробуйте позже", show_alert=True)
        return
    await callback.answer()


def _validate_view(mode: str, arg: str, raw_idx: str) -> int:
    """Проверяет (mode, arg, idx) из callback_data, возвращает idx.
    Бросает ValueError, если кнопка «протухла»/повреждена."""
    idx = int(raw_idx)
    if mode not in _MODES:
        raise ValueError(mode)
    if mode == "s":
        int(arg)
    else:
        date.fromisoformat(arg)
    return idx


@router.callback_query(F.data.startswith("hw:t:"))
async def cb_card_toggle(callback: CallbackQuery) -> None:
    """hw:t:<ISO-дата ДЗ>:<индекс предмета>:<mode>:<arg>:<idx> — переключить
    «выполнено» у карточки и перерисовать её."""
    try:
        _, _, hw_iso, raw_subject, mode, arg, raw_idx = callback.data.split(":")
        date.fromisoformat(hw_iso)
        subject_idx = int(raw_subject)
        idx = _validate_view(mode, arg, raw_idx)
    except ValueError:
        await callback.answer("Кнопка устарела", show_alert=False)
        return

    chat_id = callback.message.chat.id
    profile = db.get_or_create_user(chat_id)
    if not profile.sheet_id:
        await callback.answer("Таблица не подключена", show_alert=True)
        return
    sheet_name = profile.sheet_name or config.GOOGLE_SHEET_NAME
    try:
        subjects = sheets.get_subjects(profile.sheet_id, sheet_name)
        if not 0 <= subject_idx < len(subjects):
            await callback.answer("Кнопка устарела", show_alert=False)
            return
        subject = subjects[subject_idx]
        current = db.is_homework_done(chat_id, profile.sheet_id, hw_iso, subject)
        db.set_homework_done(chat_id, profile.sheet_id, hw_iso, subject, not current)
    except Exception:
        logger.exception("Не удалось переключить отметку (data=%s)", callback.data)
        await callback.answer("Не удалось сохранить отметку", show_alert=True)
        return
    await _refresh_card(callback, mode, arg, idx)


@router.callback_query(F.data.startswith("hw:"))
async def cb_card_page(callback: CallbackQuery) -> None:
    try:
        _, mode, arg, raw_idx = callback.data.split(":")
        idx = _validate_view(mode, arg, raw_idx)
    except ValueError:
        await callback.answer("Кнопка устарела", show_alert=False)
        return
    await _refresh_card(callback, mode, arg, idx)
