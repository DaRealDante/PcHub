import datetime

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget)

from pchub.core.dates import describeRule, formatCountdown, formatWhen, occurrencesBetween, parseDateTime, toIso
from pchub.core.events import AutomationAction
from pchub.core.i18n import T, tr
from pchub.core.plugin_api import ActiveItem, CalendarItem, HomeWidgetSpec, PluginBase, TrayEntry
from pchub.core.settings_schema import HotkeySetting, Section, Slider, Toggle
from pchub.plugins.reminders import logic
from pchub.ui.calendar_widgets import DateTimeField, RecurrenceEditor
from pchub.ui.dialogs import ThemedDialog, confirm
from pchub.ui.pickers import ITEM_COLORS, ColorSwatches
from pchub.ui.theme import theme
from pchub.ui.widgets import (Card, EmptyState, IconWidget, ToggleSwitch, clearLayout, divider, iconButton, makeButton,
                              makeLabel, setThemedIcon)

TEXT = {
    "placeholder": T("Cosa devo ricordarti? (es. \"domani alle 9 chiama Marco\")",
                     "What should I remind you? (e.g. \"tomorrow at 9 call Marco\")"),
    "add": T("Aggiungi", "Add"),
    "more": T("Altre opzioni", "More options"),
    "in10": T("Tra 10 min", "In 10 min"),
    "in60": T("Tra 1 ora", "In 1 hour"),
    "tonight": T("Stasera 20:00", "Tonight 8 PM"),
    "tomorrow": T("Domani 9:00", "Tomorrow 9 AM"),
    "overdue": T("Scaduti", "Overdue"),
    "today": T("Oggi", "Today"),
    "tomorrowSection": T("Domani", "Tomorrow"),
    "week": T("Prossimi 7 giorni", "Next 7 days"),
    "later": T("Più avanti", "Later"),
    "done": T("Completati", "Completed"),
    "empty": T("Nessun promemoria", "No reminders"),
    "emptyText": T("Scrivi qui sopra cosa devi ricordare e quando.", "Type above what to remember and when."),
    "markDone": T("Fatto", "Done"),
    "snooze": T("Posticipa {minutes} min", "Snooze {minutes} min"),
    "edit": T("Modifica", "Edit"),
    "delete": T("Elimina", "Delete"),
    "deleteTitle": T("Eliminare il promemoria?", "Delete the reminder?"),
    "deleteRepeating": T("È un promemoria che si ripete: verranno eliminate tutte le ripetizioni future.",
                         "It repeats: all future repetitions will be deleted."),
    "editorNew": T("Nuovo promemoria", "New reminder"),
    "editorEdit": T("Modifica promemoria", "Edit reminder"),
    "title": T("Titolo", "Title"),
    "notes": T("Note", "Notes"),
    "when": T("Quando", "When"),
    "repeat": T("Ripeti", "Repeat"),
    "lead": T("Avvisami", "Notify me"),
    "color": T("Colore", "Color"),
    "soundOption": T("Suono", "Sound"),
    "popupOption": T("Avviso in primo piano", "On-top alert"),
    "save": T("Salva", "Save"),
    "cancel": T("Annulla", "Cancel"),
    "ringingTitle": T("Promemoria", "Reminder"),
    "late": T("in ritardo", "late"),
    "reopen": T("Riapri", "Reopen"),
    "atTime": T("All'ora esatta", "At the time"),
    "minutesBefore": T("{count} min prima", "{count} min before"),
    "hoursBefore": T("{count} ore prima", "{count} hours before"),
    "hourBefore": T("1 ora prima", "1 hour before"),
    "dayBefore": T("1 giorno prima", "1 day before"),
    "quickTitle": T("Promemoria al volo", "Quick reminder"),
    "quickHint": T("Scrivi e premi Invio. Puoi dire quando: \"tra 20 min\", \"domani alle 9\", \"venerdì 18:30\"…",
                   "Type and press Enter. You can say when: \"in 20 min\", \"tomorrow at 9\", \"friday 6:30 pm\"…"),
    "noTimeHint": T("Nessuna data trovata: lo imposto tra 1 ora.", "No time found: I'll set it in 1 hour."),
    "next": T("Prossimi", "Upcoming"),
    "addedToast": T("Promemoria aggiunto · {when}", "Reminder added · {when}"),
}


def leadLabel(minutes):
    if minutes == 0:
        return tr(TEXT["atTime"])
    if minutes == 60:
        return tr(TEXT["hourBefore"])
    if minutes == 1440:
        return tr(TEXT["dayBefore"])
    if minutes % 60 == 0:
        return tr(TEXT["hoursBefore"], count=minutes // 60)
    return tr(TEXT["minutesBefore"], count=minutes)


class RemindersPlugin(PluginBase):
    pluginId = "reminders"
    name = T("Promemoria", "Reminders")
    description = T("Promemoria con notifiche, ripetizioni e posticipa. Compaiono anche nel calendario.",
                    "Reminders with notifications, repeats and snooze. They also show up on the calendar.")
    icon = "bell"
    version = "1.0.0"
    author = "PC Hub"
    settingsSchema = [
        Section(T("Avvisi", "Alerts")),
        Toggle("popupAlerts", T("Mostra un avviso in primo piano", "Show an on-top alert"), True, icon="bell-ring",
               description=T("Una scheda in basso a destra che resta finché non premi Fatto o Posticipa.",
                             "A card in the bottom-right corner that stays until you press Done or Snooze.")),
        Toggle("windowsNotification", T("Notifica di Windows", "Windows notification"), False, icon="bell"),
        Toggle("sound", T("Suono", "Sound"), True, icon="volume-2"),
        Slider("snoozeMinutes", T("Posticipa di", "Snooze for"), 1, 120, 10, suffix=" min", icon="history",
               pinnable=False),
        Section(T("Scorciatoie", "Shortcuts")),
        HotkeySetting("quickAddHotkey", T("Promemoria al volo", "Quick reminder"), action="openQuickAdd",
                      default="Ctrl+Alt+R", icon="keyboard",
                      description=T("Apre un campo veloce da qualsiasi programma.", "Opens a quick field from any program.")),
        Section(T("Lista", "List")),
        Toggle("showCompleted", T("Mostra i completati", "Show completed"), True, icon="check", pinnable=False),
    ]

    remindersChanged = Signal()

    def __init__(self, context):
        super().__init__(context)
        self.clock = datetime.datetime.now
        self.reminders = list(context.getData("reminders", []) or [])
        self.alertCards = {}
        self.checkTimer = QTimer(self)
        self.checkTimer.setInterval(5000)
        self.checkTimer.timeout.connect(self.check)

    # lifecycle ---------------------------------------------------------------
    def start(self):
        self.checkTimer.start()
        QTimer.singleShot(1500, self.check)
        self._refreshActive()

    def stop(self):
        self.checkTimer.stop()
        self.save()
        for card in list(self.alertCards.values()):
            try:
                card.close()
            except RuntimeError:
                pass
        self.alertCards = {}

    def save(self):
        self.context.setData("reminders", self.reminders)

    def _changed(self):
        self.save()
        self._refreshActive()
        self.remindersChanged.emit()
        self.context.notifyCalendarChanged()

    # model --------------------------------------------------------------------
    def find(self, reminderId):
        return next((reminder for reminder in self.reminders if reminder["id"] == reminderId), None)

    def add(self, title, when, rule=None, notes="", leadMinutes=0, color=None, sound=True, popup=True):
        reminder = logic.newReminder(title or tr(TEXT["ringingTitle"]), when, rule, notes, leadMinutes,
                                     color or ITEM_COLORS[0], sound, popup, now=self.clock())
        self.reminders.append(reminder)
        self._changed()
        return reminder

    def update(self, reminderId, **fields):
        reminder = self.find(reminderId)
        if reminder is None:
            return
        if "start" in fields and isinstance(fields["start"], datetime.datetime):
            fields["start"] = toIso(fields["start"])
        reminder.update(fields)
        if reminder.get("completed"):
            reminder["completed"] = False
        logic.scheduleFirst(reminder, self.clock())
        self._closeCard(reminderId)
        self._changed()

    def delete(self, reminderId):
        self.reminders = [reminder for reminder in self.reminders if reminder["id"] != reminderId]
        self._closeCard(reminderId)
        self._changed()

    def markDone(self, reminderId):
        reminder = self.find(reminderId)
        if reminder:
            logic.complete(reminder, self.clock())
            self._closeCard(reminderId)
            self._changed()

    def reopen(self, reminderId):
        reminder = self.find(reminderId)
        if reminder:
            logic.reopen(reminder, self.clock())
            self._changed()

    def snooze(self, reminderId, minutes=None):
        reminder = self.find(reminderId)
        if reminder:
            logic.snooze(reminder, minutes or int(self.setting("snoozeMinutes") or 10), self.clock())
            self._closeCard(reminderId)
            self._changed()

    def upcoming(self):
        pending = [reminder for reminder in self.reminders if not reminder.get("completed") and reminder.get("nextAt")]
        return sorted(pending, key=lambda reminder: reminder.get("snoozedUntil") or reminder["nextAt"])

    def completed(self):
        done = [reminder for reminder in self.reminders if reminder.get("completed")]
        return sorted(done, key=lambda reminder: reminder.get("completedAt") or "", reverse=True)

    # engine -----------------------------------------------------------------------
    def check(self):
        now = self.clock()
        changed = False
        for reminder in self.reminders:
            if logic.dueToRing(reminder, now):
                logic.markRung(reminder)
                self.ring(reminder, now)
                changed = True
        if changed:
            self._changed()
        else:
            self._refreshActive()

    def ring(self, reminder, now):
        reminderId = reminder["id"]
        dueAt = parseDateTime(reminder.get("snoozedUntil") or reminder["nextAt"])
        message = formatWhen(parseDateTime(reminder["nextAt"]))
        if (now - dueAt).total_seconds() > 120:
            message += f" · {tr(TEXT['late'])}"
        if reminder.get("notes"):
            message += f"\n{reminder['notes']}"
        soundName = "alarm" if (self.setting("sound") and reminder.get("sound", True)) else None
        snoozeMinutes = int(self.setting("snoozeMinutes") or 10)
        if self.setting("popupAlerts") and reminder.get("popup", True):
            self._closeCard(reminderId)
            card = self.context.alert(reminder["title"], message, "bell-ring",
                                      [(tr(TEXT["snooze"], minutes=snoozeMinutes), lambda: self.snooze(reminderId), "history"),
                                       (tr(TEXT["markDone"]), lambda: self.markDone(reminderId), "check")],
                                      accent=reminder.get("color"), sound=soundName)
            if card is not None:
                self.alertCards[reminderId] = card
            soundName = None
        if self.setting("windowsNotification") or not (self.setting("popupAlerts") and reminder.get("popup", True)):
            self.context.notify(reminder["title"], message.split("\n")[0], soundName)
        self.context.emit("ringing", reminderId=reminderId, title=reminder["title"])

    def _closeCard(self, reminderId):
        card = self.alertCards.pop(reminderId, None)
        if card is not None:
            try:
                card.close()
            except RuntimeError:
                pass

    def _refreshActive(self):
        ringing = {reminder["id"]: reminder for reminder in self.reminders if logic.isRinging(reminder)}
        for reminderId, reminder in ringing.items():
            self.context.setActive(ActiveItem(
                reminderId, reminder["title"], formatWhen(parseDateTime(reminder["nextAt"])), icon="bell-ring",
                accent=reminder.get("color"),
                actions=[(T("Posticipa", "Snooze"), "history", lambda reminderId=reminderId: self.snooze(reminderId)),
                         (TEXT["markDone"], "check", lambda reminderId=reminderId: self.markDone(reminderId))]))
        for reminder in self.reminders:
            if reminder["id"] not in ringing:
                self.context.removeActive(reminder["id"])

    # quick add ------------------------------------------------------------------
    def quickAdd(self, text):
        text = (text or "").strip()
        if not text:
            return None
        title, when = logic.parseQuickReminder(text, self.clock())
        if when is None:
            when = self.clock().replace(second=0, microsecond=0) + datetime.timedelta(hours=1)
        return self.add(title or text, when)

    def openQuickAdd(self):
        dialog = QuickAddDialog(self)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self._quickDialog = dialog

    def openEditor(self, reminderId=None, presetDate=None, parent=None):
        dialog = ReminderEditor(self, self.find(reminderId) if reminderId else None, presetDate, parent)
        dialog.exec()

    # integrations -------------------------------------------------------------------
    def calendarItems(self, startDate, endDate):
        rangeStart = datetime.datetime.combine(startDate, datetime.time())
        rangeEnd = datetime.datetime.combine(endDate + datetime.timedelta(days=1), datetime.time())
        items = []
        for reminder in self.reminders:
            start = parseDateTime(reminder["start"])
            if start is None:
                continue
            color = reminder.get("color") or ITEM_COLORS[0]
            subtitle = describeRule(reminder.get("rule")) if logic.isRepeating(reminder) else ""
            openCallback = lambda reminderId=reminder["id"]: self.openEditor(reminderId)
            if reminder.get("completed") and not logic.isRepeating(reminder):
                when = parseDateTime(reminder.get("nextAt") or reminder["start"])
                if rangeStart <= when < rangeEnd:
                    items.append(CalendarItem(f"{reminder['id']}", reminder["title"], when, icon="bell", color=color,
                                              done=True, onOpen=openCallback, kind="reminder"))
                continue
            for occurrence in occurrencesBetween(start, reminder.get("rule"), rangeStart, rangeEnd, 200):
                nextAt = parseDateTime(reminder.get("nextAt"))
                done = nextAt is not None and occurrence < nextAt
                items.append(CalendarItem(f"{reminder['id']}@{toIso(occurrence)}", reminder["title"], occurrence,
                                          icon="bell", color=color, subtitle=subtitle, done=done, onOpen=openCallback,
                                          kind="reminder"))
        return items

    def createPage(self):
        return RemindersPage(self)

    def homeWidgets(self):
        return [HomeWidgetSpec("reminders.upcoming", T("Promemoria", "Reminders"), lambda: RemindersHomeWidget(self),
                               T("I prossimi promemoria e un campo per aggiungerne al volo.",
                                 "Upcoming reminders and a field to add one quickly."), "bell", "wide",
                               ["wide", "tall", "large", "small", "full"])]

    def trayEntries(self):
        return [TrayEntry("quickAdd", T("Nuovo promemoria", "New reminder"), self.openQuickAdd, icon="bell")]

    def automationActions(self):
        return [AutomationAction("create", T("Crea promemoria", "Create reminder"),
                                 lambda params=None: self.add((params or {}).get("title", "Promemoria"),
                                                              self.clock() + datetime.timedelta(minutes=int((params or {}).get("minutes", 0)))),
                                 icon="bell")]


Plugin = RemindersPlugin


def quickPresets(now):
    today = now.date()
    tonight = datetime.datetime.combine(today, datetime.time(20, 0))
    if tonight <= now:
        tonight += datetime.timedelta(days=1)
    return [(TEXT["in10"], now + datetime.timedelta(minutes=10)), (TEXT["in60"], now + datetime.timedelta(hours=1)),
            (TEXT["tonight"], tonight),
            (TEXT["tomorrow"], datetime.datetime.combine(today + datetime.timedelta(days=1), datetime.time(9, 0)))]


class ReminderEditor(ThemedDialog):
    def __init__(self, plugin, reminder=None, presetDate=None, parent=None):
        super().__init__(parent, 520)
        self.plugin = plugin
        self.reminder = reminder
        self.addHeader(tr(TEXT["editorEdit"] if reminder else TEXT["editorNew"]), "bell", reminder.get("color") if reminder else None)
        self.titleEdit = QLineEdit(reminder["title"] if reminder else "")
        self.titleEdit.setPlaceholderText(tr(TEXT["title"]))
        self.bodyLayout.addWidget(self.titleEdit)
        self.notesEdit = QPlainTextEdit(reminder.get("notes", "") if reminder else "")
        self.notesEdit.setPlaceholderText(tr(TEXT["notes"]))
        self.notesEdit.setFixedHeight(70)
        self.bodyLayout.addWidget(self.notesEdit)
        if reminder:
            startValue = parseDateTime(reminder.get("nextAt") or reminder["start"])
        elif presetDate is not None:
            startValue = datetime.datetime.combine(presetDate, datetime.time(9, 0))
        else:
            startValue = plugin.clock().replace(second=0, microsecond=0) + datetime.timedelta(hours=1)
        self.whenField = DateTimeField(startValue)
        self._row(tr(TEXT["when"]), self.whenField)
        self.recurrence = RecurrenceEditor(reminder.get("rule") if reminder else None)
        self._row(tr(TEXT["repeat"]), self.recurrence)
        self.leadCombo = QComboBox()
        for minutes in logic.LEAD_OPTIONS:
            self.leadCombo.addItem(leadLabel(minutes), minutes)
        self.leadCombo.setCurrentIndex(max(0, self.leadCombo.findData(int(reminder.get("leadMinutes", 0)) if reminder else 0)))
        self._row(tr(TEXT["lead"]), self.leadCombo)
        self.colorPicker = ColorSwatches(reminder.get("color") if reminder else ITEM_COLORS[0])
        self._row(tr(TEXT["color"]), self.colorPicker)
        togglesRow = QHBoxLayout()
        self.soundToggle = ToggleSwitch(reminder.get("sound", True) if reminder else True)
        self.popupToggle = ToggleSwitch(reminder.get("popup", True) if reminder else True)
        togglesRow.addWidget(makeLabel(tr(TEXT["soundOption"]), "muted"))
        togglesRow.addWidget(self.soundToggle)
        togglesRow.addSpacing(18)
        togglesRow.addWidget(makeLabel(tr(TEXT["popupOption"]), "muted"))
        togglesRow.addWidget(self.popupToggle)
        togglesRow.addStretch(1)
        self.bodyLayout.addLayout(togglesRow)
        cancelButton = makeButton(tr(TEXT["cancel"]))
        cancelButton.clicked.connect(self.reject)
        self.saveButton = makeButton(tr(TEXT["save"]), "check", "primary")
        self.saveButton.clicked.connect(self._save)
        self.titleEdit.returnPressed.connect(self._save)
        self.addButtons([cancelButton, self.saveButton])

    def _row(self, label, widget):
        rowLayout = QHBoxLayout()
        rowLayout.setSpacing(10)
        labelWidget = makeLabel(label, "muted")
        labelWidget.setFixedWidth(90)
        rowLayout.addWidget(labelWidget, 0, Qt.AlignTop)
        rowLayout.addWidget(widget, 1)
        self.bodyLayout.addLayout(rowLayout)

    def showEvent(self, event):
        super().showEvent(event)
        self.titleEdit.setFocus()

    def _save(self):
        title = self.titleEdit.text().strip()
        if not title:
            self.titleEdit.setFocus()
            return
        values = dict(title=title, notes=self.notesEdit.toPlainText().strip(), rule=self.recurrence.value(),
                      leadMinutes=self.leadCombo.currentData(), color=self.colorPicker.value(),
                      sound=self.soundToggle.isChecked(), popup=self.popupToggle.isChecked())
        when = self.whenField.value()
        if self.reminder:
            self.plugin.update(self.reminder["id"], start=when, **values)
        else:
            self.plugin.add(values.pop("title"), when, values.pop("rule"), **values)
        self.accept()


class QuickAddDialog(ThemedDialog):
    def __init__(self, plugin):
        super().__init__(None, 520)
        self.plugin = plugin
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setModal(False)
        self.addHeader(tr(TEXT["quickTitle"]), "bell", None, tr(TEXT["quickHint"]))
        self.inputEdit = QLineEdit()
        self.inputEdit.setPlaceholderText(tr(TEXT["placeholder"]))
        self.inputEdit.returnPressed.connect(self._submit)
        self.inputEdit.textChanged.connect(self._preview)
        self.bodyLayout.addWidget(self.inputEdit)
        self.previewLabel = makeLabel("", "accent")
        self.bodyLayout.addWidget(self.previewLabel)

    def showEvent(self, event):
        super().showEvent(event)
        self.inputEdit.setFocus()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def _preview(self, text):
        title, when = logic.parseQuickReminder(text, self.plugin.clock())
        self.previewLabel.setText(f"🔔 {formatWhen(when)}" if when else tr(TEXT["noTimeHint"]) if text.strip() else "")

    def _submit(self):
        reminder = self.plugin.quickAdd(self.inputEdit.text())
        if reminder:
            self.plugin.context.notify(tr(TEXT["addedToast"], when=formatWhen(parseDateTime(reminder["nextAt"]))),
                                       reminder["title"])
        self.close()


class ReminderRow(QWidget):
    def __init__(self, plugin, reminder, now, parent=None):
        super().__init__(parent)
        reminderId = reminder["id"]
        completed = reminder.get("completed")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 9, 4, 9)
        layout.setSpacing(10)
        checkButton = iconButton("circle-check" if completed else "circle", tr(TEXT["reopen"] if completed else TEXT["markDone"]),
                                 "success" if completed else "muted", 20)
        checkButton.clicked.connect(lambda: plugin.reopen(reminderId) if completed else plugin.markDone(reminderId))
        layout.addWidget(checkButton)
        colorDot = QWidget()
        colorDot.setFixedSize(4, 30)
        colorDot.setStyleSheet(f"background: {reminder.get('color') or ITEM_COLORS[0]}; border-radius: 2px;")
        layout.addWidget(colorDot)
        textLayout = QVBoxLayout()
        textLayout.setSpacing(2)
        titleLabel = makeLabel(reminder["title"], "faint" if completed else None, True)
        textLayout.addWidget(titleLabel)
        if reminder.get("notes"):
            textLayout.addWidget(makeLabel(reminder["notes"].split("\n")[0], "faint", True))
        layout.addLayout(textLayout, 1)
        if logic.isRepeating(reminder):
            layout.addWidget(makeLabel(describeRule(reminder["rule"]), "chip"))
        whenValue = parseDateTime(reminder.get("snoozedUntil") or reminder.get("nextAt") or reminder["start"])
        if not completed and whenValue:
            whenLayout = QVBoxLayout()
            whenLayout.setSpacing(0)
            ringing = logic.isRinging(reminder)
            whenLabel = makeLabel(formatWhen(whenValue), "danger" if (whenValue < now) else "accent")
            whenLabel.setAlignment(Qt.AlignRight)
            whenLayout.addWidget(whenLabel)
            countdownLabel = makeLabel(formatCountdown(whenValue, now), "faint")
            countdownLabel.setAlignment(Qt.AlignRight)
            whenLayout.addWidget(countdownLabel)
            layout.addLayout(whenLayout)
            if ringing or whenValue < now:
                snoozeButton = iconButton("history", tr(TEXT["snooze"], minutes=int(plugin.setting("snoozeMinutes") or 10)), "text", 16)
                snoozeButton.clicked.connect(lambda: plugin.snooze(reminderId))
                layout.addWidget(snoozeButton)
        editButton = iconButton("pencil", tr(TEXT["edit"]), "muted", 15)
        editButton.clicked.connect(lambda: plugin.openEditor(reminderId, parent=self))
        layout.addWidget(editButton)
        deleteButton = iconButton("trash-2", tr(TEXT["delete"]), "danger", 15)
        deleteButton.clicked.connect(lambda: self._delete(plugin, reminder))
        layout.addWidget(deleteButton)

    def _delete(self, plugin, reminder):
        message = tr(TEXT["deleteRepeating"]) if logic.isRepeating(reminder) and not reminder.get("completed") else ""
        if confirm(self, tr(TEXT["deleteTitle"]), message, [reminder["title"]], danger=True, confirmText=tr(TEXT["delete"])):
            plugin.delete(reminder["id"])


def groupUpcoming(reminders, now):
    today = now.date()
    groups = {"overdue": [], "today": [], "tomorrow": [], "week": [], "later": []}
    for reminder in reminders:
        when = parseDateTime(reminder.get("snoozedUntil") or reminder["nextAt"])
        if when < now:
            groups["overdue"].append(reminder)
        elif when.date() == today:
            groups["today"].append(reminder)
        elif when.date() == today + datetime.timedelta(days=1):
            groups["tomorrow"].append(reminder)
        elif when.date() <= today + datetime.timedelta(days=7):
            groups["week"].append(reminder)
        else:
            groups["later"].append(reminder)
    return groups


class RemindersPage(QWidget):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        addCard = Card(padding=16)
        addLayout = QVBoxLayout(addCard)
        addLayout.setSpacing(10)
        inputRow = QHBoxLayout()
        inputRow.setSpacing(8)
        self.inputEdit = QLineEdit()
        self.inputEdit.setPlaceholderText(tr(TEXT["placeholder"]))
        self.inputEdit.returnPressed.connect(self._quickAdd)
        self.inputEdit.textChanged.connect(self._onTextChanged)
        inputRow.addWidget(self.inputEdit, 1)
        self.whenField = DateTimeField(None)
        inputRow.addWidget(self.whenField)
        addButton = makeButton(tr(TEXT["add"]), "plus", "primary")
        addButton.clicked.connect(self._quickAdd)
        inputRow.addWidget(addButton)
        addLayout.addLayout(inputRow)
        chipsRow = QHBoxLayout()
        chipsRow.setSpacing(6)
        for label, _ in quickPresets(datetime.datetime.now()):
            chip = makeButton(tr(label), None, "chip")
            chip.clicked.connect(lambda checked=False, labelKey=label: self._applyPreset(labelKey))
            chipsRow.addWidget(chip)
        chipsRow.addStretch(1)
        self.parsedLabel = makeLabel("", "accent")
        chipsRow.addWidget(self.parsedLabel)
        moreButton = makeButton(tr(TEXT["more"]), "sliders-horizontal", "ghost")
        moreButton.clicked.connect(lambda: plugin.openEditor(parent=self))
        chipsRow.addWidget(moreButton)
        addLayout.addLayout(chipsRow)
        layout.addWidget(addCard)
        self.listHost = QWidget()
        self.listLayout = QVBoxLayout(self.listHost)
        self.listLayout.setContentsMargins(0, 0, 0, 0)
        self.listLayout.setSpacing(4)
        layout.addWidget(self.listHost)
        self.manualTime = False
        self.whenField.changed.connect(self._onManualTime)
        plugin.remindersChanged.connect(self.rebuild)
        plugin.context.manager.settingChanged.connect(self._onSettingChanged)
        self.refreshTimer = QTimer(self)
        self.refreshTimer.setInterval(30000)
        self.refreshTimer.timeout.connect(self.rebuild)
        self.refreshTimer.start()
        self.rebuild()

    def _onSettingChanged(self, pluginId, key, value):
        if pluginId == self.plugin.pluginId:
            self.rebuild()

    def _onManualTime(self, value):
        self.manualTime = True

    def _onTextChanged(self, text):
        title, when = logic.parseQuickReminder(text, datetime.datetime.now())
        if when is not None:
            self.whenField.blockSignals(True)
            self.whenField.setValue(when)
            self.whenField.blockSignals(False)
            self.parsedLabel.setText(f"🔔 {formatWhen(when)}")
        else:
            self.parsedLabel.setText("")

    def _applyPreset(self, labelKey):
        presets = dict((tr(label), value) for label, value in quickPresets(datetime.datetime.now()))
        self.whenField.setValue(presets[tr(labelKey)])
        self.manualTime = True
        self.inputEdit.setFocus()

    def _quickAdd(self):
        text = self.inputEdit.text().strip()
        if not text:
            self.inputEdit.setFocus()
            return
        title, when = logic.parseQuickReminder(text, datetime.datetime.now())
        if when is None or self.manualTime:
            when = self.whenField.value()
        self.plugin.add(title or text, when)
        self.inputEdit.clear()
        self.manualTime = False
        self.whenField.setValue(None)

    def rebuild(self):
        clearLayout(self.listLayout)
        now = datetime.datetime.now()
        upcoming = self.plugin.upcoming()
        completed = self.plugin.completed() if self.plugin.setting("showCompleted") else []
        if not upcoming and not completed:
            emptyCard = Card(padding=10)
            emptyLayout = QVBoxLayout(emptyCard)
            emptyLayout.addWidget(EmptyState("bell", tr(TEXT["empty"]), tr(TEXT["emptyText"])))
            self.listLayout.addWidget(emptyCard)
            return
        groups = groupUpcoming(upcoming, now)
        for key, label in (("overdue", TEXT["overdue"]), ("today", TEXT["today"]), ("tomorrow", TEXT["tomorrowSection"]),
                           ("week", TEXT["week"]), ("later", TEXT["later"])):
            if groups[key]:
                self._addSection(label, groups[key], now, danger=key == "overdue")
        if completed:
            self._addSection(TEXT["done"], completed[:20], now)

    def _addSection(self, label, reminders, now, danger=False):
        title = makeLabel(f"{tr(label).upper()} · {len(reminders)}", "section")
        title.setContentsMargins(6, 10, 0, 0)
        if danger:
            title.setStyleSheet(f"color: {theme().danger.name()};")
        self.listLayout.addWidget(title)
        card = Card(padding=10)
        cardLayout = QVBoxLayout(card)
        cardLayout.setSpacing(0)
        for index, reminder in enumerate(reminders):
            if index:
                cardLayout.addWidget(divider())
            cardLayout.addWidget(ReminderRow(self.plugin, reminder, now))
        self.listLayout.addWidget(card)


class RemindersHomeWidget(QWidget):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.inputEdit = QLineEdit()
        self.inputEdit.setPlaceholderText(tr(T("Nuovo… (es. \"tra 20 min pausa\")", "New… (e.g. \"in 20 min break\")")))
        self.inputEdit.returnPressed.connect(self._add)
        layout.addWidget(self.inputEdit)
        self.rowsLayout = QVBoxLayout()
        self.rowsLayout.setSpacing(4)
        layout.addLayout(self.rowsLayout)
        layout.addStretch(1)
        plugin.remindersChanged.connect(self.rebuild)
        self.timer = QTimer(self)
        self.timer.setInterval(30000)
        self.timer.timeout.connect(self.rebuild)
        self.timer.start()
        self.rebuild()

    def _add(self):
        if self.plugin.quickAdd(self.inputEdit.text()):
            self.inputEdit.clear()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.rebuild()

    def rebuild(self):
        clearLayout(self.rowsLayout)
        now = datetime.datetime.now()
        capacity = max(1, (self.height() - 44) // 26)
        upcoming = self.plugin.upcoming()[:capacity]
        if not upcoming:
            self.rowsLayout.addWidget(makeLabel(tr(TEXT["empty"]), "faint"))
        for reminder in upcoming:
            when = parseDateTime(reminder.get("snoozedUntil") or reminder["nextAt"])
            rowLayout = QHBoxLayout()
            rowLayout.setSpacing(8)
            icon = IconWidget("bell-ring" if logic.isRinging(reminder) else "bell",
                              "danger" if when < now else "muted", 15)
            rowLayout.addWidget(icon)
            rowLayout.addWidget(makeLabel(reminder["title"]), 1)
            rowLayout.addWidget(makeLabel(formatWhen(when, now=now), "danger" if when < now else "faint"))
            doneButton = iconButton("check", tr(TEXT["markDone"]), "muted", 14)
            doneButton.clicked.connect(lambda checked=False, reminderId=reminder["id"]: self.plugin.markDone(reminderId))
            rowLayout.addWidget(doneButton)
            self.rowsLayout.addLayout(rowLayout)
