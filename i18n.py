"""Строки EN/RU/UA, склонения, форматирование дат через QLocale языка приложения."""
from __future__ import annotations

from datetime import datetime
from typing import Callable, Union

from PyQt5.QtCore import QDate, QLocale, QTime

LANGS = ("en", "ru", "uk")
LANG_NAMES = {"en": "English", "ru": "Русский", "uk": "Українська"}

Val = Union[str, tuple]

EN: dict[str, Val] = {
    "app_title": "Reminders",
    "edit": "Edit", "done": "Mark as done",
    "nav_all": "All", "nav_today": "Today", "nav_overdue": "Overdue",
    "nav_categories": "Categories", "nav_history": "History", "nav_settings": "Settings",
    "search_ph": "Search", "new_reminder": "New reminder", "edit_reminder": "Edit reminder",
    "add_category": "New category",
    "empty_title": "No reminders", "empty_hint": "Press + to add one",
    "empty_search": "Nothing found", "empty_history": "History is empty",
    "n_reminders": ("{n} reminder", "{n} reminders"),
    "snoozed_until": "Snoozed until {when}",
    "snooze": "Snooze", "snooze_10": "10 minutes", "snooze_1h": "1 hour",
    "snooze_tomorrow": "Tomorrow, {time}", "plus_min": "+{n} min", "plus_hour": "+{n} h",
    "toast_more": "+{n} more",
    "d_today": "Today", "d_tomorrow": "Tomorrow", "d_yesterday": "Yesterday",
    "f_title": "Title", "f_desc": "Description", "f_category": "Category",
    "f_priority": "Priority", "f_repeat": "Repeat", "f_date": "Date", "f_time": "Time",
    "title_ph": "What to remind?", "desc_ph": "Notes (optional)",
    "category_ph": "Choose or type a new one", "no_category": "No category",
    "prio_normal": "Normal", "prio_high": "High",
    "repeat_once": "Does not repeat", "repeat_daily": "Daily", "repeat_weekly": "Weekly",
    "repeat_monthly": "Monthly", "repeat_yearly": "Yearly",
    "preset_today": "Today", "preset_tomorrow": "Tomorrow",
    "fires_now": "Will fire immediately", "title_required": "Enter a title",
    "save": "Save", "cancel": "Cancel", "ok": "OK", "delete": "Delete", "rename": "Rename",
    "cat_rename_title": "Rename category", "cat_name": "Category name",
    "confirm_title": "Confirm", "info_title": "Reminders",
    "confirm_delete_series": "Delete this reminder and all future repeats?",
    "confirm_clear_history": "Clear the entire history?",
    "confirm_delete_selected": "Permanently delete the selected entries?",
    "confirm_delete_category": "Delete category “{name}”? Its reminders will move to “No category”.",
    "deleted": "Reminder deleted", "undo": "Undo",
    "h_restore": "Restore", "h_delete_forever": "Delete permanently",
    "h_delete_selected": "Delete selected", "h_clear": "Clear history",
    "h_completed": "Completed {when}", "selected_n": "Selected: {n}",
    "sec_appearance": "Appearance", "sec_system": "System", "sec_history": "History",
    "set_language": "Language", "set_theme": "Theme", "theme_dark": "Dark", "theme_light": "Light",
    "set_autostart": "Start at login", "set_sound": "Notification sound",
    "set_shortcut": "Desktop shortcut", "shortcut_create": "Create", "shortcut_ok": "Shortcut created on the desktop.",
    "err_shortcut": "Could not create the desktop shortcut.",
    "set_cleanup": "Clean up history", "cleanup_never": "Never",
    "cleanup_days": ("after {n} day", "after {n} days"),
    "tray_open": "Open", "tray_new": "New reminder", "tray_quit": "Quit",
    "tray_hint_title": "Reminders", "tray_hint": "The app keeps running in the tray",
    "err_title": "Reminders — error",
    "err_not_writable": "Cannot write to the data folder:\n{path}\n\nMove the program to a folder you can write to.",
    "notice_recovered_backup": "The data file was damaged. The previous version was restored from the backup.",
    "notice_recovered_empty": "The data file was damaged and no backup was available. A new empty list was created.",
    "err_autostart": "Could not change the startup setting.",
    "f_early": "Remind early", "early_none": "No", "early_before": "{t} before",
    "early_toast": "In {t} — {when}", "f_silent": "No sound for this reminder", "early_chip": "{t} early",
    "unit_min": "min", "unit_hour": "h", "unit_day": "d",
    "sec_quiet": "Quiet mode", "set_quiet": "Quiet hours (normal priority only)",
    "set_quiet_from": "From", "set_quiet_to": "Until",
    "sec_data": "Data", "set_data": "Backup", "data_export": "Export…", "data_import": "Import…",
    "export_title": "Export reminders", "import_title": "Import reminders", "json_filter": "JSON files (*.json)",
    "export_ok": "Exported to file.", "err_export": "Could not write the file.",
    "import_ok": "Imported: {r} reminders, {h} history entries.",
    "import_none": "Nothing new to import.", "err_import": "This file is not a valid reminders export.",
    "set_db": "Database", "db_optimize": "Optimize",
    "db_optimize_ok": "Database optimized: {before} → {after}.", "err_optimize": "Could not optimize the database.",
}

RU: dict[str, Val] = {
    "app_title": "Reminders",
    "edit": "Редактировать", "done": "Выполнено",
    "nav_all": "Все", "nav_today": "Сегодня", "nav_overdue": "Просрочено",
    "nav_categories": "Категории", "nav_history": "История", "nav_settings": "Настройки",
    "search_ph": "Поиск", "new_reminder": "Новое напоминание", "edit_reminder": "Редактирование",
    "add_category": "Новая категория",
    "empty_title": "Нет напоминаний", "empty_hint": "Нажмите «+», чтобы добавить",
    "empty_search": "Ничего не найдено", "empty_history": "История пуста",
    "n_reminders": ("{n} напоминание", "{n} напоминания", "{n} напоминаний"),
    "snoozed_until": "Отложено до: {when}",
    "snooze": "Отложить", "snooze_10": "10 минут", "snooze_1h": "1 час",
    "snooze_tomorrow": "Завтра, {time}", "plus_min": "+{n} мин", "plus_hour": "+{n} ч",
    "toast_more": "+{n} ещё",
    "d_today": "Сегодня", "d_tomorrow": "Завтра", "d_yesterday": "Вчера",
    "f_title": "Название", "f_desc": "Описание", "f_category": "Категория",
    "f_priority": "Приоритет", "f_repeat": "Повтор", "f_date": "Дата", "f_time": "Время",
    "title_ph": "О чём напомнить?", "desc_ph": "Заметки (необязательно)",
    "category_ph": "Выберите или введите новую", "no_category": "Без категории",
    "prio_normal": "Обычный", "prio_high": "Высокий",
    "repeat_once": "Не повторять", "repeat_daily": "Ежедневно", "repeat_weekly": "Еженедельно",
    "repeat_monthly": "Ежемесячно", "repeat_yearly": "Ежегодно",
    "preset_today": "Сегодня", "preset_tomorrow": "Завтра",
    "fires_now": "Сработает сразу", "title_required": "Введите название",
    "save": "Сохранить", "cancel": "Отмена", "ok": "OK", "delete": "Удалить", "rename": "Переименовать",
    "cat_rename_title": "Переименовать категорию", "cat_name": "Название категории",
    "confirm_title": "Подтверждение", "info_title": "Напоминания",
    "confirm_delete_series": "Удалить напоминание и все будущие повторы?",
    "confirm_clear_history": "Очистить всю историю?",
    "confirm_delete_selected": "Удалить выбранные записи навсегда?",
    "confirm_delete_category": "Удалить категорию «{name}»? Её напоминания перейдут в «Без категории».",
    "deleted": "Напоминание удалено", "undo": "Отменить",
    "h_restore": "Вернуть", "h_delete_forever": "Удалить навсегда",
    "h_delete_selected": "Удалить выбранные", "h_clear": "Очистить историю",
    "h_completed": "Выполнено {when}", "selected_n": "Выбрано: {n}",
    "sec_appearance": "Оформление", "sec_system": "Система", "sec_history": "История",
    "set_language": "Язык", "set_theme": "Тема", "theme_dark": "Тёмная", "theme_light": "Светлая",
    "set_autostart": "Запускать при входе в систему", "set_sound": "Звук уведомлений",
    "set_shortcut": "Ярлык на рабочем столе", "shortcut_create": "Создать", "shortcut_ok": "Ярлык создан на рабочем столе.",
    "err_shortcut": "Не удалось создать ярлык на рабочем столе.",
    "set_cleanup": "Автоочистка истории", "cleanup_never": "Никогда",
    "cleanup_days": ("через {n} день", "через {n} дня", "через {n} дней"),
    "tray_open": "Открыть", "tray_new": "Новое напоминание", "tray_quit": "Выход",
    "tray_hint_title": "Напоминания", "tray_hint": "Приложение продолжает работать в трее",
    "err_title": "Напоминания — ошибка",
    "err_not_writable": "Не удаётся записать в папку данных:\n{path}\n\nПереместите программу в папку, где разрешена запись.",
    "notice_recovered_backup": "Файл данных был повреждён. Восстановлена предыдущая версия из резервной копии.",
    "notice_recovered_empty": "Файл данных был повреждён, резервной копии нет. Создан новый пустой список.",
    "err_autostart": "Не удалось изменить настройку автозапуска.",
    "f_early": "Напомнить заранее", "early_none": "Нет", "early_before": "за {t}",
    "early_toast": "Через {t} — {when}", "f_silent": "Без звука для этого напоминания", "early_chip": "заранее: {t}",
    "unit_min": "мин", "unit_hour": "ч", "unit_day": "дн",
    "sec_quiet": "Тихий режим", "set_quiet": "Тихие часы (только обычный приоритет)",
    "set_quiet_from": "С", "set_quiet_to": "До",
    "sec_data": "Данные", "set_data": "Резервная копия", "data_export": "Экспорт…", "data_import": "Импорт…",
    "export_title": "Экспорт напоминаний", "import_title": "Импорт напоминаний", "json_filter": "Файлы JSON (*.json)",
    "export_ok": "Экспортировано в файл.", "err_export": "Не удалось записать файл.",
    "import_ok": "Импортировано: напоминаний — {r}, записей истории — {h}.",
    "import_none": "Нового для импорта нет.", "err_import": "Этот файл не является экспортом напоминаний.",
    "set_db": "База данных", "db_optimize": "Оптимизировать",
    "db_optimize_ok": "База оптимизирована: {before} → {after}.", "err_optimize": "Не удалось оптимизировать базу данных.",
}

UK: dict[str, Val] = {
    "app_title": "Reminders",
    "edit": "Редагувати", "done": "Виконано",
    "nav_all": "Усі", "nav_today": "Сьогодні", "nav_overdue": "Прострочено",
    "nav_categories": "Категорії", "nav_history": "Історія", "nav_settings": "Налаштування",
    "search_ph": "Пошук", "new_reminder": "Нове нагадування", "edit_reminder": "Редагування",
    "add_category": "Нова категорія",
    "empty_title": "Немає нагадувань", "empty_hint": "Натисніть «+», щоб додати",
    "empty_search": "Нічого не знайдено", "empty_history": "Історія порожня",
    "n_reminders": ("{n} нагадування", "{n} нагадування", "{n} нагадувань"),
    "snoozed_until": "Відкладено до: {when}",
    "snooze": "Відкласти", "snooze_10": "10 хвилин", "snooze_1h": "1 година",
    "snooze_tomorrow": "Завтра, {time}", "plus_min": "+{n} хв", "plus_hour": "+{n} год",
    "toast_more": "+{n} ще",
    "d_today": "Сьогодні", "d_tomorrow": "Завтра", "d_yesterday": "Вчора",
    "f_title": "Назва", "f_desc": "Опис", "f_category": "Категорія",
    "f_priority": "Пріоритет", "f_repeat": "Повтор", "f_date": "Дата", "f_time": "Час",
    "title_ph": "Про що нагадати?", "desc_ph": "Нотатки (необов'язково)",
    "category_ph": "Виберіть або введіть нову", "no_category": "Без категорії",
    "prio_normal": "Звичайний", "prio_high": "Високий",
    "repeat_once": "Не повторювати", "repeat_daily": "Щодня", "repeat_weekly": "Щотижня",
    "repeat_monthly": "Щомісяця", "repeat_yearly": "Щороку",
    "preset_today": "Сьогодні", "preset_tomorrow": "Завтра",
    "fires_now": "Спрацює одразу", "title_required": "Введіть назву",
    "save": "Зберегти", "cancel": "Скасувати", "ok": "OK", "delete": "Видалити", "rename": "Перейменувати",
    "cat_rename_title": "Перейменувати категорію", "cat_name": "Назва категорії",
    "confirm_title": "Підтвердження", "info_title": "Нагадування",
    "confirm_delete_series": "Видалити нагадування та всі майбутні повтори?",
    "confirm_clear_history": "Очистити всю історію?",
    "confirm_delete_selected": "Видалити вибрані записи назавжди?",
    "confirm_delete_category": "Видалити категорію «{name}»? Її нагадування перейдуть до «Без категорії».",
    "deleted": "Нагадування видалено", "undo": "Скасувати",
    "h_restore": "Повернути", "h_delete_forever": "Видалити назавжди",
    "h_delete_selected": "Видалити вибрані", "h_clear": "Очистити історію",
    "h_completed": "Виконано {when}", "selected_n": "Вибрано: {n}",
    "sec_appearance": "Оформлення", "sec_system": "Система", "sec_history": "Історія",
    "set_language": "Мова", "set_theme": "Тема", "theme_dark": "Темна", "theme_light": "Світла",
    "set_autostart": "Запускати під час входу в систему", "set_sound": "Звук сповіщень",
    "set_shortcut": "Ярлик на робочому столі", "shortcut_create": "Створити", "shortcut_ok": "Ярлик створено на робочому столі.",
    "err_shortcut": "Не вдалося створити ярлик на робочому столі.",
    "set_cleanup": "Автоочищення історії", "cleanup_never": "Ніколи",
    "cleanup_days": ("через {n} день", "через {n} дні", "через {n} днів"),
    "tray_open": "Відкрити", "tray_new": "Нове нагадування", "tray_quit": "Вихід",
    "tray_hint_title": "Нагадування", "tray_hint": "Застосунок продовжує працювати в треї",
    "err_title": "Нагадування — помилка",
    "err_not_writable": "Не вдається записати в папку даних:\n{path}\n\nПеремістіть програму в папку, де дозволено запис.",
    "notice_recovered_backup": "Файл даних було пошкоджено. Відновлено попередню версію з резервної копії.",
    "notice_recovered_empty": "Файл даних було пошкоджено, резервної копії немає. Створено новий порожній список.",
    "err_autostart": "Не вдалося змінити налаштування автозапуску.",
    "f_early": "Нагадати заздалегідь", "early_none": "Ні", "early_before": "за {t}",
    "early_toast": "Через {t} — {when}", "f_silent": "Без звуку для цього нагадування", "early_chip": "заздалегідь: {t}",
    "unit_min": "хв", "unit_hour": "год", "unit_day": "дн",
    "sec_quiet": "Тихий режим", "set_quiet": "Тихі години (лише звичайний пріоритет)",
    "set_quiet_from": "З", "set_quiet_to": "До",
    "sec_data": "Дані", "set_data": "Резервна копія", "data_export": "Експорт…", "data_import": "Імпорт…",
    "export_title": "Експорт нагадувань", "import_title": "Імпорт нагадувань", "json_filter": "Файли JSON (*.json)",
    "export_ok": "Експортовано у файл.", "err_export": "Не вдалося записати файл.",
    "import_ok": "Імпортовано: нагадувань — {r}, записів історії — {h}.",
    "import_none": "Нового для імпорту немає.", "err_import": "Цей файл не є експортом нагадувань.",
    "set_db": "База даних", "db_optimize": "Оптимізувати",
    "db_optimize_ok": "Базу оптимізовано: {before} → {after}.", "err_optimize": "Не вдалося оптимізувати базу даних.",
}

_S = {"en": EN, "ru": RU, "uk": UK}
_lang = "en"
_subs: list[Callable[[], None]] = []


def missing_keys() -> dict[str, set[str]]:
    """Для самопроверки: ключи, которых нет в переводах."""
    return {lg: set(EN) ^ set(d) for lg, d in _S.items() if set(EN) != set(d)}


def set_language(lang: str) -> None:
    global _lang
    _lang = lang if lang in _S else "en"
    for cb in list(_subs):
        cb()


def language() -> str:
    return _lang


def subscribe(cb: Callable[[], None]) -> None:
    if cb not in _subs:
        _subs.append(cb)


def unsubscribe(cb: Callable[[], None]) -> None:
    if cb in _subs:
        _subs.remove(cb)


def lead_label(minutes: int) -> str:
    """«15 мин», «2 ч», «1 дн» — для «напомнить заранее»."""
    if minutes % 1440 == 0:
        return f"{minutes // 1440} {tr('unit_day')}"
    if minutes % 60 == 0:
        return f"{minutes // 60} {tr('unit_hour')}"
    return f"{minutes} {tr('unit_min')}"


def tr(key: str, **kw: object) -> str:
    v = _S[_lang].get(key, EN[key])
    assert isinstance(v, str), key
    return v.format(**kw) if kw else v


def plural_index(n: int, lang: str) -> int:
    if lang == "en":
        return 0 if n == 1 else 1
    if n % 10 == 1 and n % 100 != 11:
        return 0
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return 1
    return 2


def plural(key: str, n: int) -> str:
    forms = _S[_lang].get(key, EN[key])
    assert isinstance(forms, tuple), key
    return forms[plural_index(n, _lang)].format(n=n)


def repeat_label(kind: str) -> "str | None":
    """«Ежедневно» и т.п. для плашки в списке; None для однократных."""
    return None if kind == "once" else tr(f"repeat_{kind}")


# ---- Даты/время по локали ПРИЛОЖЕНИЯ (не системы) ----------------------------------------------
def qlocale() -> QLocale:
    return {"en": QLocale(QLocale.English, QLocale.UnitedStates),
            "ru": QLocale(QLocale.Russian, QLocale.Russia),
            "uk": QLocale(QLocale.Ukrainian, QLocale.Ukraine)}[_lang]


def fmt_time(dt: datetime) -> str:
    return qlocale().toString(QTime(dt.hour, dt.minute), QLocale.ShortFormat)


def fmt_date(dt: datetime, now: datetime) -> str:
    d = QDate(dt.year, dt.month, dt.day)
    return qlocale().toString(d, "d MMM" if dt.year == now.year else "d MMM yyyy")


def fmt_due(dt: datetime, now: datetime) -> str:
    delta = (dt.date() - now.date()).days
    label = {0: tr("d_today"), 1: tr("d_tomorrow"), -1: tr("d_yesterday")}.get(delta) or fmt_date(dt, now)
    return f"{label}, {fmt_time(dt)}"
