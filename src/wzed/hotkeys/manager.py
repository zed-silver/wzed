"""Global hotkeys via pynput (WH_KEYBOARD_LL): PTT with real key-down/key-up."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from pynput import keyboard

log = logging.getLogger(__name__)

_VK_LWIN, _VK_RWIN, _VK_CONTROL = 0x5B, 0x5C, 0x11
_WM_KEYDOWN = {0x100, 0x104}  # WM_KEYDOWN, WM_SYSKEYDOWN
_WM_KEYUP = {0x101, 0x105}  # WM_KEYUP, WM_SYSKEYUP


def _ctrl_down() -> bool:
    try:
        import win32api

        return bool(win32api.GetAsyncKeyState(_VK_CONTROL) & 0x8000)
    except Exception:
        return False

_VK_MAP = {
    "<ctrl>": {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r},
    "<alt>": {keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_gr},
    "<shift>": {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r},
    "<win>": {keyboard.Key.cmd},
}


def _parse(combo: str) -> list[set]:
    """"<ctrl>+<alt>" → [ {ctrl variants}, {alt variants} ]."""
    groups: list[set] = []
    for part in combo.lower().split("+"):
        part = part.strip()
        if part in _VK_MAP:
            groups.append(_VK_MAP[part])
        elif len(part) == 1:
            groups.append({keyboard.KeyCode.from_char(part)})
        else:
            raise ValueError(f"tecla desconhecida no combo: {part!r}")
    return groups


class HotkeyManager:
    """PTT: on_press when the combo closes, on_release when any of its keys is released.

    Toggle: fires the callback on every closing of the combo.
    """

    def __init__(self) -> None:
        self._pressed: set = set()
        self._ptt_groups: list[set] = []
        self._ptt_active = False
        self._on_ptt_down: Callable[[], None] | None = None
        self._on_ptt_up: Callable[[], None] | None = None
        self._toggles: list[tuple[list[set], Callable[[], None]]] = []
        self._listener: keyboard.Listener | None = None
        self._lock = threading.Lock()
        self._suppress_win = False

    def bind_ptt(self, combo: str, on_down: Callable[[], None], on_up: Callable[[], None]) -> None:
        self._ptt_groups = _parse(combo)
        self._on_ptt_down = on_down
        self._on_ptt_up = on_up
        # If the Win key is part of the PTT, it must be suppressed system-wide so the
        # Start menu doesn't open on release. When suppressed, the normal handler doesn't
        # see it, so the filter itself feeds the state (see _win32_filter).
        self._suppress_win = any(keyboard.Key.cmd in g for g in self._ptt_groups)

    def bind_toggle(self, combo: str, callback: Callable[[], None]) -> None:
        self._toggles.append((_parse(combo), callback))

    def _combo_down(self, groups: list[set]) -> bool:
        return all(bool(g & self._pressed) for g in groups)

    def _normalize(self, key):  # noqa: ANN001
        # KeyCode with a char: normalize to lowercase (shift/caps don't break the combo)
        if isinstance(key, keyboard.KeyCode) and key.char:
            return keyboard.KeyCode.from_char(key.char.lower())
        return key

    def _on_press(self, key) -> None:  # noqa: ANN001
        key = self._normalize(key)
        with self._lock:
            self._pressed.add(key)
            for groups, cb in self._toggles:
                if self._combo_down(groups) and key in groups[-1]:
                    threading.Thread(target=cb, daemon=True).start()
            if (
                self._ptt_groups
                and not self._ptt_active
                and self._combo_down(self._ptt_groups)
            ):
                self._ptt_active = True
                if self._on_ptt_down:
                    threading.Thread(target=self._on_ptt_down, daemon=True).start()

    def _on_release(self, key) -> None:  # noqa: ANN001
        key = self._normalize(key)
        with self._lock:
            self._pressed.discard(key)
            if self._ptt_active and not self._combo_down(self._ptt_groups):
                self._ptt_active = False
                if self._on_ptt_up:
                    threading.Thread(target=self._on_ptt_up, daemon=True).start()

    def _win32_filter(self, msg, data) -> None:  # noqa: ANN001
        """Suppresses the system Win key during the PTT (prevents opening the Start menu).

        Since suppression hides the event from the on_press/on_release handlers, the
        filter itself processes the Win key here so the combo keeps closing.
        """
        if not self._suppress_win:
            return
        try:
            if data.vkCode not in (_VK_LWIN, _VK_RWIN):
                return
            if not (_ctrl_down() or self._ptt_active):
                return  # Win without Ctrl and outside the PTT: let it through (Win+E, Start, etc.)
            if msg in _WM_KEYDOWN:
                self._on_press(keyboard.Key.cmd)
            elif msg in _WM_KEYUP:
                self._on_release(keyboard.Key.cmd)
            if self._listener is not None:
                self._listener.suppress_event()
        except Exception:  # noqa: BLE001 - a filter that raises would kill the hook
            log.debug("win32_filter falhou", exc_info=True)

    def start(self) -> None:
        self._listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
            win32_event_filter=self._win32_filter,
        )
        self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None
