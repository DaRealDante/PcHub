from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QCursor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from pchub.ui.theme import theme, themeManager


class BackgroundWidget(QWidget):
    """Window backdrop. Glass cards sample `blurredImage` to fake frosted glass."""
    margin = 36

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.sharpImage = None
        self.blurredImage = None
        self.cacheKey = None
        self.shiftX = 0.0
        self.shiftY = 0.0
        self.targetShiftX = 0.0
        self.targetShiftY = 0.0
        self.parallaxTimer = QTimer(self)
        self.parallaxTimer.setInterval(33)
        self.parallaxTimer.timeout.connect(self._parallaxTick)
        manager = themeManager()
        manager.changed.connect(self._invalidate)
        manager.effectsChanged.connect(self._updateParallaxState)

    def _invalidate(self):
        self.cacheKey = None
        self.update()

    def _ensureImages(self):
        devicePixelRatio = self.devicePixelRatioF()
        currentTheme = theme()
        key = (self.width(), self.height(), round(devicePixelRatio, 2), currentTheme.styleId, currentTheme.accent.name())
        if key == self.cacheKey and self.sharpImage is not None:
            return
        self.cacheKey = key
        fullWidth = self.width() + self.margin * 2
        fullHeight = self.height() + self.margin * 2
        smallSharp, smallBlurred = currentTheme.renderBackground(fullWidth, fullHeight)
        pixelSize = (int(fullWidth * devicePixelRatio), int(fullHeight * devicePixelRatio))
        self.sharpImage = QPixmap.fromImage(smallSharp.scaled(*pixelSize, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        self.sharpImage.setDevicePixelRatio(devicePixelRatio)
        if smallBlurred is not None:
            self.blurredImage = smallBlurred.scaled(*pixelSize, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self.blurredImage.setDevicePixelRatio(devicePixelRatio)
        else:
            self.blurredImage = None

    def paintEvent(self, event):
        self._ensureImages()
        painter = QPainter(self)
        painter.fillRect(self.rect(), theme().windowColor)
        if self.sharpImage is not None:
            painter.drawPixmap(QPointF(-self.margin + self.shiftX, -self.margin + self.shiftY), self.sharpImage)

    def drawBlurredRegion(self, painter, widget, rect):
        self._ensureImages()
        if self.blurredImage is None:
            return
        devicePixelRatio = self.blurredImage.devicePixelRatio()
        offset = widget.mapTo(self, QPoint(0, 0))
        sourceRect = QRectF((offset.x() + rect.x() + self.margin - self.shiftX) * devicePixelRatio,
                            (offset.y() + rect.y() + self.margin - self.shiftY) * devicePixelRatio,
                            rect.width() * devicePixelRatio, rect.height() * devicePixelRatio)
        painter.drawImage(rect, self.blurredImage, sourceRect)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.cacheKey = None

    def changeEvent(self, event):
        if event.type() == QEvent.ActivationChange:
            self._updateParallaxState()
        super().changeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._updateParallaxState()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.parallaxTimer.stop()

    def _updateParallaxState(self):
        manager = themeManager()
        active = self.isVisible() and self.window().isActiveWindow() and manager.parallax and manager.animations
        if active:
            if not self.parallaxTimer.isActive():
                self.parallaxTimer.start()
        else:
            self.parallaxTimer.stop()
            if not manager.parallax and (self.shiftX or self.shiftY):
                self.shiftX = self.shiftY = 0.0
                self.update()

    def _parallaxTick(self):
        if self.width() <= 0 or self.height() <= 0:
            return
        cursor = self.mapFromGlobal(QCursor.pos())
        normalizedX = max(-1.0, min(1.0, (cursor.x() - self.width() / 2) / (self.width() / 2)))
        normalizedY = max(-1.0, min(1.0, (cursor.y() - self.height() / 2) / (self.height() / 2)))
        strength = themeManager().effectStrength / 100.0
        maxShift = self.margin * (0.25 + 0.6 * strength)
        self.targetShiftX = -normalizedX * maxShift
        self.targetShiftY = -normalizedY * maxShift * 0.7
        deltaX = self.targetShiftX - self.shiftX
        deltaY = self.targetShiftY - self.shiftY
        if abs(deltaX) < 0.25 and abs(deltaY) < 0.25:
            return
        self.shiftX += deltaX * 0.10
        self.shiftY += deltaY * 0.10
        self.update()
