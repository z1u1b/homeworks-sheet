from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from .. import config, db, sheets

router = Router()

USAGE_TEXT = (
    "Укажите ID таблицы: /connect_sheet &lt;ID_ТАБЛИЦЫ&gt; [название листа]\n\n"
    "ID — это часть ссылки на таблицу между /d/ и /edit, например:\n"
    "https://docs.google.com/spreadsheets/d/&lt;ЭТОТ_ID&gt;/edit\n\n"
    "Перед этим откройте доступ сервис-аккаунту бота к таблице "
    "(Настройки доступа → email сервис-аккаунта из credentials.json, "
    "право минимум «Читатель»)."
)


@router.message(Command("connect_sheet"))
async def cmd_connect_sheet(message: Message) -> None:
    text = message.text or ""
    _, _, args = text.partition(" ")
    args = args.strip()
    if not args:
        await message.answer(USAGE_TEXT)
        return

    parts = args.split(maxsplit=1)
    sheet_id = parts[0].strip()
    sheet_name = parts[1].strip() if len(parts) > 1 else config.GOOGLE_SHEET_NAME

    try:
        sheets.fetch_homework(sheet_id, sheet_name, force=True)
    except Exception:
        await message.answer(
            "Не получилось открыть таблицу. Проверьте:\n"
            "1) ID таблицы указан верно;\n"
            "2) таблица открыта сервис-аккаунту бота (см. /connect_sheet без аргументов);\n"
            f"3) в таблице есть лист с названием «{sheet_name}»."
        )
        return

    db.set_sheet(message.chat.id, sheet_id, sheet_name)
    await message.answer(
        f"Готово! Таблица подключена (лист «{sheet_name}»). Проверьте: /today"
    )
