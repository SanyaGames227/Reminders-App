"""Планировщик: один QTimer (1 с, без потоков), срабатывания, звук раз на пачку, автоочистка."""
from __future__ import annotations

from datetime import datetime, time
from typing import Optional

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

import core
import icons
from core import HIGH, Reminder
from storage import Storage

TICK_MS = 1000


class Scheduler(QObject):
    alerts = pyqtSignal(list)   # list[Reminder]: новые уведомления (одной пачкой)
    early_alerts = pyqtSignal(list)   # list[Reminder]: «скоро» (предупреждение заранее)
    refreshed = pyqtSignal()    # данные/счётчики могли измениться (смена минуты, очистка)

    def __init__(self, store: Storage, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.store = store
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self.tick)
        self._last_minute: Optional[datetime] = None
        self._last_purge_day = None
        self._held: list[str] = []          # id обычных напоминаний, задержанных тихим режимом

    def start(self) -> None:
        """Старт программы: показать все alerting и наступившие scheduled — одной пачкой."""
        now = core.now_local()
        self._purge(now)
        pending = core.pending_alerts(self.store.data, now)
        early = core.due_early(self.store.data, now, include_unseen=True)   # как и просроченные: при старте — всё сразу
        if pending or early:
            self.store.save_data()
        if pending:
            self._deliver(pending, now)
        if early:
            self._deliver_early(early, now)
        self._last_minute = now.replace(second=0)
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def tick(self) -> None:
        now = core.now_local()
        fired = core.fire_due(self.store.data, now)
        if fired:
            self.store.save_data()          # alerting сохраняется на диск СРАЗУ
            self._deliver(fired, now)
        early = core.due_early(self.store.data, now)
        if early:
            self.store.save_data()
            self._deliver_early(early, now)
        if self._held and not self._quiet(now):     # тихие часы закончились — показываем задержанные
            ids, self._held = self._held, []
            late = [r for r in (self.store.data.get(i) for i in ids) if r is not None and r.state == core.ALERTING]
            if late:
                self._notify(late)
        minute = now.replace(second=0)
        if minute != self._last_minute:     # смена минуты (в т.ч. после сна/перевода часов)
            self._last_minute = minute
            self._purge(now)
            self.refreshed.emit()

    def purge_now(self) -> None:
        """После смены настройки автоочистки."""
        self._last_purge_day = None
        self._purge(core.now_local())
        self.refreshed.emit()

    def _quiet(self, now: datetime) -> bool:
        """Тихий режим по часам из настроек (полноэкранные приложения не учитываются)."""
        st = self.store.settings
        if not st.get("quiet_on"):
            return False
        return core.in_quiet(now, core.parse_hhmm(st.get("quiet_from"), time(22, 0)),
                             core.parse_hhmm(st.get("quiet_to"), time(8, 0)))

    def _deliver(self, items: list[Reminder], now: datetime) -> None:
        """Тихие часы задерживают только обычный приоритет; важные идут всегда."""
        if self._quiet(now):
            held = [r for r in items if r.priority != HIGH]
            self._held.extend(r.id for r in held if r.id not in self._held)
            items = [r for r in items if r.priority == HIGH]
            if not items:
                self.refreshed.emit()
                return
        self._notify(items)

    def _deliver_early(self, items: list[Reminder], now: datetime) -> None:
        if self._quiet(now):
            for r in items:
                if r.priority != HIGH:
                    core.ack_early(r)                            # обычные «скоро» в тихие часы пропускаем
            self.store.save_data()
            items = [r for r in items if r.priority == HIGH]
        if not items:
            return
        if self.store.settings.get("sound", True) and any(not r.silent for r in items):
            icons.play_alert(False)
        self.early_alerts.emit(items)

    def _notify(self, items: list[Reminder]) -> None:
        loud = [r for r in items if not r.silent]            # «без звука» — только для этого напоминания
        if loud and self.store.settings.get("sound", True):
            icons.play_alert(any(r.priority == HIGH for r in loud))   # один звук на пачку
        self.alerts.emit(items)
        self.refreshed.emit()

    def _purge(self, now: datetime) -> None:
        if self._last_purge_day == now.date():
            return
        self._last_purge_day = now.date()
        if core.purge_history(self.store.data, int(self.store.settings.get("history_days", 0)), now):
            self.store.save_data()
