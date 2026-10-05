"""Иконка в трее: Открыть / Новое напоминание / Выход; двойной клик — открыть."""
from __future__ import annotations

from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import QAction, QSystemTrayIcon

import i18n
import icons
from ui.widgets import AeroMenu


class Tray(QSystemTrayIcon):
    open_requested = pyqtSignal()
    new_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(icons.app_icon(), parent)
        self.menu = AeroMenu()
        self.a_open = QAction(self.menu); self.a_new = QAction(self.menu); self.a_quit = QAction(self.menu)
        self.a_open.triggered.connect(self.open_requested)
        self.a_new.triggered.connect(self.new_requested)
        self.a_quit.triggered.connect(self.quit_requested)
        self.menu.addAction(self.a_open); self.menu.addAction(self.a_new)
        self.menu.addSeparator(); self.menu.addAction(self.a_quit)
        self.setContextMenu(self.menu)
        self.activated.connect(lambda r: self.open_requested.emit() if r == QSystemTrayIcon.DoubleClick else None)
        i18n.subscribe(self.retranslate)
        self.retranslate()

    def retranslate(self) -> None:
        self.setToolTip(i18n.tr("app_title"))
        self.a_open.setText(i18n.tr("tray_open")); self.a_new.setText(i18n.tr("tray_new"))
        self.a_quit.setText(i18n.tr("tray_quit"))

    def show_hint(self) -> None:
        self.showMessage(i18n.tr("tray_hint_title"), i18n.tr("tray_hint"), icons.app_icon(), 4000)

    def dispose(self) -> None:
        i18n.unsubscribe(self.retranslate)
        self.hide(); self.menu.deleteLater()
