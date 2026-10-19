import time
import uuid

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLineEdit, QSpinBox, QVBoxLayout, QWidget

from pchub.core.i18n import T, formatDuration, tr
from pchub.core.plugin_api import ActiveItem, HomeWidgetSpec, PluginBase, TrayEntry
from pchub.core.settings_schema import ActionButton, HotkeySetting, Section, Slider, TextInput, Toggle
from pchub.core import system
from pchub.ui.dialogs import askText
from pchub.ui.widgets import (Card, EmptyState, FlowLayout, IconTile, IconWidget, RingProgress, clearLayout, iconButton,
                              makeButton, makeLabel, setThemedIcon)
from pchub.ui.theme import theme

TEXT = {
    "newTimer": T("Nuovo timer", "New timer"),
    "name": T("Nome (facoltativo)", "Name (optional)"),
    "start": T("Avvia timer", "Start timer"),
    "stopwatch": T("Cronometro", "Stopwatch"),
    "addStopwatch": T("Nuovo cronometro", "New stopwatch"),
    "presets": T("Rapidi", "Quick"),
    "empty": T("Nessun timer", "No timers"),
    "emptyText": T("Crea un timer o un cronometro qui sopra.", "Create a timer or a stopwatch above."),
    "running": T("In corso", "Running"),
    "paused": T("In pausa", "Paused"),
    "finished": T("Tempo scaduto!", "Time's up!"),
    "idle": T("Pronto", "Ready"),
    "pause": T("Pausa", "Pause"),
    "resume": T("Riprendi", "Resume"),
    "play": T("Avvia", "Start"),
    "reset": T("Azzera", "Reset"),
    "remove": T("Rimuovi", "Remove"),
    "dismiss": T("Ok", "Dismiss"),
    "rename": T("Rinomina", "Rename"),
    "finishedTitle": T("Timer finito", "Timer finished"),
    "finishedWhileClosed": T("è scaduto mentre PC Hub era chiuso", "expired while PC Hub was closed"),
    "timerName": T("Timer {minutes} min", "Timer {minutes} min"),
    "minutes": T("min", "min"),
    "pauseAll": T("Metti in pausa tutto", "Pause everything"),
}


class TimerPlugin(PluginBase):
    pluginId = "timer"
    name = T("Timer", "Timers")
    description = T("Timer e cronometri con notifiche, sempre attivi anche a finestra chiusa.",
                    "Timers and stopwatches with notifications, running even with the window closed.")
    icon = "timer"
    version = "1.0.0"
    author = "PC Hub"
    settingsSchema = [
        Section(T("Avvisi", "Alerts")),
        Toggle("sound", T("Suono alla fine", "Sound when done"), True, icon="bell-ring"),
        Toggle("notification", T("Notifica alla fine", "Notification when done"), True, icon="bell"),
        Toggle("repeatAlarm", T("Ripeti il suono finché non lo fermi", "Repeat the sound until dismissed"), False,
               visibleIf=("sound", True), icon="refresh-cw"),
        Section(T("Timer rapido", "Quick timer")),
        Slider("quickMinutes", T("Durata timer rapido", "Quick timer length"), 1, 120, 5, suffix=" min",
               traySteps=[1, 5, 10, 15, 25, 30, 45, 60], icon="hourglass"),
        ActionButton("quickStart", T("Avvia timer rapido", "Start quick timer"), action="startQuickTimer",
                     buttonText=T("Avvia", "Start"), icon="play"),
        TextInput("presets", T("Durate rapide (minuti)", "Quick lengths (minutes)"), "1, 5, 10, 25, 45, 60",
                  description=T("Separate da virgola. Compaiono come scorciatoie nella pagina e nella Home.",
                                "Comma separated. They appear as shortcuts on the page and on Home."), icon="list-checks"),
        Section(T("Hotkey", "Hotkeys")),
        HotkeySetting("hotkeyQuick", T("Avvia timer rapido", "Start quick timer"), action="startQuickTimer", icon="keyboard"),
        HotkeySetting("hotkeyToggle", T("Avvia/pausa l'ultimo timer", "Start/pause the last timer"), action="toggleLast",
                      icon="keyboard"),
    ]

    timersChanged = Signal()
    ticked = Signal()

    def __init__(self, context):
        super().__init__(context)
        self.clock = time.time
        self.timers = context.getData("timers", []) or []
        self.tickTimer = QTimer(self)
        self.tickTimer.setInterval(250)
        self.tickTimer.timeout.connect(self.tick)
        self.lastShownSeconds = {}
        self.lastAlarmTime = {}
        self.lastToggledId = context.getData("lastToggledId")

    # lifecycle ---------------------------------------------------------
    def start(self):
        now = self.clock()
        for timerItem in self.timers:
            if timerItem["kind"] == "timer" and timerItem["state"] == "running" and timerItem["endAt"] <= now:
                timerItem["state"] = "finished"
                timerItem["remaining"] = 0
                self.context.notify(tr(TEXT["finishedTitle"]), f"{timerItem['name']} {tr(TEXT['finishedWhileClosed'])}")
        self.save()
        self.refreshActive(force=True)
        self.timersChanged.emit()
        self.tickTimer.start()
        self._syncTick()

    def stop(self):
        self.tickTimer.stop()
        self.save()

    def save(self):
        self.context.setData("timers", self.timers)

    # model ---------------------------------------------------------------
    def find(self, timerId):
        return next((timerItem for timerItem in self.timers if timerItem["id"] == timerId), None)

    def remaining(self, timerItem):
        if timerItem["kind"] != "timer":
            return 0
        if timerItem["state"] == "running":
            return max(0.0, timerItem["endAt"] - self.clock())
        return timerItem["remaining"]

    def elapsed(self, timerItem):
        if timerItem["kind"] == "stopwatch":
            extra = self.clock() - timerItem["startedAt"] if timerItem["state"] == "running" else 0
            return timerItem["elapsed"] + extra
        return timerItem["duration"] - self.remaining(timerItem)

    def progress(self, timerItem):
        if timerItem["kind"] != "timer" or timerItem["duration"] <= 0:
            return None
        return 1.0 - self.remaining(timerItem) / timerItem["duration"]

    def displayTime(self, timerItem):
        if timerItem["kind"] == "stopwatch":
            return formatDuration(self.elapsed(timerItem))
        remainingSeconds = self.remaining(timerItem)
        return formatDuration(remainingSeconds + (0.999 if timerItem["state"] == "running" else 0))

    def addTimer(self, seconds, name=None, autoStart=True):
        seconds = max(1, int(seconds))
        timerItem = {"id": uuid.uuid4().hex[:8], "kind": "timer", "name": name or self._defaultName(seconds),
                     "duration": seconds, "remaining": seconds, "state": "idle", "endAt": 0, "elapsed": 0, "startedAt": 0}
        self.timers.append(timerItem)
        if autoStart:
            self.startTimer(timerItem["id"])
        self._changed()
        return timerItem["id"]

    def addStopwatch(self, name=None, autoStart=True):
        count = sum(1 for timerItem in self.timers if timerItem["kind"] == "stopwatch") + 1
        timerItem = {"id": uuid.uuid4().hex[:8], "kind": "stopwatch", "name": name or f"{tr(TEXT['stopwatch'])} {count}",
                     "duration": 0, "remaining": 0, "state": "idle", "endAt": 0, "elapsed": 0, "startedAt": 0}
        self.timers.append(timerItem)
        if autoStart:
            self.startTimer(timerItem["id"])
        self._changed()
        return timerItem["id"]

    def _defaultName(self, seconds):
        if seconds % 60 == 0:
            return tr(TEXT["timerName"], minutes=seconds // 60)
        return f"Timer {formatDuration(seconds)}"

    def startTimer(self, timerId):
        timerItem = self.find(timerId)
        if not timerItem or timerItem["state"] == "running":
            return
        now = self.clock()
        if timerItem["kind"] == "timer":
            if timerItem["state"] == "finished" or timerItem["remaining"] <= 0:
                timerItem["remaining"] = timerItem["duration"]
            timerItem["endAt"] = now + timerItem["remaining"]
        else:
            timerItem["startedAt"] = now
        timerItem["state"] = "running"
        self.lastToggledId = timerId
        self.context.setData("lastToggledId", timerId)
        self._changed()

    def pauseTimer(self, timerId):
        timerItem = self.find(timerId)
        if not timerItem or timerItem["state"] != "running":
            return
        if timerItem["kind"] == "timer":
            timerItem["remaining"] = self.remaining(timerItem)
        else:
            timerItem["elapsed"] = self.elapsed(timerItem)
        timerItem["state"] = "paused"
        self.lastToggledId = timerId
        self._changed()

    def toggleTimer(self, timerId):
        timerItem = self.find(timerId)
        if not timerItem:
            return
        if timerItem["state"] == "running":
            self.pauseTimer(timerId)
        else:
            self.startTimer(timerId)

    def resetTimer(self, timerId):
        timerItem = self.find(timerId)
        if not timerItem:
            return
        timerItem.update({"state": "idle", "remaining": timerItem["duration"], "elapsed": 0, "endAt": 0, "startedAt": 0})
        self.lastAlarmTime.pop(timerId, None)
        self._changed()

    def removeTimer(self, timerId):
        self.timers = [timerItem for timerItem in self.timers if timerItem["id"] != timerId]
        self.context.removeActive(timerId)
        self.lastShownSeconds.pop(timerId, None)
        self._changed()

    def renameTimer(self, timerId, newName):
        timerItem = self.find(timerId)
        if timerItem and newName:
            timerItem["name"] = newName
            self._changed()

    def pauseAll(self):
        for timerItem in self.timers:
            if timerItem["state"] == "running":
                self.pauseTimer(timerItem["id"])

    def startQuickTimer(self):
        self.addTimer(int(self.setting("quickMinutes") or 5) * 60)

    def toggleLast(self):
        timerItem = self.find(self.lastToggledId) if self.lastToggledId else None
        if timerItem is None and self.timers:
            timerItem = self.timers[-1]
        if timerItem is None:
            self.startQuickTimer()
        else:
            self.toggleTimer(timerItem["id"])

    def presetMinutes(self):
        values = []
        for part in str(self.setting("presets") or "").replace(";", ",").split(","):
            part = part.strip().replace(",", ".")
            try:
                minutes = float(part)
            except ValueError:
                continue
            if 0 < minutes <= 24 * 60:
                values.append(minutes)
        return values[:10]

    def _changed(self):
        self.save()
        self.refreshActive(force=True)
        self.timersChanged.emit()
        self._syncTick()

    def needsTick(self):
        """Ticking is only needed while something counts (or a finished alarm may still ring)."""
        now = self.clock()
        for timerItem in self.timers:
            if timerItem["state"] == "running":
                return True
            if timerItem["state"] == "finished" and self.setting("repeatAlarm") and self.setting("sound") \
                    and now - timerItem.get("endAt", 0) < 125:
                return True
        return False

    def _syncTick(self):
        if self.needsTick():
            if not self.tickTimer.isActive() and self.isRunning():
                self.tickTimer.start()
        elif self.tickTimer.isActive():
            self.tickTimer.stop()

    # engine ------------------------------------------------------------
    def tick(self):
        now = self.clock()
        for timerItem in self.timers:
            if timerItem["kind"] == "timer" and timerItem["state"] == "running" and timerItem["endAt"] <= now:
                self.finish(timerItem)
            elif timerItem["state"] == "finished" and self.setting("repeatAlarm") and self.setting("sound"):
                if now - self.lastAlarmTime.get(timerItem["id"], 0) > 4 and now - timerItem["endAt"] < 120:
                    self.lastAlarmTime[timerItem["id"]] = now
                    system.playSound("alarm")
        self.refreshActive()
        self.ticked.emit()
        if not self.needsTick():
            self.tickTimer.stop()

    def finish(self, timerItem):
        timerItem["state"] = "finished"
        timerItem["remaining"] = 0
        self.lastAlarmTime[timerItem["id"]] = self.clock()
        self.save()
        if self.setting("notification"):
            self.context.notify(tr(TEXT["finishedTitle"]), timerItem["name"], "alarm" if self.setting("sound") else None)
        elif self.setting("sound"):
            system.playSound("alarm")
        self.context.emit("finished", timerId=timerItem["id"], name=timerItem["name"])
        self.refreshActive(force=True)
        self.timersChanged.emit()

    def refreshActive(self, force=False):
        for timerItem in self.timers:
            timerId = timerItem["id"]
            if timerItem["state"] == "idle":
                if self.lastShownSeconds.pop(timerId, None) is not None or force:
                    self.context.removeActive(timerId)
                continue
            shownText = self.displayTime(timerItem)
            stateKey = (shownText, timerItem["state"])
            if not force and self.lastShownSeconds.get(timerId) == stateKey:
                continue
            self.lastShownSeconds[timerId] = stateKey
            stateText = tr(TEXT[timerItem["state"]]) if timerItem["state"] in TEXT else ""
            if timerItem["state"] == "finished":
                actions = [(TEXT["dismiss"], "check", lambda timerId=timerId: self.resetTimer(timerId))]
            else:
                actions = [(TEXT["pause"] if timerItem["state"] == "running" else TEXT["resume"],
                            "pause" if timerItem["state"] == "running" else "play",
                            lambda timerId=timerId: self.toggleTimer(timerId)),
                           (TEXT["reset"], "rotate-ccw", lambda timerId=timerId: self.resetTimer(timerId))]
            self.context.setActive(ActiveItem(
                timerId, timerItem["name"], f"{shownText} · {stateText}",
                icon="watch" if timerItem["kind"] == "stopwatch" else "timer",
                progress=self.progress(timerItem), actions=actions,
                accent=theme().warning if timerItem["state"] == "finished" else None))

    # ui ------------------------------------------------------------------
    def createPage(self):
        return TimerPage(self)

    def homeWidgets(self):
        return [HomeWidgetSpec("timer.timers", T("Timer", "Timers"), lambda: TimerHomeWidget(self),
                               T("I tuoi timer con controlli rapidi.", "Your timers with quick controls."), "timer",
                               "wide", ["wide", "small", "large", "tall", "full"])]

    def trayEntries(self):
        return [TrayEntry("pauseAll", TEXT["pauseAll"], self.pauseAll, icon="pause")]

    def automationActions(self):
        from pchub.core.events import AutomationAction
        return [AutomationAction("startQuick", T("Avvia timer rapido", "Start quick timer"),
                                 lambda params=None: self.startQuickTimer(), icon="timer")]


Plugin = TimerPlugin


class TimerCard(Card):
    def __init__(self, plugin, timerId, parent=None):
        super().__init__(parent, padding=14, hoverable=True)
        self.plugin = plugin
        self.timerId = timerId
        self.setMinimumWidth(230)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        topRow = QHBoxLayout()
        self.nameLabel = makeLabel("", "subtitle")
        topRow.addWidget(self.nameLabel, 1)
        renameButton = iconButton("pencil", tr(TEXT["rename"]), "faint", 14)
        renameButton.clicked.connect(self._rename)
        topRow.addWidget(renameButton)
        removeButton = iconButton("x", tr(TEXT["remove"]), "faint", 14)
        removeButton.clicked.connect(lambda: plugin.removeTimer(timerId))
        topRow.addWidget(removeButton)
        layout.addLayout(topRow)
        middleRow = QHBoxLayout()
        middleRow.setSpacing(14)
        self.ring = RingProgress(78, 7)
        middleRow.addWidget(self.ring)
        timeLayout = QVBoxLayout()
        timeLayout.setSpacing(2)
        self.timeLabel = makeLabel("", "metric")
        self.stateLabel = makeLabel("", "faint")
        timeLayout.addStretch(1)
        timeLayout.addWidget(self.timeLabel)
        timeLayout.addWidget(self.stateLabel)
        timeLayout.addStretch(1)
        middleRow.addLayout(timeLayout, 1)
        layout.addLayout(middleRow)
        buttonsRow = QHBoxLayout()
        buttonsRow.setSpacing(8)
        self.playButton = makeButton("", "play", "primary")
        self.playButton.clicked.connect(lambda: plugin.toggleTimer(timerId))
        buttonsRow.addWidget(self.playButton, 1)
        self.resetButton = makeButton(tr(TEXT["reset"]), "rotate-ccw")
        self.resetButton.clicked.connect(lambda: plugin.resetTimer(timerId))
        buttonsRow.addWidget(self.resetButton)
        layout.addLayout(buttonsRow)
        self.refresh()

    def _rename(self):
        timerItem = self.plugin.find(self.timerId)
        if timerItem:
            accepted, newName = askText(self, tr(TEXT["rename"]), "", timerItem["name"])
            if accepted:
                self.plugin.renameTimer(self.timerId, newName)

    def refresh(self):
        timerItem = self.plugin.find(self.timerId)
        if not timerItem:
            return
        currentTheme = theme()
        self.nameLabel.setText(timerItem["name"])
        self.timeLabel.setText(self.plugin.displayTime(timerItem))
        state = timerItem["state"]
        self.stateLabel.setText(tr(TEXT[state]))
        progressValue = self.plugin.progress(timerItem)
        if timerItem["kind"] == "stopwatch":
            elapsedSeconds = self.plugin.elapsed(timerItem)
            self.ring.setProgress((elapsedSeconds % 60) / 60.0)
        else:
            self.ring.setProgress(progressValue or 0)
        self.ring.setColor(currentTheme.warning if state == "finished" else None)
        self.setTint(currentTheme.warning if state == "finished" else None)
        if state == "running":
            self.playButton.setText(tr(TEXT["pause"]))
            setThemedIcon(self.playButton, "pause", "accentText", 16)
        elif state == "finished":
            self.playButton.setText(tr(TEXT["play"]))
            setThemedIcon(self.playButton, "rotate-cw", "accentText", 16)
        else:
            self.playButton.setText(tr(TEXT["resume"]) if state == "paused" else tr(TEXT["play"]))
            setThemedIcon(self.playButton, "play", "accentText", 16)


class TimerPage(QWidget):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.cards = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        creatorCard = Card(padding=16, hoverable=True)
        creatorLayout = QVBoxLayout(creatorCard)
        creatorLayout.setSpacing(12)
        creatorLayout.addWidget(makeLabel(tr(TEXT["newTimer"]).upper(), "section"))
        inputRow = QHBoxLayout()
        inputRow.setSpacing(8)
        self.nameEdit = QLineEdit()
        self.nameEdit.setPlaceholderText(tr(TEXT["name"]))
        inputRow.addWidget(self.nameEdit, 2)
        self.hoursSpin = self._spin(0, 23, "h")
        self.minutesSpin = self._spin(0, 59, "m")
        self.minutesSpin.setValue(5)
        self.secondsSpin = self._spin(0, 59, "s")
        for spin in (self.hoursSpin, self.minutesSpin, self.secondsSpin):
            inputRow.addWidget(spin)
        startButton = makeButton(tr(TEXT["start"]), "play", "primary")
        startButton.clicked.connect(self._createTimer)
        inputRow.addWidget(startButton)
        stopwatchButton = makeButton(tr(TEXT["addStopwatch"]), "watch")
        stopwatchButton.clicked.connect(lambda: plugin.addStopwatch(self.nameEdit.text().strip() or None))
        inputRow.addWidget(stopwatchButton)
        creatorLayout.addLayout(inputRow)
        presetRow = QHBoxLayout()
        presetRow.setSpacing(8)
        presetRow.addWidget(makeLabel(tr(TEXT["presets"]), "faint"))
        self.presetHost = QWidget()
        self.presetLayout = FlowLayout(self.presetHost, 6)
        presetRow.addWidget(self.presetHost, 1)
        creatorLayout.addLayout(presetRow)
        layout.addWidget(creatorCard)
        self.gridHost = QWidget()
        self.gridLayout = QGridLayout(self.gridHost)
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.gridLayout.setSpacing(4)
        layout.addWidget(self.gridHost)
        self.emptyState = EmptyState("timer", tr(TEXT["empty"]), tr(TEXT["emptyText"]))
        layout.addWidget(self.emptyState)
        plugin.timersChanged.connect(self.rebuild)
        plugin.ticked.connect(self.refreshTimes)
        plugin.context.manager.settingChanged.connect(self._onSettingChanged)
        self.columns = 3
        self.rebuildPresets()
        self.rebuild()

    def _onSettingChanged(self, pluginId, key, value):
        if pluginId == self.plugin.pluginId and key == "presets":
            self.rebuildPresets()

    @staticmethod
    def _spin(minimum, maximum, suffix):
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSuffix(f" {suffix}")
        spin.setAlignment(Qt.AlignCenter)
        spin.setMinimumWidth(70)
        return spin

    def _createTimer(self):
        seconds = self.hoursSpin.value() * 3600 + self.minutesSpin.value() * 60 + self.secondsSpin.value()
        if seconds <= 0:
            return
        self.plugin.addTimer(seconds, self.nameEdit.text().strip() or None)
        self.nameEdit.clear()

    def rebuildPresets(self):
        while self.presetLayout.count():
            item = self.presetLayout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for minutes in self.plugin.presetMinutes():
            label = f"{minutes:g} {tr(TEXT['minutes'])}"
            chip = makeButton(label, None, "chip")
            chip.clicked.connect(lambda checked=False, value=minutes: self.plugin.addTimer(int(value * 60)))
            self.presetLayout.addWidget(chip)
        self.presetHost.updateGeometry()

    def rebuild(self):
        currentIds = [timerItem["id"] for timerItem in self.plugin.timers]
        for timerId in list(self.cards):
            if timerId not in currentIds:
                card = self.cards.pop(timerId)
                card.setParent(None)
                card.deleteLater()
        while self.gridLayout.count():
            self.gridLayout.takeAt(0)
        for index, timerId in enumerate(currentIds):
            card = self.cards.get(timerId)
            if card is None:
                card = TimerCard(self.plugin, timerId)
                self.cards[timerId] = card
            card.refresh()
            self.gridLayout.addWidget(card, index // self.columns, index % self.columns)
        for column in range(self.columns):
            self.gridLayout.setColumnStretch(column, 1)
        self.emptyState.setVisible(not currentIds)
        self.gridHost.setVisible(bool(currentIds))

    def refreshTimes(self):
        if not self.isVisible():
            return
        for card in self.cards.values():
            card.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        newColumns = 3 if self.width() > 900 else 2 if self.width() > 560 else 1
        if newColumns != self.columns:
            self.columns = newColumns
            self.rebuild()


class TimerHomeWidget(QWidget):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.rowsLayout = QVBoxLayout()
        self.rowsLayout.setSpacing(4)
        layout.addLayout(self.rowsLayout)
        layout.addStretch(1)
        self.presetHost = QWidget()
        self.presetLayout = FlowLayout(self.presetHost, 6)
        layout.addWidget(self.presetHost)
        self.rowWidgets = []
        self.lastRowCapacity = None
        plugin.timersChanged.connect(self.rebuild)
        plugin.ticked.connect(self.refreshTimes)
        self.rebuild()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        capacity = max(2, (self.height() - 36) // 24)
        if capacity != self.lastRowCapacity:
            self.lastRowCapacity = capacity
            self.rebuild()

    def rebuild(self):
        clearLayout(self.rowsLayout)
        self.rowWidgets = []
        maxRows = max(2, (self.height() - 36) // 24) if self.height() > 60 else 3
        for timerItem in self.plugin.timers[-maxRows:]:
            rowLayout = QHBoxLayout()
            rowLayout.setSpacing(8)
            rowLayout.addWidget(IconWidget("watch" if timerItem["kind"] == "stopwatch" else "timer", "muted", 16))
            nameLabel = makeLabel(timerItem["name"])
            rowLayout.addWidget(nameLabel, 1)
            timeLabel = makeLabel("", "metricSmall")
            rowLayout.addWidget(timeLabel)
            toggleButton = iconButton("play", None, "text", 16)
            toggleButton.clicked.connect(lambda checked=False, timerId=timerItem["id"]: self.plugin.toggleTimer(timerId))
            rowLayout.addWidget(toggleButton)
            self.rowsLayout.addLayout(rowLayout)
            self.rowWidgets.append((timerItem["id"], timeLabel, toggleButton))
        if not self.plugin.timers:
            self.rowsLayout.addWidget(makeLabel(tr(TEXT["emptyText"]), "faint", True))
        while self.presetLayout.count():
            item = self.presetLayout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for minutes in self.plugin.presetMinutes()[:5]:
            chip = makeButton(f"{minutes:g}m", "plus", "chip")
            chip.clicked.connect(lambda checked=False, value=minutes: self.plugin.addTimer(int(value * 60)))
            self.presetLayout.addWidget(chip)
        self.refreshTimes()

    def refreshTimes(self):
        for timerId, timeLabel, toggleButton in self.rowWidgets:
            timerItem = self.plugin.find(timerId)
            if not timerItem:
                continue
            timeLabel.setText(self.plugin.displayTime(timerItem))
            iconName = "pause" if timerItem["state"] == "running" else "rotate-cw" if timerItem["state"] == "finished" else "play"
            if getattr(toggleButton, "_themedIcon", (None,))[0] != iconName:
                setThemedIcon(toggleButton, iconName, "text", 16)
