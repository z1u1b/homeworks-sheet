#!/usr/bin/env bash
# Запуск бота одной командой: ./run.sh
# Создаёт виртуальное окружение, ставит зависимости, при первом запуске
# копирует .env.example в .env и запускает бота.
set -euo pipefail
cd "$(dirname "$0")"

# 1. Python
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then PYTHON="$c"; break; fi
  done
fi
if [ -z "$PYTHON" ]; then
  echo "Ошибка: Python 3.8+ не найден. Установите его с https://www.python.org/" >&2
  exit 1
fi
if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)'; then
  echo "Ошибка: нужен Python 3.8 или новее." >&2
  exit 1
fi

# 2. Виртуальное окружение
if [ ! -d venv ]; then
  echo "==> Создаю виртуальное окружение (venv)"
  "$PYTHON" -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate

# 3. Зависимости (переустанавливаются только при изменении requirements.txt)
STAMP="venv/.requirements.stamp"
if [ ! -f "$STAMP" ] || [ requirements.txt -nt "$STAMP" ]; then
  echo "==> Устанавливаю зависимости"
  pip install --quiet --upgrade pip
  pip install --quiet -r requirements.txt
  touch "$STAMP"
fi

# 4. Конфиг
if [ ! -f .env ]; then
  cp .env.example .env
  echo "==> Создан файл .env из .env.example."
  echo "    Откройте .env, впишите BOT_TOKEN (токен от @BotFather) и запустите ./run.sh снова."
  exit 0
fi

# Значение BOT_TOKEN не выводим — только проверяем, что оно заполнено.
if ! grep -Eq '^BOT_TOKEN=.+' .env || grep -Eq '^BOT_TOKEN=123456789:AAExampleTokenReplaceMe' .env; then
  echo "Ошибка: в .env не заполнен BOT_TOKEN." >&2
  exit 1
fi

if [ ! -f credentials.json ]; then
  echo "Ошибка: не найден credentials.json (ключ сервисного аккаунта Google)." >&2
  echo "    См. раздел «Настройка Google» в README.md; образец — credentials.json.example." >&2
  exit 1
fi

# 5. Запуск
echo "==> Запускаю бота (остановить: Ctrl+C)"
exec python main.py
