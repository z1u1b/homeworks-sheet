from datetime import date, timedelta
from typing import List, Optional

from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

# Тексты кнопок главного меню. Хендлеры в bot/handlers/common.py
# матчатся на эти же константы (F.text == BTN_...), чтобы текст был в одном месте.
BTN_TODAY = "📅 Сегодня"
BTN_TOMORROW = "📆 Завтра"
BTN_WEEK = "📋 Неделя"
BTN_ADD = "➕ Добавить ДЗ"
BTN_ADD_SUBJECT = "🆕 Новый предмет"
BTN_SUBJECT = "📚 По предмету"
BTN_STATS = "📊 Статистика"
BTN_SETTINGS = "⚙️ Настройки"
BTN_HELP = "❓ Помощь"

# Общий набор кнопок главного меню — используется хендлерами (bot/handlers/
# homework_add.py, bot/handlers/subject_manage.py), чтобы отличить кнопку
# меню от обычного текстового ввода внутри диалогов (FSM).
MENU_BUTTONS = {
    BTN_TODAY, BTN_TOMORROW, BTN_WEEK, BTN_ADD, BTN_ADD_SUBJECT,
    BTN_SUBJECT, BTN_STATS, BTN_SETTINGS, BTN_HELP,
}

COMMON_TIMES = ["07:00", "08:00", "18:00", "19:00", "20:00", "21:00", "22:00"]

# Варианты "за сколько часов до дедлайна напоминать" в /settings.
DEADLINE_HOUR_OPTIONS = [1, 2, 3, 6, 12, 24]

COMMON_TIMEZONES = [
    ("Калининград", "Europe/Kaliningrad"),
    ("Москва", "Europe/Moscow"),
    ("Самара", "Europe/Samara"),
    ("Екатеринбург", "Asia/Yekaterinburg"),
    ("Омск", "Asia/Omsk"),
    ("Новосибирск", "Asia/Novosibirsk"),
    ("Красноярск", "Asia/Krasnoyarsk"),
    ("Иркутск", "Asia/Irkutsk"),
    ("Якутск", "Asia/Yakutsk"),
    ("Владивосток", "Asia/Vladivostok"),
]


def settings_keyboard(
    notify_enabled: bool, deadline_reminder_enabled: bool = False, deadline_reminder_hours: int = 3
) -> InlineKeyboardMarkup:
    times_builder = InlineKeyboardBuilder()
    for t in COMMON_TIMES:
        times_builder.button(text=t, callback_data=f"settime:{t}")
    times_builder.adjust(4)

    tz_builder = InlineKeyboardBuilder()
    for name, tz in COMMON_TIMEZONES:
        tz_builder.button(text=name, callback_data=f"settz:{tz}")
    tz_builder.adjust(2)

    toggle_builder = InlineKeyboardBuilder()
    toggle_text = "🔕 Выключить уведомления" if notify_enabled else "🔔 Включить уведомления"
    toggle_builder.button(text=toggle_text, callback_data="togglenotify")
    toggle_builder.adjust(1)

    # Напоминания по дедлайну (тег [ЧЧ:ММ] в тексте ДЗ) — отдельный,
    # выключенный по умолчанию переключатель + выбор "за сколько часов".
    deadline_toggle_builder = InlineKeyboardBuilder()
    deadline_toggle_text = (
        "🔕 Выключить напоминания о дедлайнах" if deadline_reminder_enabled
        else "⏰ Включить напоминания о дедлайнах"
    )
    deadline_toggle_builder.button(text=deadline_toggle_text, callback_data="toggledeadline")
    deadline_toggle_builder.adjust(1)

    deadline_hours_builder = InlineKeyboardBuilder()
    for h in DEADLINE_HOUR_OPTIONS:
        prefix = "✅ " if h == deadline_reminder_hours else ""
        deadline_hours_builder.button(text=f"{prefix}{h} ч", callback_data=f"deadlinehours:{h}")
    deadline_hours_builder.adjust(3)

    builder = InlineKeyboardBuilder()
    builder.attach(times_builder)
    builder.attach(tz_builder)
    builder.attach(toggle_builder)
    builder.attach(deadline_toggle_builder)
    builder.attach(deadline_hours_builder)
    return builder.as_markup()


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Постоянная reply-клавиатура главного меню (3 + 3 + 3 кнопки)."""
    builder = ReplyKeyboardBuilder()
    for text in (
        BTN_TODAY, BTN_TOMORROW, BTN_WEEK,
        BTN_ADD, BTN_ADD_SUBJECT, BTN_SUBJECT,
        BTN_STATS, BTN_SETTINGS, BTN_HELP,
    ):
        builder.button(text=text)
    builder.adjust(3, 3, 3)
    return builder.as_markup(resize_keyboard=True, is_persistent=True)


def subjects_keyboard(subjects: List[str]) -> InlineKeyboardMarkup:
    """Сетка предметов (по 2 в ряд). callback_data — индекс предмета в шапке
    таблицы (названия могут быть длинными, а лимит callback_data — 64 байта)."""
    builder = InlineKeyboardBuilder()
    for i, name in enumerate(subjects):
        builder.button(text=name, callback_data=f"hw:s:{i}:0")
    builder.adjust(2)
    return builder.as_markup()


def card_keyboard(
    mode: str,
    arg: str,
    idx: int,
    total: int,
    toggle: Optional[str] = None,
    done: bool = False,
) -> Optional[InlineKeyboardMarkup]:
    """Кнопки пагинации карточки ДЗ: ◀️ [i/N] ▶️ (по кругу).

    callback_data: `hw:<mode>:<arg>:<idx>`. Режим "d" — один день, "w" —
    7 дней, arg = дата начала YYYY-MM-DD; режим "s" — ДЗ по предмету,
    arg = индекс предмета в шапке таблицы. idx — индекс карточки.
    Состояние нигде не хранится: при нажатии список карточек пересобирается
    из таблицы (она в кэше). В режиме "s" добавляется кнопка возврата к
    списку предметов (`hw:subj`).

    toggle — "<ISO-дата>:<индекс предмета>" текущей карточки; если задан,
    сверху добавляется кнопка «✅ Сделано» / «↩️ Отменить отметку»
    (`hw:t:<toggle>:<mode>:<arg>:<idx>`). Дата и предмет зашиты в callback,
    чтобы при смене данных в таблице отметка не попала на другую карточку.
    """
    builder = InlineKeyboardBuilder()
    rows = []
    if toggle is not None:
        label = "↩️ Отменить отметку" if done else "✅ Сделано"
        builder.button(text=label, callback_data=f"hw:t:{toggle}:{mode}:{arg}:{idx}")
        rows.append(1)
    if total > 1:
        builder.button(text="◀️", callback_data=f"hw:{mode}:{arg}:{(idx - 1) % total}")
        builder.button(text=f"{idx + 1} / {total}", callback_data="hw:noop")
        builder.button(text="▶️", callback_data=f"hw:{mode}:{arg}:{(idx + 1) % total}")
        rows.append(3)
    if mode == "s":
        builder.button(text="🔙 К предметам", callback_data="hw:subj")
        rows.append(1)
    if not rows:
        return None
    builder.adjust(*rows)
    return builder.as_markup()


# --- Диалог «➕ Добавить ДЗ» (bot/handlers/homework_add.py) ---
# callback_data: add:s:<idx предмета> / add:d:<ISO-дата> / add:ok|append|replace / add:cancel

_WD_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
ADD_CALENDAR_DAYS = 14


def add_subjects_keyboard(subjects: List[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for i, name in enumerate(subjects):
        builder.button(text=name, callback_data=f"add:s:{i}")
    builder.adjust(2)

    extra = InlineKeyboardBuilder()
    extra.button(text="➕ Новый предмет", callback_data="add:newsubj")
    extra.button(text="❌ Отмена", callback_data="add:cancel")
    extra.adjust(1, 1)
    builder.attach(extra)
    return builder.as_markup()


def add_dates_keyboard(today: date) -> InlineKeyboardMarkup:
    """Быстрые кнопки (завтра / ближайший понедельник) + календарь на 2 недели."""
    tomorrow = today + timedelta(days=1)
    monday = today + timedelta(days=7 - today.weekday())  # ближайший будущий понедельник

    quick = InlineKeyboardBuilder()
    quick.button(text=f"Завтра ({tomorrow.strftime('%d.%m')})", callback_data=f"add:d:{tomorrow.isoformat()}")
    if monday != tomorrow:
        quick.button(text=f"Понедельник ({monday.strftime('%d.%m')})", callback_data=f"add:d:{monday.isoformat()}")
    quick.adjust(2)

    grid = InlineKeyboardBuilder()
    for i in range(ADD_CALENDAR_DAYS):
        d = today + timedelta(days=i)
        grid.button(text=f"{_WD_SHORT[d.weekday()]} {d.strftime('%d.%m')}", callback_data=f"add:d:{d.isoformat()}")
    grid.adjust(4)

    cancel = InlineKeyboardBuilder()
    cancel.button(text="❌ Отмена", callback_data="add:cancel")

    builder = InlineKeyboardBuilder()
    builder.attach(quick)
    builder.attach(grid)
    builder.attach(cancel)
    return builder.as_markup()


def add_confirm_keyboard(occupied: bool) -> InlineKeyboardMarkup:
    """Если ячейка уже занята — выбор «дописать / заменить», иначе «сохранить»."""
    builder = InlineKeyboardBuilder()
    if occupied:
        builder.button(text="➕ Дописать", callback_data="add:append")
        builder.button(text="✏️ Заменить", callback_data="add:replace")
    else:
        builder.button(text="💾 Сохранить", callback_data="add:ok")
    builder.button(text="❌ Отмена", callback_data="add:cancel")
    builder.adjust(2 if occupied else 1, 1)
    return builder.as_markup()
