"""Hotkeys globais via pynput (WH_KEYBOARD_LL): PTT com key-down/key-up real."""

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
    """"<ctrl>+<alt>" → [ {variantes de ctrl}, {variantes de alt} ]."""
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
    """PTT: on_press quando o combo fecha, on_release quando qualquer tecla dele solta.

    Toggle: dispara callback a cada fechamento do combo.
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
        # Se a tecla Win faz parte do PTT, é preciso suprimi-la do sistema para o
        # menu Iniciar não abrir ao soltar. Quando suprimida, o handler normal não a
        # vê, então o próprio filtro alimenta o estado (ver _win32_filter).
        self._suppress_win = any(keyboard.Key.cmd in g for g in self._ptt_groups)

    def bind_toggle(self, combo: str, callback: Callable[[], None]) -> None:
        self._toggles.append((_parse(combo), callback))

    def _combo_down(self, groups: list[set]) -> bool:
        return all(bool(g & self._pressed) for g in groups)

    def _normalize(self, key):  # noqa: ANN001
        # KeyCode com char: normaliza p/ minúscula (shift/caps não quebram o combo)
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
        """Suprime a tecla Win do sistema durante o PTT (evita abrir o menu Iniciar).

        Como a supressão esconde o evento dos handlers on_press/on_release, o próprio
        filtro processa a tecla Win aqui para o combo continuar fechando.
        """
        if not self._suppress_win:
            return
        try:
            if data.vkCode not in (_VK_LWIN, _VK_RWIN):
                return
            if not (_ctrl_down() or self._ptt_active):
                return  # Win sem Ctrl e fora do PTT: deixa passar (Win+E, Iniciar, etc.)
            if msg in _WM_KEYDOWN:
                self._on_press(keyboard.Key.cmd)
            elif msg in _WM_KEYUP:
                self._on_release(keyboard.Key.cmd)
            if self._listener is not None:
                self._listener.suppress_event()
        except Exception:  # noqa: BLE001 - um filtro que lança mataria o hook
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
