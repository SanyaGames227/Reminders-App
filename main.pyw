"""Точка входа (.pyw — запускается через pythonw, без консоли). AppUserModelID, High-DPI,
single instance, запуск. Флаг --tray — старт в трее."""
from __future__ import annotations

import hashlib
import os
import sys
import traceback
from datetime import datetime

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtNetwork import QLocalServer, QLocalSocket
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon

import i18n
import icons
import storage
import theme
from scheduler import Scheduler
from storage import Storage, StorageError
from ui.main_window import MainWindow
from ui.toast import ToastManager
from ui.tray import Tray
from ui.widgets import FocusClearer, info

APP_ID = "Reminders.Aero.App"


def instance_key() -> str:
    """Имя сервера зависит от пути папки данных: разные portable-копии не конфликтуют."""
    return "Reminders-" + hashlib.md5(str(storage.data_dir()).lower().encode()).hexdigest()[:16]


def install_excepthook() -> None:
    """Необработанное исключение в слоте PyQt5 по умолчанию роняет процесс — пишем в лог и живём дальше."""
    def hook(exc_type: type, exc: BaseException, tb: object) -> None:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        if sys.stderr is not None:        # под pythonw stderr/stdout равны None
            sys.stderr.write(text)
        try:
            with open(storage.data_dir() / "errors.log", "a", encoding="utf-8") as f:
                f.write(f"--- {datetime.now().isoformat(timespec='seconds')}\n{text}")
        except OSError:
            pass
    sys.excepthook = hook


def main() -> int:
    install_excepthook()
    tray_start = "--tray" in sys.argv
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)  # type: ignore[attr-defined]
        except Exception:
            pass
    if sys.platform.startswith("linux") and "QT_QPA_PLATFORM" not in os.environ and os.environ.get("DISPLAY"):
        # Нативный Wayland не даёт окну задать свою позицию: уведомления не встанут в угол.
        # Через XWayland (xcb) позиция, «поверх всех» и фокус работают как на X11. Обойти: QT_QPA_PLATFORM=wayland
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Reminders")
    app.setWindowIcon(icons.app_icon())
    theme.init_app(app)
    clearer = FocusClearer(app)
    app.installEventFilter(clearer)

    key = instance_key()
    probe = QLocalSocket()
    probe.connectToServer(key)
    if probe.waitForConnected(300):          # уже запущен: поднимаем его окно
        if not tray_start:
            probe.write(b"show"); probe.flush(); probe.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(key)
    server = QLocalServer()
    server.listen(key)

    store = Storage()
    try:
        store.open()
    except StorageError as e:
        i18n.set_language(storage.detect_language()); theme.apply_theme(app, storage.detect_theme())
        info(None, i18n.tr("err_not_writable", path=str(e)), i18n.tr("err_title"))
        return 1
    i18n.set_language(store.settings["language"])
    theme.apply_theme(app, store.settings["theme"])
    storage.refresh_autostart(bool(store.settings["autostart"]))   # путь в реестре всегда актуален

    toasts = ToastManager()
    sched = Scheduler(store)
    tray = Tray() if QSystemTrayIcon.isSystemTrayAvailable() else None
    window = MainWindow(store, sched, toasts, tray)
    if tray:
        tray.open_requested.connect(window.bring_to_front)
        tray.new_requested.connect(window.new_reminder)
        tray.quit_requested.connect(window.quit_app)
        tray.show()

    def on_connection() -> None:
        sock = server.nextPendingConnection()
        if sock is None:
            return
        sock.readyRead.connect(window.bring_to_front)
        sock.disconnected.connect(sock.deleteLater)
        if sock.bytesAvailable():
            window.bring_to_front()
    server.newConnection.connect(on_connection)

    def cleanup() -> None:
        sched.stop(); toasts.close_all(); window.save_geometry(); store.close()
        if tray:
            tray.dispose()
        server.close()
    app.aboutToQuit.connect(cleanup)
    app.commitDataRequest.connect(lambda _mgr: window.save_geometry())   # завершение сеанса Windows

    if not (tray_start and tray):
        window.show()

    def after_start() -> None:
        for notice in store.notices:
            info(window if window.isVisible() else None, i18n.tr(notice))
        sched.start()
        window.check_updates_on_start()      # тихо, в фоне; окно появится только если вышла новая версия
    QTimer.singleShot(0, after_start)
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
