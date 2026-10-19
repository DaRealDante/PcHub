from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from pchub import APP_NAME, VERSION
from pchub.core.i18n import tr
from pchub.ui.theme import roundedPath, shadowImage, theme, withAlpha
from pchub.ui.widgets import LogoWidget, MeterBar, makeLabel


class SplashWindow(QWidget):
    def __init__(self):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(380, 250)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(46, 40, 46, 40)
        layout.setSpacing(8)
        layout.addWidget(LogoWidget(58), 0, Qt.AlignHCenter)
        titleLabel = makeLabel(APP_NAME, "title")
        titleLabel.setAlignment(Qt.AlignCenter)
        layout.addWidget(titleLabel)
        self.statusLabel = makeLabel(tr("splash.loading"), "muted")
        self.statusLabel.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.statusLabel)
        layout.addSpacing(6)
        self.progressBar = MeterBar(None, 6)
        layout.addWidget(self.progressBar)
        versionLabel = makeLabel(f"v{VERSION}", "faint")
        versionLabel.setAlignment(Qt.AlignCenter)
        layout.addWidget(versionLabel)
        screen = QGuiApplication.primaryScreen()
        if screen:
            center = screen.availableGeometry().center()
            self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)

    def setProgress(self, fraction, text=None):
        self.progressBar.setValue(fraction)
        if text:
            self.statusLabel.setText(text)
        QApplication.processEvents()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        currentTheme = theme()
        rect = QRectF(self.rect()).adjusted(20, 16, -20, -26)
        image, padding = shadowImage(rect.width(), rect.height(), currentTheme.radius, 14, QColor(0, 0, 0, 150),
                                     self.devicePixelRatioF())
        painter.drawImage(rect.topLeft() - QRectF(0, 0, padding, padding - 8).bottomRight(), image)
        path = roundedPath(rect, currentTheme.radius)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        if currentTheme.styleId == "clay":
            gradient.setColorAt(0, QColor("#30324A"))
            gradient.setColorAt(1, QColor("#25273A"))
        else:
            gradient.setColorAt(0, QColor(24, 26, 48, 250))
            gradient.setColorAt(1, QColor(14, 16, 32, 250))
        painter.fillPath(path, gradient)
        glow = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        glow.setColorAt(0, withAlpha(currentTheme.accent, 0.22))
        glow.setColorAt(1, withAlpha(currentTheme.accent, 0.0))
        painter.fillPath(path, glow)
        painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), currentTheme.radius, currentTheme.radius)
