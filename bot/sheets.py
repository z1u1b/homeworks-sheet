import json
import logging
import time
from datetime import date
from typing import Dict, List, Optional, Tuple

import gspread
from google.oauth2.service_account import Credentials

from . import config
from .sheet_formatting import (
    clear_banded_ranges,
    clear_conditional_formats,
    format_worksheet,
    get_formatted_dimensions,
)
from .utils import is_empty_cell, parse_row_date

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# У каждого пользователя своя таблица, поэтому кэш и запросы к API теперь
# ключуются по (sheet_id, sheet_name), а не по одному глобальному листу.
_client = None
_cache: Dict[Tuple[str, str], dict] = {}


def _get_client():
    global _client
    if _client is None:
        creds = Credentials.from_service_account_file(
            config.GOOGLE_CREDENTIALS_FILE, scopes=SCOPES
        )
        _client = gspread.authorize(creds)
    return _client


def _get_worksheet(sheet_id: str, sheet_name: str):
    spreadsheet = _get_client().open_by_key(sheet_id)
    try:
        return spreadsheet.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        return spreadsheet.get_worksheet(0)


def _load_from_sheet(sheet_id: str, sheet_name: str) -> Tuple[Dict[date, Dict[str, str]], List[str]]:
    worksheet = _get_worksheet(sheet_id, sheet_name)
    rows = worksheet.get_all_values()
    if not rows:
        return {}, []

    header = rows[0]
    subjects = [h.strip() for h in header[1:] if h.strip()]

    today = date.today()
    data: Dict[date, Dict[str, str]] = {}

    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        parsed_date = parse_row_date(row[0], today)
        if parsed_date is None:
            continue

        day_data: Dict[str, str] = {}
        for idx, subject in enumerate(subjects, start=1):
            if idx >= len(row):
                continue
            value = row[idx].strip()
            if is_empty_cell(value):
                continue
            day_data[subject] = value
        data[parsed_date] = day_data

    return data, subjects


def fetch_homework(
    sheet_id: str, sheet_name: str, force: bool = False
) -> Tuple[Dict[date, Dict[str, str]], List[str]]:
    """Возвращает (данные по дням, список предметов) для конкретной таблицы,
    используя кэш с TTL на каждую пару (sheet_id, sheet_name) отдельно."""
    cache_key = (sheet_id, sheet_name)
    cached = _cache.get(cache_key)
    now = time.monotonic()
    if not force and cached and now - cached["fetched_at"] < config.SHEET_CACHE_TTL:
        return cached["data"], cached["subjects"]

    try:
        data, subjects = _load_from_sheet(sheet_id, sheet_name)
    except Exception:
        logger.exception("Не удалось загрузить домашние задания (sheet_id=%s, лист=%s)", sheet_id, sheet_name)
        if cached:
            return cached["data"], cached["subjects"]
        raise

    _cache[cache_key] = {"data": data, "subjects": subjects, "fetched_at": now}
    return data, subjects


def get_day(sheet_id: str, sheet_name: str, target: date) -> Optional[Dict[str, str]]:
    data, _ = fetch_homework(sheet_id, sheet_name)
    return data.get(target)


def get_subjects(sheet_id: str, sheet_name: str) -> List[str]:
    _, subjects = fetch_homework(sheet_id, sheet_name)
    return subjects


class WriteAccessError(Exception):
    """У пользовательского OAuth-клиента нет доступа на запись к таблице.
    Типичная причина: таблица подключена через /connect_sheet, а не создана
    ботом (scope drive.file видит только файлы, созданные приложением)."""


class DuplicateSubjectError(Exception):
    """Такой предмет уже есть в шапке таблицы (сравнение без учёта регистра)."""


class SubjectLimitError(Exception):
    """Достигнут лимит предметов (колонок) в таблице (см. MAX_SUBJECTS)."""


# Практический лимит числа предметов (колонок) в таблице — чтобы шапка и
# сама таблица оставались читаемыми и удобными для редактирования с
# телефона. Чисто продуктовое решение, не техническое
# ограничение Google Sheets.
MAX_SUBJECTS = 20


def invalidate_cache(sheet_id: str, sheet_name: str) -> None:
    """Сбрасывает кэш таблицы (после записи, чтобы /today сразу видел данные)."""
    _cache.pop((sheet_id, sheet_name), None)


def _api_status(exc: "gspread.exceptions.APIError") -> Optional[int]:
    return getattr(getattr(exc, "response", None), "status_code", None)


def _open_spreadsheet_for_write(client, sheet_id: str):
    """Открывает таблицу клиентом пользователя (OAuth). Бросает
    WriteAccessError, если она недоступна этому клиенту. Общая часть
    open_worksheet_for_write и add_subject (обеим нужен сам объект
    Spreadsheet, не только Worksheet)."""
    try:
        return client.open_by_key(sheet_id)
    except gspread.exceptions.SpreadsheetNotFound as exc:
        raise WriteAccessError(str(exc)) from exc
    except gspread.exceptions.APIError as exc:
        if _api_status(exc) in (403, 404):
            raise WriteAccessError(str(exc)) from exc
        raise


def _worksheet_or_first(spreadsheet, sheet_name: str):
    try:
        return spreadsheet.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        return spreadsheet.get_worksheet(0)


def open_worksheet_for_write(client, sheet_id: str, sheet_name: str):
    """Открывает лист клиентом пользователя (OAuth). Бросает WriteAccessError,
    если таблица недоступна этому клиенту."""
    spreadsheet = _open_spreadsheet_for_write(client, sheet_id)
    return _worksheet_or_first(spreadsheet, sheet_name)


def write_homework(
    client, sheet_id: str, sheet_name: str, target: date, subject: str, text: str, replace: bool
) -> bool:
    """Пишет ДЗ в ячейку (дата × предмет) от имени пользователя.

    * ячейка пуста ("-" тоже считается пустой) — просто записывает text;
    * иначе replace=True заменяет содержимое, replace=False дописывает text
      с новой строки (актуальное значение читается из таблицы, а не из кэша);
    * строки с такой датой нет — добавляется новая строка внизу
      (дата в формате ДД.ММ, как в /create_sheet, остальные ячейки "-").

    Запись с value_input_option=RAW, чтобы Sheets не превращал текст вроде
    "1/2" или "=A1" в даты/формулы. Возвращает True, если создана новая строка.
    Бросает WriteAccessError, LookupError (нет такого предмета в шапке).
    """
    worksheet = open_worksheet_for_write(client, sheet_id, sheet_name)
    try:
        rows = worksheet.get_all_values()
        if not rows:
            raise LookupError("лист пуст")
        header = rows[0]
        col = next(
            (i for i, h in enumerate(header) if i >= 1 and h.strip() == subject), None
        )
        if col is None:
            raise LookupError(f"предмет «{subject}» не найден в шапке таблицы")

        today = date.today()
        row_number = None
        existing = ""
        for number, row in enumerate(rows[1:], start=2):
            if row and row[0].strip() and parse_row_date(row[0], today) == target:
                row_number = number
                existing = row[col] if col < len(row) else ""
                break

        if row_number is None:
            new_row = [target.strftime("%d.%m")] + ["-"] * (len(header) - 1)
            new_row[col] = text
            worksheet.append_row(new_row, value_input_option="RAW")
            created = True
        else:
            if replace or is_empty_cell(existing):
                value = text
            else:
                value = existing.rstrip() + "\n" + text
            worksheet.update(
                range_name=gspread.utils.rowcol_to_a1(row_number, col + 1),
                values=[[value]],
                value_input_option="RAW",
            )
            created = False
    except gspread.exceptions.APIError as exc:
        if _api_status(exc) in (403, 404):
            raise WriteAccessError(str(exc)) from exc
        raise
    invalidate_cache(sheet_id, sheet_name)
    return created


def add_subject(client, sheet_id: str, sheet_name: str, name: str) -> int:
    """Добавляет предмет (столбец) в шапку таблицы от имени пользователя
    (OAuth) — шаг 5б. Пишет название в первую свободную (пустую) ячейку
    шапки после колонки "Дата", а если свободных нет — в следующую по
    счёту колонку. Затем перенакатывает оформление на весь лист (шапка,
    границы, подсветка контрольных/экзаменов и пустых ячеек — те же
    build_format_requests, что и в /create_sheet), заранее очистив старые
    conditional-format правила (чтобы не копились при повторных вызовах) и
    чередующуюся заливку (addBanding иначе падает с ошибкой поверх уже
    забандованного диапазона). В конце сбрасывает кэш таблицы.

    name должен быть уже непустым и очищенным (strip) вызывающим кодом.

    Бросает:
    * WriteAccessError — нет доступа на запись (обычно таблица из
      /connect_sheet, а не из /create_sheet);
    * DuplicateSubjectError — такой предмет уже есть (без учёта регистра);
    * SubjectLimitError — достигнут MAX_SUBJECTS.

    Возвращает индекс новой колонки (0 = колонка "Дата", 1 = первый предмет).
    """
    spreadsheet = _open_spreadsheet_for_write(client, sheet_id)
    worksheet = _worksheet_or_first(spreadsheet, sheet_name)

    try:
        rows = worksheet.get_all_values()
        header = rows[0] if rows else ["Дата"]
        existing = [h.strip() for h in header[1:] if h.strip()]

        if len(existing) >= MAX_SUBJECTS:
            raise SubjectLimitError(
                f"Достигнут лимит предметов в таблице ({MAX_SUBJECTS}). "
                "Освободите колонку в таблице вручную, чтобы добавить ещё один."
            )
        if any(e.lower() == name.lower() for e in existing):
            raise DuplicateSubjectError(f"Предмет «{name}» уже есть в таблице.")

        # Первая пустая ячейка шапки после колонки "Дата" (index 0), иначе —
        # новая колонка сразу за текущей последней.
        col = next(
            (i for i in range(1, len(header)) if not header[i].strip()), len(header)
        )
        if col >= worksheet.col_count:
            worksheet.add_cols(col + 1 - worksheet.col_count)

        worksheet.update(
            range_name=gspread.utils.rowcol_to_a1(1, col + 1),
            values=[[name]],
            value_input_option="RAW",
        )

        n_cols = max(col + 1, len(header))
        n_rows = max(len(rows), 1)
        clear_conditional_formats(spreadsheet, worksheet.id)
        clear_banded_ranges(spreadsheet, worksheet.id)
        format_worksheet(spreadsheet, worksheet, [""] * (n_cols - 1), n_rows)
    except gspread.exceptions.APIError as exc:
        if _api_status(exc) in (403, 404):
            raise WriteAccessError(str(exc)) from exc
        raise

    invalidate_cache(sheet_id, sheet_name)
    return col


def ensure_formatted(client, sheet_id: str, sheet_name: str) -> bool:
    """Проверяет, покрывает ли текущее оформление весь реальный размер
    таблицы, и докатывает его, если нет — например, если предмет или дата
    были дописаны руками прямо в Google Sheets, а не через бота (тогда
    шапка/границы/подсветка на новую колонку/строку не распространяются,
    см. документацию к шагу 6 в implementation-plan.md).

    Возвращает True, если оформление действительно перекатывалось.
    Бросает WriteAccessError, если у клиента нет доступа на запись (вызывающий
    код — bot/scheduler.py — эту ошибку ловит и просто пропускает таблицу).
    """
    spreadsheet = _open_spreadsheet_for_write(client, sheet_id)
    worksheet = _worksheet_or_first(spreadsheet, sheet_name)

    try:
        rows = worksheet.get_all_values()
        if not rows:
            return False
        header = rows[0]
        n_rows, n_cols = len(rows), len(header)

        formatted = get_formatted_dimensions(spreadsheet, worksheet.id)
        if formatted is not None and formatted[0] >= n_rows and formatted[1] >= n_cols:
            return False  # уже отформатировано минимум на весь текущий размер

        clear_conditional_formats(spreadsheet, worksheet.id)
        clear_banded_ranges(spreadsheet, worksheet.id)
        format_worksheet(spreadsheet, worksheet, [""] * (n_cols - 1), n_rows)
    except gspread.exceptions.APIError as exc:
        if _api_status(exc) in (403, 404):
            raise WriteAccessError(str(exc)) from exc
        raise

    invalidate_cache(sheet_id, sheet_name)
    return True


def get_service_account_email() -> Optional[str]:
    """Email сервис-аккаунта из credentials.json — на него /create_sheet
    (bot/handlers/sheet_creation.py) шарит новую таблицу, чтобы бот мог
    её читать так же, как и таблицы, подключённые через /connect_sheet."""
    try:
        with open(config.GOOGLE_CREDENTIALS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("client_email")
    except Exception:
        logger.exception(
            "Не удалось прочитать email сервис-аккаунта из %s", config.GOOGLE_CREDENTIALS_FILE
        )
        return None
