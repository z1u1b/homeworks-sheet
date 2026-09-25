import re
from datetime import date, datetime, time, timedelta
from html import escape

URL_RE = re.compile(r"(https?://[^\s,]+)")
EMPTY_VALUES = {"", "-", "--", "—", "n/a"}

# Дедлайн внутри дня задаётся тегом [ЧЧ:ММ] прямо в тексте ячейки,
# например "Сделать презентацию [18:00]". Отдельного поля/колонки для
# времени нет — так формат остаётся простым и удобным для ручного редактирования.
DEADLINE_TAG_RE = re.compile(r"\[(\d{1,2}):(\d{2})\]")

WEEKDAYS_RU = [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
]


def is_empty_cell(value: str) -> bool:
    return value.strip().lower() in EMPTY_VALUES


def parse_row_date(raw: str, today: date):
    """Парсит дату из первой колонки таблицы.

    Поддерживает форматы ДД.ММ.ГГГГ, ДД.ММ.ГГ и ДД.ММ (год подбирается
    ближайший к сегодняшней дате, чтобы корректно обрабатывать переход
    через Новый год).
    """
    raw = raw.strip()
    if not raw:
        return None

    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    parts = raw.split(".")
    if len(parts) < 2:
        return None
    try:
        day, month = int(parts[0]), int(parts[1])
    except ValueError:
        return None

    best = None
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if best is None or abs((candidate - today).days) < abs((best - today).days):
            best = candidate
    return best


def parse_deadline_time(text: str):
    """Ищет тег [ЧЧ:ММ] в тексте ячейки (шаг 6) и возвращает datetime.time
    первого валидного совпадения, иначе None. Невалидные часы/минуты
    (например [25:00]) пропускаются — ищем дальше по тексту."""
    for match in DEADLINE_TAG_RE.finditer(text):
        hour, minute = int(match.group(1)), int(match.group(2))
        if 0 <= hour < 24 and 0 <= minute < 60:
            return time(hour, minute)
    return None


def cell_to_html(text: str) -> str:
    """Экранирует текст ячейки и превращает ссылки в кликабельные HTML-ссылки."""
    parts = URL_RE.split(text)
    out = []
    for part in parts:
        if URL_RE.fullmatch(part or ""):
            out.append(f'<a href="{escape(part)}">{escape(part)}</a>')
        else:
            out.append(escape(part))
    return "".join(out)


def format_date_ru(d: date) -> str:
    return f"{WEEKDAYS_RU[d.weekday()]}, {d.strftime('%d.%m')}"


def daterange(start: date, days: int):
    for i in range(days):
        yield start + timedelta(days=i)
