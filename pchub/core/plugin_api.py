"""Public API for PC Hub plugins.

A plugin is a folder with a plugin.py that defines `class Plugin(PluginBase)`.
- The "engine" (start/stop) runs in the background from app launch, even with the window hidden.
- The page (createPage) is built once at launch and kept in memory, so opening it is instant.
- settingsSchema declares plugin-specific settings: the core builds their UI, tray pins and hotkeys.
"""
import threading
import traceback

from PySide6.QtCore import QObject

from pchub.core.active_registry import ActiveItem
from pchub.core.i18n import tr

__all__ = ["PluginBase", "HomeWidgetSpec", "TrayEntry", "ActiveItem", "WidgetSizes", "CalendarItem"]


class WidgetSizes:
    SMALL = "small"
    WIDE = "wide"
    TALL = "tall"
    LARGE = "large"
    FULL = "full"
    spans = {"small": (1, 1), "wide": (2, 1), "tall": (1, 2), "large": (2, 2), "full": (4, 1)}
    order = ["small", "wide", "tall", "large", "full"]


class HomeWidgetSpec:
    def __init__(self, typeId, name, factory, description=None, icon="layout-grid", defaultSize="small", sizes=None):
        self.typeId = typeId
        self.name = name
        self.factory = factory
        self.description = description
        self.icon = icon
        self.defaultSize = defaultSize
        self.sizes = list(sizes or WidgetSizes.order)
        if self.defaultSize not in self.sizes:
            self.sizes.insert(0, self.defaultSize)
        self.pluginId = None


class TrayEntry:
    """Extra pinnable action that isn't a setting (e.g. "Start a 5 min timer")."""

    def __init__(self, entryId, label, callback, kind="action", checkedGetter=None, icon=None):
        self.entryId = entryId
        self.label = label
        self.callback = callback
        self.kind = kind
        self.checkedGetter = checkedGetter
        self.icon = icon


class CalendarItem:
    """Something a plugin wants to show on the calendar (reminder, deadline, to-do, event…).

    start/end are datetime objects; allDay items ignore the time. onOpen() is called when the user clicks it.
    """

    def __init__(self, itemId, title, start, end=None, allDay=False, icon=None, color=None, subtitle="", done=False,
                 onOpen=None, kind="event"):
        self.itemId = itemId
        self.title = title
        self.start = start
        self.end = end
        self.allDay = allDay
        self.icon = icon
        self.color = color
        self.subtitle = subtitle
        self.done = done
        self.onOpen = onOpen
        self.kind = kind
        self.pluginId = None


class PluginBase(QObject):
    pluginId = ""
    name = {"it": "Plugin", "en": "Plugin"}
    description = {"it": "", "en": ""}
    icon = "puzzle"
    version = "1.0.0"
    author = "PC Hub"
    requiresAdmin = False
    restartable = True
    settingsSchema = []
    settingsInPage = False            # True = the page shows its own settings form (not repeated under the gear)

    def __init__(self, context):
        super().__init__()
        self.context = context

    # lifecycle ----------------------------------------------------------
    def start(self):
        pass

    def stop(self):
        pass

    def createPage(self):
        """Return the plugin's main page widget, or None to show only its settings form."""
        return None

    def homeWidgets(self):
        return []

    def trayEntries(self):
        return []

    def automationTriggers(self):
        return []

    def automationActions(self):
        return []

    def onSettingChanged(self, key, value):
        pass

    def calendarItems(self, startDate, endDate):
        """[CalendarItem] between two dates (inclusive). Call context.notifyCalendarChanged() when they change."""
        return []

    # helpers ------------------------------------------------------------
    def setting(self, key):
        return self.context.getSetting(key)

    def setSetting(self, key, value):
        self.context.setSetting(key, value)

    def tr(self, textKey, **formatArgs):
        return tr(textKey, **formatArgs)

    def isRunning(self):
        return self.context.status() == "running"

    def runInThread(self, function, *args, name=None, **kwargs):
        """Run function in a daemon thread; crashes are reported to the core."""

        def guardedRun():
            try:
                function(*args, **kwargs)
            except Exception as error:
                self.context.reportError(error, traceback.format_exc())

        workerThread = threading.Thread(target=guardedRun, name=name or f"{self.pluginId}-worker", daemon=True)
        workerThread.start()
        return workerThread
