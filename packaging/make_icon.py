"""Génère file_converter/resources/app.ico (plusieurs tailles, dessinées avec Qt).

Usage : python packaging/make_icon.py
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath

SIZES = (16, 24, 32, 48, 64, 128, 256)
OUTPUT = Path(__file__).resolve().parent.parent / "file_converter" / "resources" / "app.ico"

# Hauteurs relatives des barres de l'onde sonore.
BARS = (0.35, 0.7, 1.0, 0.55, 0.8)


def render(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    margin = size * 0.04
    rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    gradient.setColorAt(0.0, QColor("#4263eb"))
    gradient.setColorAt(1.0, QColor("#7b2ff7"))
    background = QPainterPath()
    background.addRoundedRect(rect, size * 0.22, size * 0.22)
    p.fillPath(background, gradient)

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("white"))
    area = rect.adjusted(rect.width() * 0.2, rect.height() * 0.2, -rect.width() * 0.2, -rect.height() * 0.2)
    slot = area.width() / len(BARS)
    bar_width = max(slot * 0.62, 1.0)
    for i, ratio in enumerate(BARS):
        height = max(area.height() * ratio, bar_width)
        center = QPointF(area.left() + slot * (i + 0.5), area.center().y())
        bar = QRectF(center.x() - bar_width / 2, center.y() - height / 2, bar_width, height)
        p.drawRoundedRect(bar, bar_width / 2, bar_width / 2)
    p.end()
    return image


def png_bytes(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def write_ico(path: Path, images: list[QImage]) -> None:
    """Écrit un .ico dont chaque entrée est une image PNG (format accepté depuis Windows Vista)."""
    payloads = [png_bytes(img) for img in images]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = b""
    for img, data in zip(images, payloads):
        side = img.width() if img.width() < 256 else 0  # 0 signifie 256 dans le format ICO
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + entries + b"".join(payloads))


def main() -> None:
    app = QGuiApplication(sys.argv)  # noqa: F841 — requis pour peindre avec Qt
    write_ico(OUTPUT, [render(size) for size in SIZES])
    print(f"Icône écrite : {OUTPUT}")


if __name__ == "__main__":
    main()
