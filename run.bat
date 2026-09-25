@echo off
rem Запуск бота одной командой: run.bat
rem Создаёт виртуальное окружение, ставит зависимости, при первом запуске
rem копирует .env.example в .env и запускает бота.
setlocal
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Ошибка: Python 3.8+ не найден. Установите его с https://www.python.org/
  exit /b 1
)

if not exist venv (
  echo ==^> Создаю виртуальное окружение ^(venv^)
  python -m venv venv || exit /b 1
)
call venv\Scripts\activate.bat

if not exist venv\.requirements.stamp (
  echo ==^> Устанавливаю зависимости
  python -m pip install --quiet --upgrade pip
  pip install --quiet -r requirements.txt || exit /b 1
  echo ok> venv\.requirements.stamp
)

if not exist .env (
  copy .env.example .env >nul
  echo ==^> Создан файл .env из .env.example.
  echo     Откройте .env, впишите BOT_TOKEN ^(токен от @BotFather^) и запустите run.bat снова.
  exit /b 0
)

if not exist credentials.json (
  echo Ошибка: не найден credentials.json ^(ключ сервисного аккаунта Google^).
  echo     См. раздел «Настройка Google» в README.md; образец — credentials.json.example.
  exit /b 1
)

echo ==^> Запускаю бота ^(остановить: Ctrl+C^)
python main.py
