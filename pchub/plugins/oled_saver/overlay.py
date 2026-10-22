"""Black full-screen overlays (one per monitor) with smooth opacity. Never steals focus."""
import time

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

from pchub.core import winapi


def screenKey(screen):
    """Stable id for a monitor: model + serial when Windows reports them, otherwise its name (DISPLAY1…)."""
    serial = (screen.serialNumber() or "").strip()
    model = (screen.model() or screen.manufacturer() or "").strip()
    if serial:
        return f"{model}|{serial}"
    return screen.name()


def isScreenSelected(screen, selectedKeys):
    if selectedKeys is None:
        return True
    return screenKey(screen) in selectedKeys or screen.name() in selectedKeys


class OverlayWindow(QWidget):
    clicked = Signal()

    def __init__(self, screen):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setFocusPolicy(Qt.NoFocus)
        self.setWindowTitle("PC Hub OLED")
        self.clickThrough = None
        self.cursorHidden = False
        self.setScreenGeometry(screen)
        self.setWindowOpacity(0.0)

    def setScreenGeometry(self, screen):
        self.setGeometry(screen.geometry())

    def paintEvent(self, event):
        QPainter(self).fillRect(self.rect(), QColor(0, 0, 0))

    def setClickThrough(self, enabled):
        if enabled == self.clickThrough:
            return
        self.clickThrough = enabled
        if winapi.isWindows:
            winapi.setClickThrough(self, enabled)
        else:
            self.setAttribute(Qt.WA_TransparentForMouseEvents, enabled)

    def setCursorHidden(self, hidden):
        if hidden != self.cursorHidden:
            self.cursorHidden = hidden
            self.setCursor(Qt.BlankCursor if hidden else Qt.ArrowCursor)

    def mousePressEvent(self, event):
        self.clicked.emit()
        event.accept()


class OverlayController(QObject):
    """Animates the overlays towards a target darkness (0 = invisible, 1 = black)."""
    levelChanged = Signal(float)
    overlayClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.windows = []
        self.level = 0.0
        self.target = 0.0
        self.startLevel = 0.0
        self.fadeSeconds = 0.5
        self.fadeStartedAt = 0.0
        self.selectedKeys = None
        self.eatClicks = True
        self.lastTopmostAt = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        application = QGuiApplication.instance()
        if application is not None:
            application.screenAdded.connect(self._screensChanged)
            application.screenRemoved.connect(self._screensChanged)

    def setSelectedScreens(self, selectedKeys):
        selectedKeys = None if selectedKeys is None else list(selectedKeys)
        if selectedKeys != self.selectedKeys:
            self.selectedKeys = selectedKeys
            self._screensChanged()

    def _targetScreens(self):
        return [screen for screen in QGuiApplication.screens() if isScreenSelected(screen, self.selectedKeys)]

    def _screensChanged(self, *args):
        if self.windows:
            self._destroyWindows()
            if self.level > 0:
                self._ensureWindows()
                self._applyLevel()

    def _ensureWindows(self):
        if self.windows:
            return
        for screen in self._targetScreens():
            window = OverlayWindow(screen)
            window.clicked.connect(self.overlayClicked)
            self.windows.append(window)

    def _destroyWindows(self):
        for window in self.windows:
            window.hide()
            window.deleteLater()
        self.windows = []

    def setTarget(self, level, fadeMilliseconds, eatClicks=True):
        level = max(0.0, min(1.0, float(level)))
        self.eatClicks = eatClicks
        if abs(level - self.target) < 0.001 and (self.timer.isActive() or abs(level - self.level) < 0.001):
            return
        self.target = level
        self.startLevel = self.level
        self.fadeSeconds = max(0.0, fadeMilliseconds / 1000.0)
        self.fadeStartedAt = time.monotonic()
        if self.fadeSeconds == 0:
            self.level = level
            self._applyLevel()
        elif not self.timer.isActive():
            self.timer.start()

    def _tick(self):
        progress = 1.0 if self.fadeSeconds <= 0 else min(1.0, (time.monotonic() - self.fadeStartedAt) / self.fadeSeconds)
        eased = 1 - (1 - progress) ** 3
        self.level = self.startLevel + (self.target - self.startLevel) * eased
        if progress >= 1.0:
            self.level = self.target
            self.timer.stop()
        self._applyLevel()

    def _applyLevel(self):
        if self.level <= 0.002:
            for window in self.windows:
                if window.isVisible():
                    window.hide()
            self.levelChanged.emit(0.0)
            return
        self._ensureWindows()
        fullyDark = self.level >= 0.97
        for window in self.windows:
            window.setWindowOpacity(self.level)
            window.setCursorHidden(fullyDark)
            if not window.isVisible():
                window.show()
                window.setClickThrough(not (self.eatClicks and self.level >= 0.6))
                winapi.keepTopmost(window)
            else:
                window.setClickThrough(not (self.eatClicks and self.level >= 0.6))
        now = time.monotonic()
        if now - self.lastTopmostAt > 2:
            self.lastTopmostAt = now
            for window in self.windows:
                winapi.keepTopmost(window)
        self.levelChanged.emit(self.level)

    def maintain(self):
        """Re-asserts always-on-top every few seconds while visible (other topmost windows can cover it)."""
        if self.level > 0.002 and time.monotonic() - self.lastTopmostAt > 2:
            self.lastTopmostAt = time.monotonic()
            for window in self.windows:
                winapi.keepTopmost(window)

    def hideNow(self):
        self.timer.stop()
        self.level = self.target = 0.0
        self._applyLevel()

    def shutdown(self):
        self.timer.stop()
        self._destroyWindows()
