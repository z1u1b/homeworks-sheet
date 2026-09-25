import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from aiohttp import web

from bot import config, db, oauth
from bot.handlers import get_root_router
from bot.middlewares.allowlist import AllowlistMiddleware
from bot.scheduler import create_scheduler

logger = logging.getLogger(__name__)

# Список команд для меню "/" в Telegram-клиенте (BotFather делает то же
# самое через /setcommands, но так это живёт в репозитории и обновляется
# автоматически при каждом старте бота — не нужно синхронизировать руками).
BOT_COMMANDS = [
    BotCommand(command="today", description="Задания на сегодня"),
    BotCommand(command="tomorrow", description="Задания на завтра"),
    BotCommand(command="week", description="Задания на ближайшие 7 дней"),
    BotCommand(command="subject", description="Задания по предмету"),
    BotCommand(command="add", description="Добавить задание в таблицу"),
    BotCommand(command="add_subject", description="Добавить новый предмет (колонку)"),
    BotCommand(command="settings", description="Время, часовой пояс, напоминания"),
    BotCommand(command="connect_sheet", description="Подключить существующую Google-таблицу"),
    BotCommand(command="create_sheet", description="Создать новую Google-таблицу"),
    BotCommand(command="whoami", description="Узнать свой chat_id"),
    BotCommand(command="help", description="Список команд и подсказки"),
]


async def _oauth_callback(request: web.Request) -> web.Response:
    """GET /oauth/callback — сюда Google редиректит после согласия
    пользователя (см. bot/oauth.py, OAUTH_PUBLIC_BASE_URL в .env)."""
    bot: Bot = request.app["bot"]

    error = request.query.get("error")
    if error:
        return web.Response(text=f"Google вернул ошибку авторизации: {error}", status=400)

    code = request.query.get("code")
    state = request.query.get("state")
    if not code or not state:
        return web.Response(text="В запросе нет code/state", status=400)

    try:
        chat_id, _ = oauth.exchange_code(code, state)
    except ValueError as exc:
        return web.Response(text=f"Не удалось завершить авторизацию: {exc}", status=400)
    except Exception:
        logger.exception("Ошибка при обмене OAuth code на токен")
        return web.Response(text="Внутренняя ошибка, попробуйте ещё раз позже", status=500)

    try:
        await bot.send_message(
            chat_id,
            "Google подключён! Теперь повторите прежнее действие: команду /create_sheet "
            "со списком предметов или кнопку «➕ Добавить ДЗ».",
        )
    except Exception:
        logger.exception("Не удалось отправить подтверждение в Telegram (chat_id=%s)", chat_id)

    return web.Response(text="Готово! Можно вернуться в Telegram и повторить прежнее действие.")


async def _start_oauth_server(bot: Bot) -> web.AppRunner:
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/oauth/callback", _oauth_callback)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", config.OAUTH_CALLBACK_PORT)
    await site.start()
    logger.info("OAuth callback слушает 127.0.0.1:%s (наружу — через nginx на OAUTH_PUBLIC_BASE_URL)", config.OAUTH_CALLBACK_PORT)
    return runner


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    db.init_db()

    bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.message.middleware(AllowlistMiddleware())
    dp.callback_query.middleware(AllowlistMiddleware())
    dp.include_router(get_root_router())

    await bot.set_my_commands(BOT_COMMANDS)

    scheduler = create_scheduler(bot)
    scheduler.start()

    oauth_runner = None
    if config.GOOGLE_OAUTH_CLIENT_ID and config.GOOGLE_OAUTH_CLIENT_SECRET and config.OAUTH_PUBLIC_BASE_URL:
        oauth_runner = await _start_oauth_server(bot)
    else:
        logger.info(
            "GOOGLE_OAUTH_CLIENT_ID/SECRET/OAUTH_PUBLIC_BASE_URL не заданы — /create_sheet недоступен"
        )

    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        if oauth_runner is not None:
            await oauth_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
