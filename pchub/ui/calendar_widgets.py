"""Themed date widgets: MiniCalendar (month grid) and DateTimeField (date button + popup calendar + time)."""
import datetime

from PySide6.QtCore import QPoint, QPointF, QRectF, QTime, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QTimeEdit, QVBoxLayout, QWidget

from pchub.core.dates import MONTHS, WEEKDAY_SHORT, formatDayMonth, monthGrid
from pchub.core.i18n import T, language, tr
from pchub.ui.icons import drawIcon
from pchub.ui.theme import roundedPath, shadowImage, theme, withAlpha, mix
from pchub.ui.widgets import iconButton, makeButton, makeLabel, setThemedIcon


class MiniCalendar(QWidget):
    dateClicked = Signal(object)
    monthChanged = Signal(int, int)

    def __init__(self, parent=None, compact=False):
        super().__init__(parent)
        today = datetime.date.today()
        self.year, self.month = today.year, today.month
        self.selectedDate = None
        self.markers = {}
        self.highlights = set()
        self.hoverDate = None
        self.compact = compact
        self.setMouseTracking(True)
        self.setMinimumSize(230, 220 if not compact else 190)
        self.headerHeight = 34

    def setMonth(self, year, month):
        if (year, month) != (self.year, self.month):
            self.year, self.month = year, month
            self.monthChanged.emit(year, month)
            self.update()

    def shiftMonth(self, offset):
        monthIndex = self.year * 12 + self.month - 1 + offset
        self.setMonth(monthIndex // 12, monthIndex % 12 + 1)

    def setSelectedDate(self, dateValue):
        self.selectedDate = dateValue
        if dateValue is not None:
            self.setMonth(dateValue.year, dateValue.month)
        self.update()

    def setMarkers(self, markers, highlights=None):
        """markers: {date: [QColor, ...]} small dots under the day number."""
        self.markers = markers or {}
        self.highlights = set(highlights or [])
        self.update()

    def _cellRect(self, row, column):
        gridTop = self.headerHeight + 22
        cellWidth = self.width() / 7.0
        cellHeight = (self.height() - gridTop) / 6.0
        return QRectF(column * cellWidth, gridTop + row * cellHeight, cellWidth, cellHeight)

    def _arrowRects(self):
        return QRectF(0, 2, 30, 30), QRectF(self.width() - 30, 2, 30, 30)

    def _dateAt(self, position):
        grid = monthGrid(self.year, self.month)
        for row in range(6):
            for column in range(7):
                if self._cellRect(row, column).contains(QPointF(position)):
                    return grid[row][column]
        return None

    def mouseMoveEvent(self, event):
        hovered = self._dateAt(event.position())
        if hovered != self.hoverDate:
            self.hoverDate = hovered
            self.update()

    def leaveEvent(self, event):
        self.hoverDate = None
        self.update()

    def mousePressEvent(self, event):
        previousRect, nextRect = self._arrowRects()
        if previousRect.contains(event.position()):
            self.shiftMonth(-1)
            return
        if nextRect.contains(event.position()):
            self.shiftMonth(1)
            return
        clicked = self._dateAt(event.position())
        if clicked is not None:
            self.selectedDate = clicked
            if clicked.month != self.month:
                self.setMonth(clicked.year, clicked.month)
            self.update()
            self.dateClicked.emit(clicked)

    def wheelEvent(self, event):
        self.shiftMonth(-1 if event.angleDelta().y() > 0 else 1)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        currentTheme = theme()
        previousRect, nextRect = self._arrowRects()
        drawIcon(painter, previousRect.adjusted(7, 7, -7, -7), "chevron-left", currentTheme.textMuted.name())
        drawIcon(painter, nextRect.adjusted(7, 7, -7, -7), "chevron-right", currentTheme.textMuted.name())
        font = painter.font()
        font.setPixelSize(14)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(currentTheme.text)
        title = f"{MONTHS[language()][self.month - 1].capitalize()} {self.year}"
        painter.drawText(QRectF(30, 2, self.width() - 60, 30), Qt.AlignCenter, title)
        font.setPixelSize(11)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(currentTheme.textFaint)
        for column, name in enumerate(WEEKDAY_SHORT[language()]):
            painter.drawText(QRectF(self._cellRect(0, column).x(), self.headerHeight, self.width() / 7.0, 18), Qt.AlignCenter,
                             name[:2] if self.compact else name)
        today = datetime.date.today()
        grid = monthGrid(self.year, self.month)
        font.setPixelSize(12)
        for row in range(6):
            for column in range(7):
                dateValue = grid[row][column]
                cell = self._cellRect(row, column)
                size = min(cell.width(), cell.height()) - 4
                circle = QRectF(cell.center().x() - size / 2, cell.center().y() - size / 2, size, size)
                inMonth = dateValue.month == self.month
                selected = dateValue == self.selectedDate
                painter.setPen(Qt.NoPen)
                if selected:
                    painter.setBrush(currentTheme.accent)
                    painter.drawRoundedRect(circle, size * 0.32, size * 0.32)
                elif dateValue == self.hoverDate:
                    painter.setBrush(QColor(255, 255, 255, 22))
                    painter.drawRoundedRect(circle, size * 0.32, size * 0.32)
                if dateValue == today and not selected:
                    painter.setPen(QPen(currentTheme.accentLight, 1.5))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawRoundedRect(circle.adjusted(1, 1, -1, -1), size * 0.32, size * 0.32)
                if selected:
                    painter.setPen(currentTheme.accentText)
                elif dateValue in self.highlights:
                    painter.setPen(currentTheme.danger if inMonth else withAlpha(currentTheme.danger, 0.5))
                else:
                    painter.setPen(currentTheme.text if inMonth else currentTheme.textFaint)
                font.setBold(selected or dateValue == today)
                painter.setFont(font)
                painter.drawText(circle.adjusted(0, -4 if self.markers.get(dateValue) else 0, 0, 0), Qt.AlignCenter,
                                 str(dateValue.day))
                colors = self.markers.get(dateValue) or []
                if colors:
                    shown = colors[:3]
                    dotSpacing = 6
                    startX = circle.center().x() - (len(shown) - 1) * dotSpacing / 2
                    for index, color in enumerate(shown):
                        painter.setPen(Qt.NoPen)
                        painter.setBrush(currentTheme.accentText if selected else QColor(color))
                        painter.drawEllipse(QPointF(startX + index * dotSpacing, circle.bottom() - 6), 2.2, 2.2)


class CalendarPopup(QFrame):
    dateChosen = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(8)
        quickRow = QHBoxLayout()
        quickRow.setSpacing(6)
        today = datetime.date.today()
        for label, offset in ((T("Oggi", "Today"), 0), (T("Domani", "Tomorrow"), 1), (T("+1 sett.", "+1 week"), 7)):
            chip = makeButton(tr(label), None, "chip")
            chip.clicked.connect(lambda checked=False, value=today + datetime.timedelta(days=offset): self._choose(value))
            quickRow.addWidget(chip)
        quickRow.addStretch(1)
        layout.addLayout(quickRow)
        self.calendar = MiniCalendar(compact=True)
        self.calendar.setFixedSize(260, 230)
        self.calendar.dateClicked.connect(self._choose)
        layout.addWidget(self.calendar)

    def _choose(self, dateValue):
        self.dateChosen.emit(dateValue)
        self.close()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        currentTheme = theme()
        rect = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        painter.fillPath(roundedPath(rect, currentTheme.radiusSmall + 4),
                         QColor("#2A2C3F") if currentTheme.styleId == "clay" else QColor(20, 23, 42, 250))
        painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), currentTheme.radiusSmall + 4, currentTheme.radiusSmall + 4)


class DateTimeField(QWidget):
    """[📅 Lunedì 20 ottobre ▾] [18:30] [×]  — emits changed(datetime | None)."""
    changed = Signal(object)

    def __init__(self, value=None, withTime=True, allowEmpty=False, parent=None):
        super().__init__(parent)
        self.withTime = withTime
        self.allowEmpty = allowEmpty
        self.dateValue = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.dateButton = makeButton("", "calendar")
        self.dateButton.setMinimumWidth(190)
        self.dateButton.clicked.connect(self._openPopup)
        layout.addWidget(self.dateButton, 1)
        self.timeEdit = QTimeEdit()
        self.timeEdit.setDisplayFormat("HH:mm")
        self.timeEdit.setAlignment(Qt.AlignCenter)
        self.timeEdit.setMinimumWidth(80)
        self.timeEdit.timeChanged.connect(lambda value: self.changed.emit(self.value()))
        self.timeEdit.setVisible(withTime)
        layout.addWidget(self.timeEdit)
        self.clearButton = iconButton("x", tr(T("Nessuna data", "No date")), "muted", 14)
        self.clearButton.clicked.connect(lambda: self.setValue(None, emit=True))
        self.clearButton.setVisible(allowEmpty)
        layout.addWidget(self.clearButton)
        self.setValue(value)

    def setTimeVisible(self, visible):
        self.withTime = visible
        self.timeEdit.setVisible(visible and self.dateValue is not None)

    def setValue(self, value, emit=False):
        if value is None and not self.allowEmpty:
            value = datetime.datetime.now().replace(second=0, microsecond=0) + datetime.timedelta(hours=1)
        if isinstance(value, datetime.datetime):
            self.dateValue = value.date()
            self.timeEdit.blockSignals(True)
            self.timeEdit.setTime(QTime(value.hour, value.minute))
            self.timeEdit.blockSignals(False)
        elif isinstance(value, datetime.date):
            self.dateValue = value
        else:
            self.dateValue = None
        self._refresh()
        if emit:
            self.changed.emit(self.value())

    def value(self):
        if self.dateValue is None:
            return None
        timeValue = self.timeEdit.time() if self.withTime else QTime(0, 0)
        return datetime.datetime.combine(self.dateValue, datetime.time(timeValue.hour(), timeValue.minute()))

    def _refresh(self):
        if self.dateValue is None:
            self.dateButton.setText(tr(T("Nessuna data", "No date")))
        else:
            self.dateButton.setText(formatDayMonth(self.dateValue, True, self.dateValue.year != datetime.date.today().year))
        self.timeEdit.setVisible(self.withTime and self.dateValue is not None)
        self.clearButton.setVisible(self.allowEmpty and self.dateValue is not None)

    def _openPopup(self):
        popup = CalendarPopup(self)
        popup.calendar.setSelectedDate(self.dateValue or datetime.date.today())
        popup.dateChosen.connect(self._onChosen)
        popup.adjustSize()
        popup.move(self.dateButton.mapToGlobal(QPoint(0, self.dateButton.height() + 4)))
        popup.show()
        self.popup = popup

    def _onChosen(self, dateValue):
        self.dateValue = dateValue
        self._refresh()
        self.changed.emit(self.value())


class RecurrenceEditor(QWidget):
    """Repeat: [combo]  every [N]  on [Mon..Sun chips]  until [date]. value() -> rule dict."""
    changed = Signal(object)

    def __init__(self, rule=None, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QComboBox, QSpinBox
        from pchub.core.dates import REPEAT_OPTIONS, parseDate
        from pchub.ui.pickers import weekdayChips
        rule = dict(rule or {"type": "none"})
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        topRow = QHBoxLayout()
        topRow.setSpacing(6)
        self.typeCombo = QComboBox()
        for value, label in REPEAT_OPTIONS:
            self.typeCombo.addItem(tr(label), value)
        self.typeCombo.setCurrentIndex(max(0, self.typeCombo.findData(rule.get("type", "none"))))
        topRow.addWidget(self.typeCombo, 1)
        self.intervalLabel = makeLabel(tr(T("ogni", "every")), "muted")
        topRow.addWidget(self.intervalLabel)
        self.intervalSpin = QSpinBox()
        self.intervalSpin.setRange(1, 99)
        self.intervalSpin.setValue(int(rule.get("interval", 1) or 1))
        self.intervalSpin.setMinimumWidth(64)
        topRow.addWidget(self.intervalSpin)
        layout.addLayout(topRow)
        self.daysChips = weekdayChips(rule.get("days") or [])
        layout.addWidget(self.daysChips)
        untilRow = QHBoxLayout()
        untilRow.setSpacing(6)
        self.untilLabel = makeLabel(tr(T("Fino al", "Until")), "muted")
        untilRow.addWidget(self.untilLabel)
        self.untilField = DateTimeField(parseDate(rule.get("until")), withTime=False, allowEmpty=True)
        untilRow.addWidget(self.untilField, 1)
        layout.addLayout(untilRow)
        self.typeCombo.currentIndexChanged.connect(self._refresh)
        self.intervalSpin.valueChanged.connect(lambda value: self.changed.emit(self.value()))
        self.daysChips.changed.connect(lambda value: self.changed.emit(self.value()))
        self.untilField.changed.connect(lambda value: self.changed.emit(self.value()))
        self._refresh(emit=False)

    def _refresh(self, *args, emit=True):
        ruleType = self.typeCombo.currentData()
        self.intervalLabel.setVisible(ruleType in ("daily", "weekly", "monthly", "yearly"))
        self.intervalSpin.setVisible(ruleType in ("daily", "weekly", "monthly", "yearly"))
        self.daysChips.setVisible(ruleType == "custom")
        self.untilLabel.setVisible(ruleType != "none")
        self.untilField.setVisible(ruleType != "none")
        if emit:
            self.changed.emit(self.value())

    def value(self):
        ruleType = self.typeCombo.currentData()
        rule = {"type": ruleType}
        if ruleType in ("daily", "weekly", "monthly", "yearly"):
            rule["interval"] = self.intervalSpin.value()
        if ruleType == "custom":
            rule["days"] = sorted(self.daysChips.value()) or [datetime.date.today().weekday()]
        until = self.untilField.value()
        if ruleType != "none" and until is not None:
            rule["until"] = until.date().isoformat()
        return rule
