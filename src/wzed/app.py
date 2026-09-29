"""wzed: orchestrator + tray. Phase 1: global PTT → STT → rules → injection → history.

Run: uv run python -m wzed
"""

from __future__ import annotations

import logging
import os
import sys
import time

import win32api
import win32con
import win32event
import winerror
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from wzed import config as cfg_mod
from wzed.audio.capture import Recorder
from wzed.history.store import HistoryStore
from wzed.hotkeys.manager import HotkeyManager
from wzed.inject.injector import Injector, active_process_name
from wzed.postproc.rules import Rules, ensure_dictionary_file
from wzed.stt.engines import create_engine
from wzed.ui.hud import RecordingHud

log = logging.getLogger("wzed")

_PTT_VKS = (
    win32con.VK_CONTROL,
    win32con.VK_MENU,
    win32con.VK_SHIFT,
    win32con.VK_LWIN,
    win32con.VK_RWIN,
)


_MUTEX_NAME = "Local\\wzed-single-instance"
_mutex_handle = None  # kept alive for the whole process; Windows releases it on exit


def _acquire_single_instance() -> bool:
    """Prevent a second instance (autostart + Start Menu click = everything duplicated).

    Without this, each instance installs its own hook, records and injects: the text comes out twice.
    """
    global _mutex_handle
    try:
        _mutex_handle = win32event.CreateMutex(None, False, _MUTEX_NAME)
        return win32api.GetLastError() != winerror.ERROR_ALREADY_EXISTS
    except Exception:  # noqa: BLE001 - a mutex failure must not stop the app from running
        log.warning("não foi possível criar o mutex de instância única", exc_info=True)
        return True


def _wait_modifiers_released(timeout_s: float = 1.5) -> None:
    """Do not inject while physical Ctrl/Alt/Win are still held (it would trigger a shortcut in the target app)."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not any(win32api.GetAsyncKeyState(vk) & 0x8000 for vk in _PTT_VKS):
            return
        time.sleep(0.02)


def _open_dictionary() -> None:
    """Opens dictionary.txt in the default editor (creates it with a template on first use)."""
    try:
        os.startfile(ensure_dictionary_file())  # noqa: S606 - local file we own
    except Exception:  # noqa: BLE001 - a tray click must never take the app down
        log.exception("falha ao abrir o dicionário")


def _icon(color: str) -> QIcon:
    pm = QPixmap(32, 32)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(QColor("#222222"))
    p.drawEllipse(4, 4, 24, 24)
    p.end()
    return QIcon(pm)


class _UiBridge(QObject):
    """Thread-safe bridge: the PTT runs on its own thread and Qt only accepts widget
    updates on the GUI thread. The signal crosses over to it (queued connection)."""

    state = Signal(str)


# internal state -> HUD state
_HUD_STATE = {"rec": "recording", "busy": "processing", "idle": "idle"}


class WzedApp:
    def __init__(self) -> None:
        self.cfg = cfg_mod.load()
        # QApplication before any QWidget (the HUD is one)
        self.qt = QApplication(sys.argv)
        self.qt.setQuitOnLastWindowClosed(False)
        self.hud = RecordingHud() if self.cfg.show_hud else None
        self._ui = _UiBridge()
        self._ui.state.connect(self._apply_state)

        self.rules = Rules()
        self.history = HistoryStore()
        self.injector = Injector(self.cfg.inject)
        self.recorder = Recorder(
            self.cfg.audio.sample_rate,
            self.cfg.audio.device,
            self.cfg.audio.max_utterance_s,
            level_callback=self.hud.push_level if self.hud else None,
        )
        log.info(Recorder.check_device(self.cfg.audio.device, self.cfg.audio.sample_rate))
        log.info("carregando engine %s (%s)...", self.cfg.stt.engine, self.cfg.stt.device)
        t0 = time.perf_counter()
        self.stt = create_engine(self.cfg.stt.engine, self.cfg.stt.device)
        log.info("engine pronto em %.1fs", time.perf_counter() - t0)

        self._icons = {
            "idle": _icon("#8a8a8a"),
            "rec": _icon("#e04040"),
            "busy": _icon("#4080e0"),
        }
        self.tray = QSystemTrayIcon(self._icons["idle"])
        menu = QMenu()
        self._status_action = QAction(f"wzed · {self.cfg.stt.engine} · {self.cfg.stt.language}")
        self._status_action.setEnabled(False)
        menu.addAction(self._status_action)
        menu.addSeparator()
        # no "reload" item: Rules re-reads the file by mtime on every dictation
        abrir_dict = QAction("Abrir dicionário")
        abrir_dict.triggered.connect(_open_dictionary)
        menu.addAction(abrir_dict)
        sair = QAction("Sair")
        sair.triggered.connect(self.qt.quit)
        menu.addAction(sair)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("wzed: segure o atalho e fale")
        self.tray.show()

        self.hotkeys = HotkeyManager()
        self.hotkeys.bind_ptt(
            self.cfg.hotkeys.push_to_talk, self._ptt_down, self._ptt_up
        )
        self.hotkeys.start()
        log.info("PTT: segure %s para ditar", self.cfg.hotkeys.push_to_talk)

    def _set_state(self, state: str) -> None:
        """Callable from any thread; the signal delivers on the GUI thread."""
        self._ui.state.emit(state)

    def _apply_state(self, state: str) -> None:
        self.tray.setIcon(self._icons[state])
        if self.hud:
            self.hud.set_state(_HUD_STATE[state])

    def _ptt_down(self) -> None:
        try:
            self.recorder.start()
            self._set_state("rec")
        except Exception:
            log.exception("falha ao iniciar captura")

    def _ptt_up(self) -> None:
        try:
            audio = self.recorder.stop()
            self._set_state("busy")
            if len(audio) < self.cfg.audio.sample_rate * 0.3:  # < 300 ms: click noise
                self._set_state("idle")
                return
            t0 = time.perf_counter()
            raw = self.stt.transcribe(
                audio, self.cfg.stt.language, self.rules.hint_terms()
            )
            final = self.rules.apply(raw)
            latency_ms = (time.perf_counter() - t0) * 1000
            app_name = active_process_name()
            if final:
                self._set_state("idle")  # hide the HUD BEFORE typing into the app
                _wait_modifiers_released()
                tecnica = self.injector.inject(final)
                self.history.add(raw, final, app_name, self.cfg.stt.language, latency_ms)
                log.info("[%.0f ms] (%s→%s) %s", latency_ms, app_name, tecnica, final)
        except Exception:
            log.exception("falha no pipeline de ditado")
        finally:
            self._set_state("idle")

    def run(self) -> int:
        try:
            return self.qt.exec()
        finally:
            self.hotkeys.stop()
            self.history.close()


def _setup_logging() -> None:
    """Logs to %APPDATA%\\wzed\\wzed.log (running as an .exe without a console there is no stderr)
    and also to the console when one is present."""
    from logging.handlers import RotatingFileHandler

    from wzed.config import APP_DIR

    APP_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname).1s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fileh = RotatingFileHandler(
        APP_DIR / "wzed.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    fileh.setFormatter(fmt)
    root.addHandler(fileh)
    if sys.stderr:  # a console is present (launched from a terminal)
        con = logging.StreamHandler()
        con.setFormatter(fmt)
        root.addHandler(con)


def main() -> int:
    _setup_logging()
    if not _acquire_single_instance():
        log.warning("já existe uma instância do wzed rodando; encerrando esta.")
        return 0
    try:
        return WzedApp().run()
    except Exception:
        log.exception("wzed encerrou por erro fatal")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
