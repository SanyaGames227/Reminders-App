"""Чистая логика напоминалки: модели, повторы, выполнение, откладывание, удаление.

Модуль не зависит от Qt и ввода-вывода. Время — «плавающее» локальное (naive datetime).
Функции, меняющие данные, ничего не сохраняют: сохранение делает вызывающий код.
"""
from __future__ import annotations

import calendar
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any, Iterable, Optional

# ---- Константы (единый источник правды) -------------------------------------------------
ONCE, DAILY, WEEKLY, MONTHLY, YEARLY = "once", "daily", "weekly", "monthly", "yearly"
REPEATS = (ONCE, DAILY, WEEKLY, MONTHLY, YEARLY)
NORMAL, HIGH = "normal", "high"
SCHEDULED, ALERTING, ACKNOWLEDGED = "scheduled", "alerting", "acknowledged"

SNOOZE_DISMISS = timedelta(minutes=5)   # «✕» на уведомлении
SNOOZE_SHORT = timedelta(minutes=10)
SNOOZE_LONG = timedelta(hours=1)
TOMORROW_HOUR = 9                       # «завтра 09:00»
UNDO_MS = 5000                          # время полосы «Отменить»
MANUAL, BY_TITLE, BY_DUE = "manual", "title", "due"   # режимы сортировки списка
SORTS = (MANUAL, BY_TITLE, BY_DUE)
HISTORY_KEEP_CHOICES = (0, 30, 90)      # 0 = никогда не очищать
WEEK_MIN, MONTH_MIN = 7 * 1440, 30 * 1440            # «за неделю», «за месяц» (30 дней), в минутах
EARLY_CHOICES = (0, 5, 10, 15, 30, 60, 120, 1440, WEEK_MIN, MONTH_MIN)   # «напомнить заранее», минуты; 0 = выключено
EXPORT_FORMAT = "reminders-export"
APP_VERSION = "1.0.2"
GITHUB_URL = "https://github.com/SanyaGames227/Reminders-App"
RELEASES_URL = GITHUB_URL + "/releases"
RELEASES_API = "https://api.github.com/repos/SanyaGames227/Reminders-App/releases/latest"

# Фильтры списка: (вид, аргумент)
F_ALL, F_TODAY, F_OVERDUE, F_CATEGORY = "all", "today", "overdue", "category"
Filter = tuple[str, Optional[str]]


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat(timespec="seconds") if dt else None


def parse_iso(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None


def now_local() -> datetime:
    return datetime.now().replace(microsecond=0)


def next_full_hour(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


def week_morning(now: datetime) -> datetime:
    """«На неделю»: ровно через 7 дней в то же утреннее время, что и «завтра»."""
    return (now + timedelta(days=7)).replace(hour=TOMORROW_HOUR, minute=0, second=0, microsecond=0)


def tomorrow_morning(now: datetime) -> datetime:
    return (now + timedelta(days=1)).replace(hour=TOMORROW_HOUR, minute=0, second=0, microsecond=0)


# ---- Модели ----------------------------------------------------------------------------
@dataclass
class Reminder:
    title: str
    anchor: datetime
    due: datetime
    description: str = ""
    category: Optional[str] = None
    priority: str = NORMAL
    repeat: str = ONCE
    snoozed_until: Optional[datetime] = None
    state: str = SCHEDULED
    order: int = 0
    cat_order: int = 0                   # ручной порядок внутри категории (независим от общего списка)
    silent: bool = False                 # без звука
    early_min: int = 0                   # за сколько минут предупредить (0 — не надо)
    pre_sent: Optional[str] = None       # due, для которого предупреждение уже показано
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @classmethod
    def create(cls, title: str, due: datetime, **kw: Any) -> "Reminder":
        return cls(title=title, anchor=due, due=due, **kw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "description": self.description,
            "category": self.category, "priority": self.priority,
            "anchor": iso(self.anchor), "due": iso(self.due), "repeat": self.repeat,
            "snoozed_until": iso(self.snoozed_until), "state": self.state, "order": self.order,
            "cat_order": self.cat_order,
            "silent": self.silent, "early_min": self.early_min, "pre_sent": self.pre_sent,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Reminder":
        due = parse_iso(d["due"])
        assert due is not None
        return cls(
            id=d["id"], title=d["title"], description=d.get("description", ""),
            category=d.get("category") or None,
            priority=d.get("priority", NORMAL) if d.get("priority") in (NORMAL, HIGH) else NORMAL,
            anchor=parse_iso(d.get("anchor")) or due, due=due,
            repeat=d.get("repeat", ONCE) if d.get("repeat") in REPEATS else ONCE,
            snoozed_until=parse_iso(d.get("snoozed_until")),
            state=d.get("state", SCHEDULED) if d.get("state") in (SCHEDULED, ALERTING, ACKNOWLEDGED) else SCHEDULED,
            order=int(d.get("order", 0)), cat_order=int(d.get("cat_order", 0)),
            silent=bool(d.get("silent", False)),
            early_min=_early(d.get("early_min", 0)),
            pre_sent=d.get("pre_sent") or None,
        )


def _early(v: Any) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return 0
    return n if 0 < n <= MONTH_MIN else 0


@dataclass
class HistoryItem:
    title: str
    category: Optional[str]
    priority: str
    due: datetime
    completed_at: datetime
    repeat: str            # вид повтора серии (ONCE — запись была однократной)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "category": self.category,
            "priority": self.priority, "due": iso(self.due),
            "completed_at": iso(self.completed_at), "repeat": self.repeat,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HistoryItem":
        due, done = parse_iso(d["due"]), parse_iso(d["completed_at"])
        assert due is not None and done is not None
        return cls(id=d["id"], title=d["title"], category=d.get("category") or None,
                   priority=d.get("priority", NORMAL), due=due, completed_at=done,
                   repeat=d.get("repeat") if d.get("repeat") in REPEATS else ONCE)


@dataclass
class Data:
    reminders: list[Reminder] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    history: list[HistoryItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"reminders": [r.to_dict() for r in self.reminders], "categories": list(self.categories),
                "history": [h.to_dict() for h in self.history]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Data":
        data = cls(
            reminders=[Reminder.from_dict(x) for x in d.get("reminders", [])],
            categories=[str(c) for c in d.get("categories", [])],
            history=[HistoryItem.from_dict(x) for x in d.get("history", [])],
        )
        data.reminders.sort(key=lambda r: r.order)
        _renumber(data)
        _renumber_cat(data)
        for r in data.reminders:
            ensure_category(data, r.category)
        return data

    def get(self, rid: str) -> Optional[Reminder]:
        return next((r for r in self.reminders if r.id == rid), None)


def _renumber(data: Data) -> None:
    for i, r in enumerate(data.reminders):
        r.order = i


def _renumber_cat(data: Data) -> None:
    """Порядок внутри каждой категории: 0..n-1 (при равенстве — по общему порядку)."""
    groups: dict[Optional[str], list[Reminder]] = {}
    for r in sorted(data.reminders, key=lambda r: (r.cat_order, r.order)):
        groups.setdefault(r.category, []).append(r)
    for rs in groups.values():
        for i, r in enumerate(rs):
            r.cat_order = i


def _next_cat_order(data: Data, name: Optional[str]) -> int:
    return max((r.cat_order for r in data.reminders if r.category == name), default=-1) + 1


def ensure_category(data: Data, name: Optional[str]) -> None:
    if name and name not in data.categories:
        data.categories.append(name)


# ---- Повторы ---------------------------------------------------------------------------
def _occurrence(anchor: datetime, repeat: str, n: int) -> datetime:
    """n-е срабатывание серии, считая строго от якоря (без накопления дрейфа)."""
    d = anchor.date()
    if repeat == DAILY:
        nd = d + timedelta(days=n)
    elif repeat == WEEKLY:
        nd = d + timedelta(weeks=n)
    elif repeat == MONTHLY:
        y, m0 = divmod(d.year * 12 + d.month - 1 + n, 12)
        nd = d.replace(year=y, month=m0 + 1, day=min(d.day, calendar.monthrange(y, m0 + 1)[1]))
    elif repeat == YEARLY:
        y = d.year + n
        nd = d.replace(year=y, day=min(d.day, calendar.monthrange(y, d.month)[1]))
    else:
        return anchor
    return datetime.combine(nd, anchor.time())


def _estimate_index(anchor: datetime, repeat: str, after: datetime) -> int:
    days = (after.date() - anchor.date()).days
    if repeat == DAILY:
        return days
    if repeat == WEEKLY:
        return days // 7
    if repeat == MONTHLY:
        return (after.year - anchor.year) * 12 + after.month - anchor.month
    return after.year - anchor.year  # YEARLY


def next_occurrence(r: Reminder, after: datetime) -> datetime:
    """Первое срабатывание серии строго после `after`. Для однократного — его due."""
    if r.repeat == ONCE:
        return r.due
    if after < r.anchor:
        return r.anchor
    n = max(0, _estimate_index(r.anchor, r.repeat, after) - 1)
    while True:
        occ = _occurrence(r.anchor, r.repeat, n)
        if occ > after:
            return occ
        n += 1


# ---- Состояния и срабатывание ------------------------------------------------------------
def effective_time(r: Reminder) -> datetime:
    return r.snoozed_until or r.due


def fire_due(data: Data, now: datetime) -> list[Reminder]:
    """Переводит наступившие scheduled → alerting. Возвращает только свежесработавшие."""
    fired = []
    for r in data.reminders:
        if r.state == SCHEDULED and effective_time(r) <= now:
            r.state, r.snoozed_until = ALERTING, None
            fired.append(r)
    return fired


def pending_alerts(data: Data, now: datetime) -> list[Reminder]:
    """Для старта программы: все alerting, наступившие scheduled и просроченные, но не выполненные
    (acknowledged) — одной пачкой, в порядке списка. Во время работы acknowledged не напоминает."""
    fire_due(data, now)
    for r in data.reminders:
        if r.state == ACKNOWLEDGED and r.due < now:
            r.state = ALERTING
    return [r for r in data.reminders if r.state == ALERTING]


def acknowledge(r: Reminder) -> None:
    r.state = ACKNOWLEDGED


def window_start(r: Reminder) -> datetime:
    """Момент, с которого напоминанием уже «можно заниматься»: «заранее» (если включено) или сам срок."""
    return r.due - timedelta(minutes=r.early_min)


def can_snooze(r: Reminder, until: datetime, now: datetime) -> bool:
    """Откладывать можно, только когда подошло время напоминания либо его «заранее»-окно,
    и только на время позже самого срока (откладка внутри окна «заранее» на более раннее время бессмысленна)."""
    if now < window_start(r):
        return False
    return now >= r.due or until > r.due


def snooze(r: Reminder, until: datetime, now: Optional[datetime] = None) -> bool:
    """Единая функция откладывания: due не меняется. False — откладывать пока нельзя (ничего не изменено)."""
    if not can_snooze(r, until, now or now_local()):
        return False
    r.snoozed_until, r.state = until, SCHEDULED
    return True


def shown_snooze(r: Reminder, now: datetime) -> Optional[datetime]:
    return r.snoozed_until if r.snoozed_until and r.snoozed_until > now else None


def is_overdue(r: Reminder, now: datetime) -> bool:
    """Просрочено: срок прошёл, и напоминание сейчас не отложено."""
    return r.due < now and shown_snooze(r, now) is None


# ---- Предупреждение заранее и тихий режим -------------------------------------------------
def _pre_key(r: Reminder) -> str:
    return iso(r.due) or ""


def _in_early_window(r: Reminder, now: datetime) -> bool:
    return (r.state == SCHEDULED and r.snoozed_until is None and r.early_min > 0
            and r.due - timedelta(minutes=r.early_min) <= now < r.due)


def pending_early(r: Reminder, now: datetime) -> bool:
    """«Скоро» показано, но пользователь его ещё не закрыл, и окно всё ещё идёт."""
    return _in_early_window(r, now) and r.pre_sent == _pre_key(r)


def due_early(data: Data, now: datetime, include_unseen: bool = False) -> list[Reminder]:
    """Напоминания, для которых пора показать «скоро». Каждое срабатывание серии — один раз.
    pre_sent: «<due>» — показано, «<due>!» — пользователь закрыл/открыл уведомление.
    include_unseen (старт программы, как pending_alerts): повторно вернуть показанные, но не закрытые."""
    out = []
    for r in data.reminders:
        if not _in_early_window(r, now):
            continue
        key = _pre_key(r)
        if r.pre_sent == key + "!" or (r.pre_sent == key and not include_unseen):
            continue
        r.pre_sent = key
        out.append(r)
    return out


def ack_early(r: Reminder) -> bool:
    """Пользователь закрыл «скоро» — на старте больше не повторять. True, если что-то изменилось."""
    if r.pre_sent == _pre_key(r):
        r.pre_sent += "!"
        return True
    return False


def parse_hhmm(s: Any, default: time) -> time:
    try:
        h, m = str(s).split(":")
        return time(int(h), int(m))
    except (ValueError, TypeError):
        return default


def in_quiet(now: datetime, start: time, end: time) -> bool:
    """Тихие часы [start, end); интервал может переходить через полночь. start == end — выключено."""
    t = now.time().replace(second=0, microsecond=0)
    if start == end:
        return False
    return start <= t < end if start < end else (t >= start or t < end)


# ---- Обновления -------------------------------------------------------------------------
@dataclass
class Release:
    tag: str          # как на GitHub, например «v1.1.0»
    version: str      # для показа, без «v»: «1.1.0»
    notes: str        # список изменений (Markdown), может быть пустым


def parse_version(s: Any) -> tuple[int, ...]:
    """«v1.2.3», «1.2.3-beta» → (1, 2, 3). Суффиксы после числовой части игнорируются; нет цифр → ()."""
    m = re.match(r"\s*[vV]?(\d+(?:\.\d+)*)", str(s))
    return tuple(int(x) for x in m[1].split(".")) if m else ()


def is_newer(remote: Any, local: Any) -> bool:
    """Версия `remote` строго новее `local` (1.0 и 1.0.0 равны). Непонятная версия — не новее."""
    a, b = parse_version(remote), parse_version(local)
    if not a or not b:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def parse_release(payload: Any) -> Release:
    """Ответ GitHub API (releases/latest) → Release. Бросает ValueError, если это не релиз.
    Черновики и пре-релизы не считаются обновлением."""
    if not isinstance(payload, dict) or not isinstance(payload.get("tag_name"), str) \
            or not parse_version(payload["tag_name"]):
        raise ValueError("not a release")
    if payload.get("draft") or payload.get("prerelease"):
        raise ValueError("not a stable release")
    tag = payload["tag_name"].strip()
    notes = payload.get("body") if isinstance(payload.get("body"), str) else ""
    # автогенерируемая строка со ссылкой «Full Changelog» в окне не нужна
    lines = [ln for ln in notes.replace("\r\n", "\n").split("\n") if not ln.lstrip("*_ ").lower().startswith("full changelog")]
    return Release(tag=tag, version=tag.lstrip("vV"), notes="\n".join(lines).strip())


# ---- Экспорт / импорт ---------------------------------------------------------------------
def export_payload(data: Data, now: datetime) -> dict[str, Any]:
    return {"format": EXPORT_FORMAT, "version": 1, "exported": iso(now), **data.to_dict()}


def merge_import(data: Data, payload: Any) -> tuple[int, int]:
    """Добавляет из payload то, чего ещё нет (по id). Возвращает (напоминаний, записей истории).
    Повреждённые элементы пропускаются; бросает ValueError, если это не наш файл."""
    if not isinstance(payload, dict) or not isinstance(payload.get("reminders", []), list) \
            or not isinstance(payload.get("history", []), list) or not (
            "reminders" in payload or "history" in payload):
        raise ValueError("not a reminders export")
    have_r, have_h = {r.id for r in data.reminders}, {h.id for h in data.history}
    n_r = n_h = 0
    for raw in payload.get("reminders", []):
        try:
            r = Reminder.from_dict(raw)
        except (KeyError, TypeError, ValueError, AssertionError, AttributeError):
            continue
        if r.id in have_r:
            continue
        r.state, r.snoozed_until = SCHEDULED, None       # просроченные сработают сразу
        add_reminder(data, r); have_r.add(r.id); n_r += 1
    for raw in payload.get("history", []):
        try:
            h = HistoryItem.from_dict(raw)
        except (KeyError, TypeError, ValueError, AssertionError, AttributeError):
            continue
        if h.id not in have_h:
            data.history.append(h); have_h.add(h.id); n_h += 1
    for c in payload.get("categories", []):
        if isinstance(c, str) and c.strip():
            ensure_category(data, c.strip())
    return n_r, n_h


# ---- Выполнено / удаление / правка -------------------------------------------------------
def can_complete(r: Reminder, now: datetime) -> bool:
    """Однократное — всегда; повторяющееся — когда подошёл срок или начало «заранее»-окна."""
    return r.repeat == ONCE or window_start(r) <= now


def complete(data: Data, r: Reminder, now: datetime) -> Optional[HistoryItem]:
    if not can_complete(r, now):
        return None
    item = HistoryItem(r.title, r.category, r.priority, r.due, now, r.repeat)
    data.history.append(item)
    if r.repeat == ONCE:
        data.reminders.remove(r)
        _renumber(data)
    else:
        r.due, r.snoozed_until, r.state = next_occurrence(r, max(now, r.due)), None, SCHEDULED   # выполнили до срока — следующее, а не это же
    return item


def add_reminder(data: Data, r: Reminder) -> None:
    r.order = len(data.reminders)
    r.cat_order = _next_cat_order(data, r.category)
    data.reminders.append(r)
    ensure_category(data, r.category)


def delete_reminder(data: Data, r: Reminder) -> int:
    """Возвращает прежний индекс — для «Отменить»."""
    idx = data.reminders.index(r)
    data.reminders.remove(r)
    _renumber(data)
    return idx


def undo_delete(data: Data, r: Reminder, index: int) -> None:
    data.reminders.insert(min(index, len(data.reminders)), r)
    _renumber(data)


def apply_edit(data: Data, r: Reminder, *, title: str, description: str, category: Optional[str],
               priority: str, repeat: str, due: datetime, silent: bool = False, early_min: int = 0) -> None:
    if (category or None) != r.category:
        r.cat_order = _next_cat_order(data, category or None)     # при смене категории — в её конец
    r.title, r.description, r.category, r.priority = title, description, category or None, priority
    r.silent = silent
    ensure_category(data, r.category)
    if due != r.due or repeat != r.repeat:
        r.repeat, r.anchor, r.due = repeat, due, due
        r.state, r.snoozed_until, r.pre_sent = SCHEDULED, None, None
    if early_min != r.early_min:
        r.early_min, r.pre_sent = early_min, None


# ---- Список: фильтры, поиск, порядок -----------------------------------------------------
def matches(r: Reminder, flt: Filter, now: datetime) -> bool:
    kind, arg = flt
    if kind == F_TODAY:
        return r.due.date() == now.date()
    if kind == F_OVERDUE:
        return is_overdue(r, now)
    if kind == F_CATEGORY:
        return r.category == arg
    return True


def sort_reminders(items: list[Reminder], mode: str, in_category: bool = False) -> list[Reminder]:
    """Ручной порядок: общий (order) или внутри категории (cat_order); остальное — по названию / ближайшей дате."""
    if mode == BY_TITLE:
        return sorted(items, key=lambda r: (r.title.casefold(), r.order))
    if mode == BY_DUE:
        return sorted(items, key=lambda r: (effective_time(r), r.order))
    return sorted(items, key=lambda r: (r.cat_order if in_category else r.order, r.order))


def visible(data: Data, flt: Filter, now: datetime, query: str = "", sort: str = MANUAL) -> list[Reminder]:
    q = query.strip().casefold()
    out = [r for r in data.reminders if matches(r, flt, now)]
    if q:
        out = [r for r in out if q in f"{r.title}\n{r.description}\n{r.category or ''}".casefold()]
    return sort_reminders(out, sort, flt[0] == F_CATEGORY)


def counts(data: Data, now: datetime) -> dict[str, Any]:
    return {
        F_ALL: len(data.reminders),
        F_TODAY: sum(matches(r, (F_TODAY, None), now) for r in data.reminders),
        F_OVERDUE: sum(is_overdue(r, now) for r in data.reminders),
        F_CATEGORY: {c: sum(r.category == c for r in data.reminders) for c in data.categories},
    }


def reorder_subset(data: Data, new_order_ids: Iterable[str], in_category: bool = False) -> None:
    """Элементы подмножества переставляются в уже занимаемых ими позициях порядка.
    in_category — меняется только порядок внутри категории, общий список не затрагивается."""
    ids = list(new_order_ids)
    by_id = {r.id: r for r in data.reminders}
    if in_category:
        chosen = [by_id[i] for i in ids]
        for slot, r in zip(sorted(r.cat_order for r in chosen), chosen):
            r.cat_order = slot
        _renumber_cat(data)
        return
    slots = sorted(i for i, r in enumerate(data.reminders) if r.id in set(ids))
    for slot, rid in zip(slots, ids):
        data.reminders[slot] = by_id[rid]
    _renumber(data)


# ---- Категории ---------------------------------------------------------------------------
def rename_category(data: Data, old: str, new: str) -> None:
    new = new.strip()
    if not new or new == old:
        return
    if new in data.categories:
        data.categories = [c for c in data.categories if c != old]
    else:                                  # переименование не сдвигает категорию в списке
        data.categories = [new if c == old else c for c in data.categories]
        ensure_category(data, new)
    for r in data.reminders:
        if r.category == old:
            r.category = new
    _renumber_cat(data)
    for h in data.history:
        if h.category == old:
            h.category = new


def reorder_categories(data: Data, names: Iterable[str]) -> None:
    names = list(names)
    if sorted(names) == sorted(data.categories):
        data.categories = names


def delete_category(data: Data, name: str) -> None:
    data.categories = [c for c in data.categories if c != name]
    for r in data.reminders:
        if r.category == name:
            r.category = None
    _renumber_cat(data)


# ---- История -----------------------------------------------------------------------------
def restore_from_history(data: Data, item: HistoryItem) -> Reminder:
    """Возвращает запись как ОДНОКРАТНОЕ напоминание с исходной датой (повторяющиеся не возвращаются)."""
    if item.repeat != ONCE:
        raise ValueError("повторяющееся напоминание нельзя вернуть из истории")
    data.history.remove(item)
    r = Reminder.create(item.title, item.due, category=item.category, priority=item.priority)
    add_reminder(data, r)
    return r


def delete_history(data: Data, ids: Iterable[str]) -> None:
    gone = set(ids)
    data.history = [h for h in data.history if h.id not in gone]


def purge_history(data: Data, days: int, now: datetime) -> int:
    if days <= 0:
        return 0
    cutoff = now - timedelta(days=days)
    before = len(data.history)
    data.history = [h for h in data.history if h.completed_at >= cutoff]
    return before - len(data.history)
