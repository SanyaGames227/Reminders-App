"""Галерея всех типов виджетов в обеих темах (не входит в сборку). Запуск: python gallery.py"""
import sys

from PyQt5.QtCore import QDate, QRectF, QTime, Qt
from PyQt5.QtGui import QPainter
from PyQt5.QtWidgets import (QApplication, QCheckBox, QGridLayout, QGroupBox, QListWidget, QProgressBar,
                             QRadioButton, QSpinBox, QTabBar, QTextEdit, QTimeEdit, QDateEdit, QWidget, QLineEdit)

import core, i18n, theme
from ui.widgets import (AeroButton, AeroMenu, AeroCalendar, AeroComboBox, AeroLineEdit, DoneButton, IconButton, SearchEdit, confirm,
                        make_label)


class Gallery(QWidget):
    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.app, self.dark = app, False
        g = QGridLayout(self); g.setSpacing(10)
        line = AeroLineEdit("Line edit"); dis = AeroLineEdit("Disabled"); dis.setEnabled(False)
        bad = AeroLineEdit(); bad.setProperty("invalid", True); bad.setPlaceholderText("Invalid")
        combo = AeroComboBox(editable=True); combo.addItems(["Combo one", "Combo two", "Combo three"])
        combo2 = AeroComboBox(); combo2.addItems(["Plain", "Combo"]); combo2.setEnabled(False)
        date = QDateEdit(QDate.currentDate()); date.setCalendarPopup(True); date.setCalendarWidget(AeroCalendar())
        g.addWidget(make_label("Fields", "section"), 0, 0)
        for i, w in enumerate((line, dis, bad, SearchEdit(), combo, combo2, date, QTimeEdit(QTime(9, 0)), QSpinBox())):
            g.addWidget(w, 1 + i // 3, i % 3)
        row = 4
        for i, (t, r) in enumerate((("Normal", "ctl"), ("Accent", "accent"), ("Danger", "danger"), ("Flat", "flat"))):
            g.addWidget(AeroButton(t, r), row, i % 3) if i < 3 else g.addWidget(AeroButton(t, r), row + 1, 0)
        off = AeroButton("Disabled"); off.setEnabled(False); g.addWidget(off, row + 1, 1)
        icons_ = [IconButton("edit"), IconButton("trash", True), DoneButton(), DoneButton(core.HIGH)]
        for i, w in enumerate(icons_):
            g.addWidget(w, row + 2, i % 3) if i < 3 else g.addWidget(w, row + 3, 0)
        d = DoneButton(); d.setEnabled(False); g.addWidget(d, row + 3, 1)
        checks = QCheckBox("Checked"); checks.setChecked(True); part = QCheckBox("Partial"); part.setTristate(True)
        part.setCheckState(Qt.PartiallyChecked); radio = QRadioButton("Radio"); radio.setChecked(True)
        off_c = QCheckBox("Disabled"); off_c.setEnabled(False)
        for i, w in enumerate((checks, QCheckBox("Unchecked"), part, radio, QRadioButton("Radio 2"), off_c)):
            g.addWidget(w, row + 4 + i // 3, i % 3)
        lst = QListWidget(); lst.addItems([f"List item {i}" for i in range(12)]); lst.setCurrentRow(1)
        box = QGroupBox("Group"); box.setLayout(QGridLayout()); bar = QProgressBar(); bar.setValue(60)
        tabs = QTabBar(); [tabs.addTab(t) for t in ("Tab A", "Tab B")]
        box.layout().addWidget(bar); box.layout().addWidget(tabs)
        g.addWidget(lst, 0, 3, 5, 1); g.addWidget(box, 5, 3, 2, 1); g.addWidget(QTextEdit("Text edit"), 7, 0, 1, 4)
        g.addWidget(AeroCalendar(), 0, 4, 6, 1)
        menu_btn = AeroButton("Menu"); menu_btn.clicked.connect(self.menu); g.addWidget(menu_btn, row + 6, 0)
        dlg = AeroButton("Confirm"); dlg.clicked.connect(lambda: confirm(self, "Delete this reminder?", "Delete", True))
        g.addWidget(dlg, row + 6, 1)
        flip = AeroButton("Toggle theme", "accent"); flip.clicked.connect(self.flip); g.addWidget(flip, row + 6, 3)

    def menu(self) -> None:
        m = AeroMenu(self); m.addAction("Edit", lambda: None, "Return"); m.addSeparator()
        m.addAction("Disabled").setEnabled(False); sub = AeroMenu("Submenu", m); m.addMenu(sub); sub.addAction("Item")
        m.exec_(self.cursor().pos())

    def flip(self) -> None:
        self.dark = not self.dark; theme.apply_theme(self.app, "dark" if self.dark else "light"); self.update()

    def paintEvent(self, _e: object) -> None:
        theme.paint_window_background(QPainter(self), QRectF(self.rect()))


if __name__ == "__main__":
    app = QApplication(sys.argv); theme.init_app(app); i18n.set_language("en"); theme.apply_theme(app, "light")
    w = Gallery(app); w.resize(1100, 760); w.show(); sys.exit(app.exec_())
