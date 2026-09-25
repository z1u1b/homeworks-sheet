#!/bin/bash
# Одна команда для обновления бота на сервере после изменений в коде:
# подтягивает свежий код и перезапускает systemd-сервис.
#
# Использование (на сервере, из папки проекта):
#   ./deploy.sh
#
# Предполагает, что deploy/homeworks-bot.service уже один раз установлен
# и включён (см. инструкцию в самом этом файле) — deploy.sh им управляет,
# но не устанавливает его.
set -e
cd "$(dirname "$0")"

echo "==> git pull"
git pull

echo "==> перезапускаю systemd-сервис homeworks-bot"
sudo systemctl restart homeworks-bot

echo "==> статус:"
sudo systemctl status homeworks-bot --no-pager
