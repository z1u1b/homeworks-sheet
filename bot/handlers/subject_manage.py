"""Добавление предмета (колонки) через бота — шаг 5б.

Три входа, одна общая логика (try_add_subject):
* команда /add_subject <название>;
* кнопка "🆕 Новый предмет" в главном меню (свой мини-диалог на одно
  сообщение — имени неоткуда взяться, кроме как спросить);
* пункт "➕ Новый предмет" внутри диалога «➕ Добавить ДЗ»
  (bot/handlers/homework_add.py) — импортирует try_add_subject отсюда.

Те же ограничения на запись, что и в шаге 5 (bot/handlers/homework_add.py):
писать можно только в таблицы, созданные через /create_sheet (OAuth-scope
drive.file не видит таблицы, подключённые вручную через /connect_sheet).
"""
import asyncio
import logging
from html import escape
from typing import Any, Callable, NamedTuple, Optional

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from .. import config, db, oauth, sheets
from ..keyboards import BTN_ADD_SUBJECT, MENU_BUTTONS
from .homework import NO_SHEET_TEXT

router = Router()
logger = logging.getLogger(__name__)


class AddSubjectStandalone(StatesGroup):
    """FSM кнопки "🆕 Новый предмет" в главном меню — отдельно от диалога
    /add (AddHomework в bot/handlers/homework_add.py): просто спросить
    название и вызвать try_add_subject."""

    name = State()


NO_WRITE_ACCESS_TEXT = (
    "🔒 Бот не может записывать в эту таблицу. Запись доступна только в "
    "таблицы, созданные через /create_sheet — таблицу, подключённую вручную "
    "через /connect_sheet, бот может только читать.\n\n"
    "Создайте таблицу командой /create_sheet Предмет1, Предмет2, ... "
    "или добавляйте предметы в таблицу руками."
)

USAGE_TEXT = "Укажите название предмета:\n/add_subject Информатика"


async def _run(func: Callable[..., Any], *args: Any) -> Any:
    """Блокирующие вызовы gspread/OAuth — в потоке (asyncio.to_thread не
    используем: на сервере Python 3.8, см. bot/handlers/homework_add.py)."""
    return await asyncio.get_running_loop().run_in_executor(None, func, *args)


class AddSubjectResult(NamedTuple):
    """Результат try_add_subject().

    * ok — предмет добавлен;
    * message — текст для пользователя (успех или причина отказа);
    * subject — итоговое название предмета (только если ok);
    * retryable — имеет смысл только когда not ok: True, если разумно
      попросить пользователя ввести название ещё раз в том же диалоге
      (пустое название, дубликат); False — отказ окончательный для этой
      попытки (нет доступа на запись, не настроен OAuth, нужна повторная
      авторизация, лимит колонок, непредвиденная ошибка) — диалог дальше
      вести некуда, его стоит завершить.
    """

    ok: bool
    message: str
    subject: Optional[str] = None
    retryable: bool = False


async def try_add_subject(chat_id: int, raw_name: str) -> AddSubjectResult:
    """Общая логика добавления предмета: валидация названия, OAuth, запись
    через sheets.add_subject, обработка ошибок."""
    name = raw_name.strip()
    if not name:
        return AddSubjectResult(False, "Название предмета не может быть пустым. Отправьте ещё раз.", retryable=True)

    profile = db.get_or_create_user(chat_id)
    if not profile.sheet_id:
        return AddSubjectResult(False, NO_SHEET_TEXT)
    sheet_id = profile.sheet_id
    sheet_name = profile.sheet_name or config.GOOGLE_SHEET_NAME

    if not config.GOOGLE_OAUTH_CLIENT_ID or not config.GOOGLE_OAUTH_CLIENT_SECRET:
        return AddSubjectResult(False, "Добавление предметов через бота пока не настроено администратором.")

    try:
        client = await _run(oauth.get_client_for_user, chat_id)
    except LookupError:
        return AddSubjectResult(False, (
            "Чтобы бот мог записывать в вашу таблицу, один раз авторизуйтесь "
            "через Google по ссылке, потом повторите добавление предмета:\n"
            + oauth.build_auth_url(chat_id)
        ))
    except Exception:
        logger.exception("Не удалось получить OAuth-клиент для chat_id=%s", chat_id)
        return AddSubjectResult(False, (
            "Не получилось обновить доступ к вашему Google-аккаунту. "
            "Попробуйте авторизоваться заново — пришлите /create_sheet ещё раз."
        ))

    try:
        await _run(sheets.add_subject, client, sheet_id, sheet_name, name)
    except sheets.WriteAccessError:
        return AddSubjectResult(False, NO_WRITE_ACCESS_TEXT)
    except sheets.DuplicateSubjectError:
        return AddSubjectResult(
            False,
            f"Предмет «{escape(name)}» уже есть в таблице (без учёта регистра). Введите другое название.",
            retryable=True,
        )
    except sheets.SubjectLimitError as exc:
        return AddSubjectResult(False, str(exc))
    except Exception:
        logger.exception("Не удалось добавить предмет (chat_id=%s)", chat_id)
        return AddSubjectResult(False, "Не получилось добавить предмет. Попробуйте позже.")

    return AddSubjectResult(True, f"✅ Предмет «{escape(name)}» добавлен в таблицу.", subject=name)


@router.message(Command("add_subject"))
async def cmd_add_subject(message: Message) -> None:
    text = message.text or ""
    _, _, raw_name = text.partition(" ")
    if not raw_name.strip():
        await message.answer(USAGE_TEXT)
        return
    result = await try_add_subject(message.chat.id, raw_name)
    await message.answer(result.message)


# ---------- кнопка "🆕 Новый предмет" в главном меню ----------


@router.message(F.text == BTN_ADD_SUBJECT)
async def btn_add_subject(message: Message, state: FSMContext) -> None:
    await state.set_state(AddSubjectStandalone.name)
    await message.answer("Введите название нового предмета одним сообщением.\nОтмена — /cancel")


@router.message(Command("cancel"), StateFilter(AddSubjectStandalone))
async def cmd_cancel_add_subject(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Добавление предмета отменено.")


@router.message(AddSubjectStandalone.name, F.text, F.text.in_(MENU_BUTTONS))
async def msg_add_subject_interrupt(message: Message, state: FSMContext) -> None:
    """Кнопка меню посреди мини-диалога — отменяем его, а не пытаемся
    добавить предмет с названием вроде "📅 Сегодня"."""
    await state.clear()
    await message.answer("Добавление предмета отменено. Повторите нужное действие ещё раз.")


@router.message(AddSubjectStandalone.name, F.text, ~F.text.startswith("/"))
async def msg_add_subject_name(message: Message, state: FSMContext) -> None:
    result = await try_add_subject(message.chat.id, message.text)
    await message.answer(result.message)
    if not result.ok and result.retryable:
        return  # пустое название / дубликат — остаёмся в состоянии, даём попробовать ещё раз
    await state.clear()


@router.message(StateFilter(AddSubjectStandalone))
async def msg_add_subject_hint(message: Message) -> None:
    await message.answer("Отправьте название предмета текстом или /cancel.")
