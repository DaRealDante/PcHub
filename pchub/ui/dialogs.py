from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLineEdit,
                               QScrollArea, QVBoxLayout, QWidget)

from pchub.core.i18n import tr
from pchub.ui.icons import iconNames
from pchub.ui.theme import roundedPath, shadowImage, theme, themeManager, withAlpha, mix
from pchub.ui.widgets import (FlowLayout, IconTile, IconWidget, iconButton, makeButton, makeLabel, setThemedIcon)


class DialogPanel(QFrame):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        currentTheme = theme()
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = currentTheme.radius
        path = roundedPath(rect, radius)
        if currentTheme.styleId == "clay":
            gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            gradient.setColorAt(0, QColor("#303248"))
            gradient.setColorAt(1, QColor("#27293B"))
            painter.fillPath(path, gradient)
            painter.setClipPath(path)
            painter.setPen(QPen(QColor(255, 255, 255, 30), 3))
            painter.drawRoundedRect(rect.adjusted(1.5, 1.5, -1.5, -1.5), radius, radius)
        else:
            painter.fillPath(path, QColor(17, 20, 37, 246))
            glow = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.top() + 140))
            glow.setColorAt(0, withAlpha(currentTheme.accent, 0.16))
            glow.setColorAt(1, withAlpha(currentTheme.accent, 0.0))
            painter.fillPath(path, glow)
            painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


class ThemedDialog(QDialog):
    shadowMargin = 26

    def __init__(self, parent=None, width=460):
        hostWindow = parent.window() if parent is not None else None
        if hostWindow is not None and not hostWindow.isVisible():
            hostWindow = None
        super().__init__(hostWindow)
        flags = Qt.Dialog | Qt.FramelessWindowHint
        if hostWindow is None:
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.dragOffset = None
        outerLayout = QVBoxLayout(self)
        outerLayout.setContentsMargins(self.shadowMargin, self.shadowMargin, self.shadowMargin, self.shadowMargin)
        self.panel = DialogPanel(self)
        self.panel.setFixedWidth(width)
        outerLayout.addWidget(self.panel)
        self.bodyLayout = QVBoxLayout(self.panel)
        self.bodyLayout.setContentsMargins(24, 22, 24, 20)
        self.bodyLayout.setSpacing(14)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        panelRect = QRectF(self.panel.geometry())
        image, padding = shadowImage(panelRect.width(), panelRect.height(), theme().radius, 18, QColor(0, 0, 0, 150),
                                     self.devicePixelRatioF())
        painter.drawImage(panelRect.topLeft() - QPointF(padding, padding - 8), image)

    def showEvent(self, event):
        super().showEvent(event)
        self.adjustSize()
        parentWindow = self.parentWidget()
        if parentWindow is not None:
            center = parentWindow.frameGeometry().center()
        else:
            screen = QGuiApplication.screenAt(QPoint(0, 0)) or QGuiApplication.primaryScreen()
            center = screen.availableGeometry().center()
        self.move(center - QPoint(self.width() // 2, self.height() // 2))
        if themeManager().animations:
            self.setWindowOpacity(0.0)
            self.fadeAnimation = QPropertyAnimation(self, b"windowOpacity", self)
            self.fadeAnimation.setDuration(160)
            self.fadeAnimation.setStartValue(0.0)
            self.fadeAnimation.setEndValue(1.0)
            self.fadeAnimation.setEasingCurve(QEasingCurve.OutCubic)
            self.fadeAnimation.start()
        self.activateWindow()
        self.raise_()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragOffset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.dragOffset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.dragOffset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.dragOffset = None
        super().mouseReleaseEvent(event)

    def addHeader(self, title, iconName=None, iconColor=None, message=None):
        headerLayout = QHBoxLayout()
        headerLayout.setSpacing(14)
        if iconName:
            headerLayout.addWidget(IconTile(iconName, 42, iconColor), 0, Qt.AlignTop)
        textLayout = QVBoxLayout()
        textLayout.setSpacing(4)
        titleLabel = makeLabel(title, "subtitle", True)
        textLayout.addWidget(titleLabel)
        if message:
            textLayout.addWidget(makeLabel(message, "muted", True))
        headerLayout.addLayout(textLayout, 1)
        self.bodyLayout.addLayout(headerLayout)

    def addButtons(self, buttons):
        buttonRow = QHBoxLayout()
        buttonRow.setSpacing(10)
        buttonRow.addStretch(1)
        for button in buttons:
            buttonRow.addWidget(button)
        self.bodyLayout.addSpacing(4)
        self.bodyLayout.addLayout(buttonRow)


class ConfirmDialog(ThemedDialog):
    def __init__(self, parent, title, message="", details=None, danger=False, confirmText=None, cancelText=None,
                 iconName=None, checkboxText=None, showCancel=True):
        super().__init__(parent, 470)
        currentTheme = theme()
        iconName = iconName or ("triangle-alert" if danger else "circle-alert")
        title, message = tr(title), tr(message) if message else ""
        if isinstance(details, (str, dict)):
            details = [tr(details)]
        elif details:
            details = [(tr(detail[0]), tr(detail[1])) if isinstance(detail, (list, tuple)) else tr(detail) for detail in details]
        confirmText = tr(confirmText) if confirmText else confirmText
        self.addHeader(title, iconName, currentTheme.danger if danger else None, message)
        if details:
            detailsPanel = QFrame()
            detailsPanel.setObjectName("detailsPanel")
            detailsPanel.setStyleSheet(
                "#detailsPanel { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.09); border-radius: 12px; }")
            detailsLayout = QVBoxLayout(detailsPanel)
            detailsLayout.setContentsMargins(14, 10, 14, 10)
            detailsLayout.setSpacing(6)
            for detail in details[:40]:
                rowLayout = QHBoxLayout()
                rowLayout.setSpacing(8)
                if isinstance(detail, (list, tuple)):
                    labelText, valueText = detail[0], detail[1]
                    rowLayout.addWidget(IconWidget("chevron-right", "faint", 14), 0, Qt.AlignTop)
                    rowLayout.addWidget(makeLabel(labelText, None, True), 1)
                    valueLabel = makeLabel(valueText, "muted")
                    valueLabel.setAlignment(Qt.AlignRight | Qt.AlignTop)
                    rowLayout.addWidget(valueLabel)
                else:
                    rowLayout.addWidget(IconWidget("chevron-right", "faint", 14), 0, Qt.AlignTop)
                    rowLayout.addWidget(makeLabel(str(detail), None, True), 1)
                detailsLayout.addLayout(rowLayout)
            if len(details) > 40:
                detailsLayout.addWidget(makeLabel(f"+{len(details) - 40}…", "faint"))
            if len(details) > 8:
                scrollArea = QScrollArea()
                scrollArea.setWidgetResizable(True)
                scrollArea.setFrameShape(QFrame.NoFrame)
                scrollArea.setWidget(detailsPanel)
                scrollArea.setFixedHeight(220)
                self.bodyLayout.addWidget(scrollArea)
            else:
                self.bodyLayout.addWidget(detailsPanel)
        if danger:
            self.bodyLayout.addWidget(makeLabel(tr("common.irreversible"), "faint", True))
        self.checkbox = None
        if checkboxText:
            self.checkbox = QCheckBox(checkboxText)
            self.bodyLayout.addWidget(self.checkbox)
        buttons = []
        if showCancel:
            cancelButton = makeButton(cancelText or tr("common.cancel"))
            cancelButton.clicked.connect(self.reject)
            buttons.append(cancelButton)
        self.confirmButton = makeButton(confirmText or tr("common.confirm"), variant="danger" if danger else "primary")
        self.confirmButton.clicked.connect(self.accept)
        self.confirmButton.setDefault(True)
        buttons.append(self.confirmButton)
        self.addButtons(buttons)

    def checkboxChecked(self):
        return bool(self.checkbox and self.checkbox.isChecked())


def confirm(parent, title, message="", details=None, danger=False, confirmText=None, iconName=None, checkboxText=None):
    dialog = ConfirmDialog(parent, title, message, details, danger, confirmText, iconName=iconName,
                           checkboxText=checkboxText)
    accepted = dialog.exec() == QDialog.Accepted
    if checkboxText:
        return accepted, dialog.checkboxChecked()
    return accepted


def showMessage(parent, title, message="", iconName="info", details=None):
    dialog = ConfirmDialog(parent, title, message, details, False, tr("common.ok"), iconName=iconName, showCancel=False)
    dialog.exec()


class TextInputDialog(ThemedDialog):
    def __init__(self, parent, title, label="", text="", placeholder=""):
        super().__init__(parent, 420)
        self.addHeader(title, "pencil")
        if label:
            self.bodyLayout.addWidget(makeLabel(label, "muted"))
        self.lineEdit = QLineEdit(text)
        self.lineEdit.setPlaceholderText(placeholder)
        self.lineEdit.selectAll()
        self.lineEdit.returnPressed.connect(self.accept)
        self.bodyLayout.addWidget(self.lineEdit)
        cancelButton = makeButton(tr("common.cancel"))
        cancelButton.clicked.connect(self.reject)
        okButton = makeButton(tr("common.save"), variant="primary")
        okButton.clicked.connect(self.accept)
        self.addButtons([cancelButton, okButton])

    def showEvent(self, event):
        super().showEvent(event)
        self.lineEdit.setFocus()


def askText(parent, title, label="", text="", placeholder=""):
    dialog = TextInputDialog(parent, title, label, text, placeholder)
    if dialog.exec() == QDialog.Accepted:
        return True, dialog.lineEdit.text().strip()
    return False, text


class IconPickerDialog(ThemedDialog):
    def __init__(self, parent, currentIcon=None):
        super().__init__(parent, 520)
        self.selectedIcon = currentIcon
        self.addHeader(tr("iconPicker.title"), currentIcon or "sparkles")
        self.searchEdit = QLineEdit()
        self.searchEdit.setPlaceholderText(tr("common.search"))
        self.searchEdit.textChanged.connect(self._filter)
        self.bodyLayout.addWidget(self.searchEdit)
        scrollArea = QScrollArea()
        scrollArea.setWidgetResizable(True)
        scrollArea.setFrameShape(QFrame.NoFrame)
        scrollArea.setFixedHeight(300)
        gridHost = QWidget()
        self.flowLayout = FlowLayout(gridHost, 6)
        self.iconButtons = {}
        for name in iconNames():
            button = iconButton(name, name, "text", 20, checkable=True)
            button.setChecked(name == currentIcon)
            button.clicked.connect(lambda checked=False, iconName=name: self._choose(iconName))
            self.flowLayout.addWidget(button)
            self.iconButtons[name] = button
        scrollArea.setWidget(gridHost)
        self.bodyLayout.addWidget(scrollArea)
        cancelButton = makeButton(tr("common.cancel"))
        cancelButton.clicked.connect(self.reject)
        self.bodyLayout.addLayout(_rightAligned(cancelButton))

    def _filter(self, text):
        text = text.strip().lower()
        for name, button in self.iconButtons.items():
            button.setVisible(not text or text in name)
        self.flowLayout.invalidate()

    def _choose(self, iconName):
        self.selectedIcon = iconName
        self.accept()


def _rightAligned(widget):
    rowLayout = QHBoxLayout()
    rowLayout.addStretch(1)
    rowLayout.addWidget(widget)
    return rowLayout


def pickIcon(parent, currentIcon=None):
    dialog = IconPickerDialog(parent, currentIcon)
    if dialog.exec() == QDialog.Accepted:
        return dialog.selectedIcon
    return None


class ErrorDetailsDialog(ThemedDialog):
    def __init__(self, parent, title, text, detailsText):
        super().__init__(parent, 640)
        from PySide6.QtWidgets import QApplication, QPlainTextEdit
        self.addHeader(title, "triangle-alert", theme().danger, text)
        self.textBox = QPlainTextEdit(detailsText)
        self.textBox.setReadOnly(True)
        self.textBox.setMinimumHeight(260)
        font = self.textBox.font()
        font.setFamily("Consolas")
        font.setStyleHint(font.StyleHint.Monospace)
        font.setPixelSize(12)
        self.textBox.setFont(font)
        self.bodyLayout.addWidget(self.textBox)
        self.copyButton = makeButton(tr("plugin.copy"), "copy")

        def copyText():
            QApplication.clipboard().setText(detailsText)
            self.copyButton.setText(tr("plugin.copied"))

        self.copyButton.clicked.connect(copyText)
        closeButton = makeButton(tr("common.close"), variant="primary")
        closeButton.clicked.connect(self.accept)
        self.addButtons([self.copyButton, closeButton])
