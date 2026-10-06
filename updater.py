"""Проверка обновлений: один запрос к GitHub в фоновом потоке, результат — сигналом в основной поток.

Ничего не скачивает и не ставит: только узнаёт, вышла ли версия новее текущей. Интерфейс не блокируется.
Любая ошибка (нет сети, лимит запросов, непонятный ответ) даёт статус FAILED — показывать ли её, решает вызывающий код.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal

import core
from core import Release

FOUND, CURRENT, FAILED = "found", "current", "failed"
TIMEOUT_S = 10


@dataclass
class UpdateResult:
    status: str                       # FOUND | CURRENT | FAILED
    manual: bool = False              # проверка запущена пользователем (ошибки и «всё свежее» показываются)
    release: Optional[Release] = None  # заполнено при FOUND


def fetch_latest() -> Optional[Release]:
    """Последний стабильный релиз или None, если релизов ещё нет. Бросает OSError/ValueError при сбое."""
    req = urllib.request.Request(core.RELEASES_API, headers={
        "User-Agent": f"Reminders/{core.APP_VERSION}", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return core.parse_release(json.load(resp))
    except urllib.error.HTTPError as e:
        if e.code == 404:             # релизов нет — значит, и обновления нет
            return None
        raise


def check_now() -> UpdateResult:
    """Синхронная проверка (вызывается из потока). Не бросает исключений."""
    try:
        release = fetch_latest()
    except (OSError, ValueError):      # URLError, таймаут, HTTP-ошибка, битый JSON — всё сюда
        return UpdateResult(FAILED)
    if release is not None and core.is_newer(release.tag, core.APP_VERSION):
        return UpdateResult(FOUND, release=release)
    return UpdateResult(CURRENT)


class Updater(QObject):
    done = pyqtSignal(object)         # UpdateResult
    _finished = pyqtSignal(object)    # из рабочего потока → в основной (queued-соединение)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._busy = False
        self._manual = False
        self._finished.connect(self._on_finished)

    def check(self, manual: bool = False) -> None:
        """Запускает проверку в фоне. Если уже идёт — повторно не стартует; ручной запрос лишь «забирает» результат."""
        self._manual = self._manual or manual
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._work, name="update-check", daemon=True).start()

    def _work(self) -> None:
        result = check_now()
        try:
            self._finished.emit(result)
        except RuntimeError:           # программа уже закрылась, пока шёл запрос
            pass

    def _on_finished(self, result: UpdateResult) -> None:
        result.manual, self._busy, self._manual = self._manual, False, False
        self.done.emit(result)
