import datetime
import statistics
import time

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QMenu, QSizePolicy, QVBoxLayout, QWidget

from pchub.core import winapi
from pchub.core.events import AutomationAction, AutomationTrigger
from pchub.core.i18n import T, tr
from pchub.core.input_hooks import hookService
from pchub.core.plugin_api import ActiveItem, HomeWidgetSpec, PluginBase, TrayEntry
from pchub.core.settings_schema import Choice, CustomRow, HotkeySetting, NumberInput, Section, Slider, TextInput, Toggle
from pchub.plugins.oled_saver.logic import (DEFAULT_BASE_PITCH, DEFAULT_BASE_YAW, MODE_AWAY, MODE_DIM, MODE_MANUAL,
                                            MODE_NORMAL, DimController, PresenceTracker, estimatePose, pickMainFace,
                                            limitsFor, classifyDistraction, isLookingAway)
from pchub.ui.theme import roundedPath, theme, withAlpha
from pchub.ui.widgets import Card, IconTile, ToggleSwitch, makeButton, makeLabel, setRole, setThemedIcon

CAMERA_KEEPALIVE = 15.0
WAKE_FADE_MS = 140

TEXT = {
    "normal": T("Tutto normale", "All good"),
    "dim": T("Sei distratto", "You're distracted"),
    "away": T("Non ci sei · blackout", "You're away · blackout"),
    "manual": T("Blackout manuale", "Manual blackout"),
    "paused": T("In pausa", "Paused"),
    "seeYou": T("Ti vedo e stai guardando lo schermo", "I can see you looking at the screen"),
    "seeDistracted": T("Ti vedo, ma stai guardando altrove", "I can see you, but you're looking away"),
    "noFace": T("Non vedo nessuno", "I can't see anyone"),
    "cameraIdle": T("Webcam spenta: si accende quando non usi il PC", "Webcam off: it turns on when you're not using the PC"),
    "cameraStarting": T("Accendo la webcam…", "Starting the webcam…"),
    "noCamera": T("Webcam non trovata. Controlla l'indice webcam o se un'altra app la sta usando.",
                  "Webcam not found. Check the webcam index or whether another app is using it."),
    "cameraError": T("Errore webcam: {error}", "Webcam error: {error}"),
    "dimLevel": T("oscuramento {percent}%", "dimmed {percent}%"),
    "blockedExcluded": T("App esclusa in primo piano ({app})", "Excluded app in front ({app})"),
    "blockedFullscreen": T("App a schermo intero", "Full-screen app"),
    "blockedLocked": T("PC bloccato", "PC locked"),
    "blockedOff": T("Blackout e distrazione sono disattivati", "Blackout and distraction are off"),
    "pausedUntil": T("fino alle {time}", "until {time}"),
    "pausedForever": T("finché non riprendi", "until you resume"),
    "blackoutNow": T("Blackout ora", "Blackout now"),
    "pause": T("Pausa", "Pause"),
    "resume": T("Riprendi", "Resume"),
    "pause15": T("15 minuti", "15 minutes"),
    "pause30": T("30 minuti", "30 minutes"),
    "pause60": T("1 ora", "1 hour"),
    "pause120": T("2 ore", "2 hours"),
    "pauseForever": T("Finché non riprendo", "Until I resume"),
    "demo": T("Prova effetto", "Preview effect"),
    "camera": T("Webcam", "Webcam"),
    "preview": T("Anteprima", "Preview"),
    "previewOff": T("Anteprima spenta", "Preview off"),
    "calibrate": T("Calibra", "Calibrate"),
    "calibrateHint": T("Siediti come al solito, guarda il centro dello schermo e premi Calibra.",
                       "Sit as usual, look at the center of the screen and press Calibrate."),
    "calibrating": T("Guarda il centro dello schermo… {seconds}", "Look at the center of the screen… {seconds}"),
    "calibrationWaiting": T("Cerco il tuo volto…", "Looking for your face…"),
    "calibrationDone": T("Calibrato! Ora so com'è quando guardi lo schermo.", "Calibrated! Now I know what looking at the screen means."),
    "calibrationFailed": T("Non ti ho visto: controlla la webcam e riprova.", "I couldn't see you: check the webcam and try again."),
    "calibrationReset": T("Ripristina", "Reset"),
    "notCalibrated": T("Non calibrato (valori standard)", "Not calibrated (default values)"),
    "calibrated": T("Calibrato", "Calibrated"),
    "distractionTitle": T("Distrazione", "Distraction"),
    "distractionHint": T("Premi Registra e girati verso dove ti distrai (telefono, altro monitor). Puoi registrarne più di una.",
                         "Press Record and turn to where you get distracted (phone, other monitor). You can record several."),
    "distractionRecord": T("Registra distrazione", "Record distraction"),
    "distractionClear": T("Cancella", "Clear"),
    "distractionTurn": T("Girati verso dove ti distrai… {seconds}", "Turn to where you get distracted… {seconds}"),
    "distractionHold": T("Resta così…", "Hold still…"),
    "distractionSaved": T("Salvata: {direction}. Aggiungine altre o lascia così.", "Saved: {direction}. Add more or keep it."),
    "distractionTooClose": T("Troppo vicino a dove guardi lo schermo: girati di più e riprova.",
                             "Too close to where you look at the screen: turn further and try again."),
    "distractionLost": T("Da lì non vedo più il volto: in quella posizione conti già come \"via\". Prova a girarti un po' meno.",
                         "I lose your face from there: in that pose you already count as \"away\". Try turning a bit less."),
    "distractionStandard": T("Standard", "Standard"),
    "distractionCustom": T("Calibrata: {directions}", "Calibrated: {directions}"),
    "distractionStored": T("Registrata ({directions}) ma in uso: Standard", "Recorded ({directions}) but using: Standard"),
    "dirLeft": T("a sinistra", "left"),
    "dirRight": T("a destra", "right"),
    "dirDown": T("in basso", "down"),
    "dirUp": T("in alto", "up"),
    "headTurn": T("Rotazione testa", "Head turn"),
    "headTilt": T("Su / giù", "Up / down"),
    "settings": T("Impostazioni", "Settings"),
    "pausedTitle": T("OLED Saver in pausa", "OLED Saver paused"),
}


def secondsFormatter(value):
    return f"{value} s"


def sensitivityFormatter(value):
    if value <= 3:
        label = T("serve girarsi tanto", "needs a big turn")
    elif value <= 7:
        label = T("normale", "normal")
    else:
        label = T("basta poco", "a little is enough")
    return f"{value} · {tr(label)}"


def _screenPickerFactory(row):
    from pchub.plugins.oled_saver.screen_picker import ScreenPicker
    adapter = row.adapter
    return ScreenPicker(adapter.app.pluginManager.records[adapter.pluginId].instance)


class OledSaverPlugin(PluginBase):
    pluginId = "oled_saver"
    name = T("OLED Saver", "OLED Saver")
    description = T("Protegge il monitor OLED: blackout quando ti allontani, oscura piano piano quando sei distratto.",
                    "Protects your OLED: blackout when you walk away, gradual dimming when you're distracted.")
    icon = "moon"
    version = "2.2.0"
    author = "Ken"
    settingsInPage = True
    settingsSchema = [
        Section(T("Monitor", "Monitors")),
        CustomRow("screenPicker", T("Monitor da oscurare", "Monitors to darken"), _screenPickerFactory, icon="monitor",
                  pinnable=False,
                  description=T("Clicca un monitor per sceglierlo. Solo quelli colorati vengono oscurati, gli altri non vengono mai toccati.",
                                "Click a monitor to choose it. Only the coloured ones get darkened, the others are never touched.")),
        Section(T("Blackout", "Blackout")),
        Toggle("autoBlackout", T("Blackout quando ti allontani", "Blackout when you walk away"), True, icon="user",
               description=T("Se la webcam non ti vede, lo schermo diventa nero.", "If the webcam can't see you, the screen goes black.")),
        Slider("awayDelay", T("Dopo quanto tempo senza vederti", "After how long without seeing you"), 3, 300, 10,
               formatter=secondsFormatter, visibleIf=("autoBlackout", True), pinnable=False, icon="hourglass"),
        Slider("blackoutLevel", T("Intensità del blackout", "Blackout strength"), 70, 100, 100, suffix="%",
               pinnable=False, icon="moon"),
        HotkeySetting("manualHotkey", T("Blackout manuale", "Manual blackout"), action="toggleManual",
                      default="Ctrl+Alt+B", icon="keyboard",
                      description=T("Premi per oscurare subito. Qualsiasi input lo riaccende.",
                                    "Press to go black now. Any input wakes it up.")),
        Section(T("Distrazione", "Distraction")),
        Toggle("distraction", T("Scurisci quando sei distratto", "Dim when you're distracted"), True, icon="eye-off",
               description=T("Se giri la testa o guardi altrove, lo schermo si scurisce piano piano.",
                             "If you turn your head or look away, the screen slowly dims.")),
        Slider("sensitivity", T("Quanto distratto per attivarsi", "How distracted before it kicks in"), 1, 10, 5,
               formatter=sensitivityFormatter, visibleIf=("distraction", True), pinnable=True, icon="target",
               description=T("Più alto = basta girare meno la testa.", "Higher = a smaller head turn is enough.")),
        Choice("distractionMode", T("Cosa conta come distrazione", "What counts as distracted"),
               [("default", T("Standard", "Standard")), ("calibrated", T("Calibrato da me", "My calibration"))], "default",
               visibleIf=("distraction", True), icon="crosshair",
               description=T("Calibrato: registri tu dove guardi quando ti distrai (telefono, altro monitor) con "
                             "\"Registra distrazione\" qui sopra.",
                             "Calibrated: you record where you look when distracted (phone, other monitor) with "
                             "\"Record distraction\" above.")),
        Toggle("lookDown", T("Guardare in basso conta come distrazione", "Looking down counts as distraction"), True,
               visibleIf=("distraction", True), icon="arrow-down",
               description=T("Utile per il telefono. Disattivalo se guardi spesso la tastiera.",
                             "Good for the phone. Turn it off if you often look at the keyboard.")),
        Slider("distractionDelay", T("Dopo quanti secondi di distrazione", "After how many seconds distracted"), 1, 60, 4,
               formatter=secondsFormatter, visibleIf=("distraction", True), pinnable=False, icon="hourglass"),
        Slider("startDim", T("Oscuramento iniziale", "Starting dim"), 10, 90, 40, suffix="%",
               visibleIf=("distraction", True), pinnable=False, icon="sun"),
        Slider("dimStep", T("Quanto scurisce a ogni passo", "How much darker each step"), 5, 50, 15, suffix="%",
               visibleIf=("distraction", True), pinnable=False, icon="layers"),
        Slider("dimInterval", T("Ogni quanti secondi scurisce di più", "Seconds between steps"), 1, 60, 4,
               formatter=secondsFormatter, visibleIf=("distraction", True), pinnable=False, icon="timer"),
        Slider("maxDim", T("Oscuramento massimo", "Maximum dim"), 30, 100, 100, suffix="%",
               visibleIf=("distraction", True), pinnable=False, icon="moon"),
        Section(T("Risveglio", "Waking up")),
        Toggle("wakeOnLook", T("Torna normale quando rialzi lo sguardo", "Back to normal when you look back"), True,
               icon="eye", description=T("Altrimenti serve muovere il mouse o premere un tasto.",
                                         "Otherwise you need to move the mouse or press a key.")),
        Toggle("fastWake", T("Risveglio istantaneo", "Instant wake"), True, visibleIf=("wakeOnLook", True), icon="zap",
               description=T("Mentre lo schermo è scuro la webcam ti controlla 24 volte al secondo, così si riaccende "
                             "appena guardi. Usa un po' più di CPU solo in quel momento.",
                             "While the screen is dark the webcam checks 24 times a second, so it wakes as soon as you "
                             "look. Uses a bit more CPU only then.")),
        Toggle("lookToWake", T("Da distratto si riattiva solo guardando", "When distracted, only looking wakes it"), True,
               visibleIf=("wakeOnLook", True), icon="scan-eye",
               description=T("Muovere il mouse o premere tasti non toglie l'oscuramento finché non guardi lo schermo. "
                             "Se la webcam non ti vede, l'input funziona comunque.",
                             "Moving the mouse or typing won't undo the dimming until you look at the screen. "
                             "If the webcam can't see you, input still works.")),
        Toggle("clickOnlyWakes", T("Il primo clic serve solo a riattivare", "First click only wakes the screen"), True,
               pinnable=False, icon="mouse-pointer-click",
               description=T("Evita clic per sbaglio su cose che non vedi.", "Avoids clicking things you can't see.")),
        Toggle("controllerInput", T("Il controller conta come input", "Controller counts as input"), True,
               pinnable=False, icon="gamepad-2"),
        Toggle("ignoreInjected", T("Ignora input simulato (Parsec, macro)", "Ignore simulated input (Parsec, macros)"),
               False, pinnable=False, icon="shield",
               description=T("Il mouse mosso da Parsec, macro o altri programmi non riaccende lo schermo.",
                             "Mouse moved by Parsec, macros or other programs won't wake the screen.")),
        Slider("fadeDuration", T("Durata della dissolvenza", "Fade duration"), 0, 3000, 700, step=50, suffix=" ms",
               pinnable=False, icon="wand-sparkles"),
        Section(T("Webcam", "Webcam")),
        NumberInput("cameraIndex", T("Indice webcam", "Webcam index"), 0, 9, 0, icon="monitor",
                    description=T("0 = webcam principale. Prova 1, 2… se ne hai più di una.",
                                  "0 = main webcam. Try 1, 2… if you have more than one.")),
        Toggle("cameraOnlyIdle", T("Accendi la webcam solo quando non usi il PC", "Only use the webcam when you're idle"),
               True, pinnable=False, icon="power",
               description=T("Consuma meno e la lucina si accende solo quando serve.",
                             "Uses less power and the light only turns on when needed.")),
        Slider("idleBeforeCamera", T("Dopo quanti secondi di inattività", "After how many idle seconds"), 1, 60, 3,
               formatter=secondsFormatter, visibleIf=("cameraOnlyIdle", True), pinnable=False, icon="hourglass"),
        Slider("cameraFps", T("Controlli al secondo", "Checks per second"), 1, 15, 6, pinnable=False, icon="gauge"),
        Slider("confidence", T("Sicurezza nel riconoscere il volto", "Face detection confidence"), 50, 95, 70, suffix="%",
               pinnable=False, icon="scan-search",
               description=T("Più basso = ti riconosce anche al buio, ma con più falsi allarmi.",
                             "Lower = recognises you in the dark, but more false alarms.")),
        Slider("confirmFrames", T("Conferme prima di decidere", "Confirmations before deciding"), 1, 10, 3,
               pinnable=False, icon="list-checks",
               description=T("Più alto = meno errori, reazione un po' più lenta.", "Higher = fewer mistakes, slightly slower.")),
        Section(T("Eccezioni", "Exceptions")),
        TextInput("excludedApps", T("Non oscurare con queste app", "Don't dim with these apps"), "",
                  placeholder=T("es. vlc.exe, mpc-hc64.exe", "e.g. vlc.exe, mpc-hc64.exe"), icon="app-window",
                  description=T("Quando una di queste è in primo piano non si oscura da solo.",
                                "When one of these is in front it won't dim by itself.")),
        Toggle("skipFullscreen", T("Non oscurare le app a schermo intero", "Don't dim full-screen apps"), False,
               icon="maximize-2"),
    ]

    stateChanged = Signal()
    visionUpdated = Signal(dict)
    calibrationChanged = Signal(str, str)
    distractionCalibrationChanged = Signal(str, str)

    def __init__(self, context):
        super().__init__(context)
        self.tracker = PresenceTracker()
        self.controller = DimController(self.setting)
        self.overlay = None
        self.camera = None
        self.controllerWatcher = winapi.ControllerWatcher()
        self.clock = time.monotonic
        self.lastInputProvider = None
        self.extraInputAt = 0.0
        self.lastCursorPosition = None
        self.qtInputAt = time.monotonic()
        self.lastCameraNeedAt = 0.0
        self.previewRequested = False
        self.calibrationPhase = None
        self.calibrationSamples = []
        self.calibrationStartedAt = 0.0
        self.distractionPhase = None
        self.distractionSamples = []
        self.distractionStartedAt = 0.0
        self.distractionMisses = 0
        self.blockedReason = None
        self.lastEnvironmentCheck = 0.0
        self.cachedEnvironment = None
        self.demoStartedAt = None
        self.cameraStatus = "off"
        self.cameraMessage = ""
        self.lastResult = None
        self.lastMode = MODE_NORMAL
        self.hooked = False
        self.lastScreenWarning = False
        pausedValue = context.getData("pausedUntil", 0) or 0
        self.pausedUntil = pausedValue if (pausedValue < 0 or pausedValue > time.time()) else 0
        self.tickTimer = QTimer(self)
        self.tickTimer.setInterval(100)
        self.tickTimer.timeout.connect(self.tick)

    # lifecycle ------------------------------------------------------------
    def start(self):
        from pchub.plugins.oled_saver.overlay import OverlayController
        from pchub.plugins.oled_saver.vision import CameraWorker
        self.overlay = OverlayController(self)
        self.overlay.setSelectedScreens(self.selectedScreenKeys())
        self.overlay.overlayClicked.connect(self._onOverlayClicked)
        self.camera = CameraWorker(self.setting, lambda: self.previewRequested, self)
        self.camera.frameAnalyzed.connect(self._onFrame)
        self.camera.statusChanged.connect(self._onCameraStatus)
        self.controller = DimController(self.setting)
        self.tracker.reset()
        self.tickTimer.start()
        self._syncHook()
        self._refreshPausedActive()

    def stop(self):
        self.tickTimer.stop()
        if self.camera is not None:
            self.camera.stop()
            self.camera = None
        if self.overlay is not None:
            self.overlay.shutdown()
            self.overlay = None
        if self.hooked:
            hookService().unsubscribe(self.pluginId)
            self.hooked = False
        self.calibrationPhase = None
        self.context.clearActive()

    def onSettingChanged(self, key, value):
        if key == "ignoreInjected":
            self._syncHook()
        elif key == "selectedScreens" and self.overlay is not None:
            self.overlay.setSelectedScreens(self.selectedScreenKeys())
        elif key == "cameraIndex" and self.camera is not None and self.camera.isRunning():
            self.camera.stop()
            self.tracker.reset()
        self.stateChanged.emit()

    def selectedScreenKeys(self):
        """Keys of the monitors to darken, None = all of them."""
        from PySide6.QtGui import QGuiApplication
        from pchub.plugins.oled_saver.overlay import screenKey
        selected = self.setting("selectedScreens")
        if selected is None and self.setting("screens") == "primary" and QGuiApplication.primaryScreen():
            return [screenKey(QGuiApplication.primaryScreen())]
        return None if selected is None else list(selected)

    def toggleScreen(self, screen):
        from PySide6.QtGui import QGuiApplication
        from pchub.plugins.oled_saver.overlay import isScreenSelected, screenKey
        current = self.selectedScreenKeys()
        chosen = [screenKey(item) for item in QGuiApplication.screens() if isScreenSelected(item, current)]
        key = screenKey(screen)
        if key in chosen:
            if len(chosen) <= 1:
                self.lastScreenWarning = True
                self.stateChanged.emit()
                return
            chosen.remove(key)
        else:
            chosen.append(key)
        allKeys = [screenKey(item) for item in QGuiApplication.screens()]
        if set(allKeys) <= set(chosen):
            self.setSetting("screens", "all")
            chosen = None
        self.setSetting("selectedScreens", chosen)
        if self.overlay is not None:
            self.overlay.setSelectedScreens(self.selectedScreenKeys())
        self.stateChanged.emit()

    def _syncHook(self):
        wanted = bool(self.setting("ignoreInjected")) and self.tickTimer.isActive()
        if wanted and not self.hooked:
            hookService().subscribe(self.pluginId, keyboardCallback=lambda event: False,
                                    mouseCallback=lambda event: False)
            self.hooked = True
        elif not wanted and self.hooked:
            hookService().unsubscribe(self.pluginId)
            self.hooked = False

    # input ------------------------------------------------------------------
    def lastInputAt(self, now):
        if self.lastInputProvider is not None:
            return max(self.lastInputProvider(), self.extraInputAt)
        if winapi.isWindows:
            if self.hooked and hookService().isActive():
                lastInput = hookService().lastRealInput
            else:
                lastInput = now - winapi.idleSeconds()
        else:
            position = QCursor.pos()
            if position != self.lastCursorPosition:
                self.lastCursorPosition = position
                self.qtInputAt = now
            lastInput = self.qtInputAt
        if self.setting("controllerInput"):
            lastInput = max(lastInput, self.controllerWatcher.poll())
        return max(lastInput, self.extraInputAt)

    def _onOverlayClicked(self):
        self.extraInputAt = self.clock()

    # environment ------------------------------------------------------------
    def environmentBlock(self, now):
        if now - self.lastEnvironmentCheck < 1.0 and self.cachedEnvironment is not None:
            return self.cachedEnvironment
        self.lastEnvironmentCheck = now
        reason = None
        if winapi.isSessionLocked():
            reason = tr(TEXT["blockedLocked"])
        else:
            excluded = [name.strip().lower() for name in str(self.setting("excludedApps") or "").replace(";", ",").split(",")
                        if name.strip()]
            if excluded:
                foreground = winapi.foregroundProcessName()
                if foreground and any(foreground == name or foreground == f"{name}.exe" for name in excluded):
                    reason = tr(TEXT["blockedExcluded"], app=foreground)
            if reason is None and self.setting("skipFullscreen") and winapi.isForegroundFullscreen():
                reason = tr(TEXT["blockedFullscreen"])
        self.cachedEnvironment = (reason,)
        return self.cachedEnvironment

    def isPaused(self):
        return self.pausedUntil < 0 or self.pausedUntil > time.time()

    # main loop ----------------------------------------------------------------
    def tick(self):
        now = self.clock()
        lastInput = self.lastInputAt(now)
        idle = now - lastInput
        reason = None
        if self.isPaused():
            reason = tr(TEXT["paused"])
        elif self.pausedUntil > 0:
            self.resume()
        if reason is None:
            reason = self.environmentBlock(now)[0]
        if reason is None and not self.setting("autoBlackout") and not self.setting("distraction"):
            reason = tr(TEXT["blockedOff"])
        self.blockedReason = reason
        self._updateCamera(now, idle, reason is not None)
        mode, level = self.controller.update(now, lastInput, self.tracker, blocked=reason is not None,
                                             visionOk=self.visionOk(now))
        if self.camera is not None:
            self.camera.relaxed = mode in (MODE_DIM, MODE_AWAY)
        eatClicks = bool(self.setting("clickOnlyWakes"))
        if mode == MODE_DIM and self.setting("lookToWake"):
            eatClicks = False
        if self.demoStartedAt is not None:
            level, eatClicks = self._demoLevel(now), False
        if self.overlay is not None:
            darker = level > self.overlay.target + 0.001
            fadeMs = self.setting("fadeDuration") if darker else WAKE_FADE_MS
            if mode == MODE_MANUAL and darker:
                fadeMs = min(300, fadeMs)
            self.overlay.setTarget(level, fadeMs, eatClicks)
            self.overlay.maintain()
        if mode != self.lastMode:
            self._onModeChanged(self.lastMode, mode)
            self.lastMode = mode
        self._advanceCalibration(now)
        self._advanceDistraction(now)
        self.stateChanged.emit()

    def visionOk(self, now):
        """True while the webcam is delivering fresh frames (so its opinion can be trusted)."""
        if self.camera is None or not self.camera.isRunning() or getattr(self.camera, "status", "on") != "on":
            return False
        return self.tracker.lastFrameAt is not None and now - self.tracker.lastFrameAt < 3.0

    def _updateCamera(self, now, idle, blocked):
        if self.camera is None:
            return
        autoEnabled = bool(self.setting("autoBlackout") or self.setting("distraction"))
        needed = self.previewRequested or self.calibrationPhase is not None or self.distractionPhase is not None
        if autoEnabled and not blocked:
            if not self.setting("cameraOnlyIdle") or idle >= self.setting("idleBeforeCamera"):
                needed = True
            if self.controller.mode in (MODE_DIM, MODE_AWAY):
                needed = True
        if needed:
            self.lastCameraNeedAt = now
            if not self.camera.isRunning():
                self.camera.start()
        elif self.camera.isRunning() and now - self.lastCameraNeedAt > CAMERA_KEEPALIVE:
            self.camera.stop(wait=False)
            self.tracker.reset()

    def _onFrame(self, result):
        now = self.clock()
        face = pickMainFace(result["faces"])
        pose = estimatePose(face) if face is not None else None
        baseYaw, basePitch = self.calibration()
        wasAttentive = self.tracker.attentive()
        self.tracker.update(now, pose, self.setting("confirmFrames"), self.setting("sensitivity"),
                            self.setting("lookDown"), baseYaw, basePitch, self.currentLimits())
        if self.distractionPhase == "collecting":
            if pose is not None:
                self.distractionSamples.append((pose.yaw, pose.pitch))
            else:
                self.distractionMisses += 1
        if self.calibrationPhase in ("waiting", "collecting") and pose is not None:
            if self.calibrationPhase == "waiting":
                self.calibrationPhase = "collecting"
                self.calibrationStartedAt = now
            self.calibrationSamples.append((pose.yaw, pose.pitch))
        result["pose"] = pose
        self.lastResult = result
        if self.previewRequested:
            self.visionUpdated.emit(result)
        if (not wasAttentive and self.tracker.attentive() and self.controller.mode in (MODE_DIM, MODE_AWAY)
                and self.tickTimer.isActive()):
            self.tick()

    def _onCameraStatus(self, status, message):
        self.cameraStatus = status
        self.cameraMessage = message
        if status in ("off", "noCamera", "error"):
            self.tracker.reset()
        self.stateChanged.emit()

    def _onModeChanged(self, previousMode, mode):
        events = {MODE_DIM: "distracted", MODE_AWAY: "away", MODE_MANUAL: "manual"}
        if mode in events:
            self.context.emit(events[mode])
        elif mode == MODE_NORMAL and previousMode != MODE_NORMAL:
            self.context.emit("back")

    # actions ------------------------------------------------------------------
    def toggleManual(self):
        now = self.clock()
        if self.controller.mode != MODE_NORMAL:
            self.controller.wake(now)
        else:
            self.demoStartedAt = None
            self.controller.startManual(now)
        self.tick()

    def blackoutNow(self):
        if self.controller.mode != MODE_MANUAL:
            self.toggleManual()

    def pause(self, minutes=None):
        self.pausedUntil = -1 if minutes is None else time.time() + minutes * 60
        self.context.setData("pausedUntil", self.pausedUntil)
        self.controller.wake(self.clock())
        self._refreshPausedActive()
        self.tick()

    def resume(self):
        self.pausedUntil = 0
        self.context.setData("pausedUntil", 0)
        self._refreshPausedActive()
        self.stateChanged.emit()

    def setPausedFromTray(self, paused):
        if paused:
            self.pause(None)
        else:
            self.resume()

    def _refreshPausedActive(self):
        if self.isPaused():
            self.context.setActive(ActiveItem("paused", tr(TEXT["pausedTitle"]), self.pausedText(), icon="moon",
                                              actions=[(TEXT["resume"], "play", self.resume)]))
        else:
            self.context.removeActive("paused")

    def pausedText(self):
        if self.pausedUntil < 0:
            return tr(TEXT["pausedForever"])
        return tr(TEXT["pausedUntil"], time=datetime.datetime.fromtimestamp(self.pausedUntil).strftime("%H:%M"))

    def runDemo(self):
        self.demoStartedAt = self.clock()
        self.tick()

    def _demoLevel(self, now):
        elapsed = now - self.demoStartedAt
        startDim = self.setting("startDim") / 100.0
        stepDim = self.setting("dimStep") / 100.0
        maxDim = self.setting("maxDim") / 100.0
        if elapsed < 1.2:
            return startDim
        if elapsed < 2.4:
            return min(maxDim, startDim + stepDim)
        if elapsed < 3.6:
            return maxDim
        self.demoStartedAt = None
        return 0.0

    # calibration ----------------------------------------------------------------
    def calibration(self):
        baseYaw = self.context.getData("baseYaw")
        basePitch = self.context.getData("basePitch")
        return (DEFAULT_BASE_YAW if baseYaw is None else baseYaw, DEFAULT_BASE_PITCH if basePitch is None else basePitch)

    def isCalibrated(self):
        return self.context.getData("baseYaw") is not None

    def startCalibration(self):
        self.calibrationPhase = "waiting"
        self.calibrationSamples = []
        self.calibrationStartedAt = self.clock()
        self.calibrationChanged.emit("waiting", tr(TEXT["calibrationWaiting"]))
        self.tick()

    def resetCalibration(self):
        self.context.setData("baseYaw", None)
        self.context.setData("basePitch", None)
        self.calibrationChanged.emit("reset", tr(TEXT["notCalibrated"]))

    def _advanceCalibration(self, now):
        phase = self.calibrationPhase
        if phase is None:
            return
        if phase == "waiting":
            if now - self.calibrationStartedAt > 12:
                self.calibrationPhase = None
                self.calibrationChanged.emit("failed", tr(TEXT["calibrationFailed"]))
            return
        elapsed = now - self.calibrationStartedAt
        remaining = max(0, 3 - int(elapsed))
        if elapsed < 3 or len(self.calibrationSamples) < 5:
            if elapsed > 10:
                self.calibrationPhase = None
                self.calibrationChanged.emit("failed", tr(TEXT["calibrationFailed"]))
            else:
                self.calibrationChanged.emit("collecting", tr(TEXT["calibrating"], seconds=max(1, remaining)))
            return
        self.finishCalibration()

    def finishCalibration(self):
        samples = self.calibrationSamples
        self.calibrationPhase = None
        if len(samples) < 3:
            self.calibrationChanged.emit("failed", tr(TEXT["calibrationFailed"]))
            return False
        self.context.setData("baseYaw", statistics.median(sample[0] for sample in samples))
        self.context.setData("basePitch", statistics.median(sample[1] for sample in samples))
        self.calibrationChanged.emit("done", tr(TEXT["calibrationDone"]))
        return True

    # distraction calibration -----------------------------------------------------------
    def distractionPoints(self):
        return [tuple(point) for point in (self.context.getData("distractionPoints", []) or [])]

    def currentLimits(self):
        baseYaw, basePitch = self.calibration()
        points = self.distractionPoints() if self.setting("distractionMode") == "calibrated" else None
        return limitsFor(self.setting("sensitivity") or 5, bool(self.setting("lookDown")), points, baseYaw, basePitch)

    def distractionDirections(self):
        baseYaw, basePitch = self.calibration()
        names = {"left": "dirLeft", "right": "dirRight", "down": "dirDown", "up": "dirUp"}
        directions = []
        for pointYaw, pointPitch in self.distractionPoints():
            direction = classifyDistraction(pointYaw - baseYaw, pointPitch - basePitch, self.setting("sensitivity") or 5)
            if direction not in directions:
                directions.append(direction)
        return ", ".join(tr(TEXT[names[direction]]) for direction in directions)

    def startDistractionRecording(self):
        self.distractionPhase = "turn"
        self.distractionSamples = []
        self.distractionMisses = 0
        self.distractionStartedAt = self.clock()
        self.distractionCalibrationChanged.emit("turn", tr(TEXT["distractionTurn"], seconds=3))
        self.tick()

    def clearDistraction(self):
        self.distractionPhase = None
        self.context.setData("distractionPoints", [])
        self.setSetting("distractionMode", "default")
        self.distractionCalibrationChanged.emit("reset", tr(TEXT["distractionHint"]))

    def _advanceDistraction(self, now):
        phase = self.distractionPhase
        if phase is None:
            return
        elapsed = now - self.distractionStartedAt
        if phase == "turn":
            if elapsed >= 3:
                self.distractionPhase = "collecting"
                self.distractionStartedAt = now
                self.distractionSamples = []
                self.distractionMisses = 0
                self.distractionCalibrationChanged.emit("collecting", tr(TEXT["distractionHold"]))
            else:
                self.distractionCalibrationChanged.emit("turn", tr(TEXT["distractionTurn"], seconds=max(1, 3 - int(elapsed))))
            return
        if elapsed < 1.5:
            return
        self.finishDistractionRecording()

    def finishDistractionRecording(self):
        samples = self.distractionSamples
        self.distractionPhase = None
        if len(samples) < 3:
            self.distractionCalibrationChanged.emit("failed", tr(TEXT["distractionLost"]))
            return False
        pointYaw = statistics.median(sample[0] for sample in samples)
        pointPitch = statistics.median(sample[1] for sample in samples)
        baseYaw, basePitch = self.calibration()
        sensitivity = self.setting("sensitivity") or 5
        standard = limitsFor(sensitivity, True, None, baseYaw, basePitch)
        if not isLookingAway(pointYaw - baseYaw, pointPitch - basePitch, standard, 0.45):
            self.distractionCalibrationChanged.emit("failed", tr(TEXT["distractionTooClose"]))
            return False
        points = self.distractionPoints()[-5:] + [(pointYaw, pointPitch)]
        self.context.setData("distractionPoints", [list(point) for point in points])
        self.setSetting("distractionMode", "calibrated")
        direction = classifyDistraction(pointYaw - baseYaw, pointPitch - basePitch, sensitivity)
        names = {"left": "dirLeft", "right": "dirRight", "down": "dirDown", "up": "dirUp"}
        self.distractionCalibrationChanged.emit("done", tr(TEXT["distractionSaved"], direction=tr(TEXT[names[direction]])))
        return True

    # status for UI ------------------------------------------------------------------
    def statusInfo(self):
        mode = self.controller.mode
        if self.isPaused():
            return "paused", tr(TEXT["paused"]), self.pausedText()
        if mode == MODE_DIM:
            return mode, tr(TEXT["dim"]), tr(TEXT["dimLevel"], percent=int(round(self.controller.level * 100)))
        if mode in (MODE_AWAY, MODE_MANUAL):
            return mode, tr(TEXT[mode]), ""
        if self.blockedReason:
            return "blocked", tr(TEXT["normal"]), self.blockedReason
        return "normal", tr(TEXT["normal"]), self.visionText()

    def visionText(self):
        if self.cameraStatus == "noCamera":
            return tr(TEXT["noCamera"])
        if self.cameraStatus == "error":
            return tr(TEXT["cameraError"], error=self.cameraMessage)
        if self.cameraStatus == "starting":
            return tr(TEXT["cameraStarting"])
        if self.cameraStatus == "off":
            return tr(TEXT["cameraIdle"])
        if self.tracker.present is True:
            return tr(TEXT["seeDistracted"]) if self.tracker.distracted else tr(TEXT["seeYou"])
        if self.tracker.present is False:
            return tr(TEXT["noFace"])
        return tr(TEXT["cameraStarting"])

    def setPreviewRequested(self, requested):
        if requested != self.previewRequested:
            self.previewRequested = requested
            if self.isRunning():
                self.tick()

    # integrations ------------------------------------------------------------------
    def createPage(self):
        return OledPage(self)

    def homeWidgets(self):
        return [HomeWidgetSpec("oled_saver.status", T("OLED Saver", "OLED Saver"), lambda: OledHomeWidget(self),
                               T("Stato, blackout e pausa a portata di clic.", "Status, blackout and pause one click away."),
                               "moon", "small", ["small", "wide"])]

    def trayEntries(self):
        return [TrayEntry("blackout", TEXT["blackoutNow"], self.blackoutNow, icon="moon"),
                TrayEntry("pause", T("OLED Saver in pausa", "OLED Saver paused"), self.setPausedFromTray, kind="toggle",
                          checkedGetter=self.isPaused, icon="pause")]

    def automationTriggers(self):
        return [AutomationTrigger("distracted", T("Sei distratto", "You're distracted"), icon="eye-off"),
                AutomationTrigger("away", T("Ti sei allontanato", "You walked away"), icon="user"),
                AutomationTrigger("back", T("Sei tornato", "You're back"), icon="smile")]

    def automationActions(self):
        return [AutomationAction("blackout", T("Blackout schermo", "Screen blackout"), lambda params=None: self.blackoutNow(),
                                 icon="moon"),
                AutomationAction("pause", T("Metti in pausa OLED Saver", "Pause OLED Saver"),
                                 lambda params=None: self.pause((params or {}).get("minutes")), icon="pause"),
                AutomationAction("resume", T("Riprendi OLED Saver", "Resume OLED Saver"), lambda params=None: self.resume(),
                                 icon="play")]


Plugin = OledSaverPlugin


def statusColor(kind):
    currentTheme = theme()
    return {"normal": currentTheme.success, "dim": currentTheme.warning, "away": QColor("#94A3B8"),
            "manual": QColor("#94A3B8"), "paused": currentTheme.textMuted, "blocked": currentTheme.textMuted}.get(
        kind, currentTheme.accent)


def statusIcon(kind):
    return {"normal": "eye", "dim": "eye-off", "away": "moon", "manual": "moon", "paused": "pause",
            "blocked": "shield"}.get(kind, "eye")


def buildPauseMenu(plugin, parent):
    menu = QMenu(parent)
    for label, minutes in ((TEXT["pause15"], 15), (TEXT["pause30"], 30), (TEXT["pause60"], 60), (TEXT["pause120"], 120),
                           (TEXT["pauseForever"], None)):
        action = menu.addAction(tr(label))
        action.triggered.connect(lambda checked=False, value=minutes: plugin.pause(value))
    return menu


class CameraPreview(QWidget):
    """Mirrored webcam image with face box, landmarks and head direction."""

    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.result = None
        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def setResult(self, result):
        self.result = result
        self.update()

    def clear(self):
        self.result = None
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        currentTheme = theme()
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = roundedPath(rect, currentTheme.radiusSmall)
        painter.fillPath(path, QColor(0, 0, 0, 120))
        result = self.result
        if not result or result.get("preview") is None:
            painter.setPen(currentTheme.textMuted)
            painter.drawText(rect, Qt.AlignCenter | Qt.TextWordWrap, self.plugin.visionText()
                             if self.plugin.previewRequested else tr(TEXT["previewOff"]))
            return
        image = result["preview"]
        scaleToWidget = min(rect.width() / image.width(), rect.height() / image.height())
        drawWidth, drawHeight = image.width() * scaleToWidget, image.height() * scaleToWidget
        target = QRectF(rect.center().x() - drawWidth / 2, rect.center().y() - drawHeight / 2, drawWidth, drawHeight)
        painter.save()
        painter.setClipPath(path)
        painter.drawImage(target, image)
        painter.restore()
        pose = result.get("pose")
        if pose is None:
            return
        frameScale = result["scale"] * scaleToWidget

        def mapPoint(x, y):
            return QPointF(target.right() - x * frameScale, target.top() + y * frameScale)

        tracker = self.plugin.tracker
        color = currentTheme.warning if tracker.distracted else currentTheme.success
        boxX, boxY, boxWidth, boxHeight = pose.box
        topLeft = mapPoint(boxX + boxWidth, boxY)
        painter.setPen(QPen(color, 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(topLeft.x(), topLeft.y(), boxWidth * frameScale, boxHeight * frameScale), 8, 8)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        for pointX, pointY in pose.landmarks:
            painter.drawEllipse(mapPoint(pointX, pointY), 3, 3)
        nose = mapPoint(*pose.landmarks[2])
        arrow = QPointF(-tracker.deltaYaw * boxWidth * frameScale * 0.9, tracker.deltaPitch * boxHeight * frameScale * 0.9)
        painter.setPen(QPen(color, 3, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(nose, nose + arrow)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(nose + arrow, 4.5, 4.5)


class PoseMeter(QWidget):
    """Horizontal gauge: marker for the current value, shaded zones where it counts as distraction."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.value = 0.0
        self.negativeThreshold = None
        self.positiveThreshold = None
        self.span = 1.0
        self.active = False
        self.setFixedHeight(22)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def setState(self, value, negativeThreshold, positiveThreshold, span, active):
        self.value, self.negativeThreshold, self.positiveThreshold = value, negativeThreshold, positiveThreshold
        self.span, self.active = span, active
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        currentTheme = theme()
        rect = QRectF(self.rect()).adjusted(2, 7, -2, -7)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 22) if currentTheme.styleId == "glass" else QColor("#191A26"))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)

        def xFor(value):
            return rect.center().x() + max(-1.0, min(1.0, value / self.span)) * rect.width() / 2

        warning = withAlpha(currentTheme.warning, 0.35)
        if self.negativeThreshold is not None:
            painter.setBrush(warning)
            painter.drawRoundedRect(QRectF(rect.left(), rect.top(), xFor(-self.negativeThreshold) - rect.left(), rect.height()), 4, 4)
        if self.positiveThreshold is not None:
            painter.setBrush(warning)
            startX = xFor(self.positiveThreshold)
            painter.drawRoundedRect(QRectF(startX, rect.top(), rect.right() - startX, rect.height()), 4, 4)
        painter.setPen(QPen(withAlpha(currentTheme.text, 0.35), 1))
        painter.drawLine(QPointF(rect.center().x(), rect.top() - 3), QPointF(rect.center().x(), rect.bottom() + 3))
        if self.active:
            markerX = xFor(self.value)
            outside = ((self.positiveThreshold is not None and self.value > self.positiveThreshold)
                       or (self.negativeThreshold is not None and self.value < -self.negativeThreshold))
            painter.setPen(QPen(QColor(0, 0, 0, 90), 1))
            painter.setBrush(currentTheme.warning if outside else currentTheme.success)
            painter.drawEllipse(QPointF(markerX, rect.center().y()), 7, 7)


class OledPage(QWidget):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        statusCard = Card(padding=18)
        statusLayout = QHBoxLayout(statusCard)
        statusLayout.setSpacing(16)
        self.statusTile = IconTile("eye", 54)
        statusLayout.addWidget(self.statusTile)
        textLayout = QVBoxLayout()
        textLayout.setSpacing(3)
        self.statusTitle = makeLabel("", "title")
        self.statusSubtitle = makeLabel("", "muted", True)
        textLayout.addStretch(1)
        textLayout.addWidget(self.statusTitle)
        textLayout.addWidget(self.statusSubtitle)
        textLayout.addStretch(1)
        statusLayout.addLayout(textLayout, 1)
        self.demoButton = makeButton(tr(TEXT["demo"]), "wand-sparkles", "ghost")
        self.demoButton.clicked.connect(plugin.runDemo)
        statusLayout.addWidget(self.demoButton)
        self.pauseButton = makeButton(tr(TEXT["pause"]), "pause")
        self.pauseButton.clicked.connect(self._pauseClicked)
        statusLayout.addWidget(self.pauseButton)
        self.blackoutButton = makeButton(tr(TEXT["blackoutNow"]), "moon", "primary")
        self.blackoutButton.clicked.connect(plugin.blackoutNow)
        statusLayout.addWidget(self.blackoutButton)
        layout.addWidget(statusCard)

        cameraCard = Card(padding=18)
        cameraLayout = QHBoxLayout(cameraCard)
        cameraLayout.setSpacing(18)
        self.preview = CameraPreview(plugin)
        self.preview.setFixedSize(360, 270)
        cameraLayout.addWidget(self.preview)
        sideLayout = QVBoxLayout()
        sideLayout.setSpacing(10)
        headerRow = QHBoxLayout()
        headerRow.addWidget(makeLabel(tr(TEXT["camera"]).upper(), "section"))
        headerRow.addStretch(1)
        headerRow.addWidget(makeLabel(tr(TEXT["preview"]), "muted"))
        self.previewToggle = ToggleSwitch(bool(plugin.context.getData("previewOn", True)))
        self.previewToggle.toggled.connect(self._previewToggled)
        headerRow.addWidget(self.previewToggle)
        sideLayout.addLayout(headerRow)
        self.visionLabel = makeLabel("", None, True)
        sideLayout.addWidget(self.visionLabel)
        sideLayout.addWidget(makeLabel(tr(TEXT["headTurn"]), "faint"))
        self.yawMeter = PoseMeter()
        sideLayout.addWidget(self.yawMeter)
        sideLayout.addWidget(makeLabel(tr(TEXT["headTilt"]), "faint"))
        self.pitchMeter = PoseMeter()
        sideLayout.addWidget(self.pitchMeter)
        sideLayout.addStretch(1)
        self.calibrationLabel = makeLabel(tr(TEXT["calibrateHint"]), "faint", True)
        sideLayout.addWidget(self.calibrationLabel)
        calibrationRow = QHBoxLayout()
        self.calibrationState = makeLabel("", "chip")
        calibrationRow.addWidget(self.calibrationState)
        calibrationRow.addStretch(1)
        resetButton = makeButton(tr(TEXT["calibrationReset"]), "rotate-ccw", "ghost")
        resetButton.clicked.connect(plugin.resetCalibration)
        calibrationRow.addWidget(resetButton)
        self.calibrateButton = makeButton(tr(TEXT["calibrate"]), "target", "primary")
        self.calibrateButton.clicked.connect(plugin.startCalibration)
        calibrationRow.addWidget(self.calibrateButton)
        sideLayout.addLayout(calibrationRow)
        sideLayout.addWidget(makeLabel(tr(TEXT["distractionTitle"]).upper(), "section"))
        self.distractionLabel = makeLabel(tr(TEXT["distractionHint"]), "faint", True)
        sideLayout.addWidget(self.distractionLabel)
        distractionRow = QHBoxLayout()
        self.distractionState = makeLabel("", "chip")
        distractionRow.addWidget(self.distractionState)
        distractionRow.addStretch(1)
        clearButton = makeButton(tr(TEXT["distractionClear"]), "rotate-ccw", "ghost")
        clearButton.clicked.connect(plugin.clearDistraction)
        distractionRow.addWidget(clearButton)
        self.recordButton = makeButton(tr(TEXT["distractionRecord"]), "crosshair")
        self.recordButton.clicked.connect(plugin.startDistractionRecording)
        distractionRow.addWidget(self.recordButton)
        sideLayout.addLayout(distractionRow)
        cameraLayout.addLayout(sideLayout, 1)
        layout.addWidget(cameraCard)

        settingsForm = plugin.context.createSettingsForm()
        if settingsForm is not None:
            settingsTitle = makeLabel(tr(TEXT["settings"]), "subtitle")
            settingsTitle.setContentsMargins(4, 14, 0, 0)
            layout.addWidget(settingsTitle)
            layout.addWidget(settingsForm)

        plugin.stateChanged.connect(self.refresh)
        plugin.visionUpdated.connect(self._onVision)
        plugin.calibrationChanged.connect(self._onCalibration)
        plugin.distractionCalibrationChanged.connect(self._onDistractionCalibration)
        self._refreshCalibrationChip()
        self.refresh()

    def _pauseClicked(self):
        if self.plugin.isPaused():
            self.plugin.resume()
        else:
            buildPauseMenu(self.plugin, self).exec(self.pauseButton.mapToGlobal(self.pauseButton.rect().bottomLeft()))

    def _previewToggled(self, checked):
        self.plugin.context.setData("previewOn", checked)
        self.plugin.setPreviewRequested(checked and self.isVisible())
        if not checked:
            self.preview.clear()

    def showEvent(self, event):
        super().showEvent(event)
        self.plugin.setPreviewRequested(self.previewToggle.isChecked())

    def hideEvent(self, event):
        super().hideEvent(event)
        self.plugin.setPreviewRequested(False)

    def _onVision(self, result):
        if self.isVisible():
            self.preview.setResult(result)

    def _onCalibration(self, phase, message):
        self.calibrationLabel.setText(message)
        setRole(self.calibrationLabel, "success" if phase == "done" else "error" if phase == "failed" else "faint")
        self.calibrateButton.setEnabled(phase not in ("waiting", "collecting"))
        self._refreshCalibrationChip()

    def _onDistractionCalibration(self, phase, message):
        self.distractionLabel.setText(message)
        setRole(self.distractionLabel, "success" if phase == "done" else "error" if phase == "failed" else "faint")
        self.recordButton.setEnabled(phase not in ("turn", "collecting"))
        self._refreshCalibrationChip()

    def _refreshCalibrationChip(self):
        directions = self.plugin.distractionDirections()
        if self.plugin.setting("distractionMode") == "calibrated" and directions:
            self.distractionState.setText(tr(TEXT["distractionCustom"], directions=directions))
            setRole(self.distractionState, "chipSuccess")
        elif directions:
            self.distractionState.setText(tr(TEXT["distractionStored"], directions=directions))
            setRole(self.distractionState, "chip")
        else:
            self.distractionState.setText(tr(TEXT["distractionStandard"]))
            setRole(self.distractionState, "chip")
        calibrated = self.plugin.isCalibrated()
        self.calibrationState.setText(tr(TEXT["calibrated"]) if calibrated else tr(TEXT["notCalibrated"]))
        setRole(self.calibrationState, "chipSuccess" if calibrated else "chip")

    def refresh(self):
        if not self.isVisible():
            return
        plugin = self.plugin
        kind, title, subtitle = plugin.statusInfo()
        self.statusTile.setIconName(statusIcon(kind))
        self.statusTile.setColor(statusColor(kind))
        self.statusTitle.setText(title)
        self.statusSubtitle.setText(subtitle)
        paused = plugin.isPaused()
        self.pauseButton.setText(tr(TEXT["resume"]) if paused else tr(TEXT["pause"]))
        setThemedIcon(self.pauseButton, "play" if paused else "pause", "text", 16)
        self.visionLabel.setText(plugin.visionText())
        tracker = plugin.tracker
        chipKey = (plugin.setting("distractionMode"), len(plugin.distractionPoints()), plugin.isCalibrated())
        if chipKey != getattr(self, "chipKey", None):
            self.chipKey = chipKey
            self._refreshCalibrationChip()
        limits = plugin.currentLimits()
        hasPose = tracker.present is True and tracker.smoothYaw is not None
        self.yawMeter.setState(tracker.deltaYaw, limits["right"], limits["left"], 1.0, hasPose)
        self.pitchMeter.setState(tracker.deltaPitch, limits["up"], limits["down"], 0.6, hasPose)
        if not plugin.previewRequested and self.preview.result is not None:
            self.preview.clear()


class OledHomeWidget(QWidget):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.titleLabel = makeLabel("", "metricSmall")
        self.subtitleLabel = makeLabel("", "faint", True)
        layout.addWidget(self.titleLabel)
        layout.addWidget(self.subtitleLabel)
        layout.addStretch(1)
        buttonRow = QHBoxLayout()
        buttonRow.setSpacing(6)
        self.pauseButton = makeButton(tr(TEXT["pause"]), "pause")
        self.pauseButton.clicked.connect(self._pauseClicked)
        blackoutButton = makeButton(tr(TEXT["blackoutNow"]), "moon", "primary")
        blackoutButton.clicked.connect(plugin.blackoutNow)
        buttonRow.addWidget(self.pauseButton)
        buttonRow.addWidget(blackoutButton, 1)
        layout.addLayout(buttonRow)
        self.lastKey = None
        plugin.stateChanged.connect(self.refresh)
        self.refresh()

    def _pauseClicked(self):
        if self.plugin.isPaused():
            self.plugin.resume()
        else:
            buildPauseMenu(self.plugin, self).exec(self.pauseButton.mapToGlobal(self.pauseButton.rect().bottomLeft()))

    def refresh(self):
        kind, title, subtitle = self.plugin.statusInfo()
        paused = self.plugin.isPaused()
        key = (kind, title, subtitle, paused)
        if key == self.lastKey:
            return
        self.lastKey = key
        self.titleLabel.setText(title)
        self.subtitleLabel.setText(subtitle)
        self.pauseButton.setText(tr(TEXT["resume"]) if paused else tr(TEXT["pause"]))
        setThemedIcon(self.pauseButton, "play" if paused else "pause", "text", 16)
