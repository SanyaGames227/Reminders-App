"""Portable-хранилище: пути, атомарная запись, .bak, восстановление, миграции, автозапуск."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import core
from core import Data, HistoryItem, Reminder, iso

SCHEMA_VERSION = 1
SQL_ERRORS = (OSError, sqlite3.Error, ValueError, KeyError, TypeError, AssertionError)
DATA_DIR_NAME = ".reminders-data"
APP_NAME = "Reminders"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
THEME_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"

DEFAULT_SETTINGS: dict[str, Any] = {
    "language": "en", "theme": "light", "autostart": False, "sound": True,
    "history_days": 0, "geometry": "", "maximized": False, "last_page": "all",
    "last_category": None, "tray_hint_shown": False,
    "quiet_on": False, "quiet_from": "22:00", "quiet_to": "08:00",
}


IS_NUITKA = "__compiled__" in globals()
IS_FROZEN = bool(getattr(sys, "frozen", False)) or IS_NUITKA


def app_exe() -> Path:
    """Реальный путь к exe: PyInstaller (onedir/onefile) — sys.executable; Nuitka onefile — sys.executable
    указывает во временную папку, настоящий путь в sys.argv[0]."""
    if IS_NUITKA:
        arg0 = sys.argv[0] if sys.argv and sys.argv[0] else ""
        if arg0:
            found = arg0 if os.path.dirname(arg0) else (shutil.which(arg0) or arg0)
            p = Path(os.path.abspath(found))
            if p.exists():
                return p
    return Path(sys.executable).resolve()


def base_dir() -> Path:
    if IS_FROZEN:
        return app_exe().parent
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    return base_dir() / DATA_DIR_NAME


def temp_dir() -> Path:
    """Общая временная папка для звука и PNG-глифов."""
    p = Path(tempfile.gettempdir()) / "reminders-aero"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---- Системные настройки первого запуска -----------------------------------------------
def detect_language() -> str:
    code = ""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(85)
        if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85):  # type: ignore[attr-defined]
            code = buf.value
    except Exception:
        import locale
        code = (locale.getlocale()[0] or "")
    code = code.lower()
    if code.startswith("ru"):
        return "ru"
    if code.startswith("uk"):
        return "uk"
    return "en"


def detect_theme() -> str:
    """Тема системы: реестр (Windows), gsettings (GNOME и производные), иначе по палитре Qt."""
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, THEME_KEY) as k:
                return "light" if winreg.QueryValueEx(k, "AppsUseLightTheme")[0] else "dark"
        except Exception:
            return "light"
    if sys.platform.startswith("linux"):
        try:
            import subprocess
            out = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"], stdin=subprocess.DEVNULL,
                                 capture_output=True, text=True, timeout=1).stdout
            if "dark" in out:
                return "dark"
            if "light" in out or "default" in out:
                return "light"
        except Exception:
            pass
    try:
        from PyQt5.QtGui import QGuiApplication
        if QGuiApplication.instance() is not None:
            return "dark" if QGuiApplication.palette().window().color().lightness() < 128 else "light"
    except Exception:
        pass
    return "light"


# ---- Настройки: атомарный JSON ---------------------------------------------------------------------
def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _read_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict):
        raise ValueError("root is not an object")
    return obj


# ---- Данные: SQLite (stdlib) ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders(
  id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL, category TEXT,
  priority TEXT NOT NULL, anchor TEXT NOT NULL, due TEXT NOT NULL, repeat TEXT NOT NULL,
  snoozed_until TEXT, state TEXT NOT NULL, ord INTEGER NOT NULL,
  silent INTEGER NOT NULL DEFAULT 0, early_min INTEGER NOT NULL DEFAULT 0, pre_sent TEXT);
CREATE TABLE IF NOT EXISTS history(
  id TEXT PRIMARY KEY, title TEXT NOT NULL, category TEXT, priority TEXT NOT NULL,
  due TEXT NOT NULL, completed_at TEXT NOT NULL, repeat TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS history_completed ON history(completed_at);
CREATE TABLE IF NOT EXISTS categories(name TEXT PRIMARY KEY, pos INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""
R_COLS, H_COLS = 14, 7
R_MIGRATE = (("silent", "INTEGER NOT NULL DEFAULT 0"), ("early_min", "INTEGER NOT NULL DEFAULT 0"), ("pre_sent", "TEXT"))


def _reminder_row(r: Reminder, pos: int) -> tuple:
    return (r.id, r.title, r.description, r.category, r.priority, iso(r.anchor), iso(r.due), r.repeat,
            iso(r.snoozed_until), r.state, pos, int(r.silent), r.early_min, r.pre_sent)


def _history_row(h: HistoryItem) -> tuple:
    return (h.id, h.title, h.category, h.priority, iso(h.due), iso(h.completed_at), h.repeat)


def _migrate(conn: sqlite3.Connection) -> None:
    """Старые базы: дописываем недостающие колонки (в том же порядке, что в SCHEMA)."""
    have = {row[1] for row in conn.execute("PRAGMA table_info(reminders)")}
    for name, ddl in R_MIGRATE:
        if name not in have:
            conn.execute(f"ALTER TABLE reminders ADD COLUMN {name} {ddl}")


class StorageError(Exception):
    """Папка данных недоступна для записи."""


class Storage:
    def __init__(self) -> None:
        self.dir = data_dir()
        self.db_path = self.dir / "data.db"
        self.bak_path = self.dir / "data.db.bak"
        self.settings_path = self.dir / "settings.json"
        self.notices: list[str] = []          # ключи i18n для разового сообщения пользователю
        self.settings: dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.data = Data()
        self.conn: Optional[sqlite3.Connection] = None
        self._saved_r: dict[str, tuple] = {}
        self._saved_h: dict[str, tuple] = {}
        self._saved_c: list[str] = []

    # -- открытие
    def open(self) -> None:
        try:
            self.dir.mkdir(exist_ok=True)
            probe = self.dir / ".write-test"
            probe.write_text("x")
            probe.unlink()
        except OSError as e:
            raise StorageError(str(self.dir)) from e
        first_run = not self.settings_path.exists()
        self._load_settings(first_run)
        self._open_db()

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            except sqlite3.Error:
                pass
            self.conn = None

    def _quarantine(self, path: Path) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        try:
            os.replace(path, path.with_name(f"{path.name}.corrupt-{stamp}"))
        except OSError:
            pass

    # -- настройки
    def _load_settings(self, first_run: bool) -> None:
        if first_run:
            self.settings.update(language=detect_language(), theme=detect_theme())
            self.save_settings()
            return
        try:
            self.settings.update(_read_json(self.settings_path))
        except (OSError, ValueError):
            self._quarantine(self.settings_path)
            self.settings.update(language=detect_language(), theme=detect_theme())
            self.save_settings()

    def save_settings(self) -> None:
        atomic_write_json(self.settings_path, {"schema_version": SCHEMA_VERSION, **self.settings})

    def set(self, **kw: Any) -> None:
        self.settings.update(kw)
        self.save_settings()

    # -- база
    def _open_db(self) -> None:
        if not self.db_path.exists():
            if self.bak_path.exists():           # data.db потерян, но есть копия
                self._recover()
            else:
                self._init_empty()
            return
        try:
            self._load_db()
            self._make_backup()                  # копия состояния на момент старта
        except SQL_ERRORS:
            self.close()
            self._quarantine(self.db_path)
            self._recover()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _load_db(self) -> None:
        self.conn = self._connect()
        if self.conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise sqlite3.DatabaseError("integrity check failed")
        self.conn.executescript(SCHEMA)
        _migrate(self.conn)
        self.conn.execute("INSERT OR IGNORE INTO meta VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
        self.conn.commit()
        reminders = []
        for row in self.conn.execute("SELECT * FROM reminders ORDER BY ord"):
            d = dict(row); d["order"] = d.pop("ord"); reminders.append(d)
        history = [dict(r) for r in self.conn.execute("SELECT * FROM history")]
        cats = [r["name"] for r in self.conn.execute("SELECT name FROM categories ORDER BY pos")]
        self.data = Data.from_dict({"reminders": reminders, "categories": cats, "history": history})
        self._snapshot()

    def _init_empty(self) -> None:
        self.data = Data()
        self.conn = self._connect()
        self.conn.executescript(SCHEMA)
        _migrate(self.conn)
        self.conn.execute("INSERT OR IGNORE INTO meta VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
        self.conn.commit()
        self._snapshot()

    def _recover(self) -> None:
        try:
            shutil.copy2(self.bak_path, self.db_path)
            self._load_db()
            self.notices.append("notice_recovered_backup")
        except SQL_ERRORS:
            self.close()
            if self.db_path.exists():
                self._quarantine(self.db_path)
            self._init_empty()
            self.notices.append("notice_recovered_empty")
        self.save_data()

    def _make_backup(self) -> None:
        assert self.conn is not None
        tmp = self.bak_path.with_name(self.bak_path.name + ".tmp")
        dst = sqlite3.connect(tmp)
        try:
            self.conn.backup(dst)
        finally:
            dst.close()
        os.replace(tmp, self.bak_path)

    # -- сохранение: пишем только изменившиеся строки, одной транзакцией
    def _rows(self) -> tuple[dict[str, tuple], dict[str, tuple], list[str]]:
        d = self.data
        return ({r.id: _reminder_row(r, i) for i, r in enumerate(d.reminders)},
                {h.id: _history_row(h) for h in d.history}, list(d.categories))

    def _snapshot(self) -> None:
        self._saved_r, self._saved_h, self._saved_c = self._rows()

    def _apply(self, table: str, cols: int, cur: dict[str, tuple], saved: dict[str, tuple]) -> None:
        assert self.conn is not None
        changed = [row for rid, row in cur.items() if saved.get(rid) != row]
        removed = [(rid,) for rid in saved if rid not in cur]
        if changed:
            self.conn.executemany(f"INSERT OR REPLACE INTO {table} VALUES ({','.join('?' * cols)})", changed)
        if removed:
            self.conn.executemany(f"DELETE FROM {table} WHERE id=?", removed)

    def save_data(self) -> None:
        assert self.conn is not None
        r_rows, h_rows, cats = self._rows()
        with self.conn:                          # транзакция: либо всё, либо ничего
            self._apply("reminders", R_COLS, r_rows, self._saved_r)
            self._apply("history", H_COLS, h_rows, self._saved_h)
            if cats != self._saved_c:
                self.conn.execute("DELETE FROM categories")
                self.conn.executemany("INSERT INTO categories VALUES (?, ?)", [(c, i) for i, c in enumerate(cats)])
        self._saved_r, self._saved_h, self._saved_c = r_rows, h_rows, cats

    def optimize_db(self) -> tuple[int, int]:
        """VACUUM: пересобирает файл базы и возвращает место от удалённых записей.
        Возвращает (размер до, размер после) в байтах. Бросает sqlite3.Error/OSError при сбое."""
        assert self.conn is not None
        self.save_data()                         # VACUUM нельзя выполнять внутри транзакции
        before = self.db_path.stat().st_size
        self.conn.execute("VACUUM")
        self.conn.execute("PRAGMA optimize")
        return before, self.db_path.stat().st_size

    # -- экспорт / импорт (JSON)
    def export_json(self, path: str) -> None:
        atomic_write_json(Path(path), core.export_payload(self.data, core.now_local()))

    def import_json(self, path: str) -> tuple[int, int]:
        """Объединяет файл с текущими данными (по id). Бросает OSError/ValueError при проблеме с файлом."""
        with open(path, "r", encoding="utf-8-sig") as f:
            payload = json.load(f)
        counts = core.merge_import(self.data, payload)
        self.save_data()
        return counts


# ---- Запуск: автозапуск и ярлык (реестр / ~/.config/autostart / рабочий стол) ---------------------
def launch_argv(*extra: str) -> list[str]:
    """Команда запуска приложения: exe (PyInstaller/Nuitka) или интерпретатор + main.pyw (обычный Python)."""
    if IS_FROZEN:
        return [str(app_exe()), *extra]
    exe = Path(sys.executable)
    if sys.platform == "win32":
        pyw = exe.with_name("pythonw.exe")
        if pyw.exists():
            exe = pyw
    return [str(exe), str(base_dir() / "main.pyw"), *extra]


def autostart_command() -> str:
    return " ".join(f'"{a}"' for a in launch_argv("--tray"))


def _desktop_quote(arg: str) -> str:
    """Аргумент для строки Exec= в .desktop-файле (спецификация Desktop Entry)."""
    esc = arg.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%")
    return f'"{esc}"'


def linux_autostart_path() -> Path:
    cfg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(cfg) / "autostart" / "reminders.desktop"


def _desktop_entry(args: list[str], icon: Optional[Path], extra: str = "") -> str:
    exec_line = " ".join(_desktop_quote(a) for a in args)
    lines = ["[Desktop Entry]", "Type=Application", f"Name={APP_NAME}", f"Exec={exec_line}",
             f"Path={base_dir()}", "Terminal=false"]
    if icon is not None:
        lines.append(f"Icon={icon}")
    return "\n".join(lines) + "\n" + extra


def _linux_autostart_entry() -> str:
    return _desktop_entry(launch_argv("--tray"), icon_file(), "X-GNOME-Autostart-enabled=true\n")


# ---- Иконка для ярлыков: файл рядом с данными (не во временной папке) --------------------------
def icon_file() -> Optional[Path]:
    p = data_dir() / ("icon.ico" if sys.platform == "win32" else "icon.png")
    return p if p.exists() else None


def ensure_icon_file() -> Optional[Path]:
    """Создаёт icon.ico (Windows) / icon.png (Linux) в папке данных. Нужен QGuiApplication."""
    try:
        import icons
        d = data_dir(); d.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            path = d / "icon.ico"; icons.export_ico(path)
        else:
            path = d / "icon.png"
            if not icons.app_icon_image(256).save(str(path), "PNG"):
                return None
        return path
    except Exception:
        return None


# ---- Ярлык на рабочем столе ------------------------------------------------------------------
def desktop_dir() -> Path:
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            class GUID(ctypes.Structure):
                _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]
            fid = GUID(0xB4BFCC3A, 0xDB2C, 0x424C, (ctypes.c_ubyte * 8)(0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41))  # FOLDERID_Desktop
            out = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(out)) == 0:  # type: ignore[attr-defined]
                path = out.value
                ctypes.windll.ole32.CoTaskMemFree(out)  # type: ignore[attr-defined]
                if path:
                    return Path(path)
        except Exception:
            pass
        return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    try:
        import subprocess
        r = subprocess.run(["xdg-user-dir", "DESKTOP"], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=3)
        out = r.stdout.strip()
        if r.returncode == 0 and out and Path(out) != Path.home():
            return Path(out)
    except Exception:
        pass
    try:
        cfg = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "user-dirs.dirs"
        for line in cfg.read_text(encoding="utf-8").splitlines():
            if line.startswith("XDG_DESKTOP_DIR="):
                val = line.split("=", 1)[1].strip().strip('"').replace("$HOME", str(Path.home()))
                return Path(val)
    except OSError:
        pass
    return Path.home() / "Desktop"


def _make_lnk(lnk: Path, target: str, args: str, workdir: str, desc: str, icon: Optional[Path]) -> None:
    """.lnk через COM (IShellLink + IPersistFile) на чистом ctypes: без PowerShell, без pywin32,
    без консоли — работает под pythonw, PyInstaller и Nuitka."""
    import ctypes
    from ctypes import HRESULT, WINFUNCTYPE, POINTER, byref, c_void_p, wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]

    ole32 = ctypes.OleDLL("ole32")
    ole32.CoCreateInstance.argtypes = [POINTER(GUID), c_void_p, wintypes.DWORD, POINTER(GUID), POINTER(c_void_p)]
    ole32.CLSIDFromString.argtypes = [wintypes.LPCWSTR, POINTER(GUID)]

    def guid(text: str) -> GUID:
        g = GUID(); ole32.CLSIDFromString("{" + text + "}", byref(g)); return g

    def call(obj: c_void_p, index: int, argtypes: list, *args: object) -> int:
        vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
        return WINFUNCTYPE(HRESULT, c_void_p, *argtypes)(vtbl[index])(obj, *args)

    hr = ole32.CoInitialize(None)
    link, pf = c_void_p(), c_void_p()
    try:
        ole32.CoCreateInstance(byref(guid("00021401-0000-0000-C000-000000000046")), None, 1,   # CLSID_ShellLink, INPROC
                               byref(guid("000214F9-0000-0000-C000-000000000046")), byref(link))  # IID_IShellLinkW
        W = wintypes.LPCWSTR
        call(link, 20, [W], target)                    # SetPath
        call(link, 11, [W], args)                      # SetArguments
        call(link, 9, [W], workdir)                    # SetWorkingDirectory
        call(link, 7, [W], desc)                       # SetDescription
        if icon:
            call(link, 17, [W, ctypes.c_int], str(icon), 0)   # SetIconLocation
        call(link, 0, [POINTER(GUID), POINTER(c_void_p)],      # QueryInterface(IID_IPersistFile)
             byref(guid("0000010B-0000-0000-C000-000000000046")), byref(pf))
        call(pf, 6, [W, wintypes.BOOL], str(lnk), True)        # IPersistFile::Save
    finally:
        for obj in (pf, link):
            if obj.value:
                call(obj, 2, [])                       # Release
        if hr in (0, 1):
            ole32.CoUninitialize()


def _log_error() -> None:
    import traceback
    try:
        with open(data_dir() / "errors.log", "a", encoding="utf-8") as f:
            f.write(f"--- {datetime.now().isoformat(timespec='seconds')} shortcut\n{traceback.format_exc()}")
    except OSError:
        pass


def _pyw_associated() -> bool:
    """Есть ли в Windows программа для .pyw (иначе ярлык на main.pyw не откроется)."""
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(520)
        return ctypes.windll.shell32.FindExecutableW(str(base_dir() / "main.pyw"), None, buf) > 32  # type: ignore[attr-defined]
    except Exception:
        return False


def create_desktop_shortcut() -> bool:
    """Создаёт ярлык «Reminders» с иконкой на рабочем столе. Windows: .lnk; Linux: .desktop."""
    try:
        icon = ensure_icon_file()
        desk = desktop_dir(); desk.mkdir(parents=True, exist_ok=True)
        argv = launch_argv()
        if sys.platform == "win32":
            if IS_FROZEN:
                target, args = argv[0], ""
            elif _pyw_associated():   # обычный Python: ярлык прямо на main.pyw, без интерпретатора
                target, args = argv[1], ""
            else:
                target, args = argv[0], f'"{argv[1]}"'
            lnk = desk / f"{APP_NAME}.lnk"
            _make_lnk(lnk, target, args, str(base_dir()), APP_NAME, icon)
            return lnk.exists()
        path = desk / f"{APP_NAME}.desktop"
        path.write_text(_desktop_entry(argv, icon, "Categories=Utility;\n"), encoding="utf-8")
        path.chmod(0o755)
        try:   # GNOME/Nautilus: пометить как доверенный, иначе «Allow Launching»
            import subprocess
            subprocess.run(["gio", "set", str(path), "metadata::trusted", "true"],
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=5)
        except Exception:
            pass
        return path.exists()
    except Exception:
        _log_error()
        return False


def set_autostart(enabled: bool) -> bool:
    """Включает/выключает автозапуск. Возвращает False при ошибке (или на неподдерживаемой системе)."""
    if sys.platform.startswith("linux"):
        try:
            path = linux_autostart_path()
            if enabled:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(_linux_autostart_entry(), encoding="utf-8")
            else:
                path.unlink(missing_ok=True)
            return True
        except OSError:
            return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, autostart_command())
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False


def refresh_autostart(enabled: bool) -> None:
    """Вызывать при каждом старте: переносимая папка → путь в автозапуске всегда актуален."""
    if enabled:
        set_autostart(True)


def autostart_enabled() -> Optional[bool]:
    if sys.platform.startswith("linux"):
        try:
            return linux_autostart_path().exists()
        except OSError:
            return None
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except FileNotFoundError:
        return False
    except Exception:
        return None
