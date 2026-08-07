"""Valida o HUD sem precisar de teclado: não rouba foco, não recebe clique, e desenha.

Gera prévias em bench/hud_*.png. Uso: uv run python scripts/test_hud.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import win32con
import win32gui
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from wzed.ui.hud import RecordingHud  # noqa: E402

OUT = Path(__file__).parent.parent / "bench"


def main() -> None:
    app = QApplication(sys.argv)
    fg_antes = win32gui.GetForegroundWindow()

    hud = RecordingHud()
    hud.set_state("recording")  # mesma thread → conexão direta, aplica na hora
    app.processEvents()

    hwnd = int(hud.winId())
    fg_depois = win32gui.GetForegroundWindow()
    ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)

    print("== requisito crítico: o HUD não pode ativar nem receber cliques ==")
    print(f"  visível:            {hud.isVisible()}")
    print(f"  HUD é o foreground? {fg_depois == hwnd}  (tem de ser False)")
    print(f"  foreground mudou?   {fg_antes != fg_depois}  (tem de ser False)")
    print(f"  WS_EX_NOACTIVATE:   {bool(ex & win32con.WS_EX_NOACTIVATE)}")
    print(f"  WS_EX_TRANSPARENT:  {bool(ex & win32con.WS_EX_TRANSPARENT)}  (clique atravessa)")
    print(f"  WS_EX_TOOLWINDOW:   {bool(ex & win32con.WS_EX_TOOLWINDOW)}   (fora do Alt+Tab)")

    ok = (
        hud.isVisible()
        and fg_depois != hwnd
        and fg_antes == fg_depois
        and bool(ex & win32con.WS_EX_NOACTIVATE)
        and bool(ex & win32con.WS_EX_TRANSPARENT)
    )

    # prévia "gravando": simula fala (envelope senoidal + variação)
    OUT.mkdir(exist_ok=True)
    for frame in range(60):
        t = frame / 60
        fake_rms = 0.02 + 0.16 * abs(math.sin(t * 7)) * (0.5 + 0.5 * math.sin(t * 23))
        hud._on_level(fake_rms)  # direto: evita depender do event loop
        hud._tick()
        app.processEvents()
    hud.grab().save(str(OUT / "hud_recording.png"))

    hud.set_state("processing")
    for _ in range(20):
        hud._tick()
        app.processEvents()
    hud.grab().save(str(OUT / "hud_processing.png"))

    geo = hud.geometry()
    print(f"\n  posição: x={geo.x()} y={geo.y()} {geo.width()}x{geo.height()} (base, centro)")
    print(f"  prévias: {OUT / 'hud_recording.png'} e hud_processing.png")
    print("\nRESULTADO:", "OK" if ok else "FALHOU")
    hud.set_state("idle")
    app.processEvents()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
