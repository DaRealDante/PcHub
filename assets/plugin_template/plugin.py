"""PC Hub plugin template.

Copy this folder to %APPDATA%\\PC Hub\\plugins\\<your_id>\\ (or zip it and use Plugins > Install from .zip),
rename pluginId, then restart PC Hub. Everything below is optional except pluginId/name and class Plugin.
"""
import time

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from pchub.core.i18n import T, tr
from pchub.core.plugin_api import ActiveItem, HomeWidgetSpec, PluginBase, TrayEntry
from pchub.core.settings_schema import (ActionButton, Choice, HotkeySetting, Section, Slider, TextInput, Toggle)
from pchub.ui.widgets import Card, IconTile, makeButton, makeLabel


class TemplatePlugin(PluginBase):
    pluginId = "plugin_template"
    name = T("Plugin di esempio", "Example plugin")
    description = T("Mostra tutto quello che un plugin può fare.", "Shows everything a plugin can do.")
    icon = "sparkles"
    version = "1.0.0"
    author = "Ken"
    requiresAdmin = False
    restartable = True

    # The core builds the settings UI, tray pins and hotkeys from this list.
    settingsSchema = [
        Section(T("Generale", "General")),
        Toggle("greet", T("Saluta all'avvio", "Greet on start"), True, icon="smile"),
        Slider("speed", T("Velocità", "Speed"), 1, 10, 5, suffix="x", icon="gauge"),
        Choice("mood", T("Umore", "Mood"), [("happy", T("Felice", "Happy")), ("calm", T("Calmo", "Calm"))], "happy"),
        TextInput("message", T("Messaggio", "Message"), "Ciao!", icon="pencil"),
        HotkeySetting("hotkey", T("Hotkey saluto", "Greeting hotkey"), action="sayHello", icon="keyboard"),
        ActionButton("hello", T("Saluta ora", "Say hello now"), action="sayHello", buttonText=T("Saluta", "Greet")),
    ]

    counterChanged = Signal(int)

    def __init__(self, context):
        super().__init__(context)
        self.counter = context.getData("counter", 0)
        self.ticker = QTimer(self)
        self.ticker.setInterval(1000)
        self.ticker.timeout.connect(self._tick)

    # engine: runs in background from app launch, even with the window hidden
    def start(self):
        if self.setting("greet"):
            self.context.notify(tr(self.name), self.setting("message"))
        self.ticker.start()

    def stop(self):
        self.ticker.stop()
        self.context.setData("counter", self.counter)

    def _tick(self):
        self.counter += int(self.setting("speed") or 1)
        self.counterChanged.emit(self.counter)
        self.context.setActive(ActiveItem("counter", tr(self.name), f"{self.counter}", icon=self.icon,
                                          actions=[(T("Azzera", "Reset"), "rotate-ccw", self.reset)]))

    def reset(self):
        self.counter = 0
        self.counterChanged.emit(0)

    def sayHello(self):
        if self.context.confirm(tr(T("Salutare?", "Say hello?")), self.setting("message")):
            self.context.notify(tr(self.name), self.setting("message"), "notify")

    def onSettingChanged(self, key, value):
        self.context.log.info("setting %s -> %s", key, value)

    # ui: built once at launch and kept in memory
    def createPage(self):
        return TemplatePage(self)

    def homeWidgets(self):
        return [HomeWidgetSpec("plugin_template.counter", T("Contatore", "Counter"), lambda: CounterWidget(self),
                               T("Un contatore che sale da solo.", "A counter that goes up by itself."), self.icon, "small")]

    def trayEntries(self):
        return [TrayEntry("reset", T("Azzera contatore", "Reset counter"), self.reset, icon="rotate-ccw")]


Plugin = TemplatePlugin


class CounterWidget(QWidget):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.valueLabel = makeLabel(str(plugin.counter), "metric")
        layout.addWidget(self.valueLabel)
        layout.addStretch(1)
        plugin.counterChanged.connect(self._onCounter)

    def _onCounter(self, value):
        self.valueLabel.setText(str(value))


class TemplatePage(QWidget):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        card = Card(padding=18)
        cardLayout = QHBoxLayout(card)
        cardLayout.addWidget(IconTile(plugin.icon, 48))
        cardLayout.addWidget(CounterWidget(plugin), 1)
        resetButton = makeButton(tr(T("Azzera", "Reset")), "rotate-ccw", "primary")
        resetButton.clicked.connect(plugin.reset)
        cardLayout.addWidget(resetButton)
        layout.addWidget(card)
