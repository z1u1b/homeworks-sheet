"""
Общая логика оформления листа с домашними заданиями: строит и накатывает
один и тот же набор Sheets API запросов независимо от того, кто её вызывает —
одноразовый CLI-скрипт format_sheet.py или команда бота /create_sheet
(автосоздание таблицы через OAuth пользователя). Раньше вся эта логика была
только внутри format_sheet.py; вынесена сюда, чтобы не копировать её.
"""

from datetime import date, timedelta
from typing import List, Optional, Tuple

EXAM_KEYWORDS = ("контрол", "экзамен", "зачет", "зачёт", "проверочн")

HEADER_BLUE = {"red": 0.16, "green": 0.32, "blue": 0.75}
LIGHT_BLUE = {"red": 0.90, "green": 0.93, "blue": 0.99}
BAND_BLUE = {"red": 0.96, "green": 0.97, "blue": 1.0}
WHITE = {"red": 1, "green": 1, "blue": 1}
GRAY_BORDER = {"red": 0.75, "green": 0.75, "blue": 0.75}
GRAY_TEXT = {"red": 0.65, "green": 0.65, "blue": 0.65}
RED_TEXT = {"red": 0.8, "green": 0.1, "blue": 0.1}


def fill_empty_worksheet(worksheet, subjects: List[str], days_ahead: int) -> int:
    """Пишет заголовок ("Дата" + предметы) и пустые строки на days_ahead дней
    вперёд. Вызывающий код сам решает, нужно ли это (обычно — только если
    лист ещё пустой). Возвращает итоговое количество строк с данными."""
    header = ["Дата"] + subjects
    today = date.today()
    rows = [header]
    for i in range(days_ahead):
        d = today + timedelta(days=i)
        rows.append([d.strftime("%d.%m")] + ["-"] * len(subjects))
    worksheet.update(range_name="A1", values=rows, value_input_option="RAW")
    return len(rows)


def build_format_requests(sheet_id: int, n_rows: int, n_cols: int) -> list:
    """Список Sheets API requests для батч-оформления листа: шапка, заливка,
    границы, перенос текста, подсветка контрольных/экзаменов и пустых ячеек.
    n_cols включает колонку с датой."""
    requests = [
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                    "startColumnIndex": 0, "endColumnIndex": n_cols,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": HEADER_BLUE,
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                        "textFormat": {"bold": True, "foregroundColor": WHITE, "fontSize": 11},
                        "wrapStrategy": "WRAP",
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,textFormat,wrapStrategy)",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": n_rows,
                    "startColumnIndex": 0, "endColumnIndex": 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": LIGHT_BLUE,
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                        "textFormat": {"bold": True},
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,horizontalAlignment,verticalAlignment,textFormat)",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": n_rows,
                    "startColumnIndex": 1, "endColumnIndex": n_cols,
                },
                "cell": {
                    "userEnteredFormat": {
                        "wrapStrategy": "WRAP",
                        "verticalAlignment": "TOP",
                        "textFormat": {"fontSize": 10},
                    }
                },
                "fields": "userEnteredFormat(wrapStrategy,verticalAlignment,textFormat)",
            }
        },
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": sheet_id,
                    "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 1},
                },
                "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 36},
                "fields": "pixelSize",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 1, "endIndex": n_rows},
                "properties": {"pixelSize": 56},
                "fields": "pixelSize",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": 90},
                "fields": "pixelSize",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 1, "endIndex": n_cols},
                "properties": {"pixelSize": 220},
                "fields": "pixelSize",
            }
        },
        {
            "addBanding": {
                "bandedRange": {
                    "range": {
                        "sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": n_rows,
                        "startColumnIndex": 0, "endColumnIndex": n_cols,
                    },
                    "rowProperties": {
                        "headerColor": HEADER_BLUE,
                        "firstBandColor": WHITE,
                        "secondBandColor": BAND_BLUE,
                    },
                }
            }
        },
        {
            "updateBorders": {
                "range": {
                    "sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": n_rows,
                    "startColumnIndex": 0, "endColumnIndex": n_cols,
                },
                "top": {"style": "SOLID", "width": 1, "color": GRAY_BORDER},
                "bottom": {"style": "SOLID", "width": 1, "color": GRAY_BORDER},
                "left": {"style": "SOLID", "width": 1, "color": GRAY_BORDER},
                "right": {"style": "SOLID", "width": 1, "color": GRAY_BORDER},
                "innerHorizontal": {"style": "SOLID", "width": 1, "color": GRAY_BORDER},
                "innerVertical": {"style": "SOLID", "width": 1, "color": GRAY_BORDER},
            }
        },
        {
            "updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "tabColor": HEADER_BLUE},
                "fields": "tabColor",
            }
        },
    ]

    task_range = {
        "sheetId": sheet_id,
        "startRowIndex": 1,
        "endRowIndex": n_rows,
        "startColumnIndex": 1,
        "endColumnIndex": n_cols,
    }

    for keyword in EXAM_KEYWORDS:
        requests.append({
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [task_range],
                    "booleanRule": {
                        "condition": {"type": "TEXT_CONTAINS", "values": [{"userEnteredValue": keyword}]},
                        "format": {"textFormat": {"bold": True, "foregroundColor": RED_TEXT}},
                    },
                },
                "index": 0,
            }
        })

    requests.append({
        "addConditionalFormatRule": {
            "rule": {
                "ranges": [task_range],
                "booleanRule": {
                    "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": "-"}]},
                    "format": {"textFormat": {"foregroundColor": GRAY_TEXT}},
                },
            },
            "index": 0,
        }
    })

    return requests


def format_worksheet(spreadsheet, worksheet, subjects: List[str], n_rows: int) -> None:
    """Накатывает build_format_requests на конкретный лист конкретной таблицы."""
    n_cols = 1 + len(subjects)
    requests = build_format_requests(worksheet.id, n_rows, n_cols)
    spreadsheet.batch_update({"requests": requests})


def get_formatted_dimensions(spreadsheet, worksheet_id: int) -> Optional[Tuple[int, int]]:
    """Возвращает (n_rows, n_cols), которые сейчас реально покрыты
    оформлением (по диапазону banded range — его ставит build_format_requests
    вместе со всем остальным, так что он же и есть маркер "докуда докатили
    формат в последний раз"). None, если лист никогда не форматировался.

    Используется для автоматической подгонки оформления (bot/sheets.py:
    ensure_formatted) — сравниваем с реальным размером данных и, если
    таблица выросла (руками добавили предмет/дату), перенакатываем формат.
    """
    metadata = spreadsheet.fetch_sheet_metadata()
    for sheet in metadata.get("sheets", []):
        if sheet.get("properties", {}).get("sheetId") == worksheet_id:
            bands = sheet.get("bandedRanges", [])
            if not bands:
                return None
            rng = bands[0]["range"]
            return rng.get("endRowIndex", 0), rng.get("endColumnIndex", 0)
    return None


def clear_banded_ranges(spreadsheet, worksheet_id: int) -> None:
    """Удаляет чередующуюся заливку (addBanding) листа перед повторным
    build_format_requests: Sheets API запрещает addBanding поверх диапазона,
    для которого чередование уже задано ("Нельзя задать чередующиеся цвета
    фона в диапазоне, в котором они уже определены") — так что при повторном
    форматировании уже оформленного листа (см. add_subject, шаг 5б) сначала
    нужно снять старую полосатую заливку через deleteBanding.
    """
    metadata = spreadsheet.fetch_sheet_metadata()
    banded_ids = []
    for sheet in metadata.get("sheets", []):
        if sheet.get("properties", {}).get("sheetId") == worksheet_id:
            banded_ids = [b["bandedRangeId"] for b in sheet.get("bandedRanges", [])]
            break
    if not banded_ids:
        return
    requests = [{"deleteBanding": {"bandedRangeId": bid}} for bid in banded_ids]
    spreadsheet.batch_update({"requests": requests})


def clear_conditional_formats(spreadsheet, worksheet_id: int) -> None:
    """Удаляет все conditional-format правила листа (подсветку контрольных/
    экзаменов и пустых ячеек из build_format_requests).

    Нужно перед повторным вызовом format_worksheet на уже оформленном листе:
    каждый вызов build_format_requests добавляет свой набор правил (index=0),
    не трогая существующие, так что при многократном переоформлении одного
    листа (например /add_subject, который может дёргать это при каждом
    добавлении предмета) правила будут копиться. format_sheet.py и
    /create_sheet форматируют лист один раз при создании, так что их это
    пока не касалось.
    """
    metadata = spreadsheet.fetch_sheet_metadata()
    n_rules = 0
    for sheet in metadata.get("sheets", []):
        if sheet.get("properties", {}).get("sheetId") == worksheet_id:
            n_rules = len(sheet.get("conditionalFormats", []))
            break
    if not n_rules:
        return
    # Каждое удаление сдвигает индексы оставшихся правил вниз, поэтому в
    # рамках одного batch_update просто N раз удаляем правило с index=0.
    requests = [
        {"deleteConditionalFormatRule": {"sheetId": worksheet_id, "index": 0}}
        for _ in range(n_rules)
    ]
    spreadsheet.batch_update({"requests": requests})
