import datetime
import uuid

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLineEdit, QMenu, QPlainTextEdit, QScrollArea, QFrame,
                               QSizePolicy, QVBoxLayout, QWidget)

from pchub.core.dates import (MONTHS, WEEKDAY_SHORT, describeRule, formatCountdown, formatDayMonth, formatRelativeDay,
                              italianHolidays, monthGrid, nextOccurrence, occurrencesBetween, parseDateTime, toIso)
from pchub.core.i18n import T, language, tr
from pchub.core.plugin_api import CalendarItem, HomeWidgetSpec, PluginBase, TrayEntry
from pchub.core.settings_schema import Choice, Section, Slider, Toggle
from pchub.ui.calendar_widgets import DateTimeField, MiniCalendar, RecurrenceEditor
from pchub.ui.dialogs import ThemedDialog, confirm
from pchub.ui.icons import drawIcon
from pchub.ui.pickers import ITEM_COLORS, ColorSwatches
from pchub.ui.theme import roundedPath, theme, withAlpha, mix
from pchub.ui.widgets import (Card, EmptyState, IconWidget, ToggleSwitch, clearLayout, divider, iconButton, makeButton,
                              makeLabel, setRole)

HOLIDAY_COLOR = "#F87171"
TEXT = {
    "today": T("Oggi", "Today"),
    "month": T("Mese", "Month"),
    "agenda": T("Agenda", "Agenda"),
    "newEvent": T("Nuovo evento", "New event"),
    "newReminder": T("Promemoria", "Reminder"),
    "nothing": T("Niente in programma", "Nothing planned"),
    "nothingText": T("Doppio clic su un giorno per aggiungere un evento.", "Double-click a day to add an event."),
    "more": T("+{count} altri", "+{count} more"),
    "allDay": T("Tutto il giorno", "All day"),
    "title": T("Titolo", "Title"),
    "notes": T("Note", "Notes"),
    "start": T("Inizio", "Start"),
    "end": T("Fine", "End"),
    "repeat": T("Ripeti", "Repeat"),
    "notify": T("Avvisami", "Notify me"),
    "color": T("Colore", "Color"),
    "save": T("Salva", "Save"),
    "cancel": T("Annulla", "Cancel"),
    "delete": T("Elimina", "Delete"),
    "editEvent": T("Modifica evento", "Edit event"),
    "deleteTitle": T("Eliminare l'evento?", "Delete the event?"),
    "noNotify": T("Nessun avviso", "No alert"),
    "atStart": T("All'inizio", "At start"),
    "before": T("{label} prima", "{label} before"),
    "sources": T("Mostra", "Show"),
    "holidays": T("Festività", "Holidays"),
    "events": T("Eventi", "Events"),
    "eventSoon": T("Evento", "Event"),
    "ok": T("Ok", "OK"),
    "upcoming": T("Prossimi giorni", "Coming up"),
}
NOTIFY_OPTIONS = [None, 0, 5, 15, 30, 60, 120, 1440]


def notifyLabel(minutes):
    if minutes is None:
        return tr(TEXT["noNotify"])
    if minutes == 0:
        return tr(TEXT["atStart"])
    if minutes < 60:
        label = f"{minutes} min"
    elif minutes < 1440:
        label = f"{minutes // 60} h"
    else:
        label = tr(T("1 giorno", "1 day"))
    return tr(TEXT["before"], label=label)


class CalendarPlugin(PluginBase):
    pluginId = "calendar"
    name = T("Calendario", "Calendar")
    description = T("Eventi, festività e tutto quello che hanno in programma gli altri plugin: promemoria, scadenze, to-do.",
                    "Events, holidays and everything the other plugins have planned: reminders, deadlines, to-dos.")
    icon = "calendar"
    version = "1.0.0"
    author = "PC Hub"
    settingsSchema = [
        Section(T("Calendario", "Calendar")),
        Toggle("showHolidays", T("Mostra le festività italiane", "Show Italian holidays"), True, icon="flag"),
        Toggle("showDone", T("Mostra le cose già fatte", "Show completed items"), True, icon="check", pinnable=False),
        Slider("defaultDuration", T("Durata predefinita di un evento", "Default event length"), 15, 240, 60, step=15,
               suffix=" min", icon="hourglass", pinnable=False),
        Choice("defaultNotify", T("Avviso predefinito", "Default alert"),
               [("none", T("Nessuno", "None")), ("0", T("All'inizio", "At start")), ("15", T("15 min prima", "15 min before")),
                ("60", T("1 ora prima", "1 hour before")), ("1440", T("1 giorno prima", "1 day before"))], "15",
               icon="bell", pinnable=False),
        Toggle("sound", T("Suono per gli avvisi", "Sound for alerts"), True, icon="volume-2"),
    ]

    itemsChanged = Signal()

    def __init__(self, context):
        super().__init__(context)
        self.clock = datetime.datetime.now
        self.events = list(context.getData("events", []) or [])
        self.notifiedKeys = list(context.getData("notifiedKeys", []) or [])
        self.hiddenSources = set(context.getData("hiddenSources", []) or [])
        self.checkTimer = QTimer(self)
        self.checkTimer.setInterval(20000)
        self.checkTimer.timeout.connect(self.check)
        self.lastDay = datetime.date.today()
        self.changeTimer = QTimer(self)
        self.changeTimer.setSingleShot(True)
        self.changeTimer.setInterval(150)
        self.changeTimer.timeout.connect(self.itemsChanged)

    def start(self):
        self.context.events.subscribe("*", self._onAnyEvent)
        self.checkTimer.start()
        QTimer.singleShot(2000, self.check)
        self.changeTimer.start()

    def stop(self):
        self.checkTimer.stop()
        self.context.events.unsubscribe("*", self._onAnyEvent)
        self.save()

    def _onAnyEvent(self, eventName, payload):
        if eventName in ("core.calendarChanged", "core.pluginStarted", "core.pluginStopped"):
            self.changeTimer.start()

    def save(self):
        self.context.setData("events", self.events)
        self.context.setData("notifiedKeys", self.notifiedKeys[-300:])

    def onSettingChanged(self, key, value):
        self.changeTimer.start()

    # events model -------------------------------------------------------------
    def find(self, eventId):
        return next((event for event in self.events if event["id"] == eventId), None)

    def addEvent(self, title, start, end=None, allDay=False, rule=None, notes="", color=None, notifyMinutes="default"):
        if notifyMinutes == "default":
            defaultValue = self.setting("defaultNotify")
            notifyMinutes = None if defaultValue in (None, "none") else int(defaultValue)
        if end is None and not allDay:
            end = start + datetime.timedelta(minutes=int(self.setting("defaultDuration") or 60))
        event = {"id": uuid.uuid4().hex[:10], "title": title.strip(), "notes": notes, "start": toIso(start),
                 "end": toIso(end) if end else None, "allDay": bool(allDay), "rule": rule or {"type": "none"},
                 "color": color or ITEM_COLORS[1], "notifyMinutes": notifyMinutes}
        self.events.append(event)
        self._changed()
        return event

    def updateEvent(self, eventId, **fields):
        event = self.find(eventId)
        if event is None:
            return
        for key in ("start", "end"):
            if isinstance(fields.get(key), datetime.datetime):
                fields[key] = toIso(fields[key])
        event.update(fields)
        self.notifiedKeys = [key for key in self.notifiedKeys if not key.startswith(f"{eventId}@")]
        self._changed()

    def deleteEvent(self, eventId):
        self.events = [event for event in self.events if event["id"] != eventId]
        self._changed()

    def _changed(self):
        self.save()
        self.changeTimer.start()

    def eventOccurrences(self, event, rangeStart, rangeEnd):
        start = parseDateTime(event["start"])
        end = parseDateTime(event.get("end"))
        duration = (end - start) if end and end > start else datetime.timedelta(0)
        searchStart = rangeStart - duration
        return [(occurrence, occurrence + duration if end else None)
                for occurrence in occurrencesBetween(start, event.get("rule"), searchStart, rangeEnd, 400)]

    # notifications ---------------------------------------------------------------
    def check(self):
        now = self.clock()
        if now.date() != self.lastDay:
            self.lastDay = now.date()
            self.changeTimer.start()
        horizon = now + datetime.timedelta(days=2)
        changed = False
        for event in self.events:
            notifyMinutes = event.get("notifyMinutes")
            if notifyMinutes is None:
                continue
            for occurrence, _ in self.eventOccurrences(event, now - datetime.timedelta(minutes=10), horizon):
                fireAt = occurrence - datetime.timedelta(minutes=int(notifyMinutes))
                key = f"{event['id']}@{toIso(occurrence)}"
                if fireAt <= now <= occurrence + datetime.timedelta(minutes=10) and key not in self.notifiedKeys:
                    self.notifiedKeys.append(key)
                    changed = True
                    self._ring(event, occurrence, now)
        if changed:
            self.save()

    def _ring(self, event, occurrence, now):
        when = tr(TEXT["allDay"]) if event.get("allDay") else f"{occurrence.strftime('%H:%M')} · {formatCountdown(occurrence, now)}"
        self.context.alert(event["title"], when + (f"\n{event['notes']}" if event.get("notes") else ""), "calendar",
                           [(tr(TEXT["ok"]), lambda: None, "check")], accent=event.get("color"),
                           sound="notify" if self.setting("sound") else None)
        self.context.emit("eventStarting", eventId=event["id"], title=event["title"])

    # gathering ----------------------------------------------------------------------
    def ownItems(self, startDate, endDate):
        rangeStart = datetime.datetime.combine(startDate, datetime.time())
        rangeEnd = datetime.datetime.combine(endDate + datetime.timedelta(days=1), datetime.time())
        items = []
        for event in self.events:
            for occurrence, occurrenceEnd in self.eventOccurrences(event, rangeStart, rangeEnd):
                item = CalendarItem(f"{event['id']}@{toIso(occurrence)}", event["title"], occurrence, occurrenceEnd,
                                    event.get("allDay", False), "calendar", event.get("color"),
                                    describeRule(event.get("rule")) if (event.get("rule") or {}).get("type", "none") != "none" else "",
                                    onOpen=lambda eventId=event["id"]: self.openEditor(eventId), kind="event")
                item.pluginId = self.pluginId
                items.append(item)
        if self.setting("showHolidays") and "holidays" not in self.hiddenSources:
            for year in range(startDate.year, endDate.year + 1):
                for day, holidayName in italianHolidays(year).items():
                    if startDate <= day <= endDate:
                        item = CalendarItem(f"holiday@{day}", holidayName, datetime.datetime.combine(day, datetime.time()),
                                            allDay=True, icon="flag", color=HOLIDAY_COLOR, kind="holiday")
                        item.pluginId = "holidays"
                        items.append(item)
        return items

    def gatherItems(self, startDate, endDate):
        items = [item for item in self.ownItems(startDate, endDate)
                 if item.pluginId == "holidays" or self.pluginId not in self.hiddenSources]
        for plugin in self.context.allPlugins():
            if plugin is self or plugin.pluginId in self.hiddenSources:
                continue
            try:
                pluginItems = plugin.calendarItems(startDate, endDate) or []
            except Exception:
                self.context.log.exception("calendarItems failed for %s", plugin.pluginId)
                continue
            for item in pluginItems:
                item.pluginId = plugin.pluginId
                items.append(item)
        if not self.setting("showDone"):
            items = [item for item in items if not item.done]
        return sorted(items, key=lambda item: (not item.allDay, item.start))

    def itemsByDay(self, startDate, endDate):
        byDay = {}
        for item in self.gatherItems(startDate, endDate):
            firstDay = max(item.start.date(), startDate)
            lastDay = item.end.date() if item.end and item.end.date() > item.start.date() else item.start.date()
            if item.end and item.end.time() == datetime.time() and item.end.date() > item.start.date():
                lastDay -= datetime.timedelta(days=1)
            day = firstDay
            while day <= min(lastDay, endDate):
                byDay.setdefault(day, []).append(item)
                day += datetime.timedelta(days=1)
        return byDay

    def sources(self):
        sources = [(self.pluginId, tr(TEXT["events"])), ("holidays", tr(TEXT["holidays"]))]
        for plugin in self.context.allPlugins():
            if plugin is not self and type(plugin).calendarItems is not PluginBase.calendarItems:
                sources.append((plugin.pluginId, self.context.manager.displayName(plugin.pluginId)))
        return sources

    def setSourceVisible(self, sourceId, visible):
        if visible:
            self.hiddenSources.discard(sourceId)
        else:
            self.hiddenSources.add(sourceId)
        self.context.setData("hiddenSources", sorted(self.hiddenSources))
        self.changeTimer.start()

    # editors ---------------------------------------------------------------------------
    def openEditor(self, eventId=None, presetDate=None, parent=None):
        EventEditor(self, self.find(eventId) if eventId else None, presetDate, parent).exec()

    def openReminderEditor(self, presetDate=None, parent=None):
        reminders = self.context.plugin("reminders")
        if reminders is not None:
            reminders.openEditor(presetDate=presetDate, parent=parent)

    def createPage(self):
        page = CalendarPage(self)
        return page

    def homeWidgets(self):
        return [HomeWidgetSpec("calendar.month", T("Calendario", "Calendar"), lambda: CalendarHomeWidget(self),
                               T("Il mese con i pallini di quello che succede e la lista di oggi.",
                                 "The month with dots for what's happening and today's list."), "calendar", "large",
                               ["large", "tall", "wide", "full"]),
                HomeWidgetSpec("calendar.agenda", T("Prossimi giorni", "Coming up"), lambda: AgendaHomeWidget(self),
                               T("Tutto quello che succede nei prossimi giorni.", "Everything happening in the next days."),
                               "list-todo", "wide", ["wide", "tall", "large", "full", "small"])]

    def trayEntries(self):
        return [TrayEntry("newEvent", TEXT["newEvent"], lambda: self.openEditor(), icon="calendar")]


Plugin = CalendarPlugin


class EventEditor(ThemedDialog):
    def __init__(self, plugin, event=None, presetDate=None, parent=None):
        super().__init__(parent, 540)
        self.plugin = plugin
        self.event = event
        self.addHeader(tr(TEXT["editEvent"] if event else TEXT["newEvent"]), "calendar", event.get("color") if event else None)
        self.titleEdit = QLineEdit(event["title"] if event else "")
        self.titleEdit.setPlaceholderText(tr(TEXT["title"]))
        self.titleEdit.returnPressed.connect(self._save)
        self.bodyLayout.addWidget(self.titleEdit)
        if event:
            startValue = parseDateTime(event["start"])
            endValue = parseDateTime(event.get("end"))
        else:
            baseDate = presetDate or datetime.date.today()
            now = datetime.datetime.now()
            startHour = now.hour + 1 if baseDate == now.date() else 9
            startValue = datetime.datetime.combine(baseDate, datetime.time(min(23, startHour), 0))
            endValue = startValue + datetime.timedelta(minutes=int(plugin.setting("defaultDuration") or 60))
        allDayRow = QHBoxLayout()
        allDayRow.addWidget(makeLabel(tr(TEXT["allDay"]), "muted"))
        self.allDayToggle = ToggleSwitch(bool(event.get("allDay")) if event else False)
        self.allDayToggle.toggled.connect(self._onAllDay)
        allDayRow.addWidget(self.allDayToggle)
        allDayRow.addStretch(1)
        self.bodyLayout.addLayout(allDayRow)
        self.startField = DateTimeField(startValue)
        self.startField.changed.connect(self._onStartChanged)
        self._row(tr(TEXT["start"]), self.startField)
        self.endField = DateTimeField(endValue or startValue)
        self._row(tr(TEXT["end"]), self.endField)
        self.recurrence = RecurrenceEditor(event.get("rule") if event else None)
        self._row(tr(TEXT["repeat"]), self.recurrence)
        self.notifyCombo = QComboBox()
        for minutes in NOTIFY_OPTIONS:
            self.notifyCombo.addItem(notifyLabel(minutes), minutes)
        if event:
            currentNotify = event.get("notifyMinutes")
        else:
            defaultValue = plugin.setting("defaultNotify")
            currentNotify = None if defaultValue in (None, "none") else int(defaultValue)
        self.notifyCombo.setCurrentIndex(max(0, self.notifyCombo.findData(currentNotify)))
        self._row(tr(TEXT["notify"]), self.notifyCombo)
        self.colorPicker = ColorSwatches(event.get("color") if event else ITEM_COLORS[1])
        self._row(tr(TEXT["color"]), self.colorPicker)
        self.notesEdit = QPlainTextEdit(event.get("notes", "") if event else "")
        self.notesEdit.setPlaceholderText(tr(TEXT["notes"]))
        self.notesEdit.setFixedHeight(64)
        self.bodyLayout.addWidget(self.notesEdit)
        buttons = []
        if event:
            deleteButton = makeButton(tr(TEXT["delete"]), "trash-2", "danger")
            deleteButton.clicked.connect(self._delete)
            buttons.append(deleteButton)
        cancelButton = makeButton(tr(TEXT["cancel"]))
        cancelButton.clicked.connect(self.reject)
        saveButton = makeButton(tr(TEXT["save"]), "check", "primary")
        saveButton.clicked.connect(self._save)
        self.addButtons(buttons + [cancelButton, saveButton])
        self._onAllDay(self.allDayToggle.isChecked())

    def _row(self, label, widget):
        rowLayout = QHBoxLayout()
        rowLayout.setSpacing(10)
        labelWidget = makeLabel(label, "muted")
        labelWidget.setFixedWidth(80)
        rowLayout.addWidget(labelWidget, 0, Qt.AlignTop)
        rowLayout.addWidget(widget, 1)
        self.bodyLayout.addLayout(rowLayout)

    def showEvent(self, event):
        super().showEvent(event)
        self.titleEdit.setFocus()

    def _onAllDay(self, allDay):
        self.startField.setTimeVisible(not allDay)
        self.endField.setTimeVisible(not allDay)

    def _onStartChanged(self, value):
        end = self.endField.value()
        if value and end and end <= value:
            self.endField.setValue(value + datetime.timedelta(minutes=int(self.plugin.setting("defaultDuration") or 60)))

    def _save(self):
        title = self.titleEdit.text().strip()
        if not title:
            self.titleEdit.setFocus()
            return
        allDay = self.allDayToggle.isChecked()
        start = self.startField.value()
        end = self.endField.value()
        if allDay:
            start = datetime.datetime.combine(start.date(), datetime.time())
            end = datetime.datetime.combine(max(end.date(), start.date()) + datetime.timedelta(days=1), datetime.time())
        elif end is None or end <= start:
            end = start + datetime.timedelta(minutes=int(self.plugin.setting("defaultDuration") or 60))
        values = dict(title=title, start=start, end=end, allDay=allDay, rule=self.recurrence.value(),
                      notes=self.notesEdit.toPlainText().strip(), color=self.colorPicker.value(),
                      notifyMinutes=self.notifyCombo.currentData())
        if self.event:
            self.plugin.updateEvent(self.event["id"], **values)
        else:
            self.plugin.addEvent(**values)
        self.accept()

    def _delete(self):
        if confirm(self, tr(TEXT["deleteTitle"]), "", [self.event["title"]], danger=True, confirmText=tr(TEXT["delete"])):
            self.plugin.deleteEvent(self.event["id"])
            self.accept()


class MonthView(QWidget):
    daySelected = Signal(object)
    dayDoubleClicked = Signal(object)
    itemClicked = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        today = datetime.date.today()
        self.year, self.month = today.year, today.month
        self.selectedDate = today
        self.itemsByDay = {}
        self.hoverDate = None
        self.chipRects = []
        self.setMouseTracking(True)
        self.setMinimumHeight(520)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def setMonth(self, year, month):
        self.year, self.month = year, month
        self.update()

    def setItems(self, itemsByDay):
        self.itemsByDay = itemsByDay
        self.update()

    def _cellRect(self, row, column):
        headerHeight = 26
        cellWidth = self.width() / 7.0
        cellHeight = (self.height() - headerHeight) / 6.0
        return QRectF(column * cellWidth, headerHeight + row * cellHeight, cellWidth, cellHeight)

    def _dateAt(self, position):
        grid = monthGrid(self.year, self.month)
        for row in range(6):
            for column in range(7):
                if self._cellRect(row, column).contains(QPointF(position)):
                    return grid[row][column]
        return None

    def mouseMoveEvent(self, event):
        hovered = self._dateAt(event.position())
        overChip = any(rect.contains(event.position()) for rect, _ in self.chipRects)
        self.setCursor(Qt.PointingHandCursor if overChip else Qt.ArrowCursor)
        if hovered != self.hoverDate:
            self.hoverDate = hovered
            self.update()

    def leaveEvent(self, event):
        self.hoverDate = None
        self.update()

    def mousePressEvent(self, event):
        for rect, item in self.chipRects:
            if rect.contains(event.position()):
                self.itemClicked.emit(item)
                return
        clicked = self._dateAt(event.position())
        if clicked is not None:
            self.selectedDate = clicked
            self.update()
            self.daySelected.emit(clicked)

    def mouseDoubleClickEvent(self, event):
        if any(rect.contains(event.position()) for rect, _ in self.chipRects):
            return
        clicked = self._dateAt(event.position())
        if clicked is not None:
            self.dayDoubleClicked.emit(clicked)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        currentTheme = theme()
        self.chipRects = []
        font = QFont(painter.font())
        font.setPixelSize(11)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(currentTheme.textMuted)
        for column, name in enumerate(WEEKDAY_SHORT[language()]):
            cell = self._cellRect(0, column)
            painter.drawText(QRectF(cell.x(), 0, cell.width(), 22), Qt.AlignCenter, name.upper())
        today = datetime.date.today()
        grid = monthGrid(self.year, self.month)
        lineColor = QColor(255, 255, 255, 18)
        for row in range(6):
            for column in range(7):
                dateValue = grid[row][column]
                cell = self._cellRect(row, column).adjusted(2, 2, -2, -2)
                inMonth = dateValue.month == self.month
                items = self.itemsByDay.get(dateValue, [])
                holiday = any(item.kind == "holiday" for item in items)
                path = roundedPath(cell, 10)
                if dateValue == self.selectedDate:
                    painter.fillPath(path, withAlpha(currentTheme.accent, 0.20))
                    painter.setPen(QPen(withAlpha(currentTheme.accentLight, 0.7), 1.2))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawPath(path)
                elif dateValue == self.hoverDate:
                    painter.fillPath(path, QColor(255, 255, 255, 14))
                elif inMonth:
                    painter.fillPath(path, QColor(255, 255, 255, 6 if currentTheme.styleId == "glass" else 4))
                if column >= 5 and inMonth:
                    painter.fillPath(path, QColor(255, 255, 255, 5))
                numberRect = QRectF(cell.x() + 6, cell.y() + 4, 24, 20)
                if dateValue == today:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(currentTheme.accent)
                    painter.drawRoundedRect(numberRect, 8, 8)
                    painter.setPen(currentTheme.accentText)
                elif holiday or column == 6:
                    painter.setPen(QColor(HOLIDAY_COLOR) if inMonth else withAlpha(QColor(HOLIDAY_COLOR), 0.4))
                else:
                    painter.setPen(currentTheme.text if inMonth else currentTheme.textFaint)
                numberFont = QFont(font)
                numberFont.setPixelSize(12)
                numberFont.setWeight(QFont.Bold if dateValue == today else QFont.DemiBold)
                painter.setFont(numberFont)
                painter.drawText(numberRect, Qt.AlignCenter, str(dateValue.day))
                chipTop = cell.y() + 27
                chipHeight = 18
                capacity = max(0, int((cell.bottom() - chipTop - 2) // (chipHeight + 2)))
                shown = items if len(items) <= capacity else items[:max(0, capacity - 1)]
                chipFont = QFont(font)
                chipFont.setPixelSize(10)
                chipFont.setWeight(QFont.Medium)
                painter.setFont(chipFont)
                for index, item in enumerate(shown):
                    chipRect = QRectF(cell.x() + 4, chipTop + index * (chipHeight + 2), cell.width() - 8, chipHeight)
                    color = QColor(item.color or currentTheme.accent.name())
                    alpha = 0.18 if item.done else (0.85 if item.allDay else 0.22)
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(withAlpha(color, alpha if inMonth else alpha * 0.5))
                    painter.drawRoundedRect(chipRect, 6, 6)
                    if not item.allDay:
                        painter.setBrush(color)
                        painter.drawRoundedRect(QRectF(chipRect.x(), chipRect.y() + 3, 3, chipRect.height() - 6), 1.5, 1.5)
                    textColor = QColor("#FFFFFF") if item.allDay and not item.done else currentTheme.text
                    if item.done or not inMonth:
                        textColor = currentTheme.textFaint
                    painter.setPen(textColor)
                    label = item.title if item.allDay else f"{item.start.strftime('%H:%M')} {item.title}"
                    textRect = chipRect.adjusted(7, 0, -4, 0)
                    chipFontDone = QFont(chipFont)
                    chipFontDone.setStrikeOut(item.done)
                    painter.setFont(chipFontDone)
                    painter.drawText(textRect, Qt.AlignVCenter | Qt.AlignLeft,
                                     painter.fontMetrics().elidedText(label, Qt.ElideRight, int(textRect.width())))
                    self.chipRects.append((chipRect, item))
                if len(shown) < len(items):
                    painter.setFont(chipFont)
                    painter.setPen(currentTheme.textMuted)
                    moreRect = QRectF(cell.x() + 8, chipTop + len(shown) * (chipHeight + 2), cell.width() - 12, chipHeight)
                    painter.drawText(moreRect, Qt.AlignVCenter | Qt.AlignLeft, tr(TEXT["more"], count=len(items) - len(shown)))
                painter.setFont(font)


class DayItemRow(QWidget):
    def __init__(self, plugin, item, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 6, 4, 6)
        layout.setSpacing(10)
        bar = QWidget()
        bar.setFixedSize(4, 30)
        bar.setStyleSheet(f"background: {item.color or theme().accent.name()}; border-radius: 2px;")
        layout.addWidget(bar)
        timeLabel = makeLabel(tr(TEXT["allDay"]) if item.allDay else item.start.strftime("%H:%M"), "faint")
        timeLabel.setFixedWidth(52 if not item.allDay else 90)
        layout.addWidget(timeLabel)
        textLayout = QVBoxLayout()
        textLayout.setSpacing(1)
        titleLabel = makeLabel(item.title, "faint" if item.done else None, True)
        if item.done:
            titleFont = titleLabel.font()
            titleFont.setStrikeOut(True)
            titleLabel.setFont(titleFont)
        textLayout.addWidget(titleLabel)
        sourceName = plugin.context.manager.displayName(item.pluginId) if item.pluginId not in ("holidays", plugin.pluginId) else (
            tr(TEXT["holidays"]) if item.pluginId == "holidays" else tr(TEXT["events"]))
        subtitle = " · ".join(part for part in (sourceName, item.subtitle) if part)
        textLayout.addWidget(makeLabel(subtitle, "faint", True))
        layout.addLayout(textLayout, 1)
        layout.addWidget(IconWidget(item.icon or "calendar", "muted", 15))
        if item.onOpen:
            self.setCursor(Qt.PointingHandCursor)
        self.item = item

    def mouseReleaseEvent(self, event):
        if self.item.onOpen and event.button() == Qt.LeftButton:
            self.item.onOpen()


class CalendarPage(QWidget):
    noScroll = True

    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        today = datetime.date.today()
        self.year, self.month = today.year, today.month
        self.selectedDate = today
        self.view = "month"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 16)
        layout.setSpacing(8)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        previousButton = iconButton("chevron-left", None, "text", 18)
        previousButton.clicked.connect(lambda: self.shiftMonth(-1))
        nextButton = iconButton("chevron-right", None, "text", 18)
        nextButton.clicked.connect(lambda: self.shiftMonth(1))
        self.monthLabel = makeLabel("", "title")
        toolbar.addWidget(previousButton)
        toolbar.addWidget(nextButton)
        toolbar.addWidget(self.monthLabel)
        todayButton = makeButton(tr(TEXT["today"]), None, "chip")
        todayButton.clicked.connect(self.goToday)
        toolbar.addWidget(todayButton)
        toolbar.addStretch(1)
        self.monthChip = makeButton(tr(TEXT["month"]), "calendar", "chip", checkable=True)
        self.agendaChip = makeButton(tr(TEXT["agenda"]), "list-todo", "chip", checkable=True)
        self.monthChip.clicked.connect(lambda: self.setView("month"))
        self.agendaChip.clicked.connect(lambda: self.setView("agenda"))
        toolbar.addWidget(self.monthChip)
        toolbar.addWidget(self.agendaChip)
        sourcesButton = makeButton(tr(TEXT["sources"]), "filter", "ghost")
        sourcesButton.clicked.connect(lambda: self._sourcesMenu(sourcesButton))
        toolbar.addWidget(sourcesButton)
        if plugin.context.plugin("reminders") is not None or True:
            self.reminderButton = makeButton(tr(TEXT["newReminder"]), "bell")
            self.reminderButton.clicked.connect(lambda: plugin.openReminderEditor(self.selectedDate, self))
            toolbar.addWidget(self.reminderButton)
        eventButton = makeButton(tr(TEXT["newEvent"]), "plus", "primary")
        eventButton.clicked.connect(lambda: plugin.openEditor(presetDate=self.selectedDate, parent=self))
        toolbar.addWidget(eventButton)
        layout.addLayout(toolbar)
        body = QHBoxLayout()
        body.setSpacing(4)
        self.monthCard = Card(padding=12, hoverable=False)
        monthLayout = QVBoxLayout(self.monthCard)
        self.monthView = MonthView()
        self.monthView.daySelected.connect(self.selectDay)
        self.monthView.dayDoubleClicked.connect(lambda day: plugin.openEditor(presetDate=day, parent=self))
        self.monthView.itemClicked.connect(lambda item: item.onOpen() if item.onOpen else self.selectDay(item.start.date()))
        monthLayout.addWidget(self.monthView)
        self.agendaScroll = QScrollArea()
        self.agendaScroll.setWidgetResizable(True)
        self.agendaScroll.setFrameShape(QFrame.NoFrame)
        self.agendaHost = QWidget()
        self.agendaLayout = QVBoxLayout(self.agendaHost)
        self.agendaLayout.setContentsMargins(0, 0, 8, 0)
        self.agendaScroll.setWidget(self.agendaHost)
        monthLayout.addWidget(self.agendaScroll)
        body.addWidget(self.monthCard, 1)
        self.dayCard = Card(padding=16, hoverable=False)
        self.dayCard.setFixedWidth(320)
        dayLayout = QVBoxLayout(self.dayCard)
        dayLayout.setSpacing(6)
        self.dayTitle = makeLabel("", "subtitle")
        self.daySubtitle = makeLabel("", "faint")
        dayLayout.addWidget(self.dayTitle)
        dayLayout.addWidget(self.daySubtitle)
        dayScroll = QScrollArea()
        dayScroll.setWidgetResizable(True)
        dayScroll.setFrameShape(QFrame.NoFrame)
        dayHost = QWidget()
        self.dayListLayout = QVBoxLayout(dayHost)
        self.dayListLayout.setContentsMargins(0, 0, 4, 0)
        self.dayListLayout.setSpacing(0)
        dayScroll.setWidget(dayHost)
        dayLayout.addWidget(dayScroll, 1)
        body.addWidget(self.dayCard)
        layout.addLayout(body, 1)
        plugin.itemsChanged.connect(self.refresh)
        self.setView("month")

    def _sourcesMenu(self, button):
        menu = QMenu(button)
        for sourceId, label in self.plugin.sources():
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(sourceId not in self.plugin.hiddenSources)
            action.toggled.connect(lambda checked, value=sourceId: self.plugin.setSourceVisible(value, checked))
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def setView(self, view):
        self.view = view
        self.monthChip.setChecked(view == "month")
        self.agendaChip.setChecked(view == "agenda")
        self.monthView.setVisible(view == "month")
        self.agendaScroll.setVisible(view == "agenda")
        self.refresh()

    def shiftMonth(self, offset):
        monthIndex = self.year * 12 + self.month - 1 + offset
        self.year, self.month = monthIndex // 12, monthIndex % 12 + 1
        self.refresh()

    def goToday(self):
        today = datetime.date.today()
        self.year, self.month = today.year, today.month
        self.selectDay(today)

    def selectDay(self, day):
        self.selectedDate = day
        if (day.year, day.month) != (self.year, self.month) and self.view == "month":
            self.year, self.month = day.year, day.month
        self.monthView.selectedDate = day
        self.refresh()

    def refresh(self):
        self.monthLabel.setText(f"{MONTHS[language()][self.month - 1].capitalize()} {self.year}")
        grid = monthGrid(self.year, self.month)
        startDate, endDate = grid[0][0], grid[-1][-1]
        agendaEnd = datetime.date.today() + datetime.timedelta(days=45)
        byDay = self.plugin.itemsByDay(min(startDate, datetime.date.today(), self.selectedDate),
                                       max(endDate, agendaEnd, self.selectedDate))
        self.monthView.setMonth(self.year, self.month)
        self.monthView.selectedDate = self.selectedDate
        self.monthView.setItems(byDay)
        self._fillDay(byDay.get(self.selectedDate, []))
        if self.view == "agenda":
            self._fillAgenda(byDay)

    def _fillDay(self, items):
        self.dayTitle.setText(formatDayMonth(self.selectedDate, True, self.selectedDate.year != datetime.date.today().year))
        self.daySubtitle.setText(formatRelativeDay(self.selectedDate))
        clearLayout(self.dayListLayout)
        if not items:
            self.dayListLayout.addWidget(EmptyState("calendar", tr(TEXT["nothing"]), tr(TEXT["nothingText"])))
        for index, item in enumerate(items):
            if index:
                self.dayListLayout.addWidget(divider())
            self.dayListLayout.addWidget(DayItemRow(self.plugin, item))
        self.dayListLayout.addStretch(1)

    def _fillAgenda(self, byDay):
        clearLayout(self.agendaLayout)
        today = datetime.date.today()
        anyItems = False
        for offset in range(45):
            day = today + datetime.timedelta(days=offset)
            items = [item for item in byDay.get(day, []) if not item.done]
            if not items:
                continue
            anyItems = True
            header = makeLabel(f"{formatRelativeDay(day).upper()} · {formatDayMonth(day, False)}", "section")
            header.setContentsMargins(4, 10, 0, 2)
            self.agendaLayout.addWidget(header)
            for item in items:
                self.agendaLayout.addWidget(DayItemRow(self.plugin, item))
        if not anyItems:
            self.agendaLayout.addWidget(EmptyState("calendar", tr(TEXT["nothing"]), ""))
        self.agendaLayout.addStretch(1)


class CalendarHomeWidget(QWidget):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        self.calendar = MiniCalendar(compact=True)
        self.calendar.setMinimumWidth(240)
        self.calendar.dateClicked.connect(self._onDate)
        self.calendar.monthChanged.connect(lambda year, month: self.refresh())
        layout.addWidget(self.calendar, 3)
        listLayout = QVBoxLayout()
        listLayout.setSpacing(4)
        self.dayLabel = makeLabel("", "accent")
        listLayout.addWidget(self.dayLabel)
        self.itemsLayout = QVBoxLayout()
        self.itemsLayout.setSpacing(2)
        listLayout.addLayout(self.itemsLayout)
        listLayout.addStretch(1)
        self.listHost = QWidget()
        self.listHost.setLayout(listLayout)
        layout.addWidget(self.listHost, 2)
        self.selectedDate = datetime.date.today()
        self.calendar.setSelectedDate(self.selectedDate)
        plugin.itemsChanged.connect(self.refresh)
        self.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.listHost.setVisible(self.width() > 480)

    def _onDate(self, day):
        self.selectedDate = day
        self.refresh()

    def refresh(self):
        grid = monthGrid(self.calendar.year, self.calendar.month)
        byDay = self.plugin.itemsByDay(grid[0][0], grid[-1][-1])
        markers = {day: [QColor(item.color or theme().accent.name()) for item in items if item.kind != "holiday"]
                   for day, items in byDay.items()}
        holidays = [day for day, items in byDay.items() if any(item.kind == "holiday" for item in items)]
        self.calendar.setMarkers(markers, holidays)
        self.dayLabel.setText(f"{formatRelativeDay(self.selectedDate)}")
        clearLayout(self.itemsLayout)
        items = self.plugin.itemsByDay(self.selectedDate, self.selectedDate).get(self.selectedDate, [])
        if not items:
            self.itemsLayout.addWidget(makeLabel(tr(TEXT["nothing"]), "faint"))
        for item in items[:6]:
            rowLayout = QHBoxLayout()
            rowLayout.setSpacing(6)
            dot = QWidget()
            dot.setFixedSize(8, 8)
            dot.setStyleSheet(f"background: {item.color or theme().accent.name()}; border-radius: 4px;")
            rowLayout.addWidget(dot)
            rowLayout.addWidget(makeLabel(item.title, "faint" if item.done else None), 1)
            rowLayout.addWidget(makeLabel("" if item.allDay else item.start.strftime("%H:%M"), "faint"))
            self.itemsLayout.addLayout(rowLayout)


class AgendaHomeWidget(QWidget):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.rowsLayout = QVBoxLayout(self)
        self.rowsLayout.setContentsMargins(0, 0, 0, 0)
        self.rowsLayout.setSpacing(3)
        plugin.itemsChanged.connect(self.refresh)
        self.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh()

    def refresh(self):
        clearLayout(self.rowsLayout)
        today = datetime.date.today()
        now = datetime.datetime.now()
        byDay = self.plugin.itemsByDay(today, today + datetime.timedelta(days=21))
        capacity = max(2, self.height() // 24)
        rows = 0
        for offset in range(22):
            day = today + datetime.timedelta(days=offset)
            for item in byDay.get(day, []):
                if item.done or (not item.allDay and item.start < now and day == today and (item.end or item.start) < now):
                    continue
                if rows >= capacity:
                    break
                rowLayout = QHBoxLayout()
                rowLayout.setSpacing(8)
                dot = QWidget()
                dot.setFixedSize(8, 8)
                dot.setStyleSheet(f"background: {item.color or theme().accent.name()}; border-radius: 4px;")
                rowLayout.addWidget(dot)
                rowLayout.addWidget(makeLabel(item.title), 1)
                whenText = formatRelativeDay(day) + ("" if item.allDay else f" {item.start.strftime('%H:%M')}")
                rowLayout.addWidget(makeLabel(whenText, "faint"))
                self.rowsLayout.addLayout(rowLayout)
                rows += 1
        if rows == 0:
            self.rowsLayout.addWidget(makeLabel(tr(TEXT["nothing"]), "faint"))
        self.rowsLayout.addStretch(1)
