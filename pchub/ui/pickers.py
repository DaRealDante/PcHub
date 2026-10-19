"""Small reusable pickers: color swatches, weekday chips, choice chips."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from pchub.core.dates import WEEKDAY_SHORT
from pchub.core.i18n import language
from pchub.ui.widgets import makeButton

ITEM_COLORS = ["#8B7CF6", "#38BDF8", "#34D399", "#FBBF24", "#FB923C", "#F87171", "#F472B6", "#94A3B8"]


class Swatch(QPushButton):
    def __init__(self, colorHex, size=22, parent=None):
        super().__init__(parent)
        self.colorHex = colorHex
        self.setCheckable(True)
        self.setFixedSize(size + 4, size + 4)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QPushButton { background: transparent; border: none; padding: 0; }")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self.colorHex))
        painter.drawEllipse(self.rect().adjusted(4, 4, -4, -4))
        if self.isChecked() or self.underMouse():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(255, 255, 255, 230 if self.isChecked() else 110), 2))
            painter.drawEllipse(self.rect().adjusted(1, 1, -1, -1))


class ColorSwatches(QWidget):
    colorChanged = Signal(str)

    def __init__(self, value=None, colors=None, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.swatches = []
        for colorHex in colors or ITEM_COLORS:
            swatch = Swatch(colorHex)
            swatch.clicked.connect(lambda checked=False, value=colorHex: self.setValue(value, emit=True))
            layout.addWidget(swatch)
            self.swatches.append(swatch)
        layout.addStretch(1)
        self.currentValue = None
        self.setValue(value or (colors or ITEM_COLORS)[0])

    def setValue(self, value, emit=False):
        self.currentValue = value
        for swatch in self.swatches:
            swatch.setChecked(swatch.colorHex.lower() == (value or "").lower())
        if emit:
            self.colorChanged.emit(value)

    def value(self):
        return self.currentValue


class ChipGroup(QWidget):
    """Row of toggle chips. multi=True -> several selected (returns list), else exactly one."""
    changed = Signal(object)

    def __init__(self, options, value=None, multi=False, parent=None):
        super().__init__(parent)
        self.multi = multi
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.buttons = []
        for optionValue, label in options:
            button = makeButton(label, None, "chip", checkable=True)
            button.clicked.connect(lambda checked=False, value=optionValue: self._clicked(value))
            button.optionValue = optionValue
            layout.addWidget(button)
            self.buttons.append(button)
        layout.addStretch(1)
        self.setValue(value)

    def _clicked(self, optionValue):
        if self.multi:
            selected = self.value()
            if optionValue in selected:
                selected.remove(optionValue)
            else:
                selected.append(optionValue)
            self.setValue(selected)
        else:
            self.setValue(optionValue)
        self.changed.emit(self.value())

    def setValue(self, value):
        selected = set(value or []) if self.multi else {value}
        for button in self.buttons:
            button.setChecked(button.optionValue in selected)

    def value(self):
        selected = [button.optionValue for button in self.buttons if button.isChecked()]
        if self.multi:
            return selected
        return selected[0] if selected else None


def weekdayChips(value=None):
    return ChipGroup([(index, name) for index, name in enumerate(WEEKDAY_SHORT[language()])], value or [], multi=True)
