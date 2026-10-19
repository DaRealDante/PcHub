"""Renders assets/app.png and assets/app.ico (PC Hub logo). Run: python tools/make_icon.py"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QApplication


def renderLogo(size):
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    rect = QRectF(size * 0.04, size * 0.04, size * 0.92, size * 0.92)
    radius = size * 0.24
    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    gradient.setColorAt(0, QColor("#A78BFA"))
    gradient.setColorAt(0.55, QColor("#7C6CF2"))
    gradient.setColorAt(1, QColor("#22D3EE"))
    painter.setPen(Qt.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(rect, radius, radius)
    shine = QRadialGradient(QPointF(rect.left() + rect.width() * 0.3, rect.top() + rect.height() * 0.2), rect.width() * 0.7)
    shine.setColorAt(0, QColor(255, 255, 255, 90))
    shine.setColorAt(1, QColor(255, 255, 255, 0))
    painter.setBrush(shine)
    painter.drawRoundedRect(rect, radius, radius)
    painter.setPen(QPen(QColor(255, 255, 255, 110), max(1.0, size * 0.012)))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(rect.adjusted(size * 0.01, size * 0.01, -size * 0.01, -size * 0.01), radius, radius)
    center = rect.center()
    orbit = size * 0.24
    nodeRadius = size * 0.075
    nodes = [QPointF(center.x() - orbit, center.y() - orbit), QPointF(center.x() + orbit, center.y() - orbit),
             QPointF(center.x() - orbit, center.y() + orbit), QPointF(center.x() + orbit, center.y() + orbit)]
    painter.setPen(QPen(QColor(255, 255, 255, 200), max(1.5, size * 0.035), Qt.SolidLine, Qt.RoundCap))
    for node in nodes:
        painter.drawLine(center, node)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#FFFFFF"))
    for node in nodes:
        painter.drawEllipse(node, nodeRadius, nodeRadius)
    painter.setBrush(QColor("#1E1B4B"))
    painter.drawEllipse(center, size * 0.13, size * 0.13)
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawEllipse(center, size * 0.085, size * 0.085)
    painter.end()
    return image


if __name__ == "__main__":
    application = QApplication(sys.argv)
    assets = root / "assets"
    renderLogo(512).save(str(assets / "app.png"))
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    tempFolder = root / "build" / "icon-tmp"
    tempFolder.mkdir(parents=True, exist_ok=True)
    for size in sizes:
        renderLogo(size).save(str(tempFolder / f"{size}.png"))
    from PIL import Image
    images = [Image.open(tempFolder / f"{size}.png").convert("RGBA") for size in sizes]
    images[-1].save(assets / "app.ico", sizes=[(size, size) for size in sizes], append_images=images[:-1])
    for size in sizes:
        (tempFolder / f"{size}.png").unlink()
    tempFolder.rmdir()
    print("icon written")
