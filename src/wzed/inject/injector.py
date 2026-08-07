"""Text injection into the active field: per-app fallback chain.

Default: clipboard + Ctrl+V with a delayed, verified restore.
Alternative: SendInput KEYEVENTF_UNICODE (for terminals that break on paste).
UI Automation stays out of the write path (read-only by design).
"""

from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes

import win32api
import win32clipboard
import win32con
import win32gui
import win32process

log = logging.getLogger(__name__)

INPUT_KEYBOARD = 1
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MOUSEINPUT(ctypes.Structure):
    """Largest member of the INPUT union; without it cbSize is wrong on x64 and SendInput returns 0."""

    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def active_process_name() -> str:
    """Executable name of the foreground window (lowercase), for the per-app profile."""
    try:
        hwnd = win32gui.GetForegroundWindow()
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        handle = win32api.OpenProcess(
            win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        try:
            path = win32process.GetModuleFileNameEx(handle, 0)
        finally:
            win32api.CloseHandle(handle)
        return path.rsplit("\\", 1)[-1].lower()
    except Exception:  # elevated (UIPI) or protected window
        return ""


def _send_inputs(inputs: list[INPUT]) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    sent = ctypes.windll.user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise OSError(f"SendInput: {sent}/{len(inputs)} eventos (janela elevada?)")


def _key(vk: int, up: bool = False) -> INPUT:
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.u.ki = KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, 0)
    return inp


def send_unicode(text: str) -> None:
    inputs: list[INPUT] = []
    for ch in text:
        if ch == "\n":  # newline becomes Enter (works in any field)
            inputs += [_key(win32con.VK_RETURN), _key(win32con.VK_RETURN, up=True)]
            continue
        for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
            inp = INPUT(type=INPUT_KEYBOARD)
            inp.u.ki = KEYBDINPUT(0, ord(ch), flags, 0, 0)
            inputs.append(inp)
    # batches of 200 events so we don't overflow the input queue of slow apps
    for i in range(0, len(inputs), 200):
        _send_inputs(inputs[i : i + 200])
        time.sleep(0.005)


def send_combo(*vks: int) -> None:
    _send_inputs([_key(vk) for vk in vks] + [_key(vk, up=True) for vk in reversed(vks)])


def _clip_get() -> str | None:
    for _ in range(5):  # the clipboard may be locked by another app
        try:
            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                return None
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            time.sleep(0.05)
    return None


def _clip_set(text: str) -> bool:
    for _ in range(5):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
                return True
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            time.sleep(0.05)
    return False


class Injector:
    def __init__(self, cfg) -> None:  # cfg: InjectCfg
        self.cfg = cfg

    def inject(self, text: str) -> str:
        """Injects into the active field; returns the technique used (for history/debugging)."""
        if not text:
            return "noop"
        app = active_process_name()
        strategy = self.cfg.per_app.get(app, self.cfg.default_strategy)
        try:
            if strategy == "sendinput":
                send_unicode(text)
            else:
                self._paste(text, app)
        except OSError as e:
            log.warning("injeção falhou em %s (%s); tentando SendInput", app, e)
            send_unicode(text)
            strategy = "sendinput-fallback"
        return strategy

    def _paste(self, text: str, app: str) -> None:
        original = _clip_get()
        if not _clip_set(text):
            raise OSError("clipboard indisponível")
        paste_combo = (
            (win32con.VK_CONTROL, win32con.VK_SHIFT, ord("V"))
            if app in ("windowsterminal.exe", "openconsole.exe")
            else (win32con.VK_CONTROL, ord("V"))
        )
        send_combo(*paste_combo)
        # delayed restore: the documented race (Outlook/Teams read late).
        # Verification: only restore if the clipboard still holds OUR text.
        time.sleep(self.cfg.restore_clipboard_delay_ms / 1000)
        if original is not None and _clip_get() == text:
            _clip_set(original)
