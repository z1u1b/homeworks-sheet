import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from .. import config, db, oauth
from ..sheet_formatting import fill_empty_worksheet, format_worksheet
from ..sheets import get_service_account_email

router = Router()
logger = logging.getLogger(__name__)

USAGE_TEXT = (
    "Укажите предметы через запятую:\n"
    "/create_sheet Математика, Физика, Английский\n\n"
    "Я создам новую Google-таблицу прямо в вашем Google Drive (она сразу "
    "будет вашей — делиться на почту дополнительно не нужно) и оформлю её "
    "так же, как остальные таблицы бота. Потребуется один раз авторизоваться "
    "через Google."
)

DAYS_AHEAD = 30


@router.message(Command("create_sheet"))
async def cmd_create_sheet(message: Message) -> None:
    if not config.GOOGLE_OAUTH_CLIENT_ID or not config.GOOGLE_OAUTH_CLIENT_SECRET:
        await message.answer(
            "Автосоздание таблицы пока не настроено администратором бота. "
            "Подключите таблицу вручную через /connect_sheet."
        )
        return

    text = message.text or ""
    _, _, args = text.partition(" ")
    subjects = [s.strip() for s in args.split(",") if s.strip()]
    if not subjects:
        await message.answer(USAGE_TEXT)
        return

    chat_id = message.chat.id

    try:
        client = oauth.get_client_for_user(chat_id)
    except LookupError:
        auth_url = oauth.build_auth_url(chat_id)
        await message.answer(
            "Сначала авторизуйтесь через Google по ссылке, потом повторите "
            "эту же команду ещё раз:\n" + auth_url
        )
        return
    except Exception:
        logger.exception("Не удалось получить OAuth-клиент для chat_id=%s", chat_id)
        await message.answer(
            "Не получилось обновить доступ к вашему Google-аккаунту. "
            "Попробуйте авторизоваться заново — пришлите /create_sheet ещё раз."
        )
        return

    await message.answer("Создаю таблицу, это может занять несколько секунд...")

    display_name = message.from_user.full_name if message.from_user else str(chat_id)

    try:
        spreadsheet = client.create(f"Домашние задания — {display_name}")
        worksheet = spreadsheet.sheet1
        worksheet.update_title(config.GOOGLE_SHEET_NAME)

        n_rows = fill_empty_worksheet(worksheet, subjects, DAYS_AHEAD)
        format_worksheet(spreadsheet, worksheet, subjects, n_rows)

        service_account_email = get_service_account_email()
        if service_account_email:
            spreadsheet.share(service_account_email, perm_type="user", role="reader", notify=False)
        else:
            logger.warning("Не удалось прочитать email сервис-аккаунта — таблица не расшарена на бота")
    except Exception:
        logger.exception("Не удалось создать/оформить таблицу для chat_id=%s", chat_id)
        await message.answer(
            "Не получилось создать таблицу. Попробуйте позже, либо подключите "
            "таблицу вручную через /connect_sheet."
        )
        return

    db.set_sheet(chat_id, spreadsheet.id, config.GOOGLE_SHEET_NAME)

    await message.answer(
        "Готово! Таблица создана и подключена:\n"
        f"{spreadsheet.url}\n\n"
        "Проверьте: /today"
    )
