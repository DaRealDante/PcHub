from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QImage
from PySide6.QtSvg import QSvgRenderer

from pchub.core.paths import assetsDir

_svgSources = {}


def iconNames():
    folder = assetsDir() / "icons"
    return sorted(path.stem for path in folder.glob("*.svg"))


def _svgSource(name):
    if name not in _svgSources:
        iconPath = assetsDir() / "icons" / f"{name}.svg"
        if not iconPath.exists():
            iconPath = assetsDir() / "icons" / "puzzle.svg"
        _svgSources[name] = iconPath.read_text(encoding="utf-8") if iconPath.exists() else ""
    return _svgSources[name]


@lru_cache(maxsize=2048)
def _renderImage(name, colorHex, size, devicePixelRatio, strokeWidth):
    source = _svgSource(name).replace("currentColor", colorHex)
    if strokeWidth:
        source = source.replace('stroke-width="2"', f'stroke-width="{strokeWidth}"')
    renderer = QSvgRenderer(QByteArray(source.encode("utf-8")))
    pixelSize = max(1, int(round(size * devicePixelRatio)))
    image = QImage(pixelSize, pixelSize, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, pixelSize, pixelSize))
    painter.end()
    image.setDevicePixelRatio(devicePixelRatio)
    return image


def iconPixmap(name, color, size=18, devicePixelRatio=1.0, strokeWidth=None):
    colorHex = QColor(color).name(QColor.HexArgb) if not isinstance(color, str) else color
    if colorHex.startswith("#") and len(colorHex) == 9:
        colorHex = "#" + colorHex[3:]
    return QPixmap.fromImage(_renderImage(name, colorHex, size, round(devicePixelRatio, 2), strokeWidth))


def drawIcon(painter, rect, name, color, strokeWidth=None):
    size = int(min(rect.width(), rect.height()))
    devicePixelRatio = painter.device().devicePixelRatioF() if painter.device() else 1.0
    pixmap = iconPixmap(name, color, size, devicePixelRatio, strokeWidth)
    painter.drawPixmap(int(rect.x() + (rect.width() - size) / 2), int(rect.y() + (rect.height() - size) / 2), pixmap)


def makeIcon(name, color, size=18):
    icon = QIcon()
    for ratio in (1.0, 1.25, 1.5, 2.0):
        icon.addPixmap(iconPixmap(name, color, size, ratio))
    return icon
