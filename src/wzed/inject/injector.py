"""Injeção de texto no campo ativo: cadeia de fallback por app.

Padrão: clipboard + Ctrl+V com restauração retardada e verificada.
Alternativa: SendInput KEYEVENTF_UNICODE (terminais que quebram com paste).
UI Automation fica de fora do caminho de escrita (read-only por design).
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
    """Membro maior da união INPUT; sem ele o cbSize sai errado em x64 e SendInput retorna 0."""

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
    """Nome do executável da janela em foco (minúsculas), p/ o perfil por app."""
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
    except Exception:  # janela elevada (UIPI) ou protegida
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
        if ch == "\n":  # newline vira Enter (funciona em qualquer campo)
            inputs += [_key(win32con.VK_RETURN), _key(win32con.VK_RETURN, up=True)]
            continue
        for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
            inp = INPUT(type=INPUT_KEYBOARD)
            inp.u.ki = KEYBDINPUT(0, ord(ch), flags, 0, 0)
            inputs.append(inp)
    # lotes de 200 eventos para não estourar a fila de input de apps lentos
    for i in range(0, len(inputs), 200):
        _send_inputs(inputs[i : i + 200])
        time.sleep(0.005)


def send_combo(*vks: int) -> None:
    _send_inputs([_key(vk) for vk in vks] + [_key(vk, up=True) for vk in reversed(vks)])


def _clip_get() -> str | None:
    for _ in range(5):  # clipboard pode estar lockado por outro app
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
        """Injeta no campo ativo; retorna a técnica usada (p/ histórico/depuração)."""
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
        # restauração retardada: a race documentada (Outlook/Teams leem tarde).
        # Verificação: só restaura se o clipboard ainda contém NOSSO texto.
        time.sleep(self.cfg.restore_clipboard_delay_ms / 1000)
        if original is not None and _clip_get() == text:
            _clip_set(original)
