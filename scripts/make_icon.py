"""Generates assets/wzed.ico (white microphone over a blue disc) in several sizes.

Usage: uv run python scripts/make_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

OUT = Path(__file__).parent.parent / "assets" / "wzed.ico"


def _draw(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size
    # background disc (petrol-blue gradient)
    grad = QLinearGradient(0, 0, 0, s)
    grad.setColorAt(0, QColor("#2f6f8f"))
    grad.setColorAt(1, QColor("#16384a"))
    p.setBrush(QBrush(grad))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QRectF(s * 0.04, s * 0.04, s * 0.92, s * 0.92))
    # white microphone
    p.setBrush(QColor("#ffffff"))
    cap_w, cap_h = s * 0.30, s * 0.46
    cap_x = (s - cap_w) / 2
    cap_y = s * 0.20
    p.drawRoundedRect(QRectF(cap_x, cap_y, cap_w, cap_h), cap_w / 2, cap_w / 2)
    # arc + stem
    pen = p.pen()
    pen.setColor(QColor("#ffffff"))
    pen.setWidthF(max(1.5, s * 0.045))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    arc = QRectF(s * 0.30, s * 0.30, s * 0.40, s * 0.46)
    p.drawArc(arc, 180 * 16, 180 * 16)
    cx = s / 2
    p.drawLine(int(cx), int(s * 0.76), int(cx), int(s * 0.86))
    p.drawLine(int(s * 0.40), int(s * 0.86), int(s * 0.60), int(s * 0.86))
    p.end()
    return pm


def main() -> None:
    _app = QApplication(sys.argv)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = [_draw(s).toImage() for s in sizes]
    # QPixmap.save does not produce a multi-size .ico; use Qt's writer with all sizes
    from PySide6.QtGui import QImageWriter
    from PySide6.QtCore import QBuffer, QByteArray

    # Qt does not write .ico natively on all builds; write a 256 PNG and convert via Pillow
    try:
        from PIL import Image
        import io

        pil_imgs = []
        for img in imgs:
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QBuffer.OpenModeFlag.WriteOnly)
            img.save(buf, "PNG")
            pil_imgs.append(Image.open(io.BytesIO(bytes(ba))).convert("RGBA"))
        pil_imgs[-1].save(OUT, format="ICO", sizes=[(s, s) for s in sizes])
    except ImportError:
        # without Pillow: write a 256 PNG and rename it (Windows accepts PNG in a modern .ico)
        _draw(256).save(str(OUT).replace(".ico", ".png"), "PNG")
        raise SystemExit("Pillow ausente: gerado .png; instale pillow p/ .ico multi-size")
    print(f"ícone gerado: {OUT}")


if __name__ == "__main__":
    main()
