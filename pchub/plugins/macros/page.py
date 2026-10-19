"""Macros page: list on the left, editor on the right (trigger, where, what it does), plus recording indicator,
point picker and home widget."""
import time

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout, QLineEdit, QMenu,
                               QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QVBoxLayout, QWidget)

from pchub.core import winapi
from pchub.core.dates import formatWhen, parseDateTime
from pchub.core.i18n import T, tr
from pchub.core.paths import isWindows
from pchub.plugins.macros import logic
from pchub.plugins.macros.plugin import macroTitle
from pchub.ui.dialogs import confirm, pickIcon
from pchub.ui.pickers import ChipGroup, ColorSwatches, ITEM_COLORS
from pchub.ui.theme import roundedPath, theme, withAlpha
from pchub.ui.widgets import (Card, EmptyState, FlowLayout, IconTile, IconWidget, ToggleSwitch, clearLayout, divider,
                              iconButton, makeButton, makeLabel, setRole, setThemedIcon)

TEXT = {
    "new": T("Nuova", "New"),
    "newSteps": T("Macro a passi", "Step macro"),
    "newStepsHint": T("Tasti, testo, clic, attese… in ordine.", "Keys, text, clicks, waits… in order."),
    "newClicker": T("Autoclicker", "Autoclicker"),
    "newClickerHint": T("Clicca da solo a ripetizione.", "Clicks by itself, again and again."),
    "newRecord": T("Registra una macro", "Record a macro"),
    "newRecordHint": T("Fai le azioni, PC Hub le ripete.", "Do the actions, PC Hub repeats them."),
    "search": T("Cerca macro…", "Search macros…"),
    "emptyTitle": T("Nessuna macro", "No macros"),
    "emptyText": T("Crea una macro a passi, un autoclicker o registrane una.",
                   "Create a step macro, an autoclicker or record one."),
    "pickOne": T("Scegli una macro a sinistra", "Pick a macro on the left"),
    "namePlaceholder": T("Nome della macro", "Macro name"),
    "test": T("Prova", "Test"),
    "stop": T("Ferma", "Stop"),
    "duplicate": T("Duplica", "Duplicate"),
    "delete": T("Elimina", "Delete"),
    "deleteTitle": T("Eliminare la macro?", "Delete the macro?"),
    "deleteMessage": T("La macro e i suoi passi vengono cancellati.", "The macro and its steps are deleted."),
    "global": T("Ovunque", "Everywhere"),
    "noKey": T("senza tasto", "no key"),
    "running": T("in esecuzione", "running"),
    "whenTitle": T("Quando parte", "When it starts"),
    "trigger": T("Tasto", "Key"),
    "triggerHint": T("Un tasto, una combinazione o un tasto del mouse (anche Mouse 4/5 e rotellina).",
                     "A key, a combo or a mouse button (Mouse 4/5 and wheel too)."),
    "press": T("Premi un tasto o un tasto del mouse…  (Esc annulla)", "Press a key or a mouse button…  (Esc cancels)"),
    "setKey": T("Scegli tasto", "Choose key"),
    "clearKey": T("Togli tasto", "Remove key"),
    "dangerous": T("Il clic sinistro o destro da solo bloccherebbe il mouse: tieni premuto Ctrl, Alt o Shift mentre clicchi.",
                   "A plain left or right click would hijack the mouse: hold Ctrl, Alt or Shift while clicking."),
    "conflict": T("Stesso tasto di: {names}. Partiranno insieme.", "Same key as: {names}. They'll start together."),
    "mode": T("Come si comporta", "How it behaves"),
    "repeatCount": T("Quante volte", "How many times"),
    "loopDelay": T("Pausa tra un giro e l'altro", "Pause between loops"),
    "block": T("Blocca il tasto originale", "Block the original key"),
    "blockHint": T("Il gioco/app non riceve il tasto che fa partire la macro.", "The game/app doesn't get the key that starts the macro."),
    "whereTitle": T("Dove funziona", "Where it works"),
    "onlyApps": T("Solo in queste app", "Only in these apps"),
    "appsHint": T("Funziona solo quando una di queste app è in primo piano (es. RobloxPlayerBeta.exe).",
                  "Works only when one of these apps is in front (e.g. RobloxPlayerBeta.exe)."),
    "addApp": T("Aggiungi", "Add"),
    "appPlaceholder": T("nome.exe o scegli tra quelle aperte", "name.exe or pick an open one"),
    "grabApp": T("Prendi l'app in primo piano", "Grab the app in front"),
    "grabAppCountdown": T("Vai nell'app… {seconds}", "Go to the app… {seconds}"),
    "noApps": T("Nessuna app: funziona ovunque finché non ne aggiungi una.", "No apps: works everywhere until you add one."),
    "whatTitle": T("Cosa fa", "What it does"),
    "addStep": T("Aggiungi passo", "Add step"),
    "record": T("Registra", "Record"),
    "recordHint": T("PC Hub si riduce a icona: hai 3 secondi per andare dove vuoi registrare. Ferma con il pulsante "
                    "in alto o con {hotkey}.",
                    "PC Hub minimizes: you have 3 seconds to go where you want to record. Stop with the button on top "
                    "or with {hotkey}."),
    "noSteps": T("Nessun passo: aggiungine uno o registra.", "No steps: add one or record."),
    "speed": T("Velocità", "Speed"),
    "stepDelay": T("Pausa tra i passi", "Pause between steps"),
    "duration": T("Durata di un giro: circa {time}", "One loop takes about {time}"),
    "moveUp": T("Sposta su", "Move up"),
    "moveDown": T("Sposta giù", "Move down"),
    "insertBelow": T("Inserisci sotto", "Insert below"),
    "pickPoint": T("Scegli punto", "Pick point"),
    "pickPointHint": T("Clicca il punto che vuoi usare  ·  Esc annulla", "Click the point you want  ·  Esc cancels"),
    "atPosition": T("in un punto", "at a point"),
    "relative": T("di quanto (relativo)", "by how much (relative)"),
    "random": T("± casuale", "± random"),
    "browse": T("Sfoglia…", "Browse…"),
    "textPlaceholder": T("Testo da scrivere", "Text to type"),
    "pathPlaceholder": T("Programma, file, cartella o link", "Program, file, folder or link"),
    "clickerTitle": T("Autoclicker", "Autoclicker"),
    "button": T("Pulsante", "Button"),
    "cps": T("Clic al secondo", "Clicks per second"),
    "every": T("un clic ogni {ms} ms", "one click every {ms} ms"),
    "randomness": T("Variazione casuale", "Random variation"),
    "randomnessHint": T("Rende i tempi meno regolari, più umani.", "Makes timing less regular, more human."),
    "double": T("Doppio clic", "Double click"),
    "holdMs": T("Durata di ogni clic", "Length of each click"),
    "where": T("Dove clicca", "Where it clicks"),
    "atCursor": T("Dove c'è il mouse", "Where the mouse is"),
    "fixedPoint": T("Punto fisso", "Fixed point"),
    "limit": T("Quando si ferma", "When it stops"),
    "noLimit": T("Quando lo fermo io", "When I stop it"),
    "afterClicks": T("Dopo N clic", "After N clicks"),
    "afterSeconds": T("Dopo N secondi", "After N seconds"),
    "stats": T("Partita {count} volte · ultima {when}", "Ran {count} times · last {when}"),
    "neverRun": T("Mai partita", "Never run"),
    "testCountdown": T("Parte tra 3 secondi: vai nella finestra giusta. {hotkey} per fermarla.",
                       "Starts in 3 seconds: go to the right window. {hotkey} to stop it."),
    "recordingTitle": T("Registrazione", "Recording"),
    "recordingCountdown": T("Si parte tra {seconds}…", "Starting in {seconds}…"),
    "recordingNow": T("Sto registrando…", "Recording…"),
    "recordingDone": T("Registrati {count} passi.", "Recorded {count} steps."),
    "actions": T("{count} azioni", "{count} actions"),
    "stopHint": T("oppure {hotkey}", "or {hotkey}"),
    "disabledBanner": T("Le macro sono spente: nessuna parte dal suo tasto.", "Macros are off: none starts from its key."),
    "turnOn": T("Accendi", "Turn on"),
    "enabled": T("Attiva", "On"),
    "speedSuffix": T("×", "×"),
    "kindSteps": T("Passi", "Steps"),
}
SPECIAL_KEYS = [(0x5B, "Win"), (0x2C, "Stamp"), (0x13, "Pausa"), (0x14, "Caps Lock"), (0x5D, "Menu"),
                (0xB3, "Play/Pausa"), (0xB0, "Traccia succ."), (0xB1, "Traccia prec."), (0xAD, "Muto"),
                (0xAF, "Volume +"), (0xAE, "Volume -")] + [(0x7B + index, f"F{13 + index}") for index in range(1, 12)]


def stopHotkeyText(plugin):
    return plugin.setting("stopAllHotkey") or "—"


def qtKeyToVirtualKey(event):
    native = event.nativeVirtualKey()
    if isWindows and native:
        return native
    key = event.key()
    if Qt.Key_A <= key <= Qt.Key_Z or Qt.Key_0 <= key <= Qt.Key_9:
        return int(key)
    if Qt.Key_F1 <= key <= Qt.Key_F24:
        return 0x70 + (key - Qt.Key_F1)
    table = {Qt.Key_Space: 0x20, Qt.Key_Return: 0x0D, Qt.Key_Enter: 0x0D, Qt.Key_Tab: 0x09, Qt.Key_Escape: 0x1B,
             Qt.Key_Backspace: 0x08, Qt.Key_Delete: 0x2E, Qt.Key_Insert: 0x2D, Qt.Key_Home: 0x24, Qt.Key_End: 0x23,
             Qt.Key_PageUp: 0x21, Qt.Key_PageDown: 0x22, Qt.Key_Left: 0x25, Qt.Key_Up: 0x26, Qt.Key_Right: 0x27,
             Qt.Key_Down: 0x28, Qt.Key_CapsLock: 0x14, Qt.Key_Shift: 0xA0, Qt.Key_Control: 0xA2, Qt.Key_Alt: 0xA4,
             Qt.Key_Meta: 0x5B}
    return table.get(key, 0)


def qtMods(modifiers):
    mods = []
    if modifiers & Qt.ControlModifier:
        mods.append("ctrl")
    if modifiers & Qt.AltModifier:
        mods.append("alt")
    if modifiers & Qt.ShiftModifier:
        mods.append("shift")
    if modifiers & Qt.MetaModifier:
        mods.append("win")
    return mods


def physicalCursor(plugin):
    if isWindows and plugin.sender is not None:
        return plugin.sender.cursorPosition()
    position = QCursor.pos()
    return position.x(), position.y()


def spinBox(minimum, maximum, value, suffix="", step=1, width=110):
    box = QSpinBox()
    box.setRange(minimum, maximum)
    box.setSingleStep(step)
    box.setValue(int(value))
    if suffix:
        box.setSuffix(suffix)
    box.setFixedWidth(width)
    return box


def sectionCard(title, iconName):
    card = Card(padding=18, hoverable=False)
    layout = QVBoxLayout(card)
    layout.setSpacing(12)
    header = QHBoxLayout()
    header.setSpacing(10)
    header.addWidget(IconWidget(iconName, "muted", 18))
    header.addWidget(makeLabel(tr(title).upper(), "section"))
    header.addStretch(1)
    layout.addLayout(header)
    return card, layout, header


def formRow(label, control, hint=None, stretch=False):
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(14)
    textLayout = QVBoxLayout()
    textLayout.setSpacing(2)
    textLayout.addWidget(makeLabel(tr(label)))
    if hint:
        textLayout.addWidget(makeLabel(tr(hint), "faint", True))
    row.addLayout(textLayout, 1)
    if isinstance(control, QWidget):
        row.addWidget(control, 1 if stretch else 0, Qt.AlignVCenter)
    else:
        row.addLayout(control, 1 if stretch else 0)
    return row


# ---------------------------------------------------------------------------------------------------------------
class MacrosPage(QWidget):
    noScroll = True

    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.selectedId = plugin.context.getData("selectedMacro")
        self.listItems = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 14)
        layout.setSpacing(6)

        listCard = Card(padding=12, hoverable=False)
        listCard.setFixedWidth(330)
        listLayout = QVBoxLayout(listCard)
        listLayout.setSpacing(8)
        topRow = QHBoxLayout()
        topRow.setSpacing(8)
        self.masterSwitch = ToggleSwitch(plugin.setting("macrosEnabled") is not False)
        self.masterSwitch.toggled.connect(lambda checked: plugin.setSetting("macrosEnabled", checked))
        topRow.addWidget(self.masterSwitch)
        self.masterLabel = makeLabel(tr(T("Macro attive", "Macros on")), None)
        topRow.addWidget(self.masterLabel, 1)
        self.newButton = makeButton(tr(TEXT["new"]), "plus", "primary")
        self.newButton.clicked.connect(self._newMenu)
        topRow.addWidget(self.newButton)
        listLayout.addLayout(topRow)
        self.searchEdit = QLineEdit()
        self.searchEdit.setPlaceholderText(tr(TEXT["search"]))
        self.searchEdit.textChanged.connect(self.rebuildList)
        listLayout.addWidget(self.searchEdit)
        listScroll = QScrollArea()
        listScroll.setWidgetResizable(True)
        listScroll.setFrameShape(QFrame.NoFrame)
        listScroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        listHost = QWidget()
        self.listLayout = QVBoxLayout(listHost)
        self.listLayout.setContentsMargins(0, 0, 4, 0)
        self.listLayout.setSpacing(6)
        listScroll.setWidget(listHost)
        listLayout.addWidget(listScroll, 1)
        stopAllButton = makeButton(tr(T("Ferma tutte", "Stop all")), "octagon-x", "ghost")
        stopAllButton.setToolTip(stopHotkeyText(plugin))
        stopAllButton.clicked.connect(plugin.stopAll)
        listLayout.addWidget(stopAllButton)
        layout.addWidget(listCard)

        self.editorScroll = QScrollArea()
        self.editorScroll.setWidgetResizable(True)
        self.editorScroll.setFrameShape(QFrame.NoFrame)
        self.editorScroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(self.editorScroll, 1)
        self.editor = None

        plugin.macrosChanged.connect(self._onMacrosChanged)
        plugin.runStateChanged.connect(self._onRunState)
        self.rebuildList()
        if self.selectedId is None or plugin.find(self.selectedId) is None:
            self.selectedId = plugin.macros[0]["id"] if plugin.macros else None
        self.selectMacro(self.selectedId)

    # list ----------------------------------------------------------------------------------
    def _newMenu(self):
        menu = QMenu(self)
        for label, hint, iconName, callback in (
                (TEXT["newSteps"], TEXT["newStepsHint"], "list-checks", lambda: self.createMacro("steps")),
                (TEXT["newClicker"], TEXT["newClickerHint"], "mouse-pointer-click", lambda: self.createMacro("clicker")),
                (TEXT["newRecord"], TEXT["newRecordHint"], "circle-dot", lambda: self.createMacro("steps", record=True))):
            action = menu.addAction(f"{tr(label)}  —  {tr(hint)}")
            action.triggered.connect(callback)
        menu.exec(self.newButton.mapToGlobal(self.newButton.rect().bottomLeft()))

    def createMacro(self, kind, record=False):
        macro = self.plugin.add(kind)
        self.selectMacro(macro["id"])
        if self.editor is not None:
            self.editor.nameEdit.setFocus()
            if record:
                self.editor.startRecording()

    def rebuildList(self, *args):
        clearLayout(self.listLayout)
        self.listItems = {}
        query = self.searchEdit.text().strip().lower()
        shown = 0
        for macro in self.plugin.macros:
            haystack = f"{macroTitle(macro)} {logic.triggerText(macro.get('trigger'))} {' '.join(macro['apps'])}".lower()
            if query and query not in haystack:
                continue
            item = MacroListItem(self.plugin, macro)
            item.clicked.connect(lambda macroId=macro["id"]: self.selectMacro(macroId))
            item.setSelected(macro["id"] == self.selectedId)
            self.listLayout.addWidget(item)
            self.listItems[macro["id"]] = item
            shown += 1
        if not shown:
            self.listLayout.addWidget(EmptyState("zap", tr(TEXT["emptyTitle"]), tr(TEXT["emptyText"])))
        self.listLayout.addStretch(1)
        self.masterSwitch.blockSignals(True)
        self.masterSwitch.setChecked(self.plugin.setting("macrosEnabled") is not False)
        self.masterSwitch.blockSignals(False)

    def selectMacro(self, macroId):
        self.selectedId = macroId
        self.plugin.context.setData("selectedMacro", macroId)
        for itemId, item in self.listItems.items():
            item.setSelected(itemId == macroId)
        macro = self.plugin.find(macroId) if macroId else None
        if self.editor is not None:
            self.editor.detach()
        if macro is None:
            self.editor = None
            placeholder = EmptyState("zap", tr(TEXT["pickOne"]) if self.plugin.macros else tr(TEXT["emptyTitle"]),
                                     "" if self.plugin.macros else tr(TEXT["emptyText"]))
            self.editorScroll.setWidget(placeholder)
            return
        self.editor = MacroEditor(self.plugin, macroId, self)
        self.editorScroll.setWidget(self.editor)

    def _onMacrosChanged(self, macroId):
        if macroId and macroId in self.listItems:
            self.listItems[macroId].refresh()
            return
        self.rebuildList()
        if (self.selectedId is None or self.plugin.find(self.selectedId) is None) and (self.plugin.macros or self.editor):
            self.selectMacro(self.plugin.macros[0]["id"] if self.plugin.macros else None)
        elif self.editor is not None:
            self.editor.refreshBanner()

    def _onRunState(self, macroId):
        item = self.listItems.get(macroId)
        if item is not None:
            item.refresh()
        if self.editor is not None and self.editor.macroId == macroId:
            self.editor.refreshRunState()


class MacroListItem(Card):
    def __init__(self, plugin, macro, parent=None):
        super().__init__(parent, padding=10, clickable=True)
        self.plugin = plugin
        self.macroId = macro["id"]
        layout = QHBoxLayout(self)
        layout.setSpacing(10)
        self.tile = IconTile(macro.get("icon") or "zap", 34, macro.get("color"))
        layout.addWidget(self.tile)
        textLayout = QVBoxLayout()
        textLayout.setSpacing(2)
        self.titleLabel = makeLabel("")
        self.titleLabel.setStyleSheet("font-weight: 600;")
        self.subtitleLabel = makeLabel("", "faint")
        for label in (self.titleLabel, self.subtitleLabel):
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            label.setMinimumWidth(0)
        textLayout.addWidget(self.titleLabel)
        textLayout.addWidget(self.subtitleLabel)
        layout.addLayout(textLayout, 1)
        self.enabledSwitch = ToggleSwitch(bool(macro.get("enabled")))
        self.enabledSwitch.toggled.connect(lambda checked: plugin.update(self.macroId, enabled=checked))
        layout.addWidget(self.enabledSwitch)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.refresh()

    def refresh(self):
        macro = self.plugin.find(self.macroId)
        if macro is None:
            return
        self.tile.setIconName(macro.get("icon") or "zap")
        self.tile.setColor(macro.get("color"))
        self.titleLabel.setText(macroTitle(macro))
        parts = [logic.triggerText(macro.get("trigger")) if macro.get("trigger") else tr(TEXT["noKey"])]
        if macro.get("scope") == "apps" and macro.get("apps"):
            parts.append(", ".join(app.replace(".exe", "") for app in macro["apps"][:2]) + ("…" if len(macro["apps"]) > 2 else ""))
        else:
            parts.append(tr(TEXT["global"]))
        if self.plugin.isMacroRunning(self.macroId):
            parts.insert(0, "● " + tr(TEXT["running"]))
        self.subtitleLabel.setText(" · ".join(parts))
        setRole(self.subtitleLabel, "success" if self.plugin.isMacroRunning(self.macroId) else "faint")
        self.enabledSwitch.blockSignals(True)
        self.enabledSwitch.setChecked(bool(macro.get("enabled")))
        self.enabledSwitch.blockSignals(False)

    def _menu(self, point):
        menu = QMenu(self)
        running = self.plugin.isMacroRunning(self.macroId)
        menu.addAction(tr(TEXT["stop"] if running else TEXT["test"]), lambda: self.plugin.toggleMacro(self.macroId))
        menu.addAction(tr(TEXT["duplicate"]), lambda: self.plugin.duplicate(self.macroId))
        menu.addAction(tr(TEXT["moveUp"]), lambda: self.plugin.move(self.macroId, -1))
        menu.addAction(tr(TEXT["moveDown"]), lambda: self.plugin.move(self.macroId, 1))
        menu.addSeparator()
        menu.addAction(tr(TEXT["delete"]), self._delete)
        menu.exec(self.mapToGlobal(point))

    def _delete(self):
        macro = self.plugin.find(self.macroId)
        if macro and confirm(self, tr(TEXT["deleteTitle"]), tr(TEXT["deleteMessage"]), [macroTitle(macro)], danger=True,
                             confirmText=tr(TEXT["delete"])):
            self.plugin.delete(self.macroId)


# ---------------------------------------------------------------------------------------------------------------
class MacroEditor(QWidget):
    def __init__(self, plugin, macroId, page):
        super().__init__()
        self.plugin = plugin
        self.macroId = macroId
        self.page = page
        self.awaitingRecording = False
        self.attached = True
        macro = plugin.find(macroId)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 8, 8)
        layout.setSpacing(4)

        self.banner = QWidget()
        bannerLayout = QHBoxLayout(self.banner)
        bannerLayout.setContentsMargins(4, 0, 4, 6)
        bannerLayout.addWidget(IconWidget("power", "warning", 16))
        bannerLayout.addWidget(makeLabel(tr(TEXT["disabledBanner"]), "muted"), 1)
        turnOnButton = makeButton(tr(TEXT["turnOn"]), None, "ghost")
        turnOnButton.clicked.connect(lambda: plugin.setSetting("macrosEnabled", True))
        bannerLayout.addWidget(turnOnButton)
        layout.addWidget(self.banner)

        # header -----------------------------------------------------------------------------
        headerCard = Card(padding=18, hoverable=False)
        headerLayout = QVBoxLayout(headerCard)
        headerLayout.setSpacing(10)
        topRow = QHBoxLayout()
        topRow.setSpacing(10)
        self.iconButton = QPushButton()
        self.iconButton.setFixedSize(46, 46)
        self.iconButton.setCursor(Qt.PointingHandCursor)
        self.iconButton.setStyleSheet("QPushButton { background: transparent; border: none; }")
        self.iconTile = IconTile(macro.get("icon") or "zap", 46, macro.get("color"), self.iconButton)
        self.iconTile.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.iconButton.clicked.connect(self._pickIcon)
        topRow.addWidget(self.iconButton)
        nameLayout = QVBoxLayout()
        nameLayout.setSpacing(2)
        self.nameEdit = QLineEdit(macro.get("name", ""))
        self.nameEdit.setPlaceholderText(macroTitle(macro) if not macro.get("name") else tr(TEXT["namePlaceholder"]))
        self.nameEdit.setStyleSheet("QLineEdit { font-size: 19px; font-weight: 700; background: transparent; border: none; padding: 2px; }")
        self.nameEdit.textEdited.connect(lambda text: plugin.update(macroId, name=text))
        nameLayout.addWidget(self.nameEdit)
        self.statsLabel = makeLabel("", "faint")
        nameLayout.addWidget(self.statsLabel)
        topRow.addLayout(nameLayout, 1)
        self.testButton = makeButton(tr(TEXT["test"]), "play", "primary")
        self.testButton.clicked.connect(self._test)
        topRow.addWidget(self.testButton)
        moreButton = iconButton("ellipsis", None, "muted", 18)
        moreButton.clicked.connect(lambda: self._moreMenu(moreButton))
        topRow.addWidget(moreButton)
        headerLayout.addLayout(topRow)
        colorRow = QHBoxLayout()
        self.colorPicker = ColorSwatches(macro.get("color") or ITEM_COLORS[0])
        self.colorPicker.colorChanged.connect(self._onColor)
        colorRow.addWidget(self.colorPicker, 1)
        self.enabledSwitch = ToggleSwitch(bool(macro.get("enabled")))
        self.enabledSwitch.toggled.connect(lambda checked: plugin.update(macroId, enabled=checked))
        colorRow.addWidget(makeLabel(tr(TEXT["enabled"]), "muted"))
        colorRow.addWidget(self.enabledSwitch)
        headerLayout.addLayout(colorRow)
        layout.addWidget(headerCard)

        # when ---------------------------------------------------------------------------------------
        whenCard, whenLayout, _ = sectionCard(TEXT["whenTitle"], "keyboard")
        triggerRow = QHBoxLayout()
        triggerRow.setSpacing(8)
        self.triggerButton = TriggerButton(plugin)
        self.triggerButton.captured.connect(self._onTrigger)
        triggerRow.addWidget(self.triggerButton, 1)
        clearButton = iconButton("x", tr(TEXT["clearKey"]), "muted", 16)
        clearButton.clicked.connect(lambda: self._setTrigger(None))
        triggerRow.addWidget(clearButton)
        whenLayout.addLayout(formRow(TEXT["trigger"], triggerRow, TEXT["triggerHint"], stretch=True))
        self.triggerError = makeLabel("", "error", True)
        self.triggerError.hide()
        whenLayout.addWidget(self.triggerError)
        self.conflictLabel = makeLabel("", "warning", True)
        whenLayout.addWidget(self.conflictLabel)
        whenLayout.addWidget(divider())
        whenLayout.addWidget(makeLabel(tr(TEXT["mode"])))
        self.modeChips = ChipGroup([(mode, tr(logic.MODE_NAMES[mode])) for mode in logic.MODES], macro["mode"])
        self.modeChips.changed.connect(self._onMode)
        whenLayout.addWidget(self.modeChips)
        self.modeHint = makeLabel("", "faint", True)
        whenLayout.addWidget(self.modeHint)
        self.repeatSpin = spinBox(1, 100000, macro.get("repeatCount") or 5, "×")
        self.repeatSpin.valueChanged.connect(lambda value: plugin.update(macroId, repeatCount=value))
        self.repeatRow = QWidget()
        self.repeatRow.setLayout(formRow(TEXT["repeatCount"], self.repeatSpin))
        whenLayout.addWidget(self.repeatRow)
        self.loopDelaySpin = spinBox(0, 600000, macro.get("loopDelay") or 0, " ms", 50)
        self.loopDelaySpin.valueChanged.connect(lambda value: plugin.update(macroId, loopDelay=value))
        self.loopDelayRow = QWidget()
        self.loopDelayRow.setLayout(formRow(TEXT["loopDelay"], self.loopDelaySpin))
        whenLayout.addWidget(self.loopDelayRow)
        whenLayout.addWidget(divider())
        self.blockSwitch = ToggleSwitch(bool(macro.get("blockTrigger")))
        self.blockSwitch.toggled.connect(lambda checked: plugin.update(macroId, blockTrigger=checked))
        whenLayout.addLayout(formRow(TEXT["block"], self.blockSwitch, TEXT["blockHint"]))
        layout.addWidget(whenCard)

        # where ------------------------------------------------------------------------------------------
        whereCard, whereLayout, _ = sectionCard(TEXT["whereTitle"], "app-window")
        self.scopeChips = ChipGroup([("global", tr(TEXT["global"])), ("apps", tr(TEXT["onlyApps"]))], macro["scope"])
        self.scopeChips.changed.connect(self._onScope)
        whereLayout.addWidget(self.scopeChips)
        self.appsHost = QWidget()
        appsLayout = QVBoxLayout(self.appsHost)
        appsLayout.setContentsMargins(0, 0, 0, 0)
        appsLayout.setSpacing(8)
        appsLayout.addWidget(makeLabel(tr(TEXT["appsHint"]), "faint", True))
        self.appChipsHost = QWidget()
        self.appChipsLayout = FlowLayout(self.appChipsHost, 6)
        appsLayout.addWidget(self.appChipsHost)
        addRow = QHBoxLayout()
        addRow.setSpacing(6)
        self.appCombo = AppCombo()
        self.appCombo.setEditable(True)
        self.appCombo.lineEdit().setPlaceholderText(tr(TEXT["appPlaceholder"]))
        self.appCombo.lineEdit().returnPressed.connect(self._addApp)
        self.appCombo.setInsertPolicy(QComboBox.NoInsert)
        addRow.addWidget(self.appCombo, 1)
        addAppButton = makeButton(tr(TEXT["addApp"]), "plus")
        addAppButton.clicked.connect(self._addApp)
        addRow.addWidget(addAppButton)
        self.grabButton = makeButton(tr(TEXT["grabApp"]), "crosshair", "ghost")
        self.grabButton.clicked.connect(self._grabApp)
        addRow.addWidget(self.grabButton)
        appsLayout.addLayout(addRow)
        whereLayout.addWidget(self.appsHost)
        layout.addWidget(whereCard)

        # what ------------------------------------------------------------------------------------------------
        if macro["kind"] == "clicker":
            layout.addWidget(ClickerSection(plugin, macroId))
        else:
            self.stepsSection = StepsSection(plugin, macroId, self)
            layout.addWidget(self.stepsSection)
        layout.addStretch(1)

        plugin.recordingStateChanged.connect(self._onRecordingState)
        plugin.recordingFinished.connect(self._onRecordingFinished)
        plugin.macrosChanged.connect(self._onMacroChanged)
        self.refreshTrigger()
        self.refreshMode()
        self.refreshApps()
        self.refreshRunState()
        self.refreshBanner()

    def detach(self):
        """The page swapped editors: stop listening (the widget is deleted by the scroll area)."""
        self.attached = False
        self.triggerButton.cancel()
        for signal, slot in ((self.plugin.recordingStateChanged, self._onRecordingState),
                             (self.plugin.recordingFinished, self._onRecordingFinished),
                             (self.plugin.macrosChanged, self._onMacroChanged)):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        if hasattr(self, "stepsSection"):
            self.stepsSection.detach()

    def macro(self):
        return self.plugin.find(self.macroId)

    def refreshBanner(self):
        self.banner.setVisible(self.plugin.setting("macrosEnabled") is False)

    def _onMacroChanged(self, macroId):
        if macroId == self.macroId:
            self.refreshConflicts()
            self.refreshRunState()
            if hasattr(self, "stepsSection"):
                self.stepsSection.syncFromModel()

    def refreshRunState(self):
        macro = self.macro()
        if macro is None:
            return
        running = self.plugin.isMacroRunning(self.macroId)
        self.testButton.setText(tr(TEXT["stop"] if running else TEXT["test"]))
        setThemedIcon(self.testButton, "square" if running else "play", "text", 16)
        lastRun = parseDateTime(macro.get("lastRun"))
        if lastRun:
            self.statsLabel.setText(tr(TEXT["stats"], count=macro.get("runCount", 0), when=formatWhen(lastRun)))
        else:
            self.statsLabel.setText(tr(TEXT["neverRun"]))

    # header actions --------------------------------------------------------------------------------------
    def _pickIcon(self):
        macro = self.macro()
        iconName = pickIcon(self, macro.get("icon"))
        if iconName:
            self.plugin.update(self.macroId, icon=iconName)
            self.iconTile.setIconName(iconName)

    def _onColor(self, value):
        self.plugin.update(self.macroId, color=value)
        self.iconTile.setColor(value)

    def _moreMenu(self, button):
        menu = QMenu(self)
        menu.addAction(tr(TEXT["duplicate"]), self._duplicate)
        menu.addSeparator()
        menu.addAction(tr(TEXT["delete"]), self._delete)
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _duplicate(self):
        clone = self.plugin.duplicate(self.macroId)
        if clone:
            QTimer.singleShot(0, lambda: self.page.selectMacro(clone["id"]))

    def _delete(self):
        macro = self.macro()
        if macro and confirm(self, tr(TEXT["deleteTitle"]), tr(TEXT["deleteMessage"]), [macroTitle(macro)], danger=True,
                             confirmText=tr(TEXT["delete"])):
            self.plugin.delete(self.macroId)

    def _test(self):
        if self.plugin.isMacroRunning(self.macroId):
            self.plugin.stopMacro(self.macroId)
            return
        macro = self.macro()
        self.plugin.context.alert(macroTitle(macro), tr(TEXT["testCountdown"], hotkey=stopHotkeyText(self.plugin)),
                                  "play", timeoutSeconds=3, accent=macro.get("color"))
        window = self.window()
        window.showMinimized()
        QTimer.singleShot(3000, lambda: self.plugin.runMacro(self.macroId))

    # trigger -------------------------------------------------------------------------------------------------
    def _onTrigger(self, trigger):
        if trigger is None:
            self.refreshTrigger()
            return
        if logic.isDangerousTrigger(trigger):
            self.triggerError.setText(tr(TEXT["dangerous"]))
            self.triggerError.show()
            self.refreshTrigger()
            return
        self._setTrigger(trigger)

    def _setTrigger(self, trigger):
        self.triggerError.hide()
        self.plugin.update(self.macroId, trigger=trigger)
        self.refreshTrigger()

    def refreshTrigger(self):
        macro = self.macro()
        self.triggerButton.setTrigger(macro.get("trigger"))
        self.refreshConflicts()

    def refreshConflicts(self):
        conflicts = self.plugin.conflicts(self.macroId)
        self.conflictLabel.setText(tr(TEXT["conflict"], names=", ".join(macroTitle(other) for other in conflicts)))
        self.conflictLabel.setVisible(bool(conflicts))

    def _onMode(self, mode):
        if mode:
            self.plugin.update(self.macroId, mode=mode)
        self.refreshMode()

    def refreshMode(self):
        macro = self.macro()
        mode = macro["mode"]
        self.modeChips.setValue(mode)
        hint = logic.MODE_HINTS[mode]
        if macro["kind"] == "clicker" and mode in ("once", "repeat"):
            hint = T("Clicca fino al limite scelto sotto (\"Quando si ferma\"). Ripremi per fermarlo prima.",
                     "Clicks until the limit chosen below (\"When it stops\"). Press again to stop it earlier.")
        self.modeHint.setText(tr(hint))
        self.repeatRow.setVisible(mode == "repeat" and macro["kind"] == "steps")
        self.loopDelayRow.setVisible(mode != "once" and macro["kind"] == "steps")

    # where -----------------------------------------------------------------------------------------------------
    def _onScope(self, scope):
        if scope:
            self.plugin.update(self.macroId, scope=scope)
        self.refreshApps()

    def refreshApps(self):
        macro = self.macro()
        self.scopeChips.setValue(macro["scope"])
        self.appsHost.setVisible(macro["scope"] == "apps")
        while self.appChipsLayout.count():
            item = self.appChipsLayout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not macro["apps"]:
            self.appChipsLayout.addWidget(makeLabel(tr(TEXT["noApps"]), "faint"))
        for app in macro["apps"]:
            chip = makeButton(f"{app}  ✕", "app-window", "chip")
            chip.clicked.connect(lambda checked=False, value=app: self._removeApp(value))
            self.appChipsLayout.addWidget(chip)

    def _addApp(self):
        name = self.appCombo.currentText().strip().lower()
        if not name:
            return
        if isWindows and "." not in name:
            name += ".exe"
        macro = self.macro()
        if name not in macro["apps"]:
            self.plugin.update(self.macroId, apps=macro["apps"] + [name], scope="apps")
        self.appCombo.setEditText("")
        self.refreshApps()

    def _removeApp(self, app):
        macro = self.macro()
        self.plugin.update(self.macroId, apps=[item for item in macro["apps"] if item != app])
        self.refreshApps()

    def _grabApp(self):
        self.grabSeconds = 3
        self.grabButton.setEnabled(False)
        self.grabButton.setText(tr(TEXT["grabAppCountdown"], seconds=self.grabSeconds))
        self.grabTimer = QTimer(self)
        self.grabTimer.setInterval(1000)
        self.grabTimer.timeout.connect(self._grabTick)
        self.grabTimer.start()

    def _grabTick(self):
        self.grabSeconds -= 1
        if self.grabSeconds > 0:
            self.grabButton.setText(tr(TEXT["grabAppCountdown"], seconds=self.grabSeconds))
            return
        self.grabTimer.stop()
        self.grabButton.setEnabled(True)
        self.grabButton.setText(tr(TEXT["grabApp"]))
        name = winapi.foregroundProcessName()
        if name and name not in ("pchub.exe", "python.exe", "pythonw.exe"):
            self.appCombo.setEditText(name)
            self._addApp()

    # recording ---------------------------------------------------------------------------------------------------
    def startRecording(self):
        if self.plugin.isRecording():
            return
        self.awaitingRecording = True
        self.plugin.context.alert(tr(TEXT["recordingTitle"]),
                                  tr(TEXT["recordHint"], hotkey=stopHotkeyText(self.plugin)), "circle-dot",
                                  timeoutSeconds=4, accent="#F87171")
        self.window().showMinimized()
        self.plugin.startRecording(3)

    def _onRecordingState(self, state, value):
        if hasattr(self, "stepsSection"):
            self.stepsSection.setRecordingState(state, value, self.awaitingRecording)

    def _onRecordingFinished(self, steps):
        if not self.awaitingRecording or not self.attached:
            return
        self.awaitingRecording = False
        window = self.window()
        if window.isMinimized():
            window.showNormal()
            window.activateWindow()
        if steps and hasattr(self, "stepsSection"):
            self.stepsSection.appendSteps(steps)


class AppCombo(QComboBox):
    """Editable combo that lists the programs running right now when opened."""

    def showPopup(self):
        current = self.currentText()
        self.blockSignals(True)
        self.clear()
        names = sorted(name for name in winapi.runningProcessNames() if name.endswith(".exe") or not isWindows)
        self.addItems(names)
        self.setEditText(current)
        self.blockSignals(False)
        super().showPopup()


class TriggerButton(QPushButton):
    """Shows the trigger; click to capture a new one (global hook on Windows, Qt events elsewhere)."""
    captured = Signal(object)

    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.trigger = None
        self.capturing = False
        self.usingHook = False
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(40)
        self.setFocusPolicy(Qt.StrongFocus)
        self.clicked.connect(self.begin)
        plugin.captureFinished.connect(self._onCaptured)

    def setTrigger(self, trigger):
        self.trigger = trigger
        if not self.capturing:
            self._refresh()

    def _refresh(self):
        if self.capturing:
            self.setText(tr(TEXT["press"]))
            self.setProperty("variant", "chip")
            self.setChecked(True)
        else:
            self.setText(logic.triggerText(self.trigger) if self.trigger else tr(TEXT["setKey"]))
            self.setProperty("variant", "")
        self.style().unpolish(self)
        self.style().polish(self)

    def begin(self):
        if self.capturing:
            self.cancel()
            self._refresh()
            return
        self.capturing = True
        self.usingHook = self.plugin.beginCapture()
        if not self.usingHook:
            self.grabKeyboard()
        self._refresh()

    def cancel(self):
        if not self.capturing:
            return
        self.capturing = False
        if self.usingHook:
            self.plugin.cancelCapture()
        else:
            self.releaseKeyboard()

    def _finish(self, trigger):
        self.cancel()
        self._refresh()
        self.captured.emit(trigger)

    def _onCaptured(self, trigger):
        if self.capturing and self.usingHook:
            self.capturing = False
            self._refresh()
            self.captured.emit(trigger)

    def keyPressEvent(self, event):
        if not self.capturing or self.usingHook:
            super().keyPressEvent(event)
            return
        if event.key() in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta):
            return
        if event.key() == Qt.Key_Escape and not event.modifiers():
            self._finish(None)
            return
        self._finish({"device": "key", "code": qtKeyToVirtualKey(event), "mods": qtMods(event.modifiers())})

    def mousePressEvent(self, event):
        if self.capturing and not self.usingHook:
            buttons = {Qt.MiddleButton: "middle", Qt.BackButton: "x1", Qt.ForwardButton: "x2", Qt.RightButton: "right"}
            if event.button() in buttons:
                self._finish({"device": "mouse", "code": buttons[event.button()], "mods": qtMods(event.modifiers())})
                return
        super().mousePressEvent(event)


class KeyCaptureButton(QPushButton):
    """Key for a step: click, then press the key (with Ctrl/Alt/Shift if you want). ▾ menu for special keys."""
    changed = Signal(int, list)

    def __init__(self, virtualKey, mods, parent=None):
        super().__init__(parent)
        self.virtualKey = virtualKey
        self.mods = list(mods or [])
        self.capturing = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumWidth(130)
        self.clicked.connect(self._toggle)
        self._refresh()

    def _refresh(self):
        if self.capturing:
            self.setText(tr(T("Premi il tasto…", "Press the key…")))
        else:
            self.setText(" + ".join([logic.MODIFIER_LABELS[mod] for mod in logic.sortedMods(self.mods)] +
                                    [logic.keyName(self.virtualKey)]))

    def _toggle(self):
        self.capturing = not self.capturing
        if self.capturing:
            self.grabKeyboard()
        else:
            self.releaseKeyboard()
        self._refresh()

    def keyPressEvent(self, event):
        if not self.capturing:
            super().keyPressEvent(event)
            return
        if event.key() in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta):
            return
        virtualKey = qtKeyToVirtualKey(event)
        if not virtualKey:
            return
        self.capturing = False
        self.releaseKeyboard()
        self.virtualKey = virtualKey
        self.mods = qtMods(event.modifiers())
        self._refresh()
        self.changed.emit(self.virtualKey, self.mods)

    def focusOutEvent(self, event):
        if self.capturing:
            self.capturing = False
            self.releaseKeyboard()
            self._refresh()
        super().focusOutEvent(event)

    def setSpecial(self, virtualKey):
        self.virtualKey = virtualKey
        self.mods = []
        self._refresh()
        self.changed.emit(self.virtualKey, self.mods)


# ---------------------------------------------------------------------------------------------------------------
class StepsSection(Card):
    def __init__(self, plugin, macroId, editor):
        super().__init__(padding=18, hoverable=False)
        self.plugin = plugin
        self.macroId = macroId
        self.editor = editor
        self.committing = False
        self.shownSteps = []
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(IconWidget("list-checks", "muted", 18))
        header.addWidget(makeLabel(tr(TEXT["whatTitle"]).upper(), "section"))
        header.addStretch(1)
        self.recordButton = makeButton(tr(TEXT["record"]), "circle-dot", "danger")
        self.recordButton.clicked.connect(self._recordClicked)
        header.addWidget(self.recordButton)
        self.addButton = makeButton(tr(TEXT["addStep"]), "plus", "primary")
        self.addButton.clicked.connect(lambda: self._addMenu(self.addButton))
        header.addWidget(self.addButton)
        layout.addLayout(header)
        self.recordLabel = makeLabel("", "faint", True)
        self.recordLabel.hide()
        layout.addWidget(self.recordLabel)
        self.rowsLayout = QVBoxLayout()
        self.rowsLayout.setSpacing(6)
        layout.addLayout(self.rowsLayout)
        layout.addWidget(divider())
        macro = plugin.find(macroId)
        settingsRow = QHBoxLayout()
        settingsRow.setSpacing(16)
        speedLayout = QHBoxLayout()
        speedLayout.setSpacing(6)
        speedLayout.addWidget(makeLabel(tr(TEXT["speed"]), "muted"))
        self.speedSpin = QDoubleSpinBox()
        self.speedSpin.setRange(0.1, 10.0)
        self.speedSpin.setSingleStep(0.25)
        self.speedSpin.setDecimals(2)
        self.speedSpin.setSuffix(" ×")
        self.speedSpin.setValue(float(macro.get("speed") or 1.0))
        self.speedSpin.setFixedWidth(90)
        self.speedSpin.valueChanged.connect(self._onSpeed)
        speedLayout.addWidget(self.speedSpin)
        settingsRow.addLayout(speedLayout)
        delayLayout = QHBoxLayout()
        delayLayout.setSpacing(6)
        delayLayout.addWidget(makeLabel(tr(TEXT["stepDelay"]), "muted"))
        self.stepDelaySpin = spinBox(0, 10000, macro.get("stepDelay") or 0, " ms", 5, 100)
        self.stepDelaySpin.valueChanged.connect(self._onStepDelay)
        delayLayout.addWidget(self.stepDelaySpin)
        settingsRow.addLayout(delayLayout)
        settingsRow.addStretch(1)
        self.durationLabel = makeLabel("", "faint")
        settingsRow.addWidget(self.durationLabel)
        layout.addLayout(settingsRow)
        self.rebuild()

    def detach(self):
        pass

    def macro(self):
        return self.plugin.find(self.macroId)

    def steps(self):
        return self.macro()["steps"]

    def syncFromModel(self):
        if not self.committing and self.shownSteps != [step.get("id") for step in self.steps()]:
            self.rebuild()

    def commit(self, rebuild=False):
        self.committing = True
        try:
            self.plugin.setSteps(self.macroId, self.steps())
        finally:
            self.committing = False
        self._refreshDuration()
        if rebuild:
            self.rebuild()

    def rebuild(self):
        clearLayout(self.rowsLayout)
        steps = self.steps()
        self.shownSteps = [step.get("id") for step in steps]
        if not steps:
            self.rowsLayout.addWidget(makeLabel(tr(TEXT["noSteps"]), "faint"))
        for index, step in enumerate(steps):
            self.rowsLayout.addWidget(StepRow(self, index, step))
        self._refreshDuration()

    def _refreshDuration(self):
        macro = self.macro()
        if macro is None:
            return
        self.durationLabel.setText(tr(TEXT["duration"], time=logic.formatMs(logic.estimatedDuration(macro))))

    def _onSpeed(self, value):
        self.plugin.update(self.macroId, speed=round(value, 2))
        self._refreshDuration()

    def _onStepDelay(self, value):
        self.plugin.update(self.macroId, stepDelay=value)
        self._refreshDuration()

    def _addMenu(self, button, insertAt=None):
        menu = QMenu(self)
        for stepType in logic.STEP_TYPES:
            action = menu.addAction(tr(logic.STEP_NAMES[stepType]))
            action.triggered.connect(lambda checked=False, value=stepType: self.addStep(value, insertAt))
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def addStep(self, stepType, insertAt=None):
        step = logic.newStep(stepType)
        steps = self.steps()
        if insertAt is None:
            steps.append(step)
        else:
            steps.insert(insertAt, step)
        self.commit(rebuild=True)

    def appendSteps(self, newSteps):
        self.steps().extend(newSteps)
        self.commit(rebuild=True)

    def moveStep(self, index, offset):
        steps = self.steps()
        target = index + offset
        if 0 <= target < len(steps):
            steps.insert(target, steps.pop(index))
            self.commit(rebuild=True)

    def removeStep(self, index):
        steps = self.steps()
        if 0 <= index < len(steps):
            steps.pop(index)
            self.commit(rebuild=True)

    def duplicateStep(self, index):
        steps = self.steps()
        clone = dict(steps[index])
        clone["id"] = logic.newId()
        steps.insert(index + 1, clone)
        self.commit(rebuild=True)

    def _recordClicked(self):
        if self.plugin.isRecording():
            self.plugin.stopRecording()
        else:
            self.editor.startRecording()

    def setRecordingState(self, state, value, mine):
        if not mine:
            return
        if state == "countdown":
            self.recordLabel.setText(tr(TEXT["recordingCountdown"], seconds=value))
            self.recordLabel.show()
            self.recordButton.setText(tr(TEXT["stop"]))
        elif state == "recording":
            self.recordLabel.setText(tr(TEXT["recordingNow"]))
            self.recordLabel.show()
            self.recordButton.setText(tr(TEXT["stop"]))
        else:
            self.recordButton.setText(tr(TEXT["record"]))
            if state == "done":
                self.recordLabel.setText(tr(TEXT["recordingDone"], count=value))
                setRole(self.recordLabel, "success")
            else:
                self.recordLabel.hide()


class StepRow(QFrame):
    def __init__(self, section, index, step):
        super().__init__()
        self.section = section
        self.index = index
        self.step = step
        self.setObjectName("stepRow")
        self.setStyleSheet("QFrame#stepRow { background: rgba(255,255,255,0.035); border: 1px solid rgba(255,255,255,0.06); "
                           "border-radius: 12px; }")
        outerLayout = QVBoxLayout(self)
        outerLayout.setContentsMargins(10, 6, 6, 8)
        outerLayout.setSpacing(4)
        layout = QHBoxLayout()
        layout.setSpacing(8)
        outerLayout.addLayout(layout)
        numberLabel = makeLabel(str(index + 1), "faint")
        numberLabel.setFixedWidth(22)
        numberLabel.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(numberLabel)
        layout.addWidget(IconWidget(logic.STEP_ICONS[step["type"]], "accent", 18))
        layout.addWidget(makeLabel(tr(logic.STEP_NAMES[step["type"]]), "muted"))
        layout.addStretch(1)
        upButton = iconButton("chevron-up", tr(TEXT["moveUp"]), "muted", 15)
        upButton.clicked.connect(lambda: section.moveStep(index, -1))
        downButton = iconButton("chevron-down", tr(TEXT["moveDown"]), "muted", 15)
        downButton.clicked.connect(lambda: section.moveStep(index, 1))
        moreButton = iconButton("ellipsis", None, "muted", 15)
        moreButton.clicked.connect(lambda: self._menu(moreButton))
        deleteButton = iconButton("trash-2", tr(TEXT["delete"]), "danger", 15)
        deleteButton.clicked.connect(lambda: section.removeStep(index))
        for button in (upButton, downButton, moreButton, deleteButton):
            layout.addWidget(button)
        self.controls = QHBoxLayout()
        self.controls.setContentsMargins(56, 0, 4, 0)
        self.controls.setSpacing(6)
        outerLayout.addLayout(self.controls)
        self.extraLine = QHBoxLayout()
        self.extraLine.setContentsMargins(56, 0, 4, 0)
        self.extraLine.setSpacing(6)
        outerLayout.addLayout(self.extraLine)
        self._buildControls()

    def _menu(self, button):
        menu = QMenu(self)
        menu.addAction(tr(TEXT["duplicate"]), lambda: self.section.duplicateStep(self.index))
        insertMenu = menu.addMenu(tr(TEXT["insertBelow"]))
        for stepType in logic.STEP_TYPES:
            insertMenu.addAction(tr(logic.STEP_NAMES[stepType]),
                                 lambda value=stepType: self.section.addStep(value, self.index + 1))
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def set(self, **fields):
        self.step.update(fields)
        self.section.commit()

    def _buildControls(self):
        step = self.step
        stepType = step["type"]
        controls = self.controls
        if stepType == "key":
            keyButton = KeyCaptureButton(step.get("vk", 0x45), step.get("mods", []))
            keyButton.changed.connect(lambda virtualKey, mods: self.set(vk=virtualKey, mods=mods))
            controls.addWidget(keyButton)
            specialButton = iconButton("chevron-down", tr(T("Tasti speciali", "Special keys")), "muted", 14)
            specialButton.clicked.connect(lambda: self._specialMenu(specialButton, keyButton))
            controls.addWidget(specialButton)
            actionCombo = QComboBox()
            for actionId, label in logic.KEY_ACTIONS.items():
                actionCombo.addItem(tr(label).capitalize(), actionId)
            actionCombo.setCurrentIndex(max(0, actionCombo.findData(step.get("action", "tap"))))
            actionCombo.currentIndexChanged.connect(lambda _index: self.set(action=actionCombo.currentData()))
            controls.addWidget(actionCombo)
            controls.addStretch(1)
        elif stepType == "text":
            textEdit = QLineEdit(step.get("text", ""))
            textEdit.setPlaceholderText(tr(TEXT["textPlaceholder"]))
            textEdit.textEdited.connect(lambda text: self.set(text=text))
            controls.addWidget(textEdit, 1)
        elif stepType == "click":
            buttonCombo = QComboBox()
            for buttonId in ("left", "right", "middle", "x1", "x2"):
                buttonCombo.addItem(tr(logic.BUTTON_SHORT[buttonId]).capitalize(), buttonId)
            buttonCombo.setCurrentIndex(max(0, buttonCombo.findData(step.get("button", "left"))))
            buttonCombo.currentIndexChanged.connect(lambda _index: self.set(button=buttonCombo.currentData()))
            controls.addWidget(buttonCombo)
            actionCombo = QComboBox()
            for actionId, label in logic.CLICK_ACTIONS.items():
                actionCombo.addItem(tr(label).capitalize(), actionId)
            actionCombo.setCurrentIndex(max(0, actionCombo.findData(step.get("action", "click"))))
            actionCombo.currentIndexChanged.connect(lambda _index: self.set(action=actionCombo.currentData()))
            controls.addWidget(actionCombo)
            positionChip = makeButton(tr(TEXT["atPosition"]), "crosshair", "chip", checkable=True)
            positionChip.setChecked(bool(step.get("atPosition")))
            controls.addWidget(positionChip)
            controls.addStretch(1)
            pointHost = self._pointControls(step)
            pointHost.setVisible(bool(step.get("atPosition")))
            positionChip.toggled.connect(lambda checked: (self.set(atPosition=checked), pointHost.setVisible(checked)))
            self.extraLine.addWidget(pointHost)
            self.extraLine.addStretch(1)
        elif stepType == "move":
            relativeChip = makeButton(tr(TEXT["relative"]), "move", "chip", checkable=True)
            relativeChip.setChecked(bool(step.get("relative")))
            relativeChip.toggled.connect(lambda checked: self.set(relative=checked))
            controls.addWidget(self._pointControls(step, allowNegative=True))
            controls.addWidget(relativeChip)
            controls.addStretch(1)
        elif stepType == "scroll":
            amountSpin = spinBox(-100, 100, step.get("amount", -3), "", 1, 90)
            amountSpin.valueChanged.connect(lambda value: (self.set(amount=value), directionLabel.setText(directionText(value))))

            def directionText(value):
                return tr(T("scatti su", "notches up")) if value > 0 else tr(T("scatti giù", "notches down"))

            directionLabel = makeLabel(directionText(step.get("amount", -3)), "muted")
            controls.addWidget(amountSpin)
            controls.addWidget(directionLabel)
            controls.addStretch(1)
        elif stepType == "wait":
            waitSpin = spinBox(0, 3600000, step.get("ms", 500), " ms", 50, 120)
            waitSpin.valueChanged.connect(lambda value: self.set(ms=value))
            controls.addWidget(waitSpin)
            controls.addWidget(makeLabel(tr(TEXT["random"]), "muted"))
            randomSpin = spinBox(0, 600000, step.get("randomMs", 0), " ms", 10, 110)
            randomSpin.valueChanged.connect(lambda value: self.set(randomMs=value))
            controls.addWidget(randomSpin)
            controls.addStretch(1)
        elif stepType == "run":
            pathEdit = QLineEdit(step.get("path", ""))
            pathEdit.setPlaceholderText(tr(TEXT["pathPlaceholder"]))
            pathEdit.textEdited.connect(lambda text: self.set(path=text))
            controls.addWidget(pathEdit, 1)
            browseButton = makeButton(tr(TEXT["browse"]), "folder-open", "ghost")
            browseButton.clicked.connect(lambda: self._browse(pathEdit))
            controls.addWidget(browseButton)

    def _pointControls(self, step, allowNegative=False):
        host = QWidget()
        hostLayout = QHBoxLayout(host)
        hostLayout.setContentsMargins(0, 0, 0, 0)
        hostLayout.setSpacing(4)
        minimum = -100000 if allowNegative else -20000
        xSpin = spinBox(minimum, 100000, step.get("x", 0), "", 1, 80)
        ySpin = spinBox(minimum, 100000, step.get("y", 0), "", 1, 80)
        xSpin.setPrefix("x ")
        ySpin.setPrefix("y ")
        xSpin.valueChanged.connect(lambda value: self.set(x=value))
        ySpin.valueChanged.connect(lambda value: self.set(y=value))
        pickButton = iconButton("crosshair", tr(TEXT["pickPoint"]), "accent", 15)

        def picked(x, y):
            if step.get("relative"):
                return
            xSpin.setValue(x)
            ySpin.setValue(y)

        pickButton.clicked.connect(lambda: PointPicker.pick(self.section.plugin, picked))
        for widget in (xSpin, ySpin, pickButton):
            hostLayout.addWidget(widget)
        return host

    def _specialMenu(self, button, keyButton):
        menu = QMenu(self)
        for virtualKey, label in SPECIAL_KEYS:
            menu.addAction(label, lambda value=virtualKey: keyButton.setSpecial(value))
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _browse(self, pathEdit):
        path, _ = QFileDialog.getOpenFileName(self, tr(TEXT["browse"]))
        if path:
            pathEdit.setText(path)
            self.set(path=path)


# ---------------------------------------------------------------------------------------------------------------
class ClickerSection(Card):
    def __init__(self, plugin, macroId):
        super().__init__(padding=18, hoverable=False)
        self.plugin = plugin
        self.macroId = macroId
        clicker = plugin.find(macroId)["clicker"]
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(IconWidget("mouse-pointer-click", "muted", 18))
        header.addWidget(makeLabel(tr(TEXT["clickerTitle"]).upper(), "section"))
        header.addStretch(1)
        layout.addLayout(header)

        self.buttonChips = ChipGroup([(buttonId, tr(logic.BUTTON_SHORT[buttonId]).capitalize()) for buttonId in ("left", "right", "middle")],
                                     clicker["button"])
        self.buttonChips.changed.connect(lambda value: value and self.set(button=value))
        layout.addLayout(formRow(TEXT["button"], self.buttonChips))

        speedRow = QHBoxLayout()
        speedRow.setSpacing(10)
        self.cpsSlider = QSlider(Qt.Horizontal)
        self.cpsSlider.setRange(1, 100)
        self.cpsSlider.setValue(int(round(clicker["cps"])))
        self.cpsSlider.setMinimumWidth(220)
        self.cpsSpin = QDoubleSpinBox()
        self.cpsSpin.setRange(0.1, 1000)
        self.cpsSpin.setDecimals(1)
        self.cpsSpin.setValue(float(clicker["cps"]))
        self.cpsSpin.setFixedWidth(80)
        self.cpsSlider.valueChanged.connect(lambda value: self.cpsSpin.setValue(value))
        self.cpsSpin.valueChanged.connect(self._onCps)
        speedRow.addWidget(self.cpsSlider, 1)
        speedRow.addWidget(self.cpsSpin)
        self.everyLabel = makeLabel("", "faint")
        layout.addLayout(formRow(TEXT["cps"], speedRow, stretch=True))
        layout.addWidget(self.everyLabel, 0, Qt.AlignRight)

        randomRow = QHBoxLayout()
        self.randomSlider = QSlider(Qt.Horizontal)
        self.randomSlider.setRange(0, 60)
        self.randomSlider.setValue(int(clicker["randomPercent"]))
        self.randomLabel = makeLabel(f"{int(clicker['randomPercent'])}%", "muted")
        self.randomLabel.setFixedWidth(40)
        self.randomSlider.valueChanged.connect(lambda value: (self.randomLabel.setText(f"{value}%"), self.set(randomPercent=value)))
        randomRow.addWidget(self.randomSlider, 1)
        randomRow.addWidget(self.randomLabel)
        layout.addLayout(formRow(TEXT["randomness"], randomRow, TEXT["randomnessHint"], stretch=True))

        self.doubleSwitch = ToggleSwitch(bool(clicker["double"]))
        self.doubleSwitch.toggled.connect(lambda checked: self.set(double=checked))
        layout.addLayout(formRow(TEXT["double"], self.doubleSwitch))
        self.holdSpin = spinBox(0, 2000, clicker["holdMs"], " ms", 5, 100)
        self.holdSpin.valueChanged.connect(lambda value: self.set(holdMs=value))
        layout.addLayout(formRow(TEXT["holdMs"], self.holdSpin))
        layout.addWidget(divider())

        self.positionChips = ChipGroup([("cursor", tr(TEXT["atCursor"])), ("fixed", tr(TEXT["fixedPoint"]))],
                                       clicker["position"])
        self.positionChips.changed.connect(self._onPosition)
        layout.addLayout(formRow(TEXT["where"], self.positionChips))
        self.pointHost = QWidget()
        pointLayout = QHBoxLayout(self.pointHost)
        pointLayout.setContentsMargins(0, 0, 0, 0)
        pointLayout.addStretch(1)
        self.xSpin = spinBox(-20000, 100000, clicker["x"], "", 1, 90)
        self.ySpin = spinBox(-20000, 100000, clicker["y"], "", 1, 90)
        self.xSpin.setPrefix("x ")
        self.ySpin.setPrefix("y ")
        self.xSpin.valueChanged.connect(lambda value: self.set(x=value))
        self.ySpin.valueChanged.connect(lambda value: self.set(y=value))
        pickButton = makeButton(tr(TEXT["pickPoint"]), "crosshair")
        pickButton.clicked.connect(lambda: PointPicker.pick(plugin, self._picked))
        for widget in (self.xSpin, self.ySpin, pickButton):
            pointLayout.addWidget(widget)
        layout.addWidget(self.pointHost)
        layout.addWidget(divider())

        self.limitChips = ChipGroup([("none", tr(TEXT["noLimit"])), ("clicks", tr(TEXT["afterClicks"])),
                                     ("seconds", tr(TEXT["afterSeconds"]))], clicker["limit"])
        self.limitChips.changed.connect(self._onLimit)
        layout.addWidget(makeLabel(tr(TEXT["limit"])))
        layout.addWidget(self.limitChips)
        self.limitSpin = spinBox(1, 10000000, clicker["limitValue"], "", 1, 130)
        self.limitSpin.valueChanged.connect(lambda value: self.set(limitValue=value))
        limitRow = QHBoxLayout()
        limitRow.addStretch(1)
        limitRow.addWidget(self.limitSpin)
        self.limitHost = QWidget()
        self.limitHost.setLayout(limitRow)
        layout.addWidget(self.limitHost)
        self._refresh()

    def set(self, **fields):
        self.plugin.updateClicker(self.macroId, **fields)

    def _onCps(self, value):
        self.set(cps=round(value, 1))
        self.cpsSlider.blockSignals(True)
        self.cpsSlider.setValue(int(round(min(100, max(1, value)))))
        self.cpsSlider.blockSignals(False)
        self._refresh()

    def _onPosition(self, value):
        if value:
            self.set(position=value)
        self._refresh()

    def _onLimit(self, value):
        if value:
            self.set(limit=value)
        self._refresh()

    def _picked(self, x, y):
        self.xSpin.setValue(x)
        self.ySpin.setValue(y)
        self.positionChips.setValue("fixed")
        self.set(position="fixed")
        self._refresh()

    def _refresh(self):
        clicker = self.plugin.find(self.macroId)["clicker"]
        self.everyLabel.setText(tr(TEXT["every"], ms=int(round(1000.0 / max(0.1, float(clicker["cps"]))))))
        self.pointHost.setVisible(clicker["position"] == "fixed")
        self.limitHost.setVisible(clicker["limit"] != "none")
        self.limitSpin.setSuffix(tr(T(" clic", " clicks")) if clicker["limit"] == "clicks" else " s")


# ---------------------------------------------------------------------------------------------------------------
class PointPicker(QWidget):
    """Dark veil over every screen: click to pick a point (physical pixels, like the macro uses)."""
    active = []

    @classmethod
    def pick(cls, plugin, callback):
        for window in cls.active:
            window.close()
        cls.active = [cls(plugin, callback, screen) for screen in QGuiApplication.screens()]
        for window in cls.active:
            window.show()
            window.raise_()
        if cls.active:
            cls.active[0].activateWindow()

    def __init__(self, plugin, callback, screen):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.plugin = plugin
        self.callback = callback
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setCursor(Qt.CrossCursor)
        self.setGeometry(screen.geometry())
        self.setFocusPolicy(Qt.StrongFocus)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 90))
        font = QFont(self.font())
        font.setPixelSize(18)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(self.rect().adjusted(0, 60, 0, 0), Qt.AlignHCenter | Qt.AlignTop, tr(TEXT["pickPointHint"]))

    def _closeAll(self):
        for window in list(PointPicker.active):
            window.close()
        PointPicker.active = []

    def mousePressEvent(self, event):
        x, y = physicalCursor(self.plugin)
        callback = self.callback
        self._closeAll()
        callback(int(x), int(y))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._closeAll()


class RecordingIndicator(QWidget):
    """Small bar on top of the screen while recording (clicks on it are not recorded)."""

    def __init__(self, plugin):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.plugin = plugin
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 10, 10, 10)
        layout.setSpacing(10)
        self.dot = QWidget()
        self.dot.setFixedSize(12, 12)
        layout.addWidget(self.dot)
        self.label = makeLabel("", None)
        self.label.setStyleSheet("color: white; font-weight: 600;")
        layout.addWidget(self.label)
        hint = makeLabel(tr(TEXT["stopHint"], hotkey=stopHotkeyText(plugin)), None)
        hint.setStyleSheet("color: rgba(255,255,255,0.6);")
        layout.addWidget(hint)
        stopButton = makeButton(tr(TEXT["stop"]), "square", "danger")
        stopButton.clicked.connect(lambda: plugin.stopRecording())
        layout.addWidget(stopButton)
        self.blink = False
        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self._tick()
        self.adjustSize()
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - self.width() // 2, screen.top() + 14)

    def _tick(self):
        recording = self.plugin.recording
        if recording is None:
            return
        self.blink = not self.blink
        self.dot.setStyleSheet(f"background: {'#F87171' if self.blink else '#7F1D1D'}; border-radius: 6px;")
        seconds = int(time.monotonic() - recording.startedAt)
        actions = sum(1 for event in recording.events if event["kind"] != "move" and event.get("down", True))
        self.label.setText(f"{tr(TEXT['recordingNow'])}  {seconds // 60}:{seconds % 60:02d}  ·  "
                           f"{tr(TEXT['actions'], count=actions)}")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.fillPath(roundedPath(rect, rect.height() / 2), QColor(17, 19, 31, 235))
        painter.setPen(QPen(QColor(248, 113, 113, 160), 1.5))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)


# ---------------------------------------------------------------------------------------------------------------
class MacrosHomeWidget(QWidget):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.rowsLayout = QVBoxLayout()
        self.rowsLayout.setSpacing(4)
        layout.addLayout(self.rowsLayout)
        layout.addStretch(1)
        plugin.macrosChanged.connect(self.refresh)
        plugin.runStateChanged.connect(self.refresh)
        self.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh()

    def refresh(self, *args):
        clearLayout(self.rowsLayout)
        capacity = max(1, self.height() // 34)
        macros = self.plugin.macros[:capacity]
        if not macros:
            self.rowsLayout.addWidget(makeLabel(tr(TEXT["emptyTitle"]), "faint"))
        for macro in macros:
            rowLayout = QHBoxLayout()
            rowLayout.setSpacing(8)
            rowLayout.addWidget(IconWidget(macro.get("icon") or "zap", QColor(macro.get("color") or ITEM_COLORS[0]), 16))
            nameLabel = makeLabel(macroTitle(macro), None if macro.get("enabled") else "faint")
            rowLayout.addWidget(nameLabel, 1)
            if macro.get("trigger"):
                rowLayout.addWidget(makeLabel(logic.triggerText(macro["trigger"]), "chip"))
            running = self.plugin.isMacroRunning(macro["id"])
            button = iconButton("square" if running else "play", tr(TEXT["stop"] if running else TEXT["test"]),
                                "danger" if running else "muted", 14)
            button.clicked.connect(lambda checked=False, macroId=macro["id"]: self.plugin.toggleMacro(macroId))
            rowLayout.addWidget(button)
            self.rowsLayout.addLayout(rowLayout)
