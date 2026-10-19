"""In-app alert cards: always on top, bottom-right of the screen, never steal focus. Used for reminders,
calendar events, notifications and anything that must not be missed.

Every card goes away on its own: a thin line at the bottom shows how long is left, hovering pauses it, and cards
slide in, slide away and re-stack smoothly."""
import time

from PySide6.QtCore import (QEasingCurve, QParallelAnimationGroup, QPoint, QPropertyAnimation, QRectF, Qt, QTimer,
                            QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QGuiApplication, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from pchub.core import system
from pchub.ui.theme import mix, roundedPath, shadowImage, theme, themeManager, withAlpha
from pchub.ui.widgets import IconTile, iconButton, makeButton, makeLabel

ALERT_WIDTH = 380
MARGIN = 18
GAP = 4
DEFAULT_SECONDS = 8
MAX_VISIBLE = 5


def animationsOn():
    manager = themeManager()
    return bool(manager and manager.animations)


class AlertCard(QWidget):
    closed = Signal(object)

    def __init__(self, title, message="", iconName="bell", actions=None, timeoutSeconds=0, accent=None):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setFixedWidth(ALERT_WIDTH + 24)
        self.accent = QColor(accent) if accent else None
        self.closing = False
        self.progress = 1.0
        self.duration = max(0.0, float(timeoutSeconds or 0))
        self.moveAnimation = None
        outerLayout = QVBoxLayout(self)
        outerLayout.setContentsMargins(12, 10, 12, 16)
        self.panel = QWidget()
        outerLayout.addWidget(self.panel)
        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(16, 14, 12, 16)
        layout.setSpacing(10)
        topRow = QHBoxLayout()
        topRow.setSpacing(12)
        topRow.addWidget(IconTile(iconName, 38, self.accent), 0, Qt.AlignTop)
        textLayout = QVBoxLayout()
        textLayout.setSpacing(2)
        textLayout.addWidget(makeLabel(title, "subtitle", True))
        if message:
            textLayout.addWidget(makeLabel(message, "muted", True))
        topRow.addLayout(textLayout, 1)
        closeButton = iconButton("x", None, "muted", 14)
        closeButton.clicked.connect(self.dismiss)
        topRow.addWidget(closeButton, 0, Qt.AlignTop)
        layout.addLayout(topRow)
        if actions:
            buttonRow = QHBoxLayout()
            buttonRow.setSpacing(6)
            buttonRow.addStretch(1)
            for index, action in enumerate(actions):
                label, callback = action[0], action[1]
                buttonIcon = action[2] if len(action) > 2 else None
                button = makeButton(label, buttonIcon, "primary" if index == len(actions) - 1 else None)
                button.clicked.connect(lambda checked=False, function=callback: self._runAction(function))
                buttonRow.addWidget(button)
            layout.addLayout(buttonRow)
        self.countdown = None
        self.timeoutTimer = None
        if self.duration > 0:
            self.countdown = QVariantAnimation(self)
            self.countdown.setStartValue(1.0)
            self.countdown.setEndValue(0.0)
            self.countdown.setDuration(int(self.duration * 1000))
            self.countdown.valueChanged.connect(self._onCountdown)
            self.countdown.finished.connect(self.dismiss)

    # countdown ---------------------------------------------------------------------------------
    def startCountdown(self):
        if self.countdown is not None and self.countdown.state() == QVariantAnimation.Stopped and not self.closing:
            self.countdown.start()

    def _onCountdown(self, value):
        self.progress = float(value)
        self.update(self._barRect().toAlignedRect().adjusted(-2, -2, 2, 2))

    def enterEvent(self, event):
        if self.countdown is not None and self.countdown.state() == QVariantAnimation.Running:
            self.countdown.pause()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.countdown is not None and self.countdown.state() == QVariantAnimation.Paused and not self.closing:
            self.countdown.resume()
        super().leaveEvent(event)

    def remainingSeconds(self):
        if self.countdown is None:
            return None
        return max(0.0, self.duration * self.progress)

    # closing -----------------------------------------------------------------------------------
    def _runAction(self, function):
        try:
            function()
        finally:
            self.dismiss()

    def dismiss(self):
        if self.closing:
            return
        self.closing = True
        if self.countdown is not None:
            self.countdown.stop()
        self.closed.emit(self)
        if not animationsOn() or not self.isVisible():
            self.close()
            return
        group = QParallelAnimationGroup(self)
        slide = QPropertyAnimation(self, b"pos", group)
        slide.setDuration(240)
        slide.setEasingCurve(QEasingCurve.InCubic)
        slide.setStartValue(self.pos())
        slide.setEndValue(self.pos() + QPoint(self.width() // 2, 0))
        fade = QPropertyAnimation(self, b"windowOpacity", group)
        fade.setDuration(220)
        fade.setStartValue(self.windowOpacity())
        fade.setEndValue(0.0)
        group.addAnimation(slide)
        group.addAnimation(fade)
        group.finished.connect(self.close)
        self.exitAnimation = group
        group.start()

    def moveTo(self, target, animated):
        enterSlide = getattr(self, "enterSlide", None)
        if enterSlide is not None and enterSlide.state() == QPropertyAnimation.Running:
            enterSlide.setEndValue(target)
            return
        if self.moveAnimation is not None:
            self.moveAnimation.stop()
        if not animated or self.pos() == target:
            self.move(target)
            return
        self.moveAnimation = QPropertyAnimation(self, b"pos", self)
        self.moveAnimation.setDuration(260)
        self.moveAnimation.setEasingCurve(QEasingCurve.OutCubic)
        self.moveAnimation.setStartValue(self.pos())
        self.moveAnimation.setEndValue(target)
        self.moveAnimation.start()

    def enter(self, target):
        """Slides in from the right with a fade, then starts the countdown."""
        if not animationsOn():
            self.move(target)
            self.show()
            self.startCountdown()
            return
        start = target + QPoint(60, 0)
        self.move(start)
        self.setWindowOpacity(0.0)
        self.show()
        group = QParallelAnimationGroup(self)
        slide = QPropertyAnimation(self, b"pos", group)
        slide.setDuration(320)
        slide.setEasingCurve(QEasingCurve.OutBack)
        slide.setStartValue(start)
        slide.setEndValue(target)
        fade = QPropertyAnimation(self, b"windowOpacity", group)
        fade.setDuration(220)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        group.addAnimation(slide)
        group.addAnimation(fade)
        self.enterAnimation = group
        self.enterSlide = slide
        group.start()
        self.startCountdown()

    # painting ----------------------------------------------------------------------------------
    def _barRect(self):
        rect = QRectF(self.panel.geometry())
        inset = theme().radius * 0.6
        return QRectF(rect.left() + inset, rect.bottom() - 7, rect.width() - inset * 2, 3)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        currentTheme = theme()
        rect = QRectF(self.panel.geometry())
        radius = currentTheme.radius
        image, padding = shadowImage(rect.width(), rect.height(), radius, 14, QColor(0, 0, 0, 150), self.devicePixelRatioF())
        painter.drawImage(rect.topLeft() - QRectF(0, 0, padding, padding - 6).bottomRight(), image)
        path = roundedPath(rect, radius)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        if currentTheme.styleId == "clay":
            gradient.setColorAt(0, QColor("#30324A"))
            gradient.setColorAt(1, QColor("#26283A"))
        else:
            gradient.setColorAt(0, QColor(24, 27, 48, 250))
            gradient.setColorAt(1, QColor(15, 17, 33, 250))
        painter.fillPath(path, gradient)
        glowColor = self.accent or currentTheme.accent
        glow = QLinearGradient(rect.topLeft(), rect.topRight())
        glow.setColorAt(0, withAlpha(glowColor, 0.22))
        glow.setColorAt(1, withAlpha(glowColor, 0.02))
        painter.fillPath(path, glow)
        painter.setPen(QPen(withAlpha(glowColor, 0.55), 1))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        if self.countdown is not None:
            bar = self._barRect()
            painter.setPen(Qt.NoPen)
            painter.setBrush(withAlpha(QColor("#FFFFFF"), 0.07))
            painter.drawRoundedRect(bar, 1.5, 1.5)
            if self.progress > 0.002:
                filled = QRectF(bar.left(), bar.top(), bar.width() * self.progress, bar.height())
                lineGradient = QLinearGradient(filled.topLeft(), filled.topRight())
                lineGradient.setColorAt(0, withAlpha(glowColor, 0.95))
                lineGradient.setColorAt(1, mix(glowColor, QColor("#FFFFFF"), 0.35))
                painter.setBrush(lineGradient)
                painter.drawRoundedRect(filled, 1.5, 1.5)
                tip = QRectF(filled.right() - 3, filled.center().y() - 3, 6, 6)
                painter.setBrush(withAlpha(mix(glowColor, QColor("#FFFFFF"), 0.6), 0.85))
                painter.drawEllipse(tip)


class AlertManager:
    """Stacks alert cards in the bottom-right corner of the primary screen.

    timeoutSeconds: >0 that many seconds, 0/None = the app default (Settings › Notifications), <0 = stays until closed.
    """

    def __init__(self, settingsGetter=None):
        self.cards = []
        self.settingsGetter = settingsGetter or (lambda key, default=None: default)

    def resolveTimeout(self, timeoutSeconds, actions):
        if timeoutSeconds is not None and timeoutSeconds < 0:
            return 0
        if timeoutSeconds:
            return float(timeoutSeconds)
        seconds = float(self.settingsGetter("notifications.seconds", DEFAULT_SECONDS) or DEFAULT_SECONDS)
        if actions:
            if self.settingsGetter("notifications.keepImportant", False):
                return 0
            seconds *= 2
        return seconds

    def show(self, title, message="", iconName="bell", actions=None, timeoutSeconds=0, accent=None, sound=None):
        card = AlertCard(title, message, iconName, actions, self.resolveTimeout(timeoutSeconds, actions), accent)
        card.closed.connect(self._onClosed)
        card.adjustSize()
        self.cards.append(card)
        self._layoutCards(enteringCard=card)
        if sound:
            system.playSound(sound if isinstance(sound, str) else "notify")
        return card

    def _onClosed(self, card):
        if card in self.cards:
            self.cards.remove(card)
            self._layoutCards()

    def _layoutCards(self, enteringCard=None):
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        bottom = area.bottom() - MARGIN
        animated = animationsOn()
        visible = self.cards[-MAX_VISIBLE:]
        for card in reversed(visible):
            height = card.sizeHint().height()
            target = QPoint(area.right() - card.width() - MARGIN, bottom - height)
            if card is enteringCard:
                card.enter(target)
            elif card.isVisible():
                card.moveTo(target, animated)
            else:
                card.enter(target)
            bottom -= height + GAP
        for card in self.cards[:-MAX_VISIBLE]:
            card.hide()

    def closeAll(self):
        for card in list(self.cards):
            card.closing = True
            card.close()
        self.cards = []
