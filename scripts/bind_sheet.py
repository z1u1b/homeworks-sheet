"""
Разовая утилита: привязать существующую Google-таблицу к конкретному
chat_id в базе бота.

Нужна при переходе на мультипользовательскую схему — чтобы не потерять
уже работающую таблицу и не хардкодить чей-то chat_id/ID таблицы в коде
бота. Все значения передаются аргументами командной строки.

Запускать там же, где лежат .env и homeworks.db (при разработке — на
Mac; после git pull на сервере — там же, перед перезапуском бота).

Использование:
    python scripts/bind_sheet.py <CHAT_ID> <SHEET_ID> [SHEET_NAME]

CHAT_ID узнать командой /whoami в самом боте.
SHEET_ID — часть ссылки на таблицу между /d/ и /edit.
SHEET_NAME — необязательно, по умолчанию берётся GOOGLE_SHEET_NAME из
.env (или "Homework").
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot import config, db  # noqa: E402


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)

    chat_id = int(sys.argv[1])
    sheet_id = sys.argv[2]
    sheet_name = sys.argv[3] if len(sys.argv) > 3 else config.GOOGLE_SHEET_NAME

    db.init_db()
    db.get_or_create_user(chat_id)
    db.set_sheet(chat_id, sheet_id, sheet_name)
    print(f"chat_id={chat_id} привязан к таблице {sheet_id} (лист «{sheet_name}»).")


if __name__ == "__main__":
    main()
