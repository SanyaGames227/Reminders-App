"""Reminders release builder (PyQt5): PyInstaller and/or Nuitka -> ready-to-publish zip archives.

What it does:
  * finds the project files the program really needs (follows imports from main.pyw),
    without test_logic.py, gallery.py, __pycache__ or anything that is not imported;
  * takes the icon from .reminders-data/icon.ico, or generates it via icons.py if missing;
  * reads the version from core.py (APP_VERSION);
  * builds with the selected builders (all of them can run at once) in a temporary folder;
  * third option, "python": Reminders-python-v<version>.zip with the needed sources only;
  * packs into  Reminders-<builder>-v<version>.zip  ->  folder Reminders-<builder>-v<version>/ ;
  * removes every temporary file, leaving only the archives.

Put the file next to main.pyw and run it (double-click). UI languages: EN / RU / UA.
"""
from __future__ import annotations

import ast
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# ---- Project settings -----------------------------------------------------------------------
APP_NAME = "Reminders"
ENTRY = "main.pyw"
VERSION_FILE = "core.py"
VERSION_VAR = "APP_VERSION"
DATA_DIR = ".reminders-data"
ICON_REL = f"{DATA_DIR}/icon.ico"
ICON_SCRIPT = "icons.py"
EXCLUDE_FILES = {"test_logic.py"}          # never included in a build
EXCLUDE_DIRS = {"__pycache__"}
WORK_DIR_NAME = ".build-work"              # temporary folder inside the project (removed after the build)
OUT_DIR_NAME = "release"                   # where the finished archives go

IS_WIN = sys.platform == "win32"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

TOOLS = {
    "pyinstaller": {"title": "PyInstaller", "pip": ["pyinstaller", "PyQt5"]},
    "nuitka": {"title": "Nuitka", "pip": ["nuitka", "ordered-set", "zstandard", "PyQt5"]},
    "python": {"title": "Python", "pip": []},     # plain archive with the needed .py files, no compiling
}


# =============================================================================================
#  LOCALIZATION
# =============================================================================================
LANGS = {"en": "English", "ru": "Русский", "ua": "Українська"}
LANG = "en"

STR = {
"en": {
    "tool_python": "Python (sources)",
    "err_no_version_file": "{f} not found",
    "err_no_version_var": "No {var} = \"...\" line found in {f}",
    "err_no_entry": "{e} not found in {root}",
    "warn_syntax": "{f}: syntax error ({msg}), imports not parsed",
    "err_cmd_code": "Command exited with code {c}",
    "log_icon_found": "Icon: {p}",
    "log_icon_gen": "{icon} not found - generating via {script}",
    "err_icon_noscript": "{script} is not part of the project, cannot generate the icon",
    "err_icon_nofile": "icons.py finished but icon.ico was not created",
    "err_pyi_nodir": "PyInstaller did not create the {name} folder",
    "err_nuitka_nodist": "Nuitka did not create a *.dist folder",
    "log_done": "Done: {p}",
    "log_files": "Files: {n}",
    "step_copy": "Copying project files",
    "step_icon": "Icon",
    "step_pip": "Installing dependencies (pip)",
    "step_compile": "Compiling",
    "step_compile_long": "Compiling (this takes a while)",
    "step_zip": "Packing into zip",
    "window_title": "{app} builder",
    "grp_paths": "Folders", "lbl_project": "Project:", "lbl_archives": "Archives:", "browse": "Browse…",
    "lbl_language": "Language:",
    "grp_tools": "Builders",
    "keep_work": "Keep temporary files (for debugging)",
    "btn_build": "Build", "btn_cancel": "Cancel", "btn_refresh": "Refresh", "btn_open": "Open archives folder",
    "tab_log": "Log", "tab_files": "Files in the build",
    "info": "Version: <b>{v}</b> (from {f}) &nbsp;|&nbsp; Files: <b>{n}</b> ({kb} KB) &nbsp;|&nbsp; Icon: {icon}",
    "icon_found": "found ({p})",
    "icon_gen": "missing - will be generated via {s}",
    "dlg_root": "Project folder", "dlg_out": "Archives folder",
    "pick_tool": "Select at least one builder.",
    "queued": "queued…",
    "cancelling": "Cancelling…",
    "cancelled": "cancelled",
    "res_ok": "DONE: ", "res_err": "ERROR: ",
    "all_done": "All archives are in: {p}",
    "close_q": "A build is running. Abort and exit?",
},
"ru": {
    "tool_python": "Python (исходники)",
    "err_no_version_file": "Не найден {f}",
    "err_no_version_var": "В {f} не найдена строка {var} = \"...\"",
    "err_no_entry": "Не найден {e} в {root}",
    "warn_syntax": "{f}: синтаксическая ошибка ({msg}), импорты не разобраны",
    "err_cmd_code": "Команда завершилась с кодом {c}",
    "log_icon_found": "Иконка: {p}",
    "log_icon_gen": "{icon} не найдена - генерирую через {script}",
    "err_icon_noscript": "{script} не входит в проект, иконку сгенерировать нельзя",
    "err_icon_nofile": "icons.py отработал, но icon.ico не создан",
    "err_pyi_nodir": "PyInstaller не создал папку {name}",
    "err_nuitka_nodist": "Nuitka не создал папку *.dist",
    "log_done": "Готово: {p}",
    "log_files": "Файлов: {n}",
    "step_copy": "Копирую файлы проекта",
    "step_icon": "Иконка",
    "step_pip": "Устанавливаю зависимости (pip)",
    "step_compile": "Компиляция",
    "step_compile_long": "Компиляция (это долго)",
    "step_zip": "Упаковываю в zip",
    "window_title": "Сборщик {app}",
    "grp_paths": "Папки", "lbl_project": "Проект:", "lbl_archives": "Архивы:", "browse": "Обзор…",
    "lbl_language": "Язык:",
    "grp_tools": "Сборщики",
    "keep_work": "Не удалять временные файлы (для отладки)",
    "btn_build": "Собрать", "btn_cancel": "Отмена", "btn_refresh": "Обновить", "btn_open": "Открыть папку с архивами",
    "tab_log": "Лог", "tab_files": "Файлы в сборке",
    "info": "Версия: <b>{v}</b> (из {f}) &nbsp;|&nbsp; Файлов: <b>{n}</b> ({kb} КБ) &nbsp;|&nbsp; Иконка: {icon}",
    "icon_found": "найдена ({p})",
    "icon_gen": "нет - будет сгенерирована через {s}",
    "dlg_root": "Папка проекта", "dlg_out": "Папка для архивов",
    "pick_tool": "Выберите хотя бы один сборщик.",
    "queued": "в очереди…",
    "cancelling": "Отмена…",
    "cancelled": "отменено",
    "res_ok": "ГОТОВО: ", "res_err": "ОШИБКА: ",
    "all_done": "Все архивы в: {p}",
    "close_q": "Идёт сборка. Прервать и выйти?",
},
"ua": {
    "tool_python": "Python (вихідний код)",
    "err_no_version_file": "Не знайдено {f}",
    "err_no_version_var": "У {f} не знайдено рядок {var} = \"...\"",
    "err_no_entry": "Не знайдено {e} у {root}",
    "warn_syntax": "{f}: синтаксична помилка ({msg}), імпорти не розібрано",
    "err_cmd_code": "Команда завершилася з кодом {c}",
    "log_icon_found": "Іконка: {p}",
    "log_icon_gen": "{icon} не знайдено - генерую через {script}",
    "err_icon_noscript": "{script} не входить до проєкту, іконку згенерувати неможливо",
    "err_icon_nofile": "icons.py відпрацював, але icon.ico не створено",
    "err_pyi_nodir": "PyInstaller не створив теку {name}",
    "err_nuitka_nodist": "Nuitka не створила теку *.dist",
    "log_done": "Готово: {p}",
    "log_files": "Файлів: {n}",
    "step_copy": "Копіюю файли проєкту",
    "step_icon": "Іконка",
    "step_pip": "Встановлюю залежності (pip)",
    "step_compile": "Компіляція",
    "step_compile_long": "Компіляція (це довго)",
    "step_zip": "Пакую в zip",
    "window_title": "Збирач {app}",
    "grp_paths": "Теки", "lbl_project": "Проєкт:", "lbl_archives": "Архіви:", "browse": "Огляд…",
    "lbl_language": "Мова:",
    "grp_tools": "Збирачі",
    "keep_work": "Не видаляти тимчасові файли (для налагодження)",
    "btn_build": "Зібрати", "btn_cancel": "Скасувати", "btn_refresh": "Оновити", "btn_open": "Відкрити теку з архівами",
    "tab_log": "Лог", "tab_files": "Файли у збірці",
    "info": "Версія: <b>{v}</b> (з {f}) &nbsp;|&nbsp; Файлів: <b>{n}</b> ({kb} КБ) &nbsp;|&nbsp; Іконка: {icon}",
    "icon_found": "знайдено ({p})",
    "icon_gen": "немає - буде згенерована через {s}",
    "dlg_root": "Тека проєкту", "dlg_out": "Тека для архівів",
    "pick_tool": "Оберіть хоча б один збирач.",
    "queued": "у черзі…",
    "cancelling": "Скасування…",
    "cancelled": "скасовано",
    "res_ok": "ГОТОВО: ", "res_err": "ПОМИЛКА: ",
    "all_done": "Усі архіви в: {p}",
    "close_q": "Триває збірка. Перервати й вийти?",
},
}


def set_lang(code: str) -> None:
    global LANG
    LANG = code if code in STR else "en"


def tr(key: str, **kw) -> str:
    text = STR[LANG].get(key) or STR["en"][key]
    return text.format(**kw) if kw else text


def tool_title(tool: str) -> str:
    return tr("tool_python") if tool == "python" else TOOLS[tool]["title"]


# =============================================================================================
#  LOGIC (no Qt)
# =============================================================================================
class BuildError(Exception):
    pass


class Cancelled(Exception):
    pass


def python_exe() -> str:
    """Under pythonw.exe (.pyw launch) use the sibling python.exe so pip/builders can print output."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        return str(exe.with_name("python.exe"))
    return str(exe)


def rmtree(path: Path) -> None:
    def handler(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    kw = {"onexc": handler} if sys.version_info >= (3, 12) else {"onerror": handler}
    for _ in range(6):                      # antivirus/indexer sometimes hold files for a moment
        if not path.exists():
            return
        shutil.rmtree(path, **kw)
        if path.exists():
            time.sleep(0.4)


def read_version(root: Path) -> str:
    f = root / VERSION_FILE
    if not f.is_file():
        raise BuildError(tr("err_no_version_file", f=VERSION_FILE))
    m = re.search(rf"^\s*{VERSION_VAR}\s*(?::\s*\w+\s*)?=\s*[\"']([^\"']+)[\"']",
                  f.read_text(encoding="utf-8-sig"), re.M)
    if not m:
        raise BuildError(tr("err_no_version_var", f=VERSION_FILE, var=VERSION_VAR))
    return m.group(1).strip()


def collect_files(root: Path, entry: str = ENTRY) -> tuple[list[Path], list[str]]:
    """Follow local imports transitively from entry. Returns (files relative to root, warnings)."""
    warnings: list[str] = []
    entry_path = root / entry
    if not entry_path.is_file():
        raise BuildError(tr("err_no_entry", e=entry, root=root))

    def is_excluded(p: Path) -> bool:
        return p.name in EXCLUDE_FILES or any(part in EXCLUDE_DIRS for part in p.parts)

    def resolve(parts: list[str]) -> Path | None:
        if not parts:
            return None
        base = root.joinpath(*parts)
        for cand in (base.with_suffix(".py"), base / "__init__.py"):
            if cand.is_file() and not is_excluded(cand.relative_to(root)):
                return cand
        return None

    def with_parents(parts: list[str]) -> list[Path]:
        """Module a.b.c -> a/__init__.py, a/b/__init__.py, a/b/c.py (те, что существуют)."""
        found = []
        for i in range(1, len(parts) + 1):
            p = resolve(parts[:i])
            if p is not None:
                found.append(p)
        return found if resolve(parts) is not None else []

    seen: dict[Path, None] = {}
    queue: list[Path] = [entry_path]
    while queue:
        cur = queue.pop()
        if cur in seen:
            continue
        seen[cur] = None
        try:
            tree = ast.parse(cur.read_bytes(), filename=str(cur))
        except SyntaxError as e:
            warnings.append(tr("warn_syntax", f=cur.relative_to(root).as_posix(), msg=e.msg))
            continue
        pkg = list(cur.relative_to(root).parent.parts)
        targets: list[list[str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                targets += [a.name.split(".") for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    keep = len(pkg) - (node.level - 1)
                    if keep < 0:
                        continue
                    base = pkg[:keep] + (node.module.split(".") if node.module else [])
                else:
                    base = node.module.split(".") if node.module else []
                if base:
                    targets.append(base)
                targets += [base + [a.name] for a in node.names if a.name != "*"]
        for parts in targets:
            for p in with_parents(parts):
                if p not in seen:
                    queue.append(p)
    files = sorted((p.relative_to(root) for p in seen), key=lambda p: p.as_posix())
    return files, warnings


def stage_files(root: Path, files: list[Path], dest: Path) -> None:
    for rel in files:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, target)


def make_archive(src_dir: Path, archive: Path, top_name: str, check) -> None:
    """zip: <top_name>/<all contents of src_dir>. Writes to a temp file, then renames."""
    tmp = archive.with_suffix(".zip.part")
    archive.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            z.write(src_dir, top_name + "/")
            for p in sorted(src_dir.rglob("*")):
                check()
                if "__pycache__" in p.parts:
                    continue
                arc = f"{top_name}/{p.relative_to(src_dir).as_posix()}"
                z.write(p, arc + "/" if p.is_dir() else arc)
        os.replace(tmp, archive)
    finally:
        if tmp.exists():
            tmp.unlink()


def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        proc.kill()


@dataclass
class Config:
    root: Path
    out_dir: Path
    version: str
    files: list[Path]
    keep_work: bool = False

    @property
    def work_root(self) -> Path:
        return self.root / WORK_DIR_NAME


@dataclass
class Shared:
    """Shared between parallel builds: pip/icon locks and the cancel flag."""
    pip_lock: threading.Lock = field(default_factory=threading.Lock)
    icon_lock: threading.Lock = field(default_factory=threading.Lock)
    cancel: threading.Event = field(default_factory=threading.Event)


class Pipeline:
    def __init__(self, tool: str, cfg: Config, shared: Shared, log, status):
        self.tool, self.cfg, self.shared = tool, cfg, shared
        self._log, self._status = log, status
        self.proc: subprocess.Popen | None = None

    # -- helpers --
    def check(self) -> None:
        if self.shared.cancel.is_set():
            raise Cancelled()

    def log(self, text: str) -> None:
        self._log(self.tool, text)

    def step(self, text: str) -> None:
        self.check()
        self.log(f"=== {text}")
        self._status(self.tool, text)

    def cancel_proc(self) -> None:
        if self.proc is not None:
            kill_tree(self.proc)

    def run_cmd(self, cmd: list[str], cwd: Path) -> None:
        self.check()
        self.log("$ " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
        env = os.environ.copy()
        env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
        kw: dict = {"creationflags": NO_WINDOW} if IS_WIN else {"start_new_session": True}
        self.proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", **kw)
        try:
            for line in self.proc.stdout:           # type: ignore[union-attr]
                line = line.rstrip()
                if line:
                    self.log(line)
                if self.shared.cancel.is_set():
                    kill_tree(self.proc)
            code = self.proc.wait()
        finally:
            self.proc = None
        self.check()
        if code != 0:
            raise BuildError(tr("err_cmd_code", c=code))

    # -- steps --
    def ensure_icon(self) -> Path:
        with self.shared.icon_lock:
            user_icon = self.cfg.root / ICON_REL
            if user_icon.is_file():
                self.log(tr("log_icon_found", p=ICON_REL))
                return user_icon
            gen_dir = self.cfg.work_root / "icon"
            gen = gen_dir / "icon.ico"
            if gen.is_file():
                return gen
            self.log(tr("log_icon_gen", icon=ICON_REL, script=ICON_SCRIPT))
            if Path(ICON_SCRIPT) not in self.cfg.files:
                raise BuildError(tr("err_icon_noscript", script=ICON_SCRIPT))
            gen_dir.mkdir(parents=True, exist_ok=True)       # export_ico does not create the folder itself
            stage_files(self.cfg.root, self.cfg.files, gen_dir / "src")
            self.run_cmd([python_exe(), ICON_SCRIPT, str(gen)], gen_dir / "src")
            if not gen.is_file():
                raise BuildError(tr("err_icon_nofile"))
            return gen

    def pip_install(self) -> None:
        pkgs = TOOLS[self.tool]["pip"]
        while not self.shared.pip_lock.acquire(timeout=0.3):
            self.check()
        try:
            self.run_cmd([python_exe(), "-m", "pip", "install", "-q", *pkgs], self.cfg.root)
        finally:
            self.shared.pip_lock.release()

    def build_pyinstaller(self, src: Path, work: Path, icon: Path) -> Path:
        dist = work / "dist"
        self.run_cmd([python_exe(), "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
                      "--name", APP_NAME, "--distpath", str(dist), "--workpath", str(work / "build"),
                      "--specpath", str(work / "spec"), "--icon", str(icon), "--exclude-module", "tkinter",
                      str(src / ENTRY)], src)
        out = dist / APP_NAME
        if not out.is_dir():
            raise BuildError(tr("err_pyi_nodir", name=out.name))
        return out

    def build_nuitka(self, src: Path, work: Path, icon: Path) -> Path:
        out_dir = work / "out"
        exe_name = APP_NAME + (".exe" if IS_WIN else "")
        cmd = [python_exe(), "-m", "nuitka", "--standalone", "--enable-plugin=pyqt5"]
        if IS_WIN:
            cmd += ["--windows-console-mode=disable", f"--windows-icon-from-ico={icon}"]
        cmd += ["--include-qt-plugins=sensible,styles", f"--output-filename={exe_name}",
                f"--output-dir={out_dir}", "--assume-yes-for-downloads", "--remove-output",
                "--nofollow-import-to=tkinter", str(src / ENTRY)]
        self.run_cmd(cmd, src)
        dists = sorted(out_dir.glob("*.dist"))
        if not dists:
            raise BuildError(tr("err_nuitka_nodist"))
        return dists[0]

    def run(self) -> Path:
        cfg = self.cfg
        work = cfg.work_root / self.tool
        top = f"{APP_NAME}-{self.tool}-v{cfg.version}"
        archive = cfg.out_dir / f"{top}.zip"
        try:
            rmtree(work)
            work.mkdir(parents=True)
            self.step(tr("step_copy"))
            src = work / "src"
            stage_files(cfg.root, cfg.files, src)
            self.log(tr("log_files", n=len(cfg.files)))
            if self.tool == "python":
                self.step(tr("step_zip"))
                make_archive(src, archive, top, self.check)
                self.log(tr("log_done", p=archive))
                return archive
            self.step(tr("step_icon"))
            icon = self.ensure_icon()
            self.step(tr("step_pip"))
            self.pip_install()
            self.step(tr("step_compile_long") if self.tool == "nuitka" else tr("step_compile"))
            dist_dir = (self.build_pyinstaller if self.tool == "pyinstaller" else self.build_nuitka)(src, work, icon)
            self.step(tr("step_zip"))
            make_archive(dist_dir, archive, top, self.check)
            self.log(tr("log_done", p=archive))
            return archive
        finally:
            self.proc = None
            if not cfg.keep_work:
                rmtree(work)


# =============================================================================================
#  GUI
# =============================================================================================
from PyQt5.QtCore import QLocale, QThread, Qt, QUrl, pyqtSignal  # noqa: E402
from PyQt5.QtGui import QDesktopServices, QFont  # noqa: E402
from PyQt5.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QGridLayout, QGroupBox,  # noqa: E402
                             QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
                             QPushButton, QTabWidget, QVBoxLayout, QWidget)


def detect_lang() -> str:
    """UI language: system language if supported (ru / uk -> ua), otherwise English."""
    code = QLocale.system().name().split("_")[0].lower()
    return {"ru": "ru", "uk": "ua"}.get(code, "en")


class Worker(QThread):
    log = pyqtSignal(str, str)
    status = pyqtSignal(str, str)
    result = pyqtSignal(str, bool, str)     # tool, ok, text (archive path or error)

    def __init__(self, tool: str, cfg: Config, shared: Shared):
        super().__init__()
        self.pipeline = Pipeline(tool, cfg, shared, self.log.emit, self.status.emit)
        self.tool = tool

    def run(self) -> None:
        try:
            self.result.emit(self.tool, True, str(self.pipeline.run()))
        except Cancelled:
            self.result.emit(self.tool, False, tr("cancelled"))
        except BuildError as e:
            self.result.emit(self.tool, False, str(e))
        except Exception as e:                   # noqa: BLE001
            self.result.emit(self.tool, False, f"{type(e).__name__}: {e}")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.resize(820, 660)
        self.workers: dict[str, Worker] = {}
        self.shared = Shared()
        self.cfg: Config | None = None
        self.results: dict[str, tuple[bool, str]] = {}

        here = Path(__file__).resolve().parent
        self.root_edit = QLineEdit(str(here))
        self.out_edit = QLineEdit(str(here / OUT_DIR_NAME))
        for e in (self.root_edit, self.out_edit):
            e.editingFinished.connect(self.refresh)

        self.paths_box = QGroupBox()
        g = QGridLayout(self.paths_box)
        self.path_labels: list[QLabel] = []
        self.browse_btns: list[QPushButton] = []
        for row, (edit, slot) in enumerate(((self.root_edit, self.pick_root), (self.out_edit, self.pick_out))):
            lab, b = QLabel(), QPushButton()
            b.clicked.connect(slot)
            self.path_labels.append(lab)
            self.browse_btns.append(b)
            g.addWidget(lab, row, 0)
            g.addWidget(edit, row, 1)
            g.addWidget(b, row, 2)

        self.lang_label = QLabel()
        self.lang_combo = QComboBox()
        for code, name in LANGS.items():
            self.lang_combo.addItem(name, code)
        self.lang_combo.setCurrentIndex(self.lang_combo.findData(LANG))
        self.lang_combo.currentIndexChanged.connect(self.on_lang_changed)
        lang_row = QHBoxLayout()
        lang_row.addStretch(1)
        lang_row.addWidget(self.lang_label)
        lang_row.addWidget(self.lang_combo)

        self.info_label = QLabel()
        self.info_label.setTextFormat(Qt.RichText)
        self.info_label.setWordWrap(True)

        self.tools_box = QGroupBox()
        tl = QGridLayout(self.tools_box)
        self.checks: dict[str, QCheckBox] = {}
        self.status_labels: dict[str, QLabel] = {}
        for row, key in enumerate(TOOLS):
            cb = QCheckBox()
            cb.setChecked(True)
            lab = QLabel("—")
            lab.setWordWrap(True)
            self.checks[key], self.status_labels[key] = cb, lab
            tl.addWidget(cb, row, 0)
            tl.addWidget(lab, row, 1)
        tl.setColumnStretch(1, 1)
        self.keep_cb = QCheckBox()

        self.build_btn = QPushButton()
        self.build_btn.setDefault(True)
        self.build_btn.clicked.connect(self.start)
        self.cancel_btn = QPushButton()
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel)
        self.refresh_btn = QPushButton()
        self.refresh_btn.clicked.connect(self.refresh)
        self.open_btn = QPushButton()
        self.open_btn.clicked.connect(self.open_out)
        btns = QHBoxLayout()
        for b in (self.build_btn, self.cancel_btn, self.refresh_btn):
            btns.addWidget(b)
        btns.addStretch(1)
        btns.addWidget(self.open_btn)

        mono = QFont("Consolas" if IS_WIN else "monospace")
        mono.setStyleHint(QFont.Monospace)
        self.log_view = QPlainTextEdit(readOnly=True)
        self.log_view.setMaximumBlockCount(30000)
        self.log_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log_view.setFont(mono)
        self.files_view = QPlainTextEdit(readOnly=True)
        self.files_view.setFont(mono)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.log_view, "")
        self.tabs.addTab(self.files_view, "")

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.addLayout(lang_row)
        for w in (self.paths_box, self.info_label, self.tools_box, self.keep_cb):
            lay.addWidget(w)
        lay.addLayout(btns)
        lay.addWidget(self.tabs, 1)
        self.setCentralWidget(central)
        self.retranslate()

    # -- localization --
    def retranslate(self) -> None:
        self.setWindowTitle(tr("window_title", app=APP_NAME))
        self.paths_box.setTitle(tr("grp_paths"))
        for lab, key in zip(self.path_labels, ("lbl_project", "lbl_archives")):
            lab.setText(tr(key))
        for b in self.browse_btns:
            b.setText(tr("browse"))
        self.lang_label.setText(tr("lbl_language"))
        self.tools_box.setTitle(tr("grp_tools"))
        for key, cb in self.checks.items():
            cb.setText(tool_title(key))
        self.keep_cb.setText(tr("keep_work"))
        self.build_btn.setText(tr("btn_build"))
        self.cancel_btn.setText(tr("btn_cancel"))
        self.refresh_btn.setText(tr("btn_refresh"))
        self.open_btn.setText(tr("btn_open"))
        self.tabs.setTabText(0, tr("tab_log"))
        self.tabs.setTabText(1, tr("tab_files"))
        self.refresh()

    def on_lang_changed(self) -> None:
        set_lang(self.lang_combo.currentData())
        self.retranslate()

    # -- folders / project state --
    def pick_root(self) -> None:
        d = QFileDialog.getExistingDirectory(self, tr("dlg_root"), self.root_edit.text())
        if d:
            self.root_edit.setText(d)
            self.out_edit.setText(str(Path(d) / OUT_DIR_NAME))
            self.refresh()

    def pick_out(self) -> None:
        d = QFileDialog.getExistingDirectory(self, tr("dlg_out"), self.out_edit.text())
        if d:
            self.out_edit.setText(d)

    def open_out(self) -> None:
        p = Path(self.out_edit.text())
        p.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def refresh(self) -> None:
        self.cfg = None
        root = Path(self.root_edit.text().strip())
        try:
            version = read_version(root)
            files, warns = collect_files(root)
        except BuildError as e:
            self.info_label.setText(f"<span style='color:#c0392b'>⚠ {e}</span>")
            self.files_view.setPlainText("")
            return
        has_icon = (root / ICON_REL).is_file()
        size = sum((root / f).stat().st_size for f in files)
        icon_txt = tr("icon_found", p=ICON_REL) if has_icon else tr("icon_gen", s=ICON_SCRIPT)
        html = tr("info", v=version, f=VERSION_FILE, n=len(files), kb=f"{size / 1024:.0f}", icon=icon_txt)
        if warns:
            html += "<br><span style='color:#c0392b'>" + "<br>".join(warns) + "</span>"
        self.info_label.setText(html)
        self.files_view.setPlainText("\n".join(f.as_posix() for f in files))
        self.cfg = Config(root, Path(self.out_edit.text().strip()), version, files)

    # -- build --
    def selected(self) -> list[str]:
        return [k for k, cb in self.checks.items() if cb.isChecked()]

    def set_running(self, running: bool) -> None:
        self.build_btn.setEnabled(not running)
        self.refresh_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        for w in (self.root_edit, self.out_edit, self.keep_cb, self.lang_combo, *self.checks.values()):
            w.setEnabled(not running)

    def start(self) -> None:
        self.refresh()
        if self.cfg is None:
            return
        tools = self.selected()
        if not tools:
            QMessageBox.information(self, APP_NAME, tr("pick_tool"))
            return
        self.cfg.keep_work = self.keep_cb.isChecked()
        self.shared = Shared()
        self.results.clear()
        self.log_view.clear()
        for k, lab in self.status_labels.items():
            lab.setText(tr("queued") if k in tools else "—")
        self.set_running(True)
        self.workers = {}
        for t in tools:
            w = Worker(t, self.cfg, self.shared)
            w.log.connect(self.on_log)
            w.status.connect(lambda tool, text: self.status_labels[tool].setText("⏳ " + text))
            w.result.connect(self.on_result)
            self.workers[t] = w
        for w in self.workers.values():
            w.start()

    def cancel(self) -> None:
        self.cancel_btn.setEnabled(False)
        self.shared.cancel.set()
        for w in self.workers.values():
            w.pipeline.cancel_proc()
        self.on_log("", tr("cancelling"))

    def on_log(self, tool: str, text: str) -> None:
        prefix = f"[{tool_title(tool)}] " if tool else ""
        hbar, vbar = self.log_view.horizontalScrollBar(), self.log_view.verticalScrollBar()
        h = hbar.value()                    # a long line must not shift the viewport sideways
        self.log_view.appendPlainText(prefix + text)
        hbar.setValue(h)
        vbar.setValue(vbar.maximum())

    def on_result(self, tool: str, ok: bool, text: str) -> None:
        self.results[tool] = (ok, text)
        lab = self.status_labels[tool]
        lab.setText(f"✔ {Path(text).name}" if ok else f"✖ {text}")
        self.on_log(tool, tr("res_ok" if ok else "res_err") + text)
        if len(self.results) < len(self.workers):
            return
        for w in self.workers.values():
            w.wait()
        if self.cfg is not None and not self.cfg.keep_work:
            rmtree(self.cfg.work_root)
        self.set_running(False)
        if all(ok for ok, _ in self.results.values()):
            self.on_log("", tr("all_done", p=self.cfg.out_dir if self.cfg else ""))

    def closeEvent(self, ev) -> None:       # noqa: N802
        if any(w.isRunning() for w in self.workers.values()):
            if QMessageBox.question(self, APP_NAME, tr("close_q")) != QMessageBox.Yes:
                ev.ignore()
                return
            self.shared.cancel.set()
            for w in self.workers.values():
                w.pipeline.cancel_proc()
            for w in self.workers.values():
                w.wait(15000)
            if self.cfg is not None and not self.cfg.keep_work:
                rmtree(self.cfg.work_root)
        ev.accept()


def main() -> int:
    app = QApplication(sys.argv)
    set_lang(detect_lang())
    win = MainWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
