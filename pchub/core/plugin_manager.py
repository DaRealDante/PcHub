import importlib
import importlib.util
import importlib.machinery
import shutil
import sys
import tempfile
import time
import traceback
import types
import zipfile
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from pchub.core import system
from pchub.core.i18n import tr
from pchub.core.logger import getLogger
from pchub.core.paths import userPluginsDir, pluginSettingsFile, pluginDataDir
from pchub.core.plugin_api import PluginBase
from pchub.core.settings_schema import HotkeySetting, schemaDefaults, findSetting
from pchub.core.storage import JsonStore, flushAllStores

log = getLogger("plugins")

GLOBAL_DEFAULTS = {
    "enabled": True,
    "openHotkey": "",
    "separateWindow": False,
    "alwaysOnTop": False,
    "showInActive": True,
    "autoRestart": True,
    "customName": "",
    "customIcon": "",
    "hidden": False,
    "windowGeometry": "",
}


class _FreshSourceLoader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        # A quick edit can retain both timestamp and size: never reuse its pyc.
        return self.source_to_code(self.get_data(self.path), self.path)


class _FreshPluginFinder:
    def __init__(self, packageName):
        self.packageName = packageName

    def find_spec(self, fullname, path=None, target=None):
        if fullname != self.packageName and not fullname.startswith(self.packageName + "."):
            return None
        # Respect update overlays and frozen-app importers already installed.
        for finder in list(sys.meta_path):
            if isinstance(finder, _FreshPluginFinder) or not hasattr(finder, "find_spec"):
                continue
            spec = finder.find_spec(fullname, path, target)
            if spec is not None:
                if spec.origin and spec.origin.endswith(".py") and Path(spec.origin).is_file():
                    spec.loader = _FreshSourceLoader(fullname, spec.origin)
                return spec
        return None


def _enableFreshPluginImports(packageName):
    # Keep this scoped finder for lazy imports from pages or later actions, too.
    importlib.invalidate_caches()
    if not any(isinstance(finder, _FreshPluginFinder) and finder.packageName == packageName for finder in sys.meta_path):
        sys.meta_path.insert(0, _FreshPluginFinder(packageName))


def _forgetPluginModules(packageName):
    sys.meta_path[:] = [finder for finder in sys.meta_path
                       if not (isinstance(finder, _FreshPluginFinder) and finder.packageName == packageName)]
    for name in list(sys.modules):
        if name == packageName or name.startswith(packageName + "."):
            sys.modules.pop(name, None)
    parentName, _, childName = packageName.rpartition(".")
    parent = sys.modules.get(parentName)
    if parent is not None and hasattr(parent, childName):
        delattr(parent, childName)


class PluginRecord:
    def __init__(self, pluginId, pluginClass=None, builtin=True, folderPath=None, moduleName=None):
        self.pluginId = pluginId
        self.pluginClass = pluginClass
        self.builtin = builtin
        self.folderPath = folderPath
        self.moduleName = moduleName
        self.instance = None
        self.context = None
        self.settingsStore = None
        self.status = "loading"
        self.error = ""
        self.errorDetails = ""
        self.restartTimes = []
        self.widgetSpecs = []
        self.trayEntries = []
        self.dormant = False
        self.safeMode = False

    @property
    def schema(self):
        return list(getattr(self.pluginClass, "settingsSchema", []) or []) if self.pluginClass else []

    @property
    def installed(self):
        return self.status != "uninstalled"


class PluginContext:
    """What a plugin receives. Every interaction with the core goes through here."""

    def __init__(self, manager, record):
        self.manager = manager
        self.record = record
        self.pluginId = record.pluginId
        self.log = getLogger(f"plugin.{record.pluginId}")
        self.dataDir = pluginDataDir(record.pluginId)
        self.retired = False

    def _isCurrent(self):
        return not self.retired and self.manager.records.get(self.pluginId) is self.record

    def getSetting(self, key):
        return self.manager.getSetting(self.pluginId, key)

    def setSetting(self, key, value):
        if self._isCurrent():
            self.manager.setSetting(self.pluginId, key, value)

    def getData(self, key, default=None):
        return self.record.settingsStore.get(f"data.{key}", default)

    def setData(self, key, value):
        if self._isCurrent():
            self.record.settingsStore.set(f"data.{key}", value)

    def setActive(self, item):
        if self._isCurrent():
            self.manager.activeRegistry.setItem(self.pluginId, item)

    def removeActive(self, itemId):
        if self._isCurrent():
            self.manager.activeRegistry.removeItem(self.pluginId, itemId)

    def clearActive(self):
        if self._isCurrent():
            self.manager.activeRegistry.clearPlugin(self.pluginId)

    def notify(self, title, message="", sound=None):
        if self._isCurrent():
            self.manager.notifyHandler(title, message, sound)

    def confirm(self, title, message, details=None, danger=False, confirmText=None, icon=None):
        return self.manager.confirmHandler(title, message, details or [], danger, confirmText, icon)

    def reportError(self, error, tracebackText=""):
        if self._isCurrent():
            self.manager.contextErrorReported.emit(self, f"{type(error).__name__}: {error}", tracebackText)

    def status(self):
        return "stopped" if self.retired else self.record.status

    def isAdmin(self):
        return self.manager.isAdmin()

    def emit(self, eventName, **payload):
        if self._isCurrent():
            self.manager.events.emit(f"{self.pluginId}.{eventName}", **payload)

    @property
    def events(self):
        return self.manager.events

    def openPage(self):
        if self._isCurrent():
            self.manager.openPageHandler(self.pluginId, False)

    def displayName(self):
        return self.manager.displayName(self.pluginId)

    def alert(self, title, message="", icon="bell", actions=None, timeoutSeconds=0, accent=None, sound=None):
        """Always-on-top alert card (bottom-right). actions = [(label, callback[, icon])]; last one is primary."""
        if self._isCurrent():
            return self.manager.alertHandler(title, message, icon, actions, timeoutSeconds, accent, sound)

    def notifyCalendarChanged(self):
        if self._isCurrent():
            self.manager.events.emit("core.calendarChanged", pluginId=self.pluginId)

    def plugin(self, pluginId):
        """Another plugin's instance if installed and running (for integrations), else None."""
        record = self.manager.records.get(pluginId)
        if record and record.instance is not None and record.status == "running":
            return record.instance
        return None

    def createSettingsForm(self, schema=None):
        """A ready-made settings form (same as the gear one) to embed in the plugin page. None outside the app."""
        factory = self.manager.settingsFormFactory
        if factory is None:
            return None
        return factory(self.pluginId, list(schema if schema is not None else self.record.schema))

    def allPlugins(self):
        """Instances of the other running plugins (for integrations such as the calendar)."""
        return [record.instance for record in self.manager.installedRecords()
                if record.instance is not None and record.status == "running"]


class PluginManager(QObject):
    statusChanged = Signal(str)
    pluginsChanged = Signal()
    settingChanged = Signal(str, str, object)
    globalSettingChanged = Signal(str, str, object)
    hotkeyStatusChanged = Signal(str)
    errorReported = Signal(str, str, str)
    contextErrorReported = Signal(object, str, str)

    def __init__(self, appStore, activeRegistry, events, hotkeys, isAdminFunction=None, parent=None):
        super().__init__(parent)
        self.appStore = appStore
        self.activeRegistry = activeRegistry
        self.events = events
        self.hotkeys = hotkeys
        self.isAdmin = isAdminFunction or system.isAdmin
        self.records = {}
        self.order = []
        self.hotkeyStatus = {}
        self.notifyHandler = lambda title, message, sound=None: log.info("notify: %s %s", title, message)
        self.confirmHandler = lambda *args: False
        self.openPageHandler = lambda pluginId, viaHotkey=False: None
        self.settingsFormFactory = None
        self.alertHandler = lambda title, message="", iconName="bell", actions=None, timeoutSeconds=0, accent=None, sound=None: \
            log.info("alert: %s %s", title, message)
        self.errorReported.connect(self._handleError)
        self.contextErrorReported.connect(self._handleContextError)
        self.activeRegistry.visibilityChecker = lambda pluginId: bool(self.globalSetting(pluginId, "showInActive"))

    # discovery -----------------------------------------------------------
    def discover(self, includeUser=True, safeMode=False):
        """safeMode: user plugins are listed but not loaded (used after a crash at startup).
        A user plugin switched off by the user is never imported either, so a broken one can't hurt."""
        from pchub.core.plugin_updates import activeUpdates
        from pchub.plugins import BUILTIN_PLUGINS
        uninstalledIds = set(self.appStore.get("plugins.__uninstalled", []))
        moduleNames = list(BUILTIN_PLUGINS)
        for pluginId in sorted(activeUpdates):
            moduleName = f"pchub.plugins.{pluginId}.plugin"
            if moduleName not in moduleNames:
                moduleNames.append(moduleName)
        for moduleName in moduleNames:
            self._discoverModule(moduleName, uninstalledIds)
        if includeUser:
            for folderPath in self.userPluginFolders():
                if folderPath.name in self.records:
                    continue
                if safeMode or self.globalSetting(folderPath.name, "enabled") is False:
                    self._addDormantRecord(folderPath, safeMode)
                else:
                    self._discoverUserFolder(folderPath)

    @staticmethod
    def userPluginFolders():
        return [folderPath for folderPath in sorted(userPluginsDir().iterdir(), key=lambda path: path.name.lower())
                if folderPath.is_dir() and (folderPath / "plugin.py").exists()]

    def _addDormantRecord(self, folderPath, safeMode=False):
        record = PluginRecord(folderPath.name, None, False, folderPath, None)
        record.status = "disabled"
        record.dormant = True
        record.safeMode = safeMode
        self._addRecord(record)
        return record

    def loadDormant(self, pluginId):
        """Imports, creates and starts a user plugin that was not loaded (disabled / safe mode / failed import)."""
        record = self.records.get(pluginId)
        if record is None or record.builtin or record.folderPath is None:
            return None
        position = self.order.index(pluginId)
        del self.records[pluginId]
        self.order.remove(pluginId)
        newRecord = self._discoverUserFolder(Path(record.folderPath))
        self.order.remove(newRecord.pluginId)
        self.order.insert(position, newRecord.pluginId)
        if newRecord.pluginClass is not None:
            self.instantiate(newRecord)
            self.startPlugin(newRecord.pluginId)
        self.pluginsChanged.emit()
        return newRecord

    def rescanUserPlugins(self):
        """Loads plugin folders added while the app is running. Returns the new records."""
        added = []
        for folderPath in self.userPluginFolders():
            known = any(record.folderPath and Path(record.folderPath) == folderPath for record in self.records.values())
            if known or folderPath.name in self.records:
                continue
            record = self._discoverUserFolder(folderPath)
            if record.pluginClass is not None:
                self.instantiate(record)
                self.startPlugin(record.pluginId)
            added.append(record)
        if added:
            self.pluginsChanged.emit()
        return added

    def _discoverModule(self, moduleName, uninstalledIds):
        fallbackId = moduleName.split(".")[-2] if moduleName.endswith(".plugin") else moduleName.split(".")[-1]
        try:
            module = importlib.import_module(moduleName)
            pluginClass = self._findPluginClass(module)
            record = PluginRecord(pluginClass.pluginId, pluginClass, True, None, moduleName)
            if record.pluginId in uninstalledIds:
                record.status = "uninstalled"
        except Exception as error:
            log.exception("Failed to import builtin %s", moduleName)
            record = PluginRecord(fallbackId, None, True, None, moduleName)
            record.status = "error"
            record.error = f"{type(error).__name__}: {error}"
            record.errorDetails = traceback.format_exc()
        self._addRecord(record)

    def _discoverUserFolder(self, folderPath):
        folderId = folderPath.name
        try:
            module, moduleName = self._importUserPlugin(folderPath)
            pluginClass = self._findPluginClass(module)
            if pluginClass.pluginId in self.records:
                raise ValueError(f"duplicate plugin id '{pluginClass.pluginId}'")
            record = PluginRecord(pluginClass.pluginId, pluginClass, False, folderPath, moduleName)
        except Exception as error:
            log.exception("Failed to import user plugin %s", folderPath)
            record = PluginRecord(folderId, None, False, folderPath, None)
            record.status = "error"
            record.error = f"{type(error).__name__}: {error}"
            record.errorDetails = traceback.format_exc()
        self._addRecord(record)
        return record

    def _importUserPlugin(self, folderPath):
        safeName = "".join(character if character.isalnum() else "_" for character in folderPath.name)
        packageName = f"pchub_user_{safeName}_{uuid.uuid4().hex}"
        packageModule = types.ModuleType(packageName)
        packageModule.__path__ = [str(folderPath)]
        sys.modules[packageName] = packageModule
        spec = importlib.util.spec_from_file_location(f"{packageName}.plugin", folderPath / "plugin.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            _enableFreshPluginImports(packageName)
            _FreshSourceLoader(spec.name, str(folderPath / "plugin.py")).exec_module(module)
        except Exception:
            _forgetPluginModules(packageName)
            raise
        return module, spec.name

    @staticmethod
    def _findPluginClass(module):
        pluginClass = getattr(module, "Plugin", None)
        if not (isinstance(pluginClass, type) and issubclass(pluginClass, PluginBase)):
            raise TypeError("plugin.py must define class Plugin(PluginBase)")
        if not pluginClass.pluginId or not str(pluginClass.pluginId).replace("_", "").replace("-", "").isalnum():
            raise ValueError("Plugin.pluginId must be a simple id like 'my_plugin'")
        return pluginClass

    def _addRecord(self, record):
        self.records[record.pluginId] = record
        if record.pluginId not in self.order:
            self.order.append(record.pluginId)

    # lifecycle -----------------------------------------------------------
    def instantiateAll(self, progressCallback=None):
        for index, pluginId in enumerate(list(self.order)):
            record = self.records[pluginId]
            if progressCallback:
                progressCallback(index, len(self.order), record)
            if record.pluginClass and record.status not in ("uninstalled", "error"):
                self.instantiate(record)

    def instantiate(self, record):
        record.context = PluginContext(self, record)
        try:
            if self.appStore.get(f"plugins.{record.pluginId}.knownName") != record.pluginClass.name:
                self.appStore.set(f"plugins.{record.pluginId}.knownName", record.pluginClass.name)
                self.appStore.set(f"plugins.{record.pluginId}.knownIcon", record.pluginClass.icon)
            try:
                defaults = schemaDefaults(record.schema)
            except Exception:
                record.settingsStore = JsonStore(pluginSettingsFile(record.pluginId), defaults={"settings": {}, "data": {}})
                raise
            record.settingsStore = JsonStore(pluginSettingsFile(record.pluginId), defaults={"settings": defaults, "data": {}})
            record.instance = record.pluginClass(record.context)
            record.widgetSpecs = list(record.instance.homeWidgets() or [])
            for spec in record.widgetSpecs:
                spec.pluginId = record.pluginId
            record.trayEntries = list(record.instance.trayEntries() or [])
            record.status = "stopped"
            record.error = ""
        except Exception as error:
            log.exception("Failed to create plugin %s", record.pluginId)
            record.instance = None
            record.status = "error"
            record.error = f"{type(error).__name__}: {error}"
            record.errorDetails = traceback.format_exc()
        self.hotkeys.setOwnerLabel(f"open:{record.pluginId}",
                                   lambda pluginId=record.pluginId: f"{self.displayName(pluginId)} · {tr('plugin.global.openHotkey')}")
        self._bindOpenHotkey(record)
        self.statusChanged.emit(record.pluginId)

    def startAll(self):
        for pluginId in list(self.order):
            record = self.records[pluginId]
            if record.instance is not None:
                self.startPlugin(pluginId)

    def startPlugin(self, pluginId):
        record = self.records.get(pluginId)
        if not record or record.instance is None or record.status == "running":
            return
        if not self.globalSetting(pluginId, "enabled"):
            self._setStatus(record, "disabled")
            return
        if record.pluginClass.requiresAdmin and not self.isAdmin():
            self._setStatus(record, "blocked")
            return
        try:
            record.instance.start()
            record.error = ""
            self._setStatus(record, "running")
            self._bindPluginHotkeys(record)
            try:
                self.events.registerPluginAutomation(pluginId, record.instance.automationTriggers() or [],
                                                     record.instance.automationActions() or [])
            except Exception:
                log.exception("Automation registration failed for %s", pluginId)
            self.events.emit("core.pluginStarted", pluginId=pluginId)
        except Exception as error:
            log.exception("Plugin %s failed to start", pluginId)
            record.error = f"{type(error).__name__}: {error}"
            record.errorDetails = traceback.format_exc()
            self._safeStop(record)
            self._setStatus(record, "error")
            self._scheduleAutoRestart(record)

    def stopPlugin(self, pluginId, newStatus="stopped"):
        record = self.records.get(pluginId)
        if not record or record.instance is None:
            return
        wasRunning = record.status == "running"
        if wasRunning:
            self._safeStop(record)
            self.events.emit("core.pluginStopped", pluginId=pluginId)
        self._setStatus(record, newStatus)

    def _safeStop(self, record):
        self.hotkeys.unbindPrefix(f"plugin:{record.pluginId}:")
        self.events.unregisterPluginAutomation(record.pluginId)
        try:
            record.instance.stop()
        except Exception:
            log.exception("Plugin %s failed to stop cleanly", record.pluginId)
        self.activeRegistry.clearPlugin(record.pluginId)

    def restartPlugin(self, pluginId):
        record = self.records.get(pluginId)
        if not record or not record.installed or (record.pluginClass and not record.pluginClass.restartable):
            return False
        if record.instance is not None:
            if record.status != "error":
                self._safeStop(record)
            for timer in record.instance.findChildren(QTimer):
                timer.stop()
        if record.context:
            record.context.retired = True
        flushAllStores()
        packageName = record.moduleName.rsplit(".", 1)[0] if record.moduleName else None
        if packageName:
            for eventName, callbacks in list(self.events.subscribers.items()):
                for callback in list(callbacks):
                    module = getattr(callback, "__module__", "")
                    if module == packageName or module.startswith(packageName + "."):
                        self.events.unsubscribe(eventName, callback)
            _forgetPluginModules(packageName)
        newRecord = PluginRecord(pluginId, builtin=record.builtin, folderPath=record.folderPath,
                                 moduleName=record.moduleName)
        newRecord.restartTimes = list(record.restartTimes)
        self.records[pluginId] = newRecord
        moduleName = record.moduleName
        try:
            if record.builtin:
                _enableFreshPluginImports(packageName)
                module = importlib.import_module(record.moduleName)
                moduleName = record.moduleName
            else:
                module, moduleName = self._importUserPlugin(Path(record.folderPath))
            pluginClass = self._findPluginClass(module)
            if pluginClass.pluginId != pluginId:
                raise ValueError(f"Reload cannot change plugin id '{pluginId}' to '{pluginClass.pluginId}'")
            newRecord.moduleName = moduleName
            newRecord.pluginClass = pluginClass
            self.instantiate(newRecord)
            self.startPlugin(pluginId)
        except Exception as error:
            log.exception("Failed to reload plugin %s", pluginId)
            if moduleName:
                _forgetPluginModules(moduleName.rsplit(".", 1)[0])
            newRecord.status = "error"
            newRecord.error = f"{type(error).__name__}: {error}"
            newRecord.errorDetails = traceback.format_exc()
            self.statusChanged.emit(pluginId)
        self.pluginsChanged.emit()
        self.events.emit("core.calendarChanged", pluginId=pluginId)
        if record.instance is not None:
            record.instance.deleteLater()
        return newRecord.status == "running"

    def stopAll(self):
        for pluginId in reversed(self.order):
            self.stopPlugin(pluginId)

    def _setStatus(self, record, status):
        record.status = status
        self.statusChanged.emit(record.pluginId)

    def _handleError(self, pluginId, message, details):
        record = self.records.get(pluginId)
        if not record or record.instance is None or record.status != "running":
            return
        log.error("Plugin %s crashed: %s\n%s", pluginId, message, details)
        record.error = message
        record.errorDetails = details
        self._safeStop(record)
        self._setStatus(record, "error")
        self._scheduleAutoRestart(record)

    def _handleContextError(self, context, message, details):
        if context._isCurrent():
            self._handleError(context.pluginId, message, details)

    def _scheduleAutoRestart(self, record):
        if not record.pluginClass or not record.pluginClass.restartable:
            return
        if not self.globalSetting(record.pluginId, "autoRestart"):
            return
        now = time.time()
        record.restartTimes = [stamp for stamp in record.restartTimes if now - stamp < 60]
        if len(record.restartTimes) >= 3:
            log.warning("Plugin %s crashed too often, auto restart paused", record.pluginId)
            return
        record.restartTimes.append(now)
        QTimer.singleShot(3000, lambda: self._autoRestart(record.pluginId, record))

    def _autoRestart(self, pluginId, expectedRecord=None):
        record = self.records.get(pluginId)
        if (record and (expectedRecord is None or record is expectedRecord) and record.status == "error"
                and self.globalSetting(pluginId, "enabled") and self.globalSetting(pluginId, "autoRestart")):
            self.restartPlugin(pluginId)

    # settings ------------------------------------------------------------
    def getSetting(self, pluginId, key):
        record = self.records.get(pluginId)
        if not record or record.settingsStore is None:
            return None
        return record.settingsStore.get(f"settings.{key}")

    def setSetting(self, pluginId, key, value):
        record = self.records.get(pluginId)
        if not record or record.settingsStore is None:
            return
        if record.settingsStore.get(f"settings.{key}") == value:
            return
        record.settingsStore.set(f"settings.{key}", value)
        setting = findSetting(record.schema, key)
        if isinstance(setting, HotkeySetting) and record.status == "running":
            self._bindPluginHotkey(record, setting)
        if record.instance is not None:
            try:
                record.instance.onSettingChanged(key, value)
            except Exception:
                log.exception("onSettingChanged failed for %s.%s", pluginId, key)
        self.settingChanged.emit(pluginId, key, value)

    def globalSetting(self, pluginId, key):
        return self.appStore.get(f"plugins.{pluginId}.{key}", GLOBAL_DEFAULTS.get(key))

    def setGlobalSetting(self, pluginId, key, value):
        if self.globalSetting(pluginId, key) == value:
            return
        self.appStore.set(f"plugins.{pluginId}.{key}", value)
        record = self.records.get(pluginId)
        if key == "enabled" and record:
            if value and record.instance is None and not record.builtin:
                self.loadDormant(pluginId)
                record = self.records.get(pluginId)
            elif value:
                self.startPlugin(pluginId)
            else:
                self.stopPlugin(pluginId, "disabled")
                if record.status != "disabled":
                    self._setStatus(record, "disabled")
        elif key == "openHotkey" and record:
            self._bindOpenHotkey(record)
        elif key == "showInActive":
            self.activeRegistry.changed.emit()
        self.globalSettingChanged.emit(pluginId, key, value)

    def setEnabled(self, pluginId, enabled):
        self.setGlobalSetting(pluginId, "enabled", bool(enabled))

    # hotkeys -------------------------------------------------------------
    def _bindOpenHotkey(self, record):
        owner = f"open:{record.pluginId}"
        sequence = self.globalSetting(record.pluginId, "openHotkey")
        result = self.hotkeys.bind(owner, sequence, lambda pluginId=record.pluginId: self.openPageHandler(pluginId, True))
        self.hotkeyStatus[owner] = result
        self.hotkeyStatusChanged.emit(owner)

    def _bindPluginHotkeys(self, record):
        for setting in record.schema:
            if isinstance(setting, HotkeySetting):
                self._bindPluginHotkey(record, setting)

    def _bindPluginHotkey(self, record, setting):
        owner = f"plugin:{record.pluginId}:{setting.key}"
        self.hotkeys.setOwnerLabel(owner, lambda pluginId=record.pluginId, label=setting.label:
                                   f"{self.displayName(pluginId)} · {tr(label)}")

        def fire(pluginId=record.pluginId, actionName=setting.action):
            currentRecord = self.records.get(pluginId)
            if currentRecord and currentRecord.status == "running":
                getattr(currentRecord.instance, actionName)()

        result = self.hotkeys.bind(owner, self.getSetting(record.pluginId, setting.key), fire)
        self.hotkeyStatus[owner] = result
        self.hotkeyStatusChanged.emit(owner)

    # info ----------------------------------------------------------------
    def displayName(self, pluginId):
        record = self.records.get(pluginId)
        customName = self.globalSetting(pluginId, "customName")
        if customName:
            return customName
        if record and record.pluginClass:
            return tr(record.pluginClass.name)
        knownName = self.appStore.get(f"plugins.{pluginId}.knownName")
        return tr(knownName) if knownName else pluginId

    def displayIcon(self, pluginId):
        record = self.records.get(pluginId)
        customIcon = self.globalSetting(pluginId, "customIcon")
        if customIcon:
            return customIcon
        if record and record.pluginClass:
            return record.pluginClass.icon
        if record and record.status == "error":
            return "triangle-alert"
        return self.appStore.get(f"plugins.{pluginId}.knownIcon") or "puzzle"

    def installedRecords(self):
        return [self.records[pluginId] for pluginId in self.order if self.records[pluginId].installed]

    def sidebarRecords(self):
        return [record for record in self.installedRecords() if not self.globalSetting(record.pluginId, "hidden")]

    def uninstalledRecords(self):
        return [self.records[pluginId] for pluginId in self.order if not self.records[pluginId].installed]

    def widgetSpecs(self):
        specs = []
        for record in self.installedRecords():
            specs.extend(record.widgetSpecs)
        return specs

    # install / uninstall -------------------------------------------------
    def uninstall(self, pluginId, removeData=False):
        record = self.records.get(pluginId)
        if not record:
            return False
        if record.instance is not None:
            self.stopPlugin(pluginId)
        self.hotkeys.unbind(f"open:{pluginId}")
        self.activeRegistry.clearPlugin(pluginId)
        if record.settingsStore:
            record.settingsStore.flush()
        if removeData:
            self._removeData(pluginId)
        if record.builtin:
            uninstalledIds = self.appStore.get("plugins.__uninstalled", [])
            if pluginId not in uninstalledIds:
                uninstalledIds.append(pluginId)
            self.appStore.set("plugins.__uninstalled", uninstalledIds)
            record.instance = None
            record.status = "uninstalled"
        else:
            if record.folderPath and Path(record.folderPath).exists():
                shutil.rmtree(record.folderPath, ignore_errors=True)
            if record.moduleName:
                _forgetPluginModules(record.moduleName.rsplit(".", 1)[0])
            del self.records[pluginId]
            self.order.remove(pluginId)
        self.pluginsChanged.emit()
        return True

    def _removeData(self, pluginId):
        record = self.records.get(pluginId)
        if record and record.settingsStore:
            record.settingsStore.saveTimer.stop()
        for path in (pluginSettingsFile(pluginId), pluginDataDir(pluginId)):
            try:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                elif path.exists():
                    path.unlink()
            except OSError:
                pass
        allPlugins = self.appStore.get("plugins", {})
        if pluginId in allPlugins:
            self.appStore.remove(f"plugins.{pluginId}")

    def reinstall(self, pluginId):
        record = self.records.get(pluginId)
        if not record or record.installed or not record.builtin:
            return False
        uninstalledIds = [item for item in self.appStore.get("plugins.__uninstalled", []) if item != pluginId]
        self.appStore.set("plugins.__uninstalled", uninstalledIds)
        record.status = "stopped"
        self.instantiate(record)
        self.startPlugin(pluginId)
        self.pluginsChanged.emit()
        return True

    def inspectZip(self, zipPath):
        """Extracts to a temp dir and returns (tempFolder, pluginRoot, pluginClass). Raises on invalid."""
        tempFolder = Path(tempfile.mkdtemp(prefix="pchub-plugin-"))
        with zipfile.ZipFile(zipPath) as archive:
            for member in archive.namelist():
                memberPath = (tempFolder / member).resolve()
                if not str(memberPath).startswith(str(tempFolder.resolve())):
                    raise ValueError("unsafe path in zip")
            archive.extractall(tempFolder)
        candidates = [tempFolder] + [path for path in tempFolder.iterdir() if path.is_dir()]
        pluginRoot = next((path for path in candidates if (path / "plugin.py").exists()), None)
        if pluginRoot is None:
            shutil.rmtree(tempFolder, ignore_errors=True)
            raise ValueError("plugin.py not found")
        module, moduleName = self._importUserPlugin(pluginRoot)
        try:
            pluginClass = self._findPluginClass(module)
        finally:
            _forgetPluginModules(moduleName.rsplit(".", 1)[0])
        if pluginClass.pluginId in self.records:
            shutil.rmtree(tempFolder, ignore_errors=True)
            raise ValueError(f"a plugin with id '{pluginClass.pluginId}' already exists")
        return tempFolder, pluginRoot, pluginClass

    def installFromFolder(self, tempFolder, pluginRoot, pluginId):
        targetFolder = userPluginsDir() / pluginId
        if targetFolder.exists():
            raise ValueError("target folder already exists")
        shutil.copytree(pluginRoot, targetFolder)
        shutil.rmtree(tempFolder, ignore_errors=True)
        record = self._discoverUserFolder(targetFolder)
        if record.pluginClass:
            self.instantiate(record)
            self.startPlugin(record.pluginId)
        self.pluginsChanged.emit()
        return record
