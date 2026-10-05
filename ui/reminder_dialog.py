"""Диалог создания/редактирования напоминания."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from PyQt5.QtCore import QDate, QLocale, QTime, Qt
from PyQt5.QtWidgets import QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QWidget

import core
import i18n
from core import Reminder
from theme import S
from ui.widgets import (AeroButton, AeroCalendar, AeroComboBox, AeroDateEdit, AeroDialog, AeroLineEdit,
                        AeroTextEdit, AeroTimeEdit, make_label, repolish)

REPEAT_KEYS = {core.ONCE: "repeat_once", core.DAILY: "repeat_daily", core.WEEKLY: "repeat_weekly",
               core.MONTHLY: "repeat_monthly", core.YEARLY: "repeat_yearly"}
PRIORITY_KEYS = {core.NORMAL: "prio_normal", core.HIGH: "prio_high"}


def _date_format() -> str:
    fmt = i18n.qlocale().dateFormat(QLocale.ShortFormat)
    return fmt if "yyyy" in fmt else fmt.replace("yy", "yyyy")


class ReminderDialog(AeroDialog):
    def __init__(self, parent: Optional[QWidget], categories: list[str], reminder: Optional[Reminder] = None,
                 preset_category: Optional[str] = None) -> None:
        tr = i18n.tr
        super().__init__(parent, tr("edit_reminder" if reminder else "new_reminder"))
        self.setMinimumWidth(460)
        loc = i18n.qlocale()
        now = core.now_local()
        due = reminder.due if reminder else core.next_full_hour(now)

        self.title = AeroLineEdit(reminder.title if reminder else "")
        self.title.setPlaceholderText(tr("title_ph"))
        self.desc = AeroTextEdit(); self.desc.setAcceptRichText(False); self.desc.setFixedHeight(72)
        self.desc.setPlaceholderText(tr("desc_ph"))
        if reminder:
            self.desc.setPlainText(reminder.description)

        self.category = AeroComboBox(editable=True)
        self.category.setInsertPolicy(QComboBox.NoInsert)
        self.category.addItem(tr("no_category"))
        self.category.addItems(categories)
        self.category.lineEdit().setPlaceholderText(tr("category_ph"))
        cur = reminder.category if reminder else preset_category
        self.category.setCurrentIndex(max(0, self.category.findText(cur)) if cur else 0)

        self.priority = AeroComboBox()
        for key, label in PRIORITY_KEYS.items():
            self.priority.addItem(tr(label), key)
        self.repeat = AeroComboBox()
        for key, label in REPEAT_KEYS.items():
            self.repeat.addItem(tr(label), key)
        self.early = AeroComboBox()
        for m in core.EARLY_CHOICES:
            self.early.addItem(tr("early_none") if m == 0 else tr("early_before", t=i18n.lead_label(m)), m)
        self.silent = QCheckBox(tr("f_silent"))
        if reminder:
            self.priority.setCurrentIndex(self.priority.findData(reminder.priority))
            self.repeat.setCurrentIndex(self.repeat.findData(reminder.repeat))
            self.early.setCurrentIndex(max(0, self.early.findData(reminder.early_min)))
            self.silent.setChecked(reminder.silent)

        self.date = AeroDateEdit(QDate(due.year, due.month, due.day))
        self.date.setLocale(loc); self.date.setDisplayFormat(_date_format())
        cal = AeroCalendar(); cal.setLocale(loc)
        self.date.setCalendarPopup(True); self.date.setCalendarWidget(cal)
        self.time = AeroTimeEdit(QTime(due.hour, due.minute))
        self.time.setLocale(loc); self.time.setDisplayFormat(loc.timeFormat(QLocale.ShortFormat))
        today = AeroButton(tr("preset_today"), "flat", compact=True)
        tomorrow = AeroButton(tr("preset_tomorrow"), "flat", compact=True)
        today.clicked.connect(lambda: self._preset(0)); tomorrow.clicked.connect(lambda: self._preset(1))

        self.hint = make_label("", "hint")
        grid = QGridLayout(self)
        grid.setContentsMargins(24, 20, 24, 16); grid.setHorizontalSpacing(S.SP * 2); grid.setVerticalSpacing(S.SP + 2)
        rows = [("f_title", self.title), ("f_desc", self.desc), ("f_category", self.category),
                ("f_priority", self.priority), ("f_repeat", self.repeat), ("f_early", self.early)]
        for i, (key, w) in enumerate(rows):
            lb = make_label(tr(key), "dim"); lb.setAlignment(Qt.AlignRight | Qt.AlignTop if w is self.desc else Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(lb, i, 0); grid.addWidget(w, i, 1)
        r = len(rows)
        grid.addWidget(make_label(tr("f_date"), "dim"), r, 0, Qt.AlignRight)
        drow = QHBoxLayout(); drow.setSpacing(S.SP)
        drow.addWidget(self.date, 1); drow.addWidget(today); drow.addWidget(tomorrow)
        grid.addLayout(drow, r, 1)
        grid.addWidget(make_label(tr("f_time"), "dim"), r + 1, 0, Qt.AlignRight)
        trow = QHBoxLayout(); trow.addWidget(self.time); trow.addSpacing(S.SP); trow.addWidget(self.hint, 1)
        grid.addLayout(trow, r + 1, 1)
        grid.addWidget(self.silent, r + 2, 1)

        cancel = AeroButton(tr("cancel")); cancel.clicked.connect(self.reject)
        self.ok = AeroButton(tr("save"), "accent"); self.ok.setDefault(True); self.ok.clicked.connect(self._accept)
        brow = QHBoxLayout(); brow.addStretch(1); brow.setSpacing(S.SP)
        brow.addWidget(cancel); brow.addWidget(self.ok)
        grid.setRowMinimumHeight(r + 3, S.SP)
        grid.addLayout(brow, r + 4, 0, 1, 2)

        self.date.dateChanged.connect(self._update_hint); self.time.timeChanged.connect(self._update_hint)
        self.title.textChanged.connect(self._clear_invalid)
        chain = (self.title, self.desc, self.category, self.priority, self.repeat, self.early, self.date,
                 self.time, self.silent, today, tomorrow, cancel, self.ok)
        for a, b in zip(chain, chain[1:] + chain[:1]):
            self.setTabOrder(a, b)
        self._update_hint()
        self.title.setFocus()

    # -- поведение
    def _preset(self, days: int) -> None:
        d = core.now_local().date() + timedelta(days=days)
        self.date.setDate(QDate(d.year, d.month, d.day))

    def _due(self) -> datetime:
        d, t = self.date.date(), self.time.time()
        return datetime(d.year(), d.month(), d.day(), t.hour(), t.minute())

    def _update_hint(self) -> None:
        self.hint.setText(i18n.tr("fires_now") if self._due() <= core.now_local() else "")

    def _clear_invalid(self) -> None:
        if self.title.property("invalid"):
            self.title.setProperty("invalid", False); repolish(self.title)

    def _accept(self) -> None:
        if not self.title.text().strip():
            self.title.setProperty("invalid", True); repolish(self.title)
            self.title.setPlaceholderText(i18n.tr("title_required")); self.title.setFocus()
            return
        self.accept()

    def values(self) -> dict[str, Any]:
        cat = self.category.currentText().strip()
        return {
            "title": self.title.text().strip(), "description": self.desc.toPlainText().strip(),
            "category": None if not cat or cat == i18n.tr("no_category") else cat,
            "priority": self.priority.currentData(), "repeat": self.repeat.currentData(), "due": self._due(),
            "silent": self.silent.isChecked(), "early_min": self.early.currentData(),
        }
