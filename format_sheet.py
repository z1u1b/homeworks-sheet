"""
Скрипт для красивого оформления Google Таблицы с домашними заданиями.

Что делает:
  * если лист ещё пустой — создаёт заголовок (Дата + предметы из SUBJECTS)
    и пустые строки на DAYS_AHEAD дней вперёд;
  * если в листе уже есть данные — НЕ трогает значения ячеек, только
    оформляет: закрепляет первую строку/колонку, красит заголовок,
    делает полосатую заливку строк, переносит текст в ячейках заданий,
    подсвечивает "контрольные/экзамены" красным жирным, приглушает
    пустые ячейки ("-"), выставляет ширину колонок и границы.

Запуск (после того как заполнены .env и credentials.json, как в README):
    python format_sheet.py

Скрипт можно запускать повторно в любой момент — он идемпотентен для
оформления (данные не перезаписывает).

Сама логика построения запросов к Sheets API вынесена в
bot/sheet_formatting.py — её же использует команда бота /create_sheet
(bot/handlers/sheet_creation.py), чтобы не дублировать код.
"""

import os
import sys

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

from bot.sheet_formatting import clear_banded_ranges, clear_conditional_formats, fill_empty_worksheet, format_worksheet

load_dotenv()

GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Homework")

if not GOOGLE_SHEET_ID:
    sys.exit("GOOGLE_SHEET_ID не задан в .env")

# --- Настройки, используются только если лист ещё пустой -------------------
SUBJECTS = ["Математика", "Физика", "Английский", "Русский язык", "История"]
DAYS_AHEAD = 30  # на сколько дней вперёд создать пустые строки
# ----------------------------------------------------------------------------

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def main():
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)

    try:
        worksheet = spreadsheet.worksheet(GOOGLE_SHEET_NAME)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=GOOGLE_SHEET_NAME, rows=100, cols=10)

    existing = worksheet.get_all_values()
    is_empty = not any(cell.strip() for row in existing for cell in row)

    if is_empty:
        subjects = SUBJECTS
        n_rows = fill_empty_worksheet(worksheet, subjects, DAYS_AHEAD)
        print(f"Заполнил лист «{GOOGLE_SHEET_NAME}»: {len(subjects)} предметов, {DAYS_AHEAD} дней вперёд.")
    else:
        header = existing[0]
        subjects = [h.strip() for h in header[1:] if h.strip()]
        if not subjects:
            sys.exit(
                "Не удалось определить предметы по первой строке листа. "
                "Проверьте, что в A1 стоит 'Дата', а дальше — названия предметов."
            )
        n_rows = len(existing)
        print(f"Лист «{GOOGLE_SHEET_NAME}» уже содержит данные — значения не трогаю, только оформляю.")

    if not is_empty:
        # На уже оформленном листе addBanding/addConditionalFormatRule
        # падают или копятся поверх старых правил (см. bot/sheets.py:
        # add_subject — тот же самый фикс). Без этого повторный запуск на
        # НЕпустом листе был бы не идемпотентным, вопреки докстрингу выше.
        clear_conditional_formats(spreadsheet, worksheet.id)
        clear_banded_ranges(spreadsheet, worksheet.id)
    format_worksheet(spreadsheet, worksheet, subjects, n_rows)

    print("Готово! Открой таблицу:")
    print(f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/edit#gid={worksheet.id}")


if __name__ == "__main__":
    main()
