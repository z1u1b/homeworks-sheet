import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

# Таблица теперь не общая на всех: у каждого пользователя своя (bot/db.py:
# users.sheet_id / users.sheet_name), привязывается командой /connect_sheet.
# Эти переменные — только запасное имя листа по умолчанию для новых
# привязок и для однопользовательских скриптов вроде format_sheet.py.
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Homework")

DB_PATH = os.getenv("DB_PATH", "homeworks.db")

# OAuth пользователя (не сервис-аккаунт) — для /create_sheet: автосоздание
# таблицы прямо в Drive пользователя. Если не заданы — main.py не поднимает
# aiohttp-сервер для /oauth/callback, а /create_sheet отвечает, что функция
# не настроена; остальной бот работает как раньше.
GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
# Публичный HTTPS-адрес бота (домен, не IP — так требует Google OAuth),
# куда Google редиректит после согласия. Путь /oauth/callback
# приписывается в bot/oauth.py.
OAUTH_PUBLIC_BASE_URL = os.getenv("OAUTH_PUBLIC_BASE_URL", "")
# Порт, на котором локально (127.0.0.1) слушает aiohttp-сервер
# /oauth/callback — наружу его открывает nginx на OAUTH_PUBLIC_BASE_URL.
OAUTH_CALLBACK_PORT = int(os.getenv("OAUTH_CALLBACK_PORT", "8081"))

# Allowlist онбординга: chat_id, которым разрешено пользоваться ботом.
# Пустой список (переменная не задана) — allowlist выключен, все могут
# писать боту (по умолчанию для локальной разработки без .env).
ALLOWED_CHAT_IDS = {
    int(x) for x in os.getenv("ALLOWED_CHAT_IDS", "").split(",") if x.strip()
}
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "Europe/Moscow")
DEFAULT_NOTIFY_TIME = os.getenv("DEFAULT_NOTIFY_TIME", "20:00")
# Сколько часов до дедлайна (тег [ЧЧ:ММ] в тексте ячейки) напоминать
# по умолчанию, для только что заведённых пользователей — сама функция
# по умолчанию выключена (deadline_reminder_enabled=0), это только число.
DEFAULT_DEADLINE_HOURS = int(os.getenv("DEFAULT_DEADLINE_HOURS", "3"))

# Автоподгонка оформления (шаг 6+): раз в день, в это время (по часовому
# поясу пользователя), бот проверяет — не выросла ли таблица (предмет/дата,
# дописанные руками в Google Sheets) за пределы последнего оформления, и
# если да, докатывает формат. Работает только для таблиц, где у бота есть
# доступ на запись через OAuth (созданных через /create_sheet) — для
# /connect_sheet-таблиц тихо пропускается (WriteAccessError).
REFORMAT_CHECK_TIME = os.getenv("REFORMAT_CHECK_TIME", "03:30")
SHEET_CACHE_TTL = int(os.getenv("SHEET_CACHE_TTL", "120"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан. Заполните .env (см. .env.example)")
