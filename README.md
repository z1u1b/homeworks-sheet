# Homeworks Sheet

Telegram-бот для учёта домашних заданий. Задания ведутся в обычной Google
Таблице (её удобно редактировать с телефона), а бот показывает их по
командам и присылает напоминания.

## Возможности

* Просмотр заданий: `/today`, `/tomorrow`, `/week`, по предметам, с отметкой «выполнено».
* Напоминание о задании на завтра в выбранное время (с учётом часового пояса пользователя).
* Точечные напоминания о дедлайне: тег `[ЧЧ:ММ]` в тексте ячейки, например `Презентация [18:00]`.
* Добавление заданий и предметов прямо из бота.
* Подключение существующей таблицы (`/connect_sheet`) или автосоздание новой (`/create_sheet`) через Google OAuth.
* Отдельная таблица и настройки у каждого пользователя.
* Необязательный список допуска (allowlist) по `chat_id`.

## Стек

Python 3.8+, [aiogram 3](https://docs.aiogram.dev/), [gspread](https://docs.gspread.org/) и Google Sheets API,
APScheduler, SQLite, aiohttp (только для OAuth-колбэка).

## Быстрый старт

```bash
git clone https://github.com/z1u1b/homeworks-sheet.git
cd homeworks-sheet
./run.sh            # Windows: run.bat
```

Скрипт создаёт виртуальное окружение, ставит зависимости и при первом запуске
копирует `.env.example` в `.env`, после чего останавливается. Дальше:

1. Впишите в `.env` токен бота `BOT_TOKEN` (получить у [@BotFather](https://t.me/BotFather), команда `/newbot`).
2. Положите в корень проекта `credentials.json` — ключ сервисного аккаунта Google
   (см. [Настройка Google](#настройка-google)).
3. Запустите `./run.sh` ещё раз.

**Ожидаемый результат:** в консоли появятся логи aiogram (`Start polling`), а бот
ответит на `/start` в Telegram. Веб-адреса у бота нет — он работает через long
polling, поэтому открытый порт или домен не нужны.

## Настройка Google

1. В [Google Cloud Console](https://console.cloud.google.com/) создайте проект и
   включите **Google Sheets API** (для `/create_sheet` ещё и **Google Drive API**).
2. **APIs & Services → Credentials → Create Credentials → Service Account**.
   Затем **Keys → Add Key → Create new key → JSON**, сохраните файл как
   `credentials.json` в корне проекта (образец — `credentials.json.example`).
3. Откройте свою таблицу, нажмите «Настройки доступа» и добавьте `client_email`
   из `credentials.json` с правом «Читатель» (или «Редактор», если бот должен
   писать в таблицу).

### Формат таблицы

Первая строка — заголовок: в первой колонке `Дата`, дальше — предметы.
Каждая следующая строка — одна дата (`ДД.ММ` или `ДД.ММ.ГГГГ`), в ячейках —
текст задания, можно с несколькими ссылками. Пустая ячейка — `-`, `—` или
просто пусто; такие ячейки в уведомлениях пропускаются.

| Дата  | Математика  | Физика | Английский |
| ----- | ----------- | ------ | ---------- |
| 18.09 | №123, §5    | §12    | Unit 4     |
| 19.09 | Контрольная | —      | слова      |

## Команды бота

| Команда | Что делает |
| ------- | ---------- |
| `/start`, `/help` | Регистрация и список команд |
| `/connect_sheet <ID> [лист]` | Подключить свою таблицу (ID — часть ссылки между `/d/` и `/edit`) |
| `/create_sheet <предмет1>, <предмет2>, ...` | Создать и оформить новую таблицу в вашем Google Диске |
| `/today`, `/tomorrow`, `/week` | Задания на сегодня, завтра, ближайшие 7 дней |
| `/settings` | Время напоминания, часовой пояс, уведомления, напоминания о дедлайнах |
| `/whoami` | Показать свой `chat_id` |

## Конфигурация

Все параметры задаются в `.env`, полный список с комментариями — в
[`.env.example`](.env.example). Основные:

| Переменная | Назначение |
| ---------- | ---------- |
| `BOT_TOKEN` | Токен Telegram-бота (обязательно) |
| `GOOGLE_CREDENTIALS_FILE` | Путь к ключу сервисного аккаунта (по умолчанию `credentials.json`) |
| `DEFAULT_TIMEZONE`, `DEFAULT_NOTIFY_TIME` | Часовой пояс и время напоминаний для новых пользователей |
| `ALLOWED_CHAT_IDS` | `chat_id` через запятую, кому разрешён доступ; пусто — бот открыт для всех |
| `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `OAUTH_PUBLIC_BASE_URL`, `OAUTH_CALLBACK_PORT` | Нужны только для `/create_sheet` |

### Включение `/create_sheet`

Команда создаёт таблицу в Google Диске самого пользователя через OAuth. Для
этого нужен OAuth-клиент типа **Web application** с redirect URI
`https://<ваш-домен>/oauth/callback` и HTTPS-прокси (например, nginx) на
`127.0.0.1:OAUTH_CALLBACK_PORT`. Google не принимает голый IP в redirect URI.
Без этих настроек остальной бот работает как обычно.

## Запуск на сервере

Шаблон systemd-юнита лежит в `deploy/homeworks-bot.service` (инструкция —
в комментариях файла). После обновления кода:

```bash
./deploy.sh   # git pull + перезапуск сервиса
```

Привязать таблицу к чату без диалога с ботом можно скриптом:

```bash
python scripts/bind_sheet.py <CHAT_ID> <SHEET_ID> [SHEET_NAME]
```

## Структура проекта

```
homeworks-sheet/
├── main.py                 # точка входа
├── run.sh / run.bat        # запуск одной командой
├── deploy.sh, deploy/      # обновление и systemd-юнит для сервера
├── format_sheet.py         # оформление таблицы (шапка, заливка, подсветка контрольных)
├── scripts/bind_sheet.py   # привязка chat_id к таблице из командной строки
├── requirements.txt
├── .env.example
├── credentials.json.example
└── bot/
    ├── config.py           # настройки из .env
    ├── db.py               # SQLite: пользователи, настройки, защита от дублей
    ├── sheets.py           # чтение и кэширование Google Sheets
    ├── oauth.py            # Google OAuth для /create_sheet
    ├── sheet_formatting.py # общее оформление таблиц
    ├── scheduler.py        # APScheduler: напоминания
    ├── keyboards.py, utils.py
    ├── middlewares/        # allowlist
    └── handlers/           # обработчики команд и диалогов
```

## Заметки

* Данные из таблицы кэшируются на `SHEET_CACHE_TTL` секунд (по умолчанию 120),
  чтобы не упираться в лимиты Google API, поэтому правки появляются в боте с небольшой задержкой.
* Ссылки `https://...` в ячейках становятся кликабельными.
* Настройки пользователей хранятся в `homeworks.db`, файл создаётся автоматически.
* Никогда не публикуйте `.env`, `credentials.json` и `homeworks.db` — они уже в `.gitignore`.
