from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.types import Message

from .. import db
from ..keyboards import (
    BTN_HELP,
    BTN_SETTINGS,
    BTN_STATS,
    BTN_SUBJECT,
    BTN_TODAY,
    BTN_TOMORROW,
    BTN_WEEK,
    main_menu_keyboard,
)
from .homework import cmd_subject, cmd_today, cmd_tomorrow, cmd_week
from .settings import cmd_settings

router = Router()
# Роутер-«ловушка» для непонятных сообщений. Подключается в
# handlers/__init__.py ПОСЛЕДНИМ, иначе он перехватит сообщения,
# предназначенные другим хендлерам.
fallback_router = Router()

SOON_TEXT = "🚧 Эта функция появится в одном из ближайших обновлений."

HELP_TEXT = (
    "Привет! Я бот для учёта домашних заданий 📚\n\n"
    "Сначала подключите свою Google-таблицу:\n"
    "/connect_sheet &lt;ID_ТАБЛИЦЫ&gt; [название листа]\n\n"
    "Команды:\n"
    "/today — задания на сегодня\n"
    "/tomorrow — задания на завтра\n"
    "/week — задания на ближайшие 7 дней\n"
    "/subject — задания по выбранному предмету\n"
    "/add — добавить задание в таблицу\n"
    "/add_subject &lt;название&gt; — добавить новый предмет (колонку) в таблицу\n"
    "/settings — время и часовой пояс уведомлений\n"
    "/whoami — узнать свой chat_id\n\n"
    "Каждый день в выбранное время я буду присылать напоминание "
    "о домашнем задании на завтра.\n\n"
    "Хотите точечное напоминание по дедлайну (например, за 3 часа до "
    "сдачи)? Добавьте в текст задания тег [ЧЧ:ММ], например «Сделать "
    "презентацию [18:00]», и включите напоминания в /settings."
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    db.get_or_create_user(message.chat.id)
    await message.answer(HELP_TEXT, reply_markup=main_menu_keyboard())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT)


@router.message(Command("whoami"))
async def cmd_whoami(message: Message) -> None:
    user = message.from_user
    username = f"@{user.username}" if user and user.username else "—"
    await message.answer(
        "🆔 Ваши данные:\n"
        f"chat_id: <code>{message.chat.id}</code>\n"
        f"username: {username}\n\n"
        "chat_id пригодится для привязки таблицы через scripts/bind_sheet.py "
        "или для списка допуска (allowlist)."
    )


# --- Кнопки главного меню: тонкие обёртки над существующими командами ---


@router.message(F.text == BTN_TODAY)
async def btn_today(message: Message) -> None:
    await cmd_today(message)


@router.message(F.text == BTN_TOMORROW)
async def btn_tomorrow(message: Message) -> None:
    await cmd_tomorrow(message)


@router.message(F.text == BTN_WEEK)
async def btn_week(message: Message) -> None:
    await cmd_week(message)


@router.message(F.text == BTN_SUBJECT)
async def btn_subject(message: Message) -> None:
    await cmd_subject(message)


@router.message(F.text == BTN_SETTINGS)
async def btn_settings(message: Message) -> None:
    await cmd_settings(message)


@router.message(F.text == BTN_HELP)
async def btn_help(message: Message) -> None:
    await cmd_help(message)


# Заглушки для функций из следующих шагов плана
# (статистика — шаг 7).
@router.message(F.text == BTN_STATS)
async def btn_not_implemented(message: Message) -> None:
    await message.answer(SOON_TEXT, reply_markup=main_menu_keyboard())


# --- Fallback: любое непонятное сообщение -> показать меню ---


@fallback_router.message(StateFilter(None))
async def fallback(message: Message) -> None:
    await message.answer(
        "Не понял сообщение 🤔 Выберите действие в меню ниже "
        "или отправьте /help.",
        reply_markup=main_menu_keyboard(),
    )
