"""Monitor map like Windows' display settings: click a monitor to choose whether OLEDSaver darkens it."""
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from pchub.core.i18n import T, tr
from pchub.plugins.oled_saver.overlay import isScreenSelected, screenKey
from pchub.ui.theme import mix, roundedPath, theme, withAlpha
from pchub.ui.widgets import makeButton, makeLabel

TEXT = {
    "identify": T("Identifica", "Identify"),
    "test": T("Prova", "Test"),
    "dimmed": T("Si oscura", "Dims"),
    "notDimmed": T("Non toccato", "Untouched"),
    "primary": T("principale", "primary"),
    "lastOne": T("Almeno un monitor deve restare scelto.", "At least one monitor must stay selected."),
    "summaryAll": T("Oscura tutti i monitor", "Darkens every monitor"),
    "summarySome": T("Oscura {count} monitor su {total}", "Darkens {count} of {total} monitors"),
}


def orderedScreens():
    """Monitors left-to-right, top-to-bottom, so numbers match their position."""
    return sorted(QGuiApplication.screens(), key=lambda screen: (screen.geometry().x(), screen.geometry().y()))


class ScreenMap(QWidget):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.hoverIndex = -1
        self.monitorRects = []
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(340, 150)

    def selectedKeys(self):
        return self.plugin.selectedScreenKeys()

    def _layoutRects(self):
        screens = orderedScreens()
        if not screens:
            return []
        geometries = [screen.geometry() for screen in screens]
        left = min(geometry.left() for geometry in geometries)
        top = min(geometry.top() for geometry in geometries)
        right = max(geometry.right() + 1 for geometry in geometries)
        bottom = max(geometry.bottom() + 1 for geometry in geometries)
        area = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        scale = min(area.width() / max(1, right - left), area.height() / max(1, bottom - top))
        offsetX = area.x() + (area.width() - (right - left) * scale) / 2
        offsetY = area.y() + (area.height() - (bottom - top) * scale) / 2
        rects = []
        for screen, geometry in zip(screens, geometries):
            rect = QRectF(offsetX + (geometry.left() - left) * scale, offsetY + (geometry.top() - top) * scale,
                          geometry.width() * scale, geometry.height() * scale).adjusted(3, 3, -3, -3)
            rects.append((screen, rect))
        return rects

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        currentTheme = theme()
        selected = self.selectedKeys()
        primary = QGuiApplication.primaryScreen()
        self.monitorRects = self._layoutRects()
        for index, (screen, rect) in enumerate(self.monitorRects):
            isOn = isScreenSelected(screen, selected)
            hovered = index == self.hoverIndex
            if isOn:
                fillColor = mix(currentTheme.accent, QColor("#000000"), 0.25 if not hovered else 0.1)
                borderColor = currentTheme.accentLight
            else:
                fillColor = QColor(255, 255, 255, 22 if not hovered else 40)
                borderColor = withAlpha(currentTheme.textFaint, 0.8)
            path = roundedPath(rect, 8)
            painter.fillPath(path, fillColor)
            painter.setPen(QPen(borderColor, 2 if isOn else 1))
            painter.drawPath(path)
            numberFont = QFont(self.font())
            numberFont.setPixelSize(int(max(14, min(34, rect.height() * 0.38))))
            numberFont.setWeight(QFont.Bold)
            painter.setFont(numberFont)
            painter.setPen(currentTheme.text if isOn else currentTheme.textMuted)
            painter.drawText(rect.adjusted(0, -10, 0, -10), Qt.AlignCenter, str(index + 1))
            labelFont = QFont(self.font())
            labelFont.setPixelSize(10)
            painter.setFont(labelFont)
            label = tr(TEXT["dimmed"] if isOn else TEXT["notDimmed"])
            if screen is primary:
                label += f" · {tr(TEXT['primary'])}"
            painter.setPen(currentTheme.text if isOn else currentTheme.textFaint)
            painter.drawText(rect.adjusted(4, 0, -4, -6), Qt.AlignHCenter | Qt.AlignBottom, label)

    def _indexAt(self, position):
        screens = QGuiApplication.screens()
        for index, (screen, rect) in enumerate(self.monitorRects):
            if rect.contains(position):
                return index if screen in screens else -1
        return -1

    def forgetScreens(self):
        self.monitorRects = []
        self.hoverIndex = -1

    def mouseMoveEvent(self, event):
        index = self._indexAt(event.position())
        if index != self.hoverIndex:
            self.hoverIndex = index
            if index >= 0:
                screen = self.monitorRects[index][0]
                geometry = screen.geometry()
                self.setToolTip(f"{screen.model() or screen.name()} — {geometry.width()}×{geometry.height()}")
            else:
                self.setToolTip("")
            self.update()

    def leaveEvent(self, event):
        self.hoverIndex = -1
        self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        index = self._indexAt(event.position())
        if index < 0:
            return
        self.plugin.toggleScreen(self.monitorRects[index][0])
        self.update()


class ScreenPicker(QWidget):
    """Map + buttons, used as a custom settings row."""

    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.identifyWindows = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.screenMap = ScreenMap(plugin)
        layout.addWidget(self.screenMap)
        bottomRow = QHBoxLayout()
        bottomRow.setSpacing(6)
        self.summaryLabel = makeLabel("", "faint")
        bottomRow.addWidget(self.summaryLabel, 1)
        identifyButton = makeButton(tr(TEXT["identify"]), "scan-eye", "ghost")
        identifyButton.clicked.connect(self.identify)
        bottomRow.addWidget(identifyButton)
        testButton = makeButton(tr(TEXT["test"]), "wand-sparkles", "ghost")
        testButton.clicked.connect(plugin.runDemo)
        bottomRow.addWidget(testButton)
        layout.addLayout(bottomRow)
        plugin.stateChanged.connect(self.refresh)
        application = QGuiApplication.instance()
        application.screenAdded.connect(self.refresh)
        application.screenRemoved.connect(self.refresh)
        self.refresh()

    def refresh(self, *args):
        self.screenMap.forgetScreens()
        if not self.isVisible():
            self.dirty = True
            return
        self.dirty = False
        screens = QGuiApplication.screens()
        selected = self.plugin.selectedScreenKeys()
        count = sum(1 for screen in screens if isScreenSelected(screen, selected))
        if count >= len(screens):
            self.summaryLabel.setText(tr(TEXT["summaryAll"]))
        else:
            self.summaryLabel.setText(tr(TEXT["summarySome"], count=count, total=len(screens)))
        if self.plugin.lastScreenWarning:
            self.summaryLabel.setText(tr(TEXT["lastOne"]))
            self.plugin.lastScreenWarning = False
        self.screenMap.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def identify(self):
        for window in self.identifyWindows:
            window.close()
        self.identifyWindows = []
        for index, screen in enumerate(orderedScreens()):
            window = IdentifyWindow(index + 1, isScreenSelected(screen, self.plugin.selectedScreenKeys()), screen)
            window.show()
            self.identifyWindows.append(window)
        QTimer.singleShot(2500, self._closeIdentify)

    def _closeIdentify(self):
        for window in self.identifyWindows:
            window.close()
            window.deleteLater()
        self.identifyWindows = []


class IdentifyWindow(QWidget):
    """Big number in the corner of a monitor, like Windows' "Identify"."""

    def __init__(self, number, isOn, screen):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.number = number
        self.isOn = isOn
        geometry = screen.availableGeometry()
        self.setGeometry(geometry.x() + 40, geometry.y() + 40, 170, 190)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        currentTheme = theme()
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        painter.fillPath(roundedPath(rect, 22), QColor(11, 13, 25, 235))
        painter.setPen(QPen(currentTheme.accent if self.isOn else currentTheme.textFaint, 3))
        painter.drawRoundedRect(rect, 22, 22)
        numberFont = QFont(self.font())
        numberFont.setPixelSize(110)
        numberFont.setWeight(QFont.Bold)
        painter.setFont(numberFont)
        painter.setPen(currentTheme.text)
        painter.drawText(rect.adjusted(0, -16, 0, -16), Qt.AlignCenter, str(self.number))
        labelFont = QFont(self.font())
        labelFont.setPixelSize(14)
        painter.setFont(labelFont)
        painter.setPen(currentTheme.accentLight if self.isOn else currentTheme.textMuted)
        painter.drawText(rect.adjusted(0, 0, 0, -14), Qt.AlignHCenter | Qt.AlignBottom,
                         tr(TEXT["dimmed"] if self.isOn else TEXT["notDimmed"]))
