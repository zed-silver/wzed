"""Recording HUD: pill at the bottom of the screen with a mic-reactive waveform.

Critical requirement: the window can NEVER receive focus or clicks. The injector writes to the
foreground window, so a HUD that activated would steal the target of the text. Hence
WA_ShowWithoutActivating + WS_EX_NOACTIVATE/TRANSPARENT/TOOLWINDOW.

States: "recording" (bars react to audio) → "processing" (running wave) → "idle" (fade out).
"""

from __future__ import annotations

import math
from collections import deque

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

BARS = 42
BAR_W = 3.0
BAR_GAP = 3.0
PILL_W = int(BARS * (BAR_W + BAR_GAP) + 44)
PILL_H = 52
MARGIN_BOTTOM = 90
FPS = 30

_BG = QColor(22, 22, 26, 235)
_BORDER = QColor(255, 255, 255, 28)
_REC = QColor(255, 255, 255, 235)
_PROC = QColor(96, 165, 250, 235)


def _norm_level(rms: float) -> float:
    """Linear RMS → 0..1 on a dB scale (hearing is logarithmic; linear barely moves)."""
    if rms <= 1e-6:
        return 0.0
    db = 20.0 * math.log10(rms)
    v = (db + 55.0) / 55.0  # -55 dBFS .. 0 dBFS
    return max(0.0, min(1.0, v)) ** 0.75


class RecordingHud(QWidget):
    _level_sig = Signal(float)
    _state_sig = Signal(str)

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool  # outside the taskbar and Alt+Tab
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput  # clicks pass through
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.resize(PILL_W, PILL_H)

        self._state = "idle"
        self._raw = 0.0  # last raw RMS (written by the slot, read by the timer)
        self._smooth = 0.0
        self._phase = 0.0
        self._hist: deque[float] = deque([0.0] * BARS, maxlen=BARS)

        self._timer = QTimer(self)
        self._timer.setInterval(int(1000 / FPS))
        self._timer.timeout.connect(self._tick)

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(180)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.finished.connect(self._after_fade)

        self._level_sig.connect(self._on_level)
        self._state_sig.connect(self._on_state)

    # --- thread-safe API (called from the audio and PTT threads) ---

    def push_level(self, rms: float) -> None:
        self._level_sig.emit(rms)

    def set_state(self, state: str) -> None:
        self._state_sig.emit(state)

    # --- slots (GUI thread) ---

    def _on_level(self, rms: float) -> None:
        self._raw = rms

    def _on_state(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        if state == "recording":
            self._hist = deque([0.0] * BARS, maxlen=BARS)
            self._smooth = 0.0
            self._reposition()
            self._fade.stop()
            self.setWindowOpacity(1.0)
            self.show()
            self._harden_window()  # after show: the HWND already exists
            self._timer.start()
        elif state == "processing":
            self.show()
            self._timer.start()
        else:  # idle
            self._fade.stop()
            self._fade.setStartValue(self.windowOpacity())
            self._fade.setEndValue(0.0)
            self._fade.start()

    def _after_fade(self) -> None:
        if self._state == "idle" and self.windowOpacity() <= 0.01:
            self._timer.stop()
            self.hide()
            self._raw = 0.0

    # --- window ---

    def _reposition(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + geo.height() - self.height() - MARGIN_BOTTOM
        self.move(QPoint(x, y))

    def _harden_window(self) -> None:
        """Ensures at the Win32 level that the window neither activates nor receives clicks."""
        try:
            import win32con
            import win32gui

            hwnd = int(self.winId())
            ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            win32gui.SetWindowLong(
                hwnd,
                win32con.GWL_EXSTYLE,
                ex
                | win32con.WS_EX_NOACTIVATE
                | win32con.WS_EX_TRANSPARENT
                | win32con.WS_EX_TOOLWINDOW,
            )
        except Exception:  # noqa: BLE001 - HUD is cosmetic; never bring down the dictation
            pass

    # --- animation and painting ---

    def _tick(self) -> None:
        if self._state == "recording":
            target = _norm_level(self._raw)
            # fast attack, slow release: the bar "jumps" on the voice and descends smoothly
            k = 0.55 if target > self._smooth else 0.18
            self._smooth += (target - self._smooth) * k
            self._hist.append(self._smooth)
        elif self._state == "processing":
            self._phase += 0.28
            self._hist.append(0.0)  # the value doesn't matter; the painting uses the phase
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001, N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # background pill
        path = QPainterPath()
        r = self.height() / 2
        path.addRoundedRect(0, 0, self.width(), self.height(), r, r)
        p.fillPath(path, _BG)
        p.setPen(_BORDER)
        p.drawPath(path)

        color = _PROC if self._state == "processing" else _REC
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)

        cy = self.height() / 2
        max_h = self.height() - 22
        min_h = 3.0
        x = (self.width() - (BARS * BAR_W + (BARS - 1) * BAR_GAP)) / 2

        for i, lvl in enumerate(self._hist):
            if self._state == "processing":
                # running wave: sine with per-bar phase offset
                wave = 0.5 + 0.5 * math.sin(self._phase - i * 0.38)
                h = min_h + wave * (max_h * 0.42)
            else:
                # slight envelope at the tips, so the wave "dies" at the edges
                edge = math.sin(math.pi * (i + 0.5) / BARS) ** 0.5
                h = min_h + lvl * max_h * edge
            bar = QPainterPath()
            bar.addRoundedRect(
                x + i * (BAR_W + BAR_GAP), cy - h / 2, BAR_W, h, BAR_W / 2, BAR_W / 2
            )
            p.fillPath(bar, color)
        p.end()
