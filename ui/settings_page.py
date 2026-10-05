"""Страница настроек: язык, тема, автозапуск, звук, автоочистка истории."""
from __future__ import annotations

from typing import Any, Optional

from PyQt5.QtCore import QSignalBlocker, QSize, QTime, Qt, pyqtSignal
from PyQt5.QtWidgets import QCheckBox, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

import core
import i18n
from theme import S
from ui.widgets import AeroButton, AeroComboBox, AeroTimeEdit, GlassPanel, make_label


class SettingsPage(QWidget):
    changed = pyqtSignal(str, object)   # (ключ настройки, значение)
    shortcut_requested = pyqtSignal()
    export_requested = pyqtSignal()
    import_requested = pyqtSignal()
    optimize_requested = pyqtSignal()

    def __init__(self, settings: dict[str, Any], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.language = AeroComboBox(); self.theme = AeroComboBox(); self.cleanup = AeroComboBox()
        self.autostart = QCheckBox(); self.sound = QCheckBox()
        self.shortcut = AeroButton("", "ctl", compact=True)
        self.shortcut.setFixedWidth(100)
        self.quiet = QCheckBox()
        self.q_from, self.q_to = AeroTimeEdit(), AeroTimeEdit()
        for w in (self.q_from, self.q_to):
            w.setDisplayFormat("HH:mm"); w.setFixedWidth(90)
        self.btn_export = AeroButton("", "ctl", compact=True); self.btn_import = AeroButton("", "ctl", compact=True)
        self.btn_optimize = AeroButton("", "ctl", compact=True)
        self.data_row = QWidget(); dr = QHBoxLayout(self.data_row)
        dr.setContentsMargins(0, 0, 0, 0); dr.setSpacing(S.SP)
        dr.addWidget(self.btn_export); dr.addWidget(self.btn_import)
        self._labels: dict[str, Any] = {}
        self._left = (self.shortcut, self.q_from, self.q_to, self.data_row, self.btn_optimize)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(S.SP * 2)

        def section(key: str, rows: list[tuple[Optional[str], QWidget]]) -> None:
            panel = GlassPanel(); g = QGridLayout(panel)
            g.setContentsMargins(20, 14, 20, 16); g.setHorizontalSpacing(S.SP * 3); g.setVerticalSpacing(S.SP + 4)
            head = make_label("", "section"); self._labels[key] = head
            g.addWidget(head, 0, 0, 1, 2)
            for i, (lk, w) in enumerate(rows, 1):
                if lk:
                    lb = make_label("", "dim"); self._labels[lk] = lb
                    g.addWidget(lb, i, 0); g.addWidget(w, i, 1, Qt.AlignLeft) if w in self._left else g.addWidget(w, i, 1)
                else:
                    g.addWidget(w, i, 0, 1, 2)
            g.setColumnStretch(1, 1); g.setColumnMinimumWidth(0, 160)
            root.addWidget(panel)

        section("sec_appearance", [("set_language", self.language), ("set_theme", self.theme)])
        section("sec_system", [(None, self.autostart), (None, self.sound), ("set_shortcut", self.shortcut)])
        section("sec_quiet", [(None, self.quiet), ("set_quiet_from", self.q_from), ("set_quiet_to", self.q_to)])
        section("sec_history", [("set_cleanup", self.cleanup)])
        section("sec_data", [("set_data", self.data_row), ("set_db", self.btn_optimize)])
        root.addStretch(1)

        for code in i18n.LANGS:
            self.language.addItem(i18n.LANG_NAMES[code], code)
        self.language.setCurrentIndex(self.language.findData(settings["language"]))
        self.language.currentIndexChanged.connect(lambda _i: self.changed.emit("language", self.language.currentData()))
        self.theme.currentIndexChanged.connect(lambda _i: self.changed.emit("theme", self.theme.currentData()))
        self.cleanup.currentIndexChanged.connect(lambda _i: self.changed.emit("history_days", self.cleanup.currentData()))
        self.autostart.toggled.connect(lambda v: self.changed.emit("autostart", v))
        self.sound.toggled.connect(lambda v: self.changed.emit("sound", v))
        self.shortcut.clicked.connect(lambda _c=False: self.shortcut_requested.emit())
        self.btn_export.clicked.connect(lambda _c=False: self.export_requested.emit())
        self.btn_import.clicked.connect(lambda _c=False: self.import_requested.emit())
        self.btn_optimize.clicked.connect(lambda _c=False: self.optimize_requested.emit())
        self.quiet.setChecked(bool(settings.get("quiet_on")))
        for w, key, dflt in ((self.q_from, "quiet_from", "22:00"), (self.q_to, "quiet_to", "08:00")):
            w.setTime(QTime.fromString(str(settings.get(key) or dflt), "HH:mm"))
            w.setEnabled(self.quiet.isChecked())
        self.quiet.toggled.connect(self._on_quiet)
        self.q_from.timeChanged.connect(lambda t: self.changed.emit("quiet_from", t.toString("HH:mm")))
        self.q_to.timeChanged.connect(lambda t: self.changed.emit("quiet_to", t.toString("HH:mm")))
        self.autostart.setChecked(bool(settings["autostart"])); self.sound.setChecked(bool(settings["sound"]))
        self._settings = settings
        self.retranslate()

    def minimumSizeHint(self) -> QSize:
        """Высота не сжимается ниже естественной — при нехватке места работает прокрутка, а не сжатие кнопок."""
        return QSize(super().minimumSizeHint().width(), self.sizeHint().height())

    def retranslate(self) -> None:
        """Тексты меняются на лету; сохранённые значения комбобоксов восстанавливаются."""
        tr, s = i18n.tr, self._settings
        blockers = [QSignalBlocker(w) for w in (self.theme, self.cleanup)]
        self.theme.clear()
        self.theme.addItem(tr("theme_light"), "light"); self.theme.addItem(tr("theme_dark"), "dark")
        self.theme.setCurrentIndex(self.theme.findData(s["theme"]))
        self.cleanup.clear()
        self.cleanup.addItem(tr("cleanup_never"), 0)
        for days in core.HISTORY_KEEP_CHOICES[1:]:
            self.cleanup.addItem(i18n.plural("cleanup_days", days), days)
        self.cleanup.setCurrentIndex(max(0, self.cleanup.findData(s["history_days"])))
        del blockers
        for key, lb in self._labels.items():
            lb.setText(tr(key))
        self.autostart.setText(tr("set_autostart")); self.sound.setText(tr("set_sound"))
        self.shortcut.setText(tr("shortcut_create")); self.quiet.setText(tr("set_quiet"))
        self.btn_export.setText(tr("data_export")); self.btn_import.setText(tr("data_import"))
        self.btn_optimize.setText(tr("db_optimize"))

    def _on_quiet(self, on: bool) -> None:
        self.q_from.setEnabled(on); self.q_to.setEnabled(on)
        self.changed.emit("quiet_on", on)

    def set_autostart_checked(self, value: bool) -> None:
        blocker = QSignalBlocker(self.autostart)
        self.autostart.setChecked(value)
        del blocker
