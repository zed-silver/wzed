"""Phase 0, item 3: smoke test of the text injection techniques.

Opens its own Notepad, injects an accented sentence with each technique
(clipboard-paste and SendInput Unicode), reads it back via Ctrl+A/Ctrl+C and compares.
Closes Notepad without saving. Runs in ~5 s; do NOT touch the keyboard during the test.

Usage: uv run python scripts/test_inject.py
"""

from __future__ import annotations

import ctypes
import subprocess
import time
from ctypes import wintypes

import win32api
import win32clipboard
import win32con
import win32gui
import win32process

AMOSTRA = "Olá, wzed! Ação e coração: pão, çã, é, 123 €."

# ---------- SendInput (structs) ----------

ULONG_PTR = ctypes.POINTER(ctypes.c_ulong)


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MOUSEINPUT(ctypes.Structure):
    """Largest member of the INPUT union; without it cbSize comes out wrong on x64 and SendInput returns 0."""

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


INPUT_KEYBOARD = 1
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002
SendInput = ctypes.windll.user32.SendInput


def _send_unicode(text: str) -> None:
    inputs = []
    for ch in text:
        code = ord(ch)
        for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
            inp = INPUT(type=INPUT_KEYBOARD)
            inp.u.ki = KEYBDINPUT(0, code, flags, 0, 0)
            inputs.append(inp)
    arr = (INPUT * len(inputs))(*inputs)
    sent = SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise OSError(f"SendInput enviou {sent}/{len(inputs)} eventos")


def _send_vk_combo(*vks: int) -> None:
    for vk in vks:
        win32api.keybd_event(vk, 0, 0, 0)
    for vk in reversed(vks):
        win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)


# ---------- clipboard ----------

def _clip_get() -> str | None:
    win32clipboard.OpenClipboard()
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        return None
    finally:
        win32clipboard.CloseClipboard()


def _clip_set(text: str) -> None:
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
    finally:
        win32clipboard.CloseClipboard()


# ---------- target (our own Notepad) ----------

def _proc_name(pid: int) -> str:
    try:
        handle = win32api.OpenProcess(
            win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        try:
            return win32process.GetModuleFileNameEx(handle, 0).rsplit("\\", 1)[-1].lower()
        finally:
            win32api.CloseHandle(handle)
    except Exception:
        return ""


def _find_window_of_process(name: str, timeout: float = 6.0) -> int:
    """Finds a process's visible window by the executable NAME.

    (Win11's notepad.exe hands off to the Store app: the launcher's PID
    is not the window's PID; searching by name covers both.)
    """
    hwnd_found = 0

    def cb(hwnd: int, _param) -> bool:
        nonlocal hwnd_found
        if not win32gui.IsWindowVisible(hwnd) or not win32gui.GetWindowText(hwnd):
            return True
        _, wpid = win32process.GetWindowThreadProcessId(hwnd)
        if _proc_name(wpid) == name:
            hwnd_found = hwnd
            return False
        return True

    deadline = time.time() + timeout
    while time.time() < deadline and not hwnd_found:
        try:
            win32gui.EnumWindows(cb, None)
        except Exception:  # EnumWindows raises when the callback returns False
            pass
        if not hwnd_found:
            time.sleep(0.2)
    return hwnd_found


def _focus(hwnd: int) -> None:
    """Focuses the window and CONFIRMS focus; never inject blindly (it would land in the user's window)."""
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    # an Alt tap unlocks SetForegroundWindow for background processes
    win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
    win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(0.2)
    if win32gui.GetForegroundWindow() != hwnd:
        # plan B: AttachThreadInput to the thread that owns the current foreground
        cur = win32api.GetCurrentThreadId()
        fg = win32gui.GetForegroundWindow()
        fg_thread = win32process.GetWindowThreadProcessId(fg)[0] if fg else 0
        target_thread = win32process.GetWindowThreadProcessId(hwnd)[0]
        attached = []
        for tid in {fg_thread, target_thread} - {0, cur}:
            try:
                ctypes.windll.user32.AttachThreadInput(cur, tid, True)
                attached.append(tid)
            except Exception:
                pass
        try:
            ctypes.windll.user32.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        finally:
            for tid in attached:
                ctypes.windll.user32.AttachThreadInput(cur, tid, False)
    time.sleep(0.4)
    if win32gui.GetForegroundWindow() != hwnd:
        raise SystemExit(
            "ABORTADO: não consegui focar a janela de teste (foreground lock). "
            "Nenhuma tecla foi injetada fora dela."
        )


def _read_back() -> str:
    _clip_set("__wzed_sentinela__")
    _send_vk_combo(win32con.VK_CONTROL, ord("A"))
    time.sleep(0.15)
    _send_vk_combo(win32con.VK_CONTROL, ord("C"))
    time.sleep(0.3)
    return _clip_get() or ""


def _clear_field() -> None:
    _send_vk_combo(win32con.VK_CONTROL, ord("A"))
    time.sleep(0.1)
    _send_vk_combo(win32con.VK_DELETE)
    time.sleep(0.1)


def main() -> None:
    print("Abrindo Notepad de teste (não toque no teclado por ~8 s)...")
    proc = subprocess.Popen(["notepad.exe"])
    hwnd = _find_window_of_process("notepad.exe")
    if not hwnd:
        raise SystemExit("Janela do Notepad não encontrada")

    resultados = {}
    try:
        # Technique 1: clipboard + Ctrl+V
        _focus(hwnd)
        clip_antes = _clip_get()
        _clip_set(AMOSTRA)
        _send_vk_combo(win32con.VK_CONTROL, ord("V"))
        time.sleep(0.4)  # delay before restoring (the documented race)
        lido = _read_back()
        resultados["clipboard_paste"] = "OK" if lido == AMOSTRA else f"DIVERGIU: {lido!r}"
        _clear_field()

        # Technique 2: SendInput Unicode
        _focus(hwnd)
        t0 = time.perf_counter()
        _send_unicode(AMOSTRA)
        dt_ms = (time.perf_counter() - t0) * 1000
        time.sleep(0.3)
        lido = _read_back()
        ok = lido == AMOSTRA
        resultados["sendinput_unicode"] = (
            f"OK ({dt_ms:.0f} ms p/ {len(AMOSTRA)} chars)" if ok else f"DIVERGIU: {lido!r}"
        )

        if clip_antes is not None:
            _clip_set(clip_antes)  # restore the user's clipboard
    finally:
        proc.kill()

    print("\n== Resultado do smoke test ==")
    for tecnica, res in resultados.items():
        print(f"  {tecnica}: {res}")
    print("\nMatriz completa (8 apps reais) é manual: rodar com cada app em foco.")


if __name__ == "__main__":
    main()
