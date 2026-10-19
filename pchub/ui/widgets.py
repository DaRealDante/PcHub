import math
import weakref

import shiboken6
from PySide6.QtCore import (QEasingCurve, QPoint, QPointF, QPropertyAnimation, QParallelAnimationGroup, QRect,
                            QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QCursor, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLayout,
                               QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from pchub.core.i18n import tr
from pchub.ui.icons import drawIcon, makeIcon
from pchub.ui.theme import SurfaceState, theme, themeManager, withAlpha, mix, roundedPath

_themedButtons = weakref.WeakSet()


def _roleColor(role):
    currentTheme = theme()
    if isinstance(role, QColor):
        return role
    return {
        "text": currentTheme.text, "muted": currentTheme.textMuted, "faint": currentTheme.textFaint,
        "accent": currentTheme.accentLight, "accentText": currentTheme.accentText, "danger": currentTheme.danger,
        "success": currentTheme.success, "warning": currentTheme.warning,
    }.get(role, currentTheme.text)


def setThemedIcon(button, iconName, role="text", size=18):
    signature = (iconName, role, size, theme().styleId, theme().accent.name())
    if getattr(button, "_themedSignature", None) == signature:
        return
    button._themedSignature = signature
    button._themedIcon = (iconName, role, size)
    button.setIcon(makeIcon(iconName, _roleColor(role).name(), size))
    button.setIconSize(QSize(size, size))
    _themedButtons.add(button)


def refreshThemedIcons():
    for button in list(_themedButtons):
        if shiboken6.isValid(button) and getattr(button, "_themedIcon", None):
            iconName, role, size = button._themedIcon
            button._themedSignature = (iconName, role, size, theme().styleId, theme().accent.name())
            button.setIcon(makeIcon(iconName, _roleColor(role).name(), size))


def polish(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def makeLabel(text="", role=None, wordWrap=False, parent=None):
    labelWidget = QLabel(text, parent)
    if role:
        labelWidget.setProperty("role", role)
    labelWidget.setWordWrap(wordWrap)
    if wordWrap:
        labelWidget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    return labelWidget


class StableLabel(QLabel):
    """Label for values that change all the time (CPU %, speeds…). Its size hint only grows, so a new number never
    re-lays out and repaints the whole page: only the label itself is redrawn."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._hint = QSize(0, 0)
        self._minimumHint = QSize(0, 0)
        self._heights = {}

    def sizeHint(self):
        self._hint = self._hint.expandedTo(super().sizeHint())
        return QSize(self._hint)

    def minimumSizeHint(self):
        self._minimumHint = self._minimumHint.expandedTo(super().minimumSizeHint())
        return QSize(self._minimumHint)

    def heightForWidth(self, width):
        height = max(super().heightForWidth(width), self._heights.get(width, 0))
        if len(self._heights) > 64:
            self._heights.clear()
        self._heights[width] = height
        return height

    def setText(self, text):
        if text != self.text():
            super().setText(text)

    def resetHint(self):
        self._hint = QSize(0, 0)
        self._minimumHint = QSize(0, 0)
        self._heights = {}
        self.updateGeometry()


def makeStableLabel(text="", role=None, wordWrap=False, parent=None):
    labelWidget = StableLabel(text, parent)
    if role:
        labelWidget.setProperty("role", role)
    labelWidget.setWordWrap(wordWrap)
    if wordWrap:
        labelWidget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    return labelWidget


def setRole(widget, role):
    if widget.property("role") == role:
        return
    widget.setProperty("role", role)
    polish(widget)


def makeButton(text="", iconName=None, variant=None, iconRole=None, tooltip=None, parent=None, checkable=False):
    button = QPushButton(text, parent)
    button.setCursor(Qt.PointingHandCursor)
    if variant:
        button.setProperty("variant", variant)
    if iconName:
        role = iconRole or ("accentText" if variant == "primary" else "danger" if variant == "danger" else "text")
        setThemedIcon(button, iconName, role, 16 if text else 18)
    if tooltip:
        button.setToolTip(tooltip)
    button.setCheckable(checkable)
    return button


def iconButton(iconName, tooltip=None, role="muted", size=18, checkable=False, parent=None):
    button = makeButton("", iconName, "icon", role, tooltip, parent, checkable)
    setThemedIcon(button, iconName, role, size)
    button.setFixedSize(size + 16, size + 16)
    return button


def divider():
    line = QFrame()
    line.setProperty("role", "divider")
    line.setFrameShape(QFrame.NoFrame)
    return line


def clearLayout(layout):
    while layout.count():
        item = layout.takeAt(0)
        childWidget = item.widget()
        if childWidget is not None:
            childWidget.setParent(None)
            childWidget.deleteLater()
        elif item.layout() is not None:
            clearLayout(item.layout())


class LiquidState:
    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.velocityX = 0.0
        self.velocityY = 0.0
        self.intensity = 0.0
        self.speed = 0.0
        self.angle = 0.0


class RippleState:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.progress = 0.0


class Card(QFrame):
    """Themed container. Glass = frosted panel, Clay = soft raised block. Reacts to the mouse."""
    clicked = Signal()

    def __init__(self, parent=None, level=None, padding=16, hoverable=True, clickable=False, radius=None,
                 liquid=True, tint=None):
        super().__init__(parent)
        self.fixedLevel = level
        self.padding = padding
        self.hoverable = hoverable
        self.clickable = clickable
        self.cardRadius = radius
        self.liquidEnabled = liquid
        self.tint = tint
        self.selected = False
        self.hoverAmount = 0.0
        self.pressedState = False
        self.liquidState = LiquidState()
        self.ripple = None
        self.lastTickTime = None
        self.animationTimer = QTimer(self)
        self.animationTimer.setInterval(16)
        self.animationTimer.timeout.connect(self._tick)
        self.setAttribute(Qt.WA_Hover, True)
        if clickable:
            self.setCursor(Qt.PointingHandCursor)
        themeManager().changed.connect(self._applyMargins)
        self._applyMargins()

    def level(self):
        if self.fixedLevel is not None:
            return self.fixedLevel
        parentWidget = self.parentWidget()
        while parentWidget is not None:
            if isinstance(parentWidget, Card):
                return 1
            parentWidget = parentWidget.parentWidget()
        return 0

    def shadowMargins(self):
        pad = theme().shadowPad(self.level())
        return pad, int(pad * 0.6), pad, int(pad * 1.4)

    def visualRect(self):
        left, top, right, bottom = self.shadowMargins()
        return QRectF(self.rect()).adjusted(left, top, -right, -bottom)

    def _applyMargins(self):
        if not shiboken6.isValid(self):
            return
        left, top, right, bottom = self.shadowMargins()
        self.setContentsMargins(left + self.padding, top + self.padding, right + self.padding, bottom + self.padding)
        self.update()

    def showEvent(self, event):
        self._applyMargins()
        super().showEvent(event)

    def setSelected(self, selected):
        if self.selected != selected:
            self.selected = selected
            self.update()

    def setTint(self, tint):
        self.tint = tint
        self.update()

    def enterEvent(self, event):
        if self.hoverable:
            cursor = self.mapFromGlobal(QCursor.pos())
            self.liquidState.x, self.liquidState.y = float(cursor.x()), float(cursor.y())
            self._startAnimation()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.pressedState = False
        if self.hoverable:
            self._startAnimation()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if self.clickable and event.button() == Qt.LeftButton:
            self.pressedState = True
            if themeManager().animations:
                self.ripple = RippleState(event.position().x(), event.position().y())
                self._startAnimation()
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self.clickable and event.button() == Qt.LeftButton:
            wasPressed = self.pressedState
            self.pressedState = False
            self.update()
            if wasPressed and self.rect().contains(event.position().toPoint()):
                self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _startAnimation(self):
        manager = themeManager()
        if not manager.animations and not manager.mouseEffects:
            self.hoverAmount = 1.0 if self.underMouse() else 0.0
            self.update()
            return
        if not self.animationTimer.isActive():
            self.animationTimer.start()

    def _tick(self):
        if not shiboken6.isValid(self):
            return
        manager = themeManager()
        hovered = self.underMouse() and self.isVisible()
        targetHover = 1.0 if hovered else 0.0
        changeAmount = abs(targetHover - self.hoverAmount)
        self.hoverAmount += (targetHover - self.hoverAmount) * (0.22 if manager.animations else 1.0)
        liquid = self.liquidState
        useLiquid = manager.mouseEffects and self.liquidEnabled and self.hoverable
        if useLiquid:
            cursor = self.mapFromGlobal(QCursor.pos())
            targetX, targetY = float(cursor.x()), float(cursor.y())
            liquid.velocityX += (targetX - liquid.x) * 0.16
            liquid.velocityY += (targetY - liquid.y) * 0.16
            liquid.velocityX *= 0.66
            liquid.velocityY *= 0.66
            liquid.x += liquid.velocityX
            liquid.y += liquid.velocityY
            liquid.speed = math.hypot(liquid.velocityX, liquid.velocityY) * 60
            if liquid.speed > 20:
                targetAngle = math.atan2(liquid.velocityY, liquid.velocityX)
                angleDelta = (targetAngle - liquid.angle + math.pi) % (2 * math.pi) - math.pi
                liquid.angle += angleDelta * 0.3
            changeAmount += abs(targetHover - liquid.intensity) + abs(liquid.velocityX) + abs(liquid.velocityY)
            liquid.intensity += (targetHover - liquid.intensity) * 0.12
        else:
            liquid.intensity = 0.0
        if self.ripple is not None:
            self.ripple.progress += 0.045
            changeAmount += 1
            if self.ripple.progress >= 1:
                self.ripple = None
        if changeAmount > 0.02:
            self.update()
        elif not hovered and self.ripple is None:
            self.hoverAmount = targetHover
            liquid.intensity = 0.0
            self.animationTimer.stop()
            self.update()

    def _surfaceKey(self, currentTheme, level, devicePixelRatio):
        backgroundKey = None
        if level == 0 and currentTheme.needsBlurredBackground():
            from pchub.ui.theme import findBackground
            background = findBackground(self)
            if background is not None:
                offset = self.mapTo(background, QPoint(0, 0))
                backgroundKey = (offset.x(), offset.y(), round(background.shiftX, 1), round(background.shiftY, 1),
                                 background.cacheKey)
        manager = themeManager()
        return (self.width(), self.height(), devicePixelRatio, level, self.selected, self.pressedState,
                self.tint.name(QColor.HexArgb) if self.tint is not None else None, currentTheme.styleId,
                currentTheme.accent.name(), manager.glassOpacity, self.cardRadius, backgroundKey, self.isEnabled())

    def paintEvent(self, event):
        """The static surface (shadow, frosted glass / clay body, border) is cached in a pixmap; only the
        dynamic layer (hover, liquid, ripple) is painted every frame. Keeps animations cheap on 4K screens."""
        currentTheme = theme()
        level = self.level()
        rect = self.visualRect()
        devicePixelRatio = self.devicePixelRatioF()
        key = self._surfaceKey(currentTheme, level, devicePixelRatio)
        cache = getattr(self, "_surfaceCache", None)
        if cache is None or getattr(self, "_surfaceCacheKey", None) != key:
            cache = QPixmap(max(1, int(self.width() * devicePixelRatio)), max(1, int(self.height() * devicePixelRatio)))
            cache.setDevicePixelRatio(devicePixelRatio)
            cache.fill(Qt.transparent)
            cachePainter = QPainter(cache)
            cachePainter.setRenderHint(QPainter.Antialiasing)
            staticState = SurfaceState(pressed=self.pressedState, selected=self.selected, tint=self.tint,
                                       disabled=not self.isEnabled())
            currentTheme.paintSurface(cachePainter, self, rect, level, staticState, self.cardRadius)
            cachePainter.end()
            self._surfaceCache = cache
            self._surfaceCacheKey = key
        painter = QPainter(self)
        painter.drawPixmap(0, 0, cache)
        hover = self.hoverAmount if self.hoverable else 0.0
        liquid = self.liquidState if self.liquidState.intensity > 0.01 else None
        if hover > 0.001 or liquid is not None or self.ripple is not None:
            painter.setRenderHint(QPainter.Antialiasing)
            currentTheme.paintOverlay(painter, rect, level, SurfaceState(hover=hover, liquid=liquid, ripple=self.ripple),
                                      self.cardRadius)

    def hideEvent(self, event):
        QTimer.singleShot(5000, self._dropCacheIfHidden)
        super().hideEvent(event)

    def _dropCacheIfHidden(self):
        if shiboken6.isValid(self) and not self.isVisible():
            self._surfaceCache = None


class IconWidget(QWidget):
    def __init__(self, iconName, role="text", size=18, parent=None):
        super().__init__(parent)
        self.iconName = iconName
        self.role = role
        self.iconSize = size
        self.setFixedSize(size, size)
        themeManager().changed.connect(self.update)

    def setIconName(self, iconName):
        self.iconName = iconName
        self.update()

    def setRole(self, role):
        self.role = role
        self.update()

    def paintEvent(self, event):
        if not self.iconName:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        drawIcon(painter, QRectF(self.rect()), self.iconName, _roleColor(self.role).name())


class IconTile(QWidget):
    """Rounded tile with an icon, tinted with the accent (or a given color)."""

    def __init__(self, iconName, size=40, color=None, parent=None):
        super().__init__(parent)
        self.iconName = iconName
        self.tileColor = color
        self.setFixedSize(size, size)
        themeManager().changed.connect(self.update)

    def setIconName(self, iconName):
        self.iconName = iconName
        self.update()

    def setColor(self, color):
        self.tileColor = color
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        currentTheme = theme()
        baseColor = QColor(self.tileColor) if self.tileColor else currentTheme.accent
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = rect.width() * (0.32 if currentTheme.styleId == "clay" else 0.28)
        path = roundedPath(rect, radius)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        if currentTheme.styleId == "clay":
            gradient.setColorAt(0, mix(baseColor, QColor("#FFFFFF"), 0.25))
            gradient.setColorAt(1, mix(baseColor, QColor("#000000"), 0.15))
            painter.fillPath(path, gradient)
            painter.setClipPath(path)
            painter.setPen(QPen(QColor(255, 255, 255, 80), 2))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius, radius)
            painter.setPen(QPen(QColor(0, 0, 0, 60), 3))
            painter.drawLine(QPointF(rect.left() + radius, rect.bottom() - 1), QPointF(rect.right() - radius, rect.bottom() - 1))
            painter.setClipping(False)
            iconColor = QColor("#FFFFFF")
        else:
            gradient.setColorAt(0, withAlpha(baseColor, 0.42))
            gradient.setColorAt(1, withAlpha(baseColor, 0.14))
            painter.fillPath(path, gradient)
            painter.setPen(QPen(withAlpha(mix(baseColor, QColor("#FFFFFF"), 0.4), 0.55), 1))
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
            iconColor = mix(baseColor, QColor("#FFFFFF"), 0.55)
        iconSize = rect.width() * 0.5
        iconRect = QRectF(rect.center().x() - iconSize / 2, rect.center().y() - iconSize / 2, iconSize, iconSize)
        drawIcon(painter, iconRect, self.iconName, iconColor.name())


class LogoWidget(QWidget):
    """The PC Hub logo (assets/app.png), drawn smoothly at any size."""
    _pixmap = None

    def __init__(self, size=36, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, event):
        from PySide6.QtGui import QPixmap
        from pchub.core.paths import assetsDir
        if LogoWidget._pixmap is None:
            LogoWidget._pixmap = QPixmap(str(assetsDir() / "app.png"))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.Antialiasing)
        if LogoWidget._pixmap.isNull():
            return
        painter.drawPixmap(self.rect(), LogoWidget._pixmap)


class ToggleSwitch(QAbstractButton):
    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(46, 26)
        self.knobPosition = 1.0 if checked else 0.0
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(170)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.valueChanged.connect(self._setKnob)
        self.toggled.connect(self._animate)
        themeManager().changed.connect(self.update)

    def _setKnob(self, value):
        self.knobPosition = float(value)
        self.update()

    def _animate(self, checked):
        targetValue = 1.0 if checked else 0.0
        if not themeManager().animations or not self.isVisible():
            self.knobPosition = targetValue
            self.update()
            return
        self.animation.stop()
        self.animation.setStartValue(self.knobPosition)
        self.animation.setEndValue(targetValue)
        self.animation.start()

    def setCheckedSilently(self, checked):
        self.blockSignals(True)
        self.setChecked(checked)
        self.blockSignals(False)
        self.knobPosition = 1.0 if checked else 0.0
        self.update()

    def sizeHint(self):
        return QSize(46, 26)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        currentTheme = theme()
        colors = currentTheme.trackColors()
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = rect.height() / 2
        progress = self.knobPosition
        offColor = colors["off"]
        if currentTheme.styleId == "clay":
            painter.setPen(Qt.NoPen)
            painter.setBrush(offColor)
            painter.drawRoundedRect(rect, radius, radius)
            if progress > 0:
                onGradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
                onGradient.setColorAt(0, withAlpha(currentTheme.accentLight, progress))
                onGradient.setColorAt(1, withAlpha(currentTheme.accent, progress))
                painter.setBrush(onGradient)
                painter.drawRoundedRect(rect, radius, radius)
            painter.setPen(QPen(QColor(0, 0, 0, 80), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawArc(rect.adjusted(1, 1, -1, -1), 30 * 16, 120 * 16)
        else:
            trackColor = mix(offColor, withAlpha(currentTheme.accent, 0.9), progress)
            painter.setPen(QPen(mix(colors["offBorder"], withAlpha(currentTheme.accentLight, 0.8), progress), 1))
            painter.setBrush(trackColor)
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        knobDiameter = rect.height() - 6
        knobX = rect.left() + 3 + (rect.width() - knobDiameter - 6) * progress
        knobRect = QRectF(knobX, rect.top() + 3, knobDiameter, knobDiameter)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 70))
        painter.drawEllipse(knobRect.translated(0, 1.5))
        knobGradient = QLinearGradient(knobRect.topLeft(), knobRect.bottomLeft())
        knobColor = mix(colors["knobOff"], colors["knob"], progress)
        knobGradient.setColorAt(0, mix(knobColor, QColor("#FFFFFF"), 0.4))
        knobGradient.setColorAt(1, knobColor)
        painter.setBrush(knobGradient)
        painter.drawEllipse(knobRect)
        if not self.isEnabled():
            painter.setBrush(QColor(0, 0, 0, 90))
            painter.drawRoundedRect(rect, radius, radius)


MODIFIER_KEYS = {Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta, Qt.Key_AltGr, Qt.Key_Super_L, Qt.Key_Super_R}


class HotkeyEdit(QPushButton):
    sequenceChanged = Signal(str)
    suspendHooks = None

    def __init__(self, sequence="", parent=None):
        super().__init__(parent)
        self.sequence = sequence or ""
        self.recording = False
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(150)
        self.setToolTip(tr("hotkey.clearTip"))
        self.setFocusPolicy(Qt.StrongFocus)
        self._refreshText()

    def setSequence(self, sequence):
        self.sequence = sequence or ""
        self._refreshText()

    def _refreshText(self, partial=None):
        if self.recording:
            self.setText(partial or tr("hotkey.press"))
        else:
            self.setText(self._pretty(self.sequence) if self.sequence else tr("hotkey.none"))

    @staticmethod
    def _pretty(sequence):
        return QKeySequence(sequence).toString(QKeySequence.NativeText).replace("Meta", "Win")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.recording:
                self._stopRecording()
            else:
                self._startRecording()
            event.accept()
            return
        super().mousePressEvent(event)

    def _startRecording(self):
        self.recording = True
        self.setProperty("variant", "chip")
        self.setCheckable(True)
        self.setChecked(True)
        polish(self)
        self.setFocus()
        self.grabKeyboard()
        if HotkeyEdit.suspendHooks:
            HotkeyEdit.suspendHooks[0]()
        self._refreshText()

    def _stopRecording(self):
        if not self.recording:
            return
        self.recording = False
        self.releaseKeyboard()
        self.setChecked(False)
        self.setCheckable(False)
        self.setProperty("variant", None)
        polish(self)
        if HotkeyEdit.suspendHooks:
            HotkeyEdit.suspendHooks[1]()
        self._refreshText()

    def keyPressEvent(self, event):
        if not self.recording:
            super().keyPressEvent(event)
            return
        key = event.key()
        modifiers = event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier | Qt.AltModifier | Qt.MetaModifier)
        if key in MODIFIER_KEYS or key == Qt.Key_unknown:
            partNames = [name for flag, name in ((Qt.ControlModifier, "Ctrl"), (Qt.AltModifier, "Alt"),
                                                 (Qt.ShiftModifier, "Shift"), (Qt.MetaModifier, "Win"))
                         if modifiers & flag]
            self._refreshText(("+".join(partNames) + "+…") if partNames else None)
            return
        if key == Qt.Key_Escape and not modifiers:
            self._stopRecording()
            return
        if key in (Qt.Key_Backspace, Qt.Key_Delete) and not modifiers:
            self.sequence = ""
            self._stopRecording()
            self.sequenceChanged.emit("")
            return
        combination = event.keyCombination()
        sequenceText = QKeySequence(combination).toString(QKeySequence.PortableText)
        self.sequence = sequenceText
        self._stopRecording()
        self.sequenceChanged.emit(sequenceText)

    def focusOutEvent(self, event):
        self._stopRecording()
        super().focusOutEvent(event)


class Sparkline(QWidget):
    def __init__(self, color=None, maximum=None, parent=None, fill=True, lineWidth=2.0):
        super().__init__(parent)
        self.values = []
        self.lineColor = color
        self.maximum = maximum
        self.fill = fill
        self.lineWidth = lineWidth
        self.setMinimumHeight(36)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def setValues(self, values):
        self.values = list(values)
        self.update()

    def setColor(self, color):
        self.lineColor = color
        self.update()

    def paintEvent(self, event):
        if len(self.values) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 3, -1, -1)
        maximum = self.maximum or max(max(self.values), 1e-6) * 1.15
        color = QColor(self.lineColor) if self.lineColor else theme().accentLight
        count = len(self.values)
        points = [QPointF(rect.left() + rect.width() * index / (count - 1),
                          rect.bottom() - rect.height() * min(1.0, max(0.0, value / maximum)))
                  for index, value in enumerate(self.values)]
        path = QPainterPath(points[0])
        for index in range(1, count):
            previous, current = points[index - 1], points[index]
            midX = (previous.x() + current.x()) / 2
            path.cubicTo(QPointF(midX, previous.y()), QPointF(midX, current.y()), current)
        if self.fill:
            fillPath = QPainterPath(path)
            fillPath.lineTo(points[-1].x(), rect.bottom())
            fillPath.lineTo(points[0].x(), rect.bottom())
            fillPath.closeSubpath()
            gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            gradient.setColorAt(0, withAlpha(color, 0.35))
            gradient.setColorAt(1, withAlpha(color, 0.0))
            painter.fillPath(fillPath, gradient)
        painter.setPen(QPen(color, self.lineWidth, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(path)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(points[-1], 3, 3)


class RingProgress(QWidget):
    def __init__(self, size=72, thickness=7, color=None, parent=None):
        super().__init__(parent)
        self.progress = 0.0
        self.ringColor = color
        self.thickness = thickness
        self.centerText = ""
        self.setFixedSize(size, size)

    def setProgress(self, progress, text=None):
        self.progress = max(0.0, min(1.0, progress))
        if text is not None:
            self.centerText = text
        self.update()

    def setColor(self, color):
        self.ringColor = color
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        currentTheme = theme()
        inset = self.thickness / 2 + 1
        rect = QRectF(self.rect()).adjusted(inset, inset, -inset, -inset)
        trackColor = QColor(255, 255, 255, 22) if currentTheme.styleId == "glass" else QColor("#191A26")
        painter.setPen(QPen(trackColor, self.thickness, Qt.SolidLine, Qt.RoundCap))
        painter.drawEllipse(rect)
        color = QColor(self.ringColor) if self.ringColor else currentTheme.accentLight
        if self.progress > 0:
            gradientPen = QPen(color, self.thickness, Qt.SolidLine, Qt.RoundCap)
            painter.setPen(gradientPen)
            painter.drawArc(rect, 90 * 16, int(-360 * 16 * self.progress))
        if self.centerText:
            painter.setPen(currentTheme.text)
            font = painter.font()
            font.setPixelSize(max(10, int(self.width() * 0.2)))
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignCenter, self.centerText)


class MeterBar(QWidget):
    def __init__(self, color=None, height=8, parent=None):
        super().__init__(parent)
        self.value = 0.0
        self.barColor = color
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def setValue(self, fraction):
        self.value = max(0.0, min(1.0, fraction))
        self.update()

    def setColor(self, color):
        self.barColor = color
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        currentTheme = theme()
        rect = QRectF(self.rect())
        radius = rect.height() / 2
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 22) if currentTheme.styleId == "glass" else QColor("#191A26"))
        painter.drawRoundedRect(rect, radius, radius)
        if self.value > 0:
            color = QColor(self.barColor) if self.barColor else currentTheme.accent
            filledRect = QRectF(rect.left(), rect.top(), max(rect.height(), rect.width() * self.value), rect.height())
            gradient = QLinearGradient(filledRect.topLeft(), filledRect.topRight())
            gradient.setColorAt(0, mix(color, QColor("#000000"), 0.15))
            gradient.setColorAt(1, mix(color, QColor("#FFFFFF"), 0.2))
            painter.setBrush(gradient)
            painter.drawRoundedRect(filledRect, radius, radius)


class StatusDot(QWidget):
    def __init__(self, status="stopped", parent=None):
        super().__init__(parent)
        self.status = status
        self.setFixedSize(8, 8)

    def setStatus(self, status):
        self.status = status
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(statusColor(self.status))
        painter.drawEllipse(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))


def statusColor(status):
    currentTheme = theme()
    return {"running": currentTheme.success, "error": currentTheme.danger, "blocked": currentTheme.warning}.get(
        status, currentTheme.textFaint)


def statusChipRole(status):
    return {"running": "chipSuccess", "error": "chipDanger", "blocked": "chipWarning"}.get(status, "chip")


class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=8):
        super().__init__(parent)
        self.items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._doLayout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._doLayout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())

    def _doLayout(self, rect, testOnly):
        x, y = rect.x(), rect.y()
        lineHeight = 0
        spacing = self.spacing()
        for item in self.items:
            itemSize = item.sizeHint()
            nextX = x + itemSize.width() + spacing
            if nextX - spacing > rect.right() and lineHeight > 0:
                x = rect.x()
                y = y + lineHeight + spacing
                nextX = x + itemSize.width() + spacing
                lineHeight = 0
            if not testOnly:
                item.setGeometry(QRect(QPoint(x, y), itemSize))
            x = nextX
            lineHeight = max(lineHeight, itemSize.height())
        return y + lineHeight - rect.y()


class _TransitionOverlay(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.pixmap = None
        self.progress = 1.0
        self.hide()

    def paintEvent(self, event):
        if self.pixmap is None:
            return
        painter = QPainter(self)
        eased = 1 - (1 - self.progress) ** 3
        painter.setOpacity(eased)
        painter.drawPixmap(0, int(round(12 * (1 - eased))), self.pixmap)


class AnimatedStack(QStackedWidget):
    """Page switches fade + slide in. The new page is rendered ONCE into a pixmap and the animation only moves
    that picture, so it stays smooth even with heavy pages on 4K screens."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.placeholder = QWidget()
        self.addWidget(self.placeholder)
        self.overlay = _TransitionOverlay(self)
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(170)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.valueChanged.connect(self._onProgress)
        self.animation.finished.connect(self._finish)
        self.targetWidget = None

    def addWidget(self, widget):
        index = super().addWidget(widget)
        if widget is not self.placeholder and self.currentWidget() is self.placeholder and self.targetWidget is None:
            self.setCurrentWidget(widget)
        return index

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.overlay.setGeometry(self.rect())

    def setCurrentAnimated(self, widget):
        if self.animation.state() == QVariantAnimation.Running:
            self.animation.stop()
            self._finish()
        if widget is self.currentWidget():
            return
        self.setCurrentWidget(widget)
        if not themeManager().animations or not self.isVisible():
            return
        self.overlay.pixmap = widget.grab()
        self.targetWidget = widget
        self.setCurrentWidget(self.placeholder)
        self.overlay.setGeometry(self.rect())
        self.overlay.progress = 0.0
        self.overlay.show()
        self.overlay.raise_()
        self.animation.start()

    def _onProgress(self, value):
        self.overlay.progress = float(value)
        self.overlay.update()

    def _finish(self):
        target = self.targetWidget
        self.targetWidget = None
        self.overlay.hide()
        self.overlay.pixmap = None
        if target is not None and shiboken6.isValid(target) and self.indexOf(target) >= 0:
            self.setCurrentWidget(target)

    def currentPage(self):
        """The page being shown (also while its transition is still running)."""
        return self.targetWidget or self.currentWidget()


def makeScrollPage(margins=(28, 24, 28, 28), spacing=16):
    scrollArea = QScrollArea()
    scrollArea.setWidgetResizable(True)
    scrollArea.setFrameShape(QFrame.NoFrame)
    scrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    contentWidget = QWidget()
    contentLayout = QVBoxLayout(contentWidget)
    contentLayout.setContentsMargins(*margins)
    contentLayout.setSpacing(spacing)
    scrollArea.setWidget(contentWidget)
    return scrollArea, contentLayout


class EmptyState(QWidget):
    def __init__(self, iconName, title, text="", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 18, 12, 18)
        layout.setSpacing(6)
        layout.addStretch(1)
        iconWidget = IconWidget(iconName, "faint", 30)
        layout.addWidget(iconWidget, 0, Qt.AlignHCenter)
        titleLabel = makeLabel(title, "subtitle")
        titleLabel.setAlignment(Qt.AlignCenter)
        layout.addWidget(titleLabel)
        if text:
            textLabel = makeLabel(text, "muted", True)
            textLabel.setAlignment(Qt.AlignCenter)
            layout.addWidget(textLabel)
        layout.addStretch(1)


class Banner(Card):
    """Inline notice with optional action button."""

    def __init__(self, iconName, text, color, buttonText=None, buttonCallback=None, parent=None):
        super().__init__(parent, padding=12, hoverable=False, tint=QColor(color))
        layout = QHBoxLayout(self)
        layout.setSpacing(12)
        self.iconWidget = IconWidget(iconName, QColor(color), 20)
        layout.addWidget(self.iconWidget)
        self.textLabel = makeLabel(text, None, True)
        layout.addWidget(self.textLabel, 1)
        self.button = None
        if buttonText:
            self.button = makeButton(buttonText, variant="primary")
            if buttonCallback:
                self.button.clicked.connect(buttonCallback)
            layout.addWidget(self.button)

    def setText(self, text):
        self.textLabel.setText(text)


def hLayout(*widgets, spacing=8, margins=(0, 0, 0, 0), stretchIndex=None):
    layout = QHBoxLayout()
    layout.setSpacing(spacing)
    layout.setContentsMargins(*margins)
    for index, item in enumerate(widgets):
        if item is None:
            layout.addStretch(1)
        elif isinstance(item, QLayout):
            layout.addLayout(item)
        else:
            layout.addWidget(item, 1 if index == stretchIndex else 0)
    return layout


def vLayout(*widgets, spacing=8, margins=(0, 0, 0, 0)):
    layout = QVBoxLayout()
    layout.setSpacing(spacing)
    layout.setContentsMargins(*margins)
    for item in widgets:
        if item is None:
            layout.addStretch(1)
        elif isinstance(item, QLayout):
            layout.addLayout(item)
        else:
            layout.addWidget(item)
    return layout


class BarChart(QWidget):
    """Simple rounded bar chart. values = [(label, value)]; highlightLast colors the last bar with the accent."""

    def __init__(self, parent=None, valueFormatter=None, highlightLast=True):
        super().__init__(parent)
        self.values = []
        self.valueFormatter = valueFormatter or (lambda value: f"{value:.0f}")
        self.highlightLast = highlightLast
        self.hoverIndex = None
        self.setMouseTracking(True)
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def setValues(self, values):
        self.values = list(values)
        self.update()

    def _barRects(self):
        count = len(self.values)
        if not count:
            return []
        rect = QRectF(self.rect()).adjusted(4, 18, -4, -20)
        slotWidth = rect.width() / count
        barWidth = max(6.0, min(34.0, slotWidth * 0.62))
        maximum = max([value for _, value in self.values] + [1e-9])
        rects = []
        for index, (_, value) in enumerate(self.values):
            height = max(3.0, rect.height() * (value / maximum)) if value > 0 else 3.0
            x = rect.left() + slotWidth * index + (slotWidth - barWidth) / 2
            rects.append(QRectF(x, rect.bottom() - height, barWidth, height))
        return rects

    def mouseMoveEvent(self, event):
        hovered = None
        for index, barRect in enumerate(self._barRects()):
            if barRect.left() - 4 <= event.position().x() <= barRect.right() + 4:
                hovered = index
        if hovered != self.hoverIndex:
            self.hoverIndex = hovered
            self.update()

    def leaveEvent(self, event):
        self.hoverIndex = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        currentTheme = theme()
        font = painter.font()
        font.setPixelSize(10)
        painter.setFont(font)
        for index, barRect in enumerate(self._barRects()):
            label, value = self.values[index]
            highlighted = index == self.hoverIndex or (self.highlightLast and index == len(self.values) - 1)
            gradient = QLinearGradient(barRect.topLeft(), barRect.bottomLeft())
            baseColor = currentTheme.accent if highlighted else mix(currentTheme.accent, currentTheme.windowColor, 0.45)
            gradient.setColorAt(0, mix(baseColor, QColor("#FFFFFF"), 0.25))
            gradient.setColorAt(1, baseColor)
            painter.setPen(Qt.NoPen)
            painter.setBrush(gradient)
            painter.drawRoundedRect(barRect, min(6.0, barRect.width() / 2), min(6.0, barRect.width() / 2))
            painter.setPen(currentTheme.textFaint)
            painter.drawText(QRectF(barRect.center().x() - 24, self.height() - 18, 48, 16), Qt.AlignCenter, label)
            if index == self.hoverIndex or (highlighted and self.hoverIndex is None):
                painter.setPen(currentTheme.text)
                painter.drawText(QRectF(barRect.center().x() - 50, barRect.top() - 17, 100, 15), Qt.AlignCenter,
                                 self.valueFormatter(value))
