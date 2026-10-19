import datetime
import os
import threading
import time

from PySide6.QtCore import QTimer, Signal

from pchub.core import winapi
from pchub.core.events import AutomationAction, AutomationTrigger
from pchub.core.hotkeys import parseSequence
from pchub.core.i18n import T, tr
from pchub.core.input_hooks import WM_MOUSEHWHEEL, WM_MOUSEMOVE, WM_MOUSEWHEEL, hookService
from pchub.core.logger import getLogger
from pchub.core.paths import isWindows
from pchub.core.plugin_api import ActiveItem, HomeWidgetSpec, PluginBase, TrayEntry
from pchub.core.settings_schema import HotkeySetting, Section, Toggle
from pchub.core.dates import toIso
from pchub.plugins.macros import logic
from pchub.plugins.macros.runner import MacroRun
from pchub.plugins.macros.sender import createSender

log = getLogger("plugin.macros")
TEXT = {
    "stopAll": T("Ferma tutte le macro", "Stop all macros"),
    "enabled": T("Macro attive", "Macros on"),
    "running": T("In esecuzione", "Running"),
    "stop": T("Ferma", "Stop"),
    "untitled": T("Macro senza nome", "Unnamed macro"),
    "clicker": T("Autoclicker", "Autoclicker"),
    "clicks": T("{count} clic", "{count} clicks"),
    "loops": T("giro {count}", "loop {count}"),
}
OWN_PROCESS_ID = os.getpid()


def macroTitle(macro):
    if macro.get("name"):
        return macro["name"]
    return tr(TEXT["clicker"]) if macro.get("kind") == "clicker" else tr(TEXT["untitled"])


class Recording:
    def __init__(self, recordMoves):
        self.events = []
        self.active = False
        self.recordMoves = recordMoves
        self.startedAt = 0.0
        self.countdown = 3


class MacrosPlugin(PluginBase):
    pluginId = "macros"
    name = T("Macro", "Macros")
    description = T("Macro globali o solo per un gioco/app: tasti, testo, clic, attese, registrazione e autoclicker.",
                    "Global or per game/app macros: keys, text, clicks, waits, recording and autoclicker.")
    icon = "zap"
    version = "1.0.0"
    author = "PC Hub"
    settingsSchema = [
        Section(T("Generale", "General")),
        Toggle("macrosEnabled", TEXT["enabled"], True, icon="zap",
               description=T("Spento = nessuna macro parte dai suoi tasti (puoi sempre provarle dalla pagina).",
                             "Off = no macro starts from its key (you can still test them from the page).")),
        HotkeySetting("stopAllHotkey", TEXT["stopAll"], action="stopAll", default="Ctrl+Alt+End", icon="octagon-x",
                      description=T("Ferma subito tutto, anche la registrazione.", "Stops everything right away, recording too.")),
        HotkeySetting("toggleAllHotkey", T("Accendi / spegni le macro", "Turn macros on / off"), action="toggleAll",
                      default="", icon="power"),
        Toggle("ignoreInPCHub", T("Non partono mentre usi PC Hub", "Don't start while you use PC Hub"), True,
               icon="app-window", pinnable=False,
               description=T("Così puoi premere i loro tasti mentre le modifichi.", "So you can press their keys while editing them.")),
        Toggle("loopAlert", T("Avviso quando parte una macro in loop", "Notice when a looping macro starts"), True,
               icon="bell", pinnable=False),
        Section(T("Invio dei tasti", "Sending keys")),
        Toggle("scanCodes", T("Modalità giochi", "Game mode"), True, icon="gamepad-2", pinnable=False,
               description=T("Manda i tasti come una tastiera vera: funziona nella maggior parte dei giochi. Se in "
                             "qualche app escono tasti sbagliati, spegnila. Se un gioco è avviato come "
                             "amministratore, attiva Permessi Avanzati nelle impostazioni di PC Hub.",
                             "Sends keys like a real keyboard: works in most games. If some app gets wrong keys, turn "
                             "it off. If a game runs as administrator, turn on Advanced Permissions in PC Hub's settings.")),
        Section(T("Registrazione", "Recording")),
        Toggle("recordWaits", T("Registra le pause", "Record pauses"), True, icon="hourglass", pinnable=False,
               description=T("Rifà tutto con gli stessi tempi. Spento = una dopo l'altra.",
                             "Replays with the same timing. Off = one after the other.")),
        Toggle("recordPositions", T("I clic tornano nello stesso punto", "Clicks go back to the same spot"), True,
               icon="crosshair", pinnable=False),
        Toggle("recordMoves", T("Registra anche i movimenti del mouse", "Also record mouse movement"), False,
               icon="move", pinnable=False,
               description=T("Crea molti passi: utile per disegnare o trascinare.", "Creates many steps: useful to draw or drag.")),
    ]

    macrosChanged = Signal(str)
    runStateChanged = Signal(str)
    triggerFired = Signal(list, bool)
    captureFinished = Signal(object)
    recordingStateChanged = Signal(str, int)
    recordingFinished = Signal(list)
    _runFinished = Signal(object)
    _resync = Signal()

    def __init__(self, context):
        super().__init__(context)
        self.macros = [logic.normalizeMacro(macro) for macro in context.getData("macros", []) or []]
        self.macrosSnapshot = list(self.macros)
        self.runs = {}
        self.sender = None
        self.hooked = False
        self.capture = None
        self.captureSwallow = set()
        self.recording = None
        self.recordingIndicator = None
        self.pressedTriggers = {}
        self.trackedMods = set()
        self.enabledFlag = True
        self.ignoreInPCHubFlag = True
        self.hookLock = threading.Lock()
        self.saveTimer = QTimer(self)
        self.saveTimer.setSingleShot(True)
        self.saveTimer.setInterval(500)
        self.saveTimer.timeout.connect(self.save)
        self.countdownTimer = QTimer(self)
        self.countdownTimer.setInterval(1000)
        self.countdownTimer.timeout.connect(self._countdownTick)
        self.triggerFired.connect(self._onTrigger)
        self._runFinished.connect(self._onRunFinished)
        self.captureFinished.connect(lambda trigger: self._syncHook())
        self._resync.connect(self._syncHook)

    # lifecycle ----------------------------------------------------------------------
    def start(self):
        self.sender = createSender(bool(self.setting("scanCodes")))
        self._readFlags()
        self._syncHook()

    def stop(self):
        self.stopAll()
        self.cancelCapture()
        if self.hooked:
            hookService().unsubscribe(self.pluginId)
            self.hooked = False
        self.hookState = None
        self.save()
        self.context.clearActive()

    def save(self):
        self.saveTimer.stop()
        self.context.setData("macros", self.macros)

    def onSettingChanged(self, key, value):
        if key == "scanCodes":
            self.sender = createSender(bool(value))
        self._readFlags()
        self._syncHook()
        self.macrosChanged.emit("")

    def _readFlags(self):
        self.enabledFlag = self.setting("macrosEnabled") is not False
        self.ignoreInPCHubFlag = self.setting("ignoreInPCHub") is not False

    def _syncHook(self):
        """Hooks only while something needs them; the mouse hook only for mouse triggers, capture or recording."""
        activeTriggers = [macro["trigger"] for macro in self.macros if macro.get("enabled") and macro.get("trigger")] \
            if self.enabledFlag else []
        busy = self.capture is not None or self.recording is not None or bool(self.captureSwallow)
        needed = self.isRunning() and (busy or bool(activeTriggers))
        wantMouse = busy or any(trigger.get("device") == "mouse" for trigger in activeTriggers)
        wantMoves = self.recording is not None and self.recording.recordMoves
        state = (needed, wantMouse, wantMoves) if needed else None
        if state == getattr(self, "hookState", None):
            return
        self.hookState = state
        if needed:
            hookService().subscribe(self.pluginId, self._onKeyEvent, self._onMouseEvent if wantMouse else None,
                                    wantsMoves=wantMoves)
            self.hooked = True
        elif self.hooked:
            hookService().unsubscribe(self.pluginId)
            self.hooked = False
            self.pressedTriggers = {}
            self.trackedMods = set()

    # model ---------------------------------------------------------------------------------
    def find(self, macroId):
        return next((macro for macro in self.macros if macro["id"] == macroId), None)

    def _changed(self, macroId=""):
        self.macrosSnapshot = list(self.macros)
        self.saveTimer.start()
        self._syncHook()
        self.macrosChanged.emit(macroId)

    def add(self, kind="steps", **fields):
        macro = logic.newMacro(kind)
        macro.update(fields)
        self.macros.append(macro)
        self._changed("")
        return macro

    def update(self, macroId, **fields):
        macro = self.find(macroId)
        if macro is None:
            return
        macro.update(fields)
        self._changed(macroId)

    def updateClicker(self, macroId, **fields):
        macro = self.find(macroId)
        if macro is not None:
            macro["clicker"].update(fields)
            self._changed(macroId)

    def setSteps(self, macroId, steps):
        self.update(macroId, steps=steps)

    def delete(self, macroId):
        self.stopMacro(macroId)
        self.macros = [macro for macro in self.macros if macro["id"] != macroId]
        self._changed("")

    def duplicate(self, macroId):
        macro = self.find(macroId)
        if macro is None:
            return None
        clone = logic.duplicateMacro(macro)
        self.macros.insert(self.macros.index(macro) + 1, clone)
        self._changed("")
        return clone

    def move(self, macroId, offset):
        macro = self.find(macroId)
        if macro is None:
            return
        index = self.macros.index(macro)
        newIndex = max(0, min(len(self.macros) - 1, index + offset))
        self.macros.insert(newIndex, self.macros.pop(index))
        self._changed("")

    def conflicts(self, macroId):
        macro = self.find(macroId)
        return logic.triggerConflicts(self.macros, macro) if macro else []

    # running -----------------------------------------------------------------------------------
    def isMacroRunning(self, macroId):
        run = self.runs.get(macroId)
        return run is not None and not run.stopped()

    def runMacro(self, macroId, fromTrigger=False):
        macro = self.find(macroId)
        if macro is None or self.isMacroRunning(macroId) or self.sender is None:
            return False
        run = MacroRun(macro, self.sender, onFinished=self._runFinished.emit)
        trigger = macro.get("trigger") or {}
        if fromTrigger and macro["kind"] == "steps" and macro["mode"] != "hold" and trigger.get("mods"):
            run.beforeStart = lambda: self._waitForModifiersReleased(run)
        self.runs[macroId] = run
        macro["runCount"] = int(macro.get("runCount") or 0) + 1
        macro["lastRun"] = toIso(datetime.datetime.now().replace(microsecond=0))
        self.saveTimer.start()
        run.start()
        self._refreshActive()
        self.runStateChanged.emit(macroId)
        self.context.emit("started", macroId=macroId, name=macroTitle(macro))
        loops = macro["kind"] == "clicker" or macro["mode"] in ("toggle", "hold")
        if loops and fromTrigger and self.setting("loopAlert") and macro["mode"] != "hold":
            self.context.alert(macroTitle(macro), tr(T("Partita. Ripremi {key} per fermarla.",
                                                      "Started. Press {key} again to stop it."),
                                                    key=logic.triggerText(macro.get("trigger"))),
                               macro.get("icon") or "zap", timeoutSeconds=3, accent=macro.get("color"))
        return True

    def stopMacro(self, macroId):
        run = self.runs.get(macroId)
        if run is not None:
            run.stop()

    def toggleMacro(self, macroId):
        if self.isMacroRunning(macroId):
            self.stopMacro(macroId)
        else:
            self.runMacro(macroId)

    def stopAll(self):
        for run in list(self.runs.values()):
            run.stop()
        if self.recording is not None:
            self.stopRecording()

    def toggleAll(self):
        self.setSetting("macrosEnabled", not self.enabledFlag)

    def _waitForModifiersReleased(self, run):
        deadline = time.monotonic() + 1.5
        while self.currentMods() and time.monotonic() < deadline and not run.stopped():
            run.stopEvent.wait(0.02)

    def _onRunFinished(self, run):
        macroId = run.macro.get("id")
        if self.runs.get(macroId) is run:
            del self.runs[macroId]
        self._refreshActive()
        self.runStateChanged.emit(macroId)
        self.context.emit("stopped", macroId=macroId, name=macroTitle(run.macro))
        if run.error is not None:
            self.context.notify(macroTitle(run.macro), f"{type(run.error).__name__}: {run.error}")

    def _onTrigger(self, macroIds, pressed):
        for macroId in macroIds:
            macro = self.find(macroId)
            if macro is None:
                continue
            running = self.isMacroRunning(macroId)
            if macro["mode"] == "hold":
                if pressed and not running:
                    self.runMacro(macroId, fromTrigger=True)
                elif not pressed and running:
                    self.stopMacro(macroId)
            elif pressed:
                if running:
                    self.stopMacro(macroId)
                else:
                    self.runMacro(macroId, fromTrigger=True)

    def _refreshActive(self):
        for macro in self.macros:
            run = self.runs.get(macro["id"])
            if run is None or (macro["kind"] == "steps" and macro["mode"] == "once"):
                self.context.removeActive(macro["id"])
                continue
            subtitle = tr(TEXT["running"])
            if macro.get("trigger"):
                subtitle += f" · {logic.triggerText(macro['trigger'])}"
            self.context.setActive(ActiveItem(macro["id"], macroTitle(macro), subtitle, icon=macro.get("icon") or "zap",
                                              actions=[(TEXT["stop"], "square",
                                                        lambda macroId=macro["id"]: self.stopMacro(macroId))],
                                              accent=macro.get("color")))

    # input (runs on the hook thread: keep it fast, no UI) ------------------------------------------
    def currentMods(self):
        if isWindows:
            import ctypes
            getState = ctypes.windll.user32.GetAsyncKeyState
            mods = []
            for name, keys in (("ctrl", (0x11,)), ("alt", (0x12,)), ("shift", (0x10,)), ("win", (0x5B, 0x5C))):
                if any(getState(key) & 0x8000 for key in keys):
                    mods.append(name)
            return mods
        return logic.sortedMods(self.trackedMods)

    def _foreground(self):
        hwnd = winapi.foregroundWindow()
        processId = winapi.windowProcessId(hwnd)
        return processId, winapi.processName(processId).lower() if processId else ""

    def _matchAndFire(self, device, code, store=True):
        if not self.enabledFlag:
            return False
        processId, processName = self._foreground()
        if self.ignoreInPCHubFlag and processId == OWN_PROCESS_ID:
            return False
        matches = logic.matchingMacros(self.macrosSnapshot, device, code, self.currentMods(), processName)
        if not matches:
            return False
        macroIds = [macro["id"] for macro in matches]
        block = any(macro.get("blockTrigger") for macro in matches)
        if store:
            self.pressedTriggers[(device, code)] = (macroIds, block)
        self.triggerFired.emit(macroIds, True)
        return block

    def _onKeyEvent(self, event):
        if event.fromPCHub:
            return False
        virtualKey = event.virtualKey
        if virtualKey in logic.MODIFIER_KEYS:
            modifier = logic.MODIFIER_KEYS[virtualKey]
            if event.isDown:
                self.trackedMods.add(modifier)
            else:
                self.trackedMods.discard(modifier)
        if self.capture is not None:
            return self._captureKey(event)
        if ("key", virtualKey) in self.captureSwallow and not event.isDown:
            self.captureSwallow.discard(("key", virtualKey))
            self._resync.emit()
            return True
        if self.recording is not None:
            if self.recording.active and not self._ownWindowInFront():
                self.recording.events.append({"t": event.timestamp, "kind": "key", "vk": virtualKey, "down": event.isDown})
            return False
        if virtualKey in logic.MODIFIER_KEYS:
            return False
        key = ("key", virtualKey)
        if event.isDown:
            if key in self.pressedTriggers:
                return self.pressedTriggers[key][1]
            return self._matchAndFire("key", virtualKey)
        info = self.pressedTriggers.pop(key, None)
        if info is not None:
            self.triggerFired.emit(info[0], False)
            return info[1]
        return False

    def _onMouseEvent(self, event):
        if event.fromPCHub:
            return False
        message = event.message
        if message == WM_MOUSEMOVE:
            recording = self.recording
            if recording is not None and recording.active and recording.recordMoves and not self._pointIsOurs(event.x, event.y):
                recording.events.append({"t": event.timestamp, "kind": "move", "x": event.x, "y": event.y})
            return False
        wheelCode = None
        if message in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
            if message == WM_MOUSEHWHEEL:
                return False
            wheelCode = "wheelUp" if event.wheelDelta > 0 else "wheelDown"
        if self.capture is not None:
            return self._captureMouse(event, wheelCode)
        button = event.button
        if button is not None and ("mouse", button) in self.captureSwallow and not event.isDown:
            self.captureSwallow.discard(("mouse", button))
            self._resync.emit()
            return True
        if self.recording is not None:
            if self.recording.active and not self._pointIsOurs(event.x, event.y):
                if wheelCode:
                    self.recording.events.append({"t": event.timestamp, "kind": "wheel",
                                                  "amount": 1 if wheelCode == "wheelUp" else -1, "x": event.x, "y": event.y})
                elif button is not None:
                    self.recording.events.append({"t": event.timestamp, "kind": "button", "button": button,
                                                  "down": event.isDown, "x": event.x, "y": event.y})
            return False
        if wheelCode:
            return self._matchAndFire("mouse", wheelCode, store=False)
        if button is None:
            return False
        key = ("mouse", button)
        if event.isDown:
            if key in self.pressedTriggers:
                return self.pressedTriggers[key][1]
            return self._matchAndFire("mouse", button)
        info = self.pressedTriggers.pop(key, None)
        if info is not None:
            self.triggerFired.emit(info[0], False)
            return info[1]
        return False

    def _ownWindowInFront(self):
        return winapi.windowProcessId(winapi.foregroundWindow()) == OWN_PROCESS_ID if isWindows else False

    def _pointIsOurs(self, x, y):
        if not isWindows:
            return False
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.WindowFromPoint.argtypes = [wintypes.POINT]
        user32.WindowFromPoint.restype = wintypes.HWND
        hwnd = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
        return winapi.windowProcessId(hwnd) == OWN_PROCESS_ID

    # trigger capture ---------------------------------------------------------------------------------
    def beginCapture(self):
        """Next key / mouse button pressed anywhere becomes the trigger (captureFinished). False = no hooks here."""
        if not hookService().available:
            return False
        self.capture = {"startedAt": time.monotonic()}
        self._syncHook()
        return True

    def cancelCapture(self):
        if self.capture is not None:
            self.capture = None
            self._syncHook()

    def _finishCapture(self, trigger):
        self.capture = None
        self.captureFinished.emit(trigger)

    def _captureKey(self, event):
        virtualKey = event.virtualKey
        if virtualKey in logic.MODIFIER_KEYS:
            return False
        if not event.isDown:
            return False
        mods = self.currentMods()
        self.captureSwallow.add(("key", virtualKey))
        if virtualKey == 0x1B and not mods:
            self._finishCapture(None)
            return True
        self._finishCapture({"device": "key", "code": virtualKey, "mods": mods})
        return True

    def _captureMouse(self, event, wheelCode):
        if time.monotonic() - self.capture["startedAt"] < 0.25:
            return False
        if wheelCode:
            self._finishCapture({"device": "mouse", "code": wheelCode, "mods": self.currentMods()})
            return True
        if event.button is None or not event.isDown:
            return False
        self.captureSwallow.add(("mouse", event.button))
        self._finishCapture({"device": "mouse", "code": event.button, "mods": self.currentMods()})
        return True

    # recording -------------------------------------------------------------------------------------------
    def isRecording(self):
        return self.recording is not None

    def startRecording(self, countdown=3):
        if self.recording is not None:
            return False
        self.stopAll()
        self.recording = Recording(bool(self.setting("recordMoves")))
        self.recording.countdown = countdown
        self._syncHook()
        if countdown <= 0:
            self._beginRecording()
        else:
            self.recordingStateChanged.emit("countdown", countdown)
            self.countdownTimer.start()
        return True

    def _countdownTick(self):
        if self.recording is None:
            self.countdownTimer.stop()
            return
        self.recording.countdown -= 1
        if self.recording.countdown <= 0:
            self.countdownTimer.stop()
            self._beginRecording()
        else:
            self.recordingStateChanged.emit("countdown", self.recording.countdown)

    def _beginRecording(self):
        self.recording.active = True
        self.recording.startedAt = time.monotonic()
        self.recordingStateChanged.emit("recording", 0)
        from pchub.plugins.macros.page import RecordingIndicator
        self.recordingIndicator = RecordingIndicator(self)
        self.recordingIndicator.show()

    def stopRecording(self, cancel=False):
        recording = self.recording
        if recording is None:
            return []
        self.countdownTimer.stop()
        recording.active = False
        self.recording = None
        self._syncHook()
        if self.recordingIndicator is not None:
            self.recordingIndicator.close()
            self.recordingIndicator.deleteLater()
            self.recordingIndicator = None
        if cancel:
            self.recordingStateChanged.emit("cancelled", 0)
            return []
        events = self._trimStopKeys(list(recording.events))
        steps = logic.recordingToSteps(events, bool(self.setting("recordWaits")), recording.recordMoves)
        if not self.setting("recordPositions"):
            for step in steps:
                if step["type"] == "click":
                    step["atPosition"] = False
        self.recordingStateChanged.emit("done", len(steps))
        self.recordingFinished.emit(steps)
        return steps

    def _trimStopKeys(self, events):
        stopKeys = set(logic.MODIFIER_KEYS)
        parsed = parseSequence(self.setting("stopAllHotkey") or "")
        if parsed:
            stopKeys.add(parsed[1])
        while events and events[-1]["kind"] == "key" and events[-1]["vk"] in stopKeys:
            events.pop()
        return events

    # integrations ---------------------------------------------------------------------------------------------
    def createPage(self):
        from pchub.plugins.macros.page import MacrosPage
        return MacrosPage(self)

    def homeWidgets(self):
        from pchub.plugins.macros.page import MacrosHomeWidget
        return [HomeWidgetSpec("macros.list", T("Macro", "Macros"), lambda: MacrosHomeWidget(self),
                               T("Le tue macro con il loro tasto: avviale o fermale da qui.",
                                 "Your macros with their key: start or stop them from here."), "zap", "wide",
                               ["wide", "tall", "large", "small"])]

    def trayEntries(self):
        return [TrayEntry("stopAll", TEXT["stopAll"], self.stopAll, icon="octagon-x")]

    def automationTriggers(self):
        return [AutomationTrigger("started", T("Una macro parte", "A macro starts"), icon="play"),
                AutomationTrigger("stopped", T("Una macro finisce", "A macro ends"), icon="square")]

    def automationActions(self):
        return [AutomationAction("run", T("Avvia una macro", "Run a macro"),
                                 lambda params=None: self.runMacro((params or {}).get("macroId")), icon="play"),
                AutomationAction("stop", T("Ferma una macro", "Stop a macro"),
                                 lambda params=None: self.stopMacro((params or {}).get("macroId")), icon="square"),
                AutomationAction("stopAll", TEXT["stopAll"], lambda params=None: self.stopAll(), icon="octagon-x")]


Plugin = MacrosPlugin
