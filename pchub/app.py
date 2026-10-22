import getpass
import os
import shutil
import sys
import time
import zipfile

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import QApplication, QFileDialog

from pchub import APP_NAME, BUILD_LEVEL, VERSION
from pchub.core import system
from pchub.core.active_registry import ActiveRegistry
from pchub.core.events import EventBus
from pchub.core.hotkeys import HotkeyManager
from pchub.core.i18n import setLanguage, tr
from pchub.core.logger import getLogger, setupLogging
from pchub.core.paths import assetsDir, dataDir, isWindows, userPluginsDir
from pchub.core.pins import PinService
from pchub.core.plugin_manager import PluginManager
from pchub.core.single_instance import SingleInstance
from pchub.core.storage import JsonStore, flushAllStores

APP_DEFAULTS = {
    "general": {
        "language": "auto", "userName": "", "openHotkey": "Ctrl+Alt+H", "startWithWindows": False,
        "startHidden": True, "closeToTray": True, "showSplash": True,
    },
    "appearance": {
        "style": "glass", "accent": "#8B7CF6", "glassOpacity": 7, "animations": True, "mouseEffects": True,
        "effectStrength": 60, "parallax": False,
    },
    "system": {"advancedPermissions": False},
    "notifications": {"style": "pchub", "seconds": 8, "keepImportant": False},
    "updates": {"autoCheck": True, "autoInstall": True, "lastCheck": None},
    "tray": {"pinned": []},
}


class PCHubApp(QObject):
    appHotkeyStatusChanged = Signal()
    threadErrorRaised = Signal(object, object, str)

    def __init__(self, argv):
        super().__init__()
        self.argv = list(argv)
        self.log = getLogger("app")
        self.quitting = False
        self.skipSaveOnQuit = False
        self.mainWindow = None
        self.tray = None
        self.hosts = {}
        self.detachedWindows = {}
        self.appHotkeyResult = None
        self.elevationFailed = False

    # boot -----------------------------------------------------------------
    def run(self):
        if not self.setup():
            return 0
        return self.qtApp.exec()

    def setup(self):
        """Builds everything. Returns False when this process should exit (another instance, elevation)."""
        setupLogging()
        self.qtApp = QApplication.instance() or QApplication(self.argv)
        self.qtApp.setApplicationName(APP_NAME)
        self.qtApp.setApplicationVersion(VERSION)
        self.qtApp.setQuitOnLastWindowClosed(False)
        self.log.info("Starting %s %s (admin=%s)", APP_NAME, VERSION, system.isAdmin())

        self.singleInstance = SingleInstance(self)
        if "--replace" in self.argv:
            self._waitForPreviousInstance()
        elif self.singleInstance.sendToPrimary(self._forwardArgs()):
            self.log.info("Another instance is running, forwarded arguments")
            return False
        self.singleInstance.becomePrimary()
        self.singleInstance.messageReceived.connect(self._handleInstanceMessage)
        system.createAppMutex()

        self.appStore = JsonStore(dataDir() / "app.json", defaults=APP_DEFAULTS)
        if not self.appStore.get("general.userName"):
            try:
                self.appStore.set("general.userName", getpass.getuser())
            except Exception:
                pass
        setLanguage(self.appStore.get("general.language"))

        if (isWindows and self.appStore.get("system.advancedPermissions") and not system.isAdmin()
                and "--no-elevate" not in self.argv):
            if system.relaunch(True, self._forwardArgs() + ["--replace", "--no-elevate"]):
                self.singleInstance.release()
                return False
            self.elevationFailed = True

        from pchub.core.crash_guard import CrashGuard, HEARTBEAT_SECONDS
        self.crashGuard = CrashGuard(VERSION)
        self.previousCrash = self.crashGuard.begin()
        self.threadErrorRaised.connect(self._onThreadError)
        self.crashGuard.threadErrorHandler = self.threadErrorRaised.emit
        self.heartbeatTimer = QTimer(self)
        self.heartbeatTimer.setInterval(HEARTBEAT_SECONDS * 1000)
        self.heartbeatTimer.timeout.connect(self.crashGuard.heartbeat)
        self.heartbeatTimer.start()

        from pchub.ui.fonts import loadFonts
        from pchub.ui.theme import ThemeManager, setThemeManager
        loadFonts()
        self.themeManager = ThemeManager(self.appStore)
        setThemeManager(self.themeManager)
        self.themeManager.apply(self.qtApp)
        from pchub.ui.widgets import HotkeyEdit, refreshThemedIcons
        self.themeManager.changed.connect(refreshThemedIcons)
        self.appIcon = self._loadAppIcon()
        self.qtApp.setWindowIcon(self.appIcon)

        startHidden = "--tray" in self.argv and self.appStore.get("general.startHidden")
        splash = None
        if not startHidden and self.appStore.get("general.showSplash") and "--no-splash" not in self.argv:
            from pchub.ui.splash import SplashWindow
            splash = SplashWindow()
            splash.show()
            splash.setProgress(0.05)

        self.events = EventBus(self)
        self.activeRegistry = ActiveRegistry(parent=self)
        self.hotkeys = HotkeyManager(self)
        HotkeyEdit.suspendHooks = (self.hotkeys.suspend, self.hotkeys.resume)
        self.pluginManager = PluginManager(self.appStore, self.activeRegistry, self.events, self.hotkeys,
                                           system.isAdmin, self)
        self.pluginManager.notifyHandler = self.notify
        self.pluginManager.confirmHandler = self._pluginConfirm
        self.pluginManager.openPageHandler = self.openPlugin
        self.pluginManager.settingsFormFactory = self._createPluginSettingsForm
        from pchub.ui.alerts import AlertManager
        self.alerts = AlertManager(self.appStore.get)
        self.pluginManager.alertHandler = self.alerts.show
        self.pinService = PinService(self.appStore, self.pluginManager, self.invokePluginAction, self)

        from pathlib import Path
        self.startupMarker = Path(dataDir()) / "startup.lock"
        crashedLastTime = self.startupMarker.exists()
        self.safeMode = crashedLastTime and "--no-safe-mode" not in self.argv
        from pchub.core import plugin_updates
        self.pluginUpdateResults = plugin_updates.prepare(VERSION, BUILD_LEVEL, crashedLastTime)
        try:
            self.startupMarker.write_text(str(time.time()), encoding="utf-8")
        except OSError:
            pass
        self.pluginManager.discover(includeUser="--no-user-plugins" not in self.argv, safeMode=self.safeMode)

        def progress(index, total, record):
            if splash:
                name = tr(record.pluginClass.name) if record.pluginClass else record.pluginId
                splash.setProgress(0.1 + 0.6 * index / max(1, total), tr("splash.loadingPlugin", name=name))

        self.pluginManager.instantiateAll(progress)
        if splash:
            splash.setProgress(0.75)
        self._buildWindow()
        if splash:
            splash.setProgress(0.9)
        self.pluginManager.startAll()
        self.pluginManager.pluginsChanged.connect(self._onPluginsChanged)
        self.pluginManager.globalSettingChanged.connect(self._onGlobalSettingChanged)
        self.pluginManager.statusChanged.connect(lambda pluginId: self.mainWindow.sidebar.tree.viewport().update())

        from pchub.ui.tray import TrayController
        self.tray = TrayController(self)
        self.bindAppHotkey()
        self._syncStartupState()
        self.events.emit("core.appStarted")

        if splash:
            splash.setProgress(1.0)
            splash.close()
        if not startHidden:
            lastPage = self.appStore.get("ui.lastPage", "home")
            self.mainWindow.showPage(lastPage if lastPage in self.mainWindow.pages else "home", animated=False)
            self.mainWindow.show()
            self.mainWindow.bringToFront()
        else:
            self.mainWindow.showPage("home", animated=False)
        openIndex = self.argv.index("--open") if "--open" in self.argv else -1
        if 0 <= openIndex < len(self.argv) - 1:
            QTimer.singleShot(0, lambda: self.openPlugin(self.argv[openIndex + 1]))
        if self.elevationFailed:
            QTimer.singleShot(800, lambda: self.notify(APP_NAME, tr("settings.elevationFailed")))
        self.qtApp.aboutToQuit.connect(self._shutdown)
        sys.excepthook = self.handleUncaughtException
        self.pluginManager.statusChanged.connect(self._onPluginStatusForProblems)
        QTimer.singleShot(20000, self._clearStartupMarker)
        QTimer.singleShot(1500, self._announceUpdateStatus)
        self.updateTimer = QTimer(self)
        self.updateTimer.setInterval(10000)
        self.updateTimer.timeout.connect(self._checkPendingUpdate)
        self.updateTimer.start()
        QTimer.singleShot(1200, self._announceStartupProblems)
        self._setupGitHubUpdates()
        return True

    def _forwardArgs(self):
        return [arg for arg in self.argv[1:] if arg not in ("--replace", "--no-elevate")]

    def _waitForPreviousInstance(self):
        from PySide6.QtNetwork import QLocalSocket
        deadline = time.time() + 8
        while time.time() < deadline:
            socket = QLocalSocket()
            socket.connectToServer(self.singleInstance.serverName)
            if not socket.waitForConnected(150):
                return
            socket.write(b'["--probe"]')
            socket.flush()
            socket.waitForBytesWritten(100)
            socket.disconnectFromServer()
            time.sleep(0.15)

    def _loadAppIcon(self):
        for fileName in ("app.ico", "app.png"):
            iconPath = assetsDir() / fileName
            if iconPath.exists():
                return QIcon(str(iconPath))
        from pchub.ui.icons import makeIcon
        return makeIcon("layout-grid", "#8B7CF6", 32)

    def _buildWindow(self):
        from pchub.ui.home import HomePage
        from pchub.ui.main_window import MainWindow
        from pchub.ui.pages import AppSettingsPage, PluginsPage
        self.mainWindow = MainWindow(self)
        self.mainWindow.addPage("home", HomePage(self))
        self.mainWindow.addPage("plugins", PluginsPage(self))
        self.mainWindow.addPage("settings", AppSettingsPage(self))
        for record in self.pluginManager.installedRecords():
            self._createHost(record)
        self.refreshSidebar()
        tree = self.mainWindow.sidebar.tree
        tree.statusGetter = lambda pluginId: self.pluginManager.records[pluginId].status if pluginId in self.pluginManager.records else "stopped"
        tree.layoutEdited.connect(self._saveSidebarLayout)
        tree.contextRequested.connect(self._sidebarContextMenu)

    def _createPluginSettingsForm(self, pluginId, schema):
        from pchub.ui.adapters import PluginSettingsAdapter
        from pchub.ui.settings_form import SettingsForm
        return SettingsForm(schema, PluginSettingsAdapter(self, pluginId))

    def _createHost(self, record):
        if record.pluginId in self.hosts or not record.installed:
            return
        from pchub.ui.plugin_host import PluginErrorHost, PluginPageHost
        if record.instance is None:
            host = PluginErrorHost(self, record, record.error or tr("status.error"), record.errorDetails)
        else:
            try:
                host = PluginPageHost(self, record)
            except Exception as error:
                import traceback
                self.reportPluginProblem(record.pluginId, error, traceback.format_exc())
                host = PluginErrorHost(self, record, f"{type(error).__name__}: {error}", record.errorDetails)
        host.detachRequested.connect(self.detachPlugin)
        self.hosts[record.pluginId] = host
        self.mainWindow.addPage(f"plugin:{record.pluginId}", host)

    def _syncHosts(self, pluginId):
        wasCurrent = self.mainWindow.currentKey == f"plugin:{pluginId}"
        self._onPluginsChanged()
        if wasCurrent and f"plugin:{pluginId}" in self.mainWindow.pages:
            self.mainWindow.showPage(f"plugin:{pluginId}", animated=False)

    def _rebuildHost(self, pluginId):
        wasCurrent = self.mainWindow.currentKey == f"plugin:{pluginId}"
        oldHost = self.hosts.get(pluginId)
        showingSettings = bool(getattr(oldHost, "gearButton", None) and oldHost.gearButton.isChecked())
        oldWindow = self.detachedWindows.get(pluginId)
        detachedState = None
        if oldWindow is not None:
            oldWindow.saveGeometryState()
            detachedState = (oldWindow.isVisible(), oldWindow.saveGeometry(), oldWindow.windowState(), oldWindow.size())
        self._removeHost(pluginId)
        record = self.pluginManager.records.get(pluginId)
        if record is not None:
            self._createHost(record)
        host = self.hosts.get(pluginId)
        if host is not None:
            host.showSettings(showingSettings)
            if detachedState is not None:
                from pchub.ui.plugin_host import DetachedPlaceholder, PluginWindow
                self.mainWindow.stack.removeWidget(host)
                window = PluginWindow(self, host)
                window.closed.connect(self.attachPlugin)
                self.detachedWindows[pluginId] = window
                self.mainWindow.addPage(f"plugin:{pluginId}", DetachedPlaceholder(self, pluginId))
                visible, geometry, state, size = detachedState
                window.restoreGeometry(geometry)
                window.resize(size)
                window.setWindowState(state)
                window.setVisible(visible)
        self.refreshSidebar()
        if wasCurrent:
            self.mainWindow.showPage(f"plugin:{pluginId}", animated=False)

    # plugin problems ------------------------------------------------------------
    def pluginForTraceback(self, tracebackObject):
        """Which plugin's code raised this exception (deepest frame inside a plugin folder), or None."""
        import traceback as tracebackModule
        return self.pluginForFiles([frame.filename for frame in tracebackModule.extract_tb(tracebackObject)])

    def pluginForFiles(self, fileNames):
        """The plugin owning the last of these source files that is inside a plugin folder, or None."""
        from pathlib import Path
        builtinRoot = str(Path(__file__).resolve().parent / "plugins")
        userRoot = str(userPluginsDir().resolve())
        found = None
        for fileName in fileNames:
            fileName = fileName.replace("/", os.sep)
            for root in (userRoot, builtinRoot):
                if fileName.startswith(root + os.sep):
                    folderName = fileName[len(root) + 1:].split(os.sep)[0]
                    record = self.pluginManager.records.get(folderName) or next(
                        (item for item in self.pluginManager.records.values()
                         if item.folderPath and Path(item.folderPath).name == folderName), None)
                    if record is not None:
                        found = record.pluginId
        return found

    def handleUncaughtException(self, excType, excValue, excTraceback):
        import traceback as tracebackModule
        detailsText = "".join(tracebackModule.format_exception(excType, excValue, excTraceback))
        self.log.error("Uncaught exception:\n%s", detailsText)
        pluginId = self.pluginForTraceback(excTraceback) if getattr(self, "pluginManager", None) else None
        if pluginId:
            self.reportPluginProblem(pluginId, excValue, detailsText)

    def reportPluginProblem(self, pluginId, error, detailsText=""):
        """Tells the user which plugin broke, with Details / Delete / Disable right in the alert."""
        import time as timeModule
        record = self.pluginManager.records.get(pluginId)
        if record is None:
            return
        errorText = f"{type(error).__name__}: {error}" if isinstance(error, BaseException) else str(error)
        record.problem = errorText
        record.problemDetails = detailsText or record.errorDetails
        if not record.error:
            record.error = errorText
            record.errorDetails = record.problemDetails
        self.log.error("Plugin %s problem: %s", pluginId, errorText)
        lastShown = getattr(record, "problemShownAt", 0)
        if timeModule.time() - lastShown < 60 or not hasattr(self, "alerts"):
            return
        record.problemShownAt = timeModule.time()
        name = self.pluginManager.displayName(pluginId)
        QTimer.singleShot(0, lambda: self.alerts.show(
            tr("plugin.problemTitle", name=name), tr("plugin.problemMessage", error=errorText), "triangle-alert",
            [(tr("plugin.errorDetails"), lambda: self.showPluginErrorDetails(pluginId), "file-text"),
             (tr("plugin.global.uninstallButton"), lambda: self.requestUninstall(pluginId), "trash-2"),
             (tr("plugin.disable"), lambda: self.disableBrokenPlugin(pluginId), "power")],
            accent="#F87171", sound="notify"))

    def _onThreadError(self, error, tracebackObject, detailsText):
        pluginId = self.pluginForTraceback(tracebackObject) if getattr(self, "pluginManager", None) else None
        if pluginId:
            self.reportPluginProblem(pluginId, error, detailsText)

    def _reportPreviousCrash(self):
        previous = self.previousCrash
        if not previous:
            return
        aliveAt = time.strftime("%H:%M", time.localtime(float(previous.get("aliveAt") or time.time())))
        dump = previous.get("dump")
        logPath = self.crashGuard.lastCrashPath if dump else self.crashGuard.crashPath.parent / "pchub.log"
        pluginId = None
        if dump:
            pluginId = self.pluginForFiles([frame[0] for frame in reversed(dump["frames"])])
        actions = [(tr("crash.openLog"), lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(logPath))),
                    "file-text")]
        if pluginId and pluginId in self.pluginManager.records:
            self.pluginManager.records[pluginId].problemShownAt = time.time()
            self.reportPluginProblem(pluginId, tr("crash.nativeError", error=dump["error"]), dump["text"])
            message = tr("crash.messagePlugin", name=self.pluginManager.displayName(pluginId), error=dump["error"],
                         time=aliveAt)
            actions = [(tr("plugin.errorDetails"), lambda: self.showPluginErrorDetails(pluginId), "file-text"),
                       (tr("plugin.disable"), lambda: self.disableBrokenPlugin(pluginId), "power")]
        else:
            cause = tr("crash.causeDump", error=dump["error"]) if dump else tr("crash.causeNone")
            message = tr("crash.messageUnknown", time=aliveAt, cause=cause)
        self.alerts.show(tr("crash.title"), message, "triangle-alert", actions, accent="#F87171", sound="notify")

    def _onPluginStatusForProblems(self, pluginId):
        record = self.pluginManager.records.get(pluginId)
        if record is not None and record.status == "error":
            self.reportPluginProblem(pluginId, record.error, record.errorDetails)

    def showPluginErrorDetails(self, pluginId):
        from pchub import VERSION
        from pchub.ui.dialogs import ErrorDetailsDialog
        record = self.pluginManager.records.get(pluginId)
        if record is None:
            return
        name = self.pluginManager.displayName(pluginId)
        version = record.pluginClass.version if record.pluginClass else "?"
        header = f"PC Hub {VERSION} · plugin '{pluginId}' v{version} ({'builtin' if record.builtin else 'user'})\n"
        body = getattr(record, "problemDetails", "") or record.errorDetails or record.error or ""
        ErrorDetailsDialog(self.activeParent(), tr("plugin.errorDialogTitle", name=name), tr("plugin.errorDialogText"),
                           header + "\n" + body).exec()

    def disableBrokenPlugin(self, pluginId):
        record = self.pluginManager.records.get(pluginId)
        if record is None:
            return
        self.pluginManager.setEnabled(pluginId, False)
        self._syncHosts(pluginId)

    def retryBrokenPlugin(self, pluginId):
        record = self.pluginManager.records.get(pluginId)
        if record is None:
            return
        self.appStore.set(f"plugins.{pluginId}.enabled", True)
        if record.status == "error":
            self.pluginManager.restartPlugin(pluginId)
        elif record.instance is None and not record.builtin:
            newRecord = self.pluginManager.loadDormant(pluginId)
            pluginId = newRecord.pluginId if newRecord else pluginId
        else:
            self.pluginManager.startPlugin(pluginId)
        self._syncHosts(pluginId)

    def reloadUserPlugins(self):
        """Loads plugin folders copied in while PC Hub is running (no restart needed)."""
        added = self.pluginManager.rescanUserPlugins()
        for record in added:
            if record.status == "error":
                self.reportPluginProblem(record.pluginId, record.error, record.errorDetails)
        return added

    def _removeHost(self, pluginId):
        window = self.detachedWindows.pop(pluginId, None)
        if window is not None:
            window.closed.disconnect()
            window.close()
            window.deleteLater()
        host = self.hosts.pop(pluginId, None)
        removedWidget = self.mainWindow.removePage(f"plugin:{pluginId}")
        if removedWidget is not None and removedWidget is not host:
            removedWidget.deleteLater()
        if host is not None:
            for timer in host.findChildren(QTimer):
                timer.stop()
            host.hide()
            host.setParent(None)
            host.deleteLater()

    def _onPluginsChanged(self):
        installedIds = {record.pluginId for record in self.pluginManager.installedRecords()}
        for pluginId in list(self.hosts):
            record = self.pluginManager.records.get(pluginId)
            if pluginId not in installedIds or record is None:
                self._removeHost(pluginId)
            elif getattr(self.hosts[pluginId], "record", None) is not record:
                self._rebuildHost(pluginId)
        for record in self.pluginManager.installedRecords():
            self._createHost(record)
        self.refreshSidebar()

    def _onGlobalSettingChanged(self, pluginId, key, value):
        if key in ("customName", "customIcon", "hidden"):
            self.refreshSidebar()
        elif key == "alwaysOnTop" and pluginId in self.detachedWindows:
            self.detachedWindows[pluginId].applyAlwaysOnTop()

    # sidebar --------------------------------------------------------------
    def refreshSidebar(self):
        from pchub.ui.sidebar import syncLayout
        manager = self.pluginManager
        visibleIds = [record.pluginId for record in manager.sidebarRecords()]
        layoutNodes = syncLayout(self.appStore.get("sidebar.layout", []), visibleIds)
        self.appStore.set("sidebar.layout", layoutNodes)
        tree = self.mainWindow.sidebar.tree
        tree.populate(layoutNodes, manager.displayName, manager.displayIcon)
        if self.mainWindow.currentKey:
            self.mainWindow.sidebar.setCurrent(self.mainWindow.currentKey)

    def _saveSidebarLayout(self):
        self.appStore.set("sidebar.layout", self.mainWindow.sidebar.tree.serialize())

    def _sidebarContextMenu(self, item, point):
        from PySide6.QtWidgets import QMenu
        from pchub.ui.dialogs import askText, confirm, pickIcon
        from pchub.ui.icons import makeIcon
        from pchub.ui.sidebar import ID_ROLE, ICON_ROLE, KIND_ROLE
        from pchub.ui.theme import theme
        import uuid
        tree = self.mainWindow.sidebar.tree
        menu = QMenu(tree)
        textColor = theme().text.name()

        def addAction(iconName, text, callback, danger=False):
            action = menu.addAction(makeIcon(iconName, theme().danger.name() if danger else textColor, 16), text)
            action.triggered.connect(callback)

        def newFolder(parentItem=None):
            accepted, name = askText(self.mainWindow, tr("sidebar.newFolder"), tr("sidebar.folderName"), "")
            if not accepted or not name:
                return
            nodes = tree.serialize()
            folderNode = {"type": "folder", "id": uuid.uuid4().hex[:8], "name": name, "icon": "", "expanded": True,
                          "children": []}
            if parentItem is None:
                nodes.append(folderNode)
            else:
                targetId = parentItem.data(0, ID_ROLE)

                def insertInto(nodeList):
                    for node in nodeList:
                        if node["type"] == "folder" and node["id"] == targetId:
                            node["children"].append(folderNode)
                            node["expanded"] = True
                            return True
                        if node["type"] == "folder" and insertInto(node["children"]):
                            return True
                    return False

                insertInto(nodes)
            self.appStore.set("sidebar.layout", nodes)
            self.refreshSidebar()

        if item is None:
            addAction("folder-plus", tr("sidebar.newFolder"), lambda: newFolder())
            menu.addSeparator()

            def resetOrder():
                if confirm(self.mainWindow, tr("sidebar.resetOrder"), tr("sidebar.resetOrderMessage")):
                    self.appStore.set("sidebar.layout", [])
                    self.refreshSidebar()

            addAction("rotate-ccw", tr("sidebar.resetOrder"), resetOrder)
        elif item.data(0, KIND_ROLE) == "folder":
            def renameFolder():
                accepted, name = askText(self.mainWindow, tr("common.rename"), tr("sidebar.folderName"), item.text(0))
                if accepted and name:
                    item.setText(0, name)
                    self._saveSidebarLayout()

            def folderIcon():
                iconName = pickIcon(self.mainWindow, item.data(0, ICON_ROLE) or "folder")
                if iconName:
                    item.setData(0, ICON_ROLE, iconName)
                    self._saveSidebarLayout()
                    tree.viewport().update()

            def deleteFolder():
                if not confirm(self.mainWindow, tr("sidebar.deleteFolder"), tr("sidebar.deleteFolderMessage"), danger=False,
                               confirmText=tr("common.delete")):
                    return
                parentItem = item.parent() or tree.invisibleRootItem()
                index = parentItem.indexOfChild(item)
                children = [item.takeChild(0) for _ in range(item.childCount())]
                removedFolder = parentItem.takeChild(index)
                for offset, child in enumerate(children):
                    parentItem.insertChild(index + offset, child)
                del removedFolder
                self._saveSidebarLayout()
                self.refreshSidebar()

            addAction("pencil", tr("common.rename"), renameFolder)
            addAction("palette", tr("sidebar.changeIcon"), folderIcon)
            addAction("folder-plus", tr("sidebar.newSubfolder"), lambda: newFolder(item))
            menu.addSeparator()
            addAction("trash-2", tr("sidebar.deleteFolder"), deleteFolder, danger=True)
        else:
            pluginId = item.data(0, ID_ROLE)
            addAction("external-link", tr("common.open"), lambda: self.openPlugin(pluginId))
            addAction("square-arrow-out-up-right", tr("sidebar.openWindow"), lambda: self.detachPlugin(pluginId))
            addAction("settings", tr("sidebar.pluginSettings"), lambda: self.openPlugin(pluginId, settings=True))
            menu.addSeparator()

            def renamePlugin():
                accepted, name = askText(self.mainWindow, tr("common.rename"), tr("plugin.global.customName"),
                                         self.pluginManager.displayName(pluginId))
                if accepted:
                    self.pluginManager.setGlobalSetting(pluginId, "customName", name)

            addAction("pencil", tr("common.rename"), renamePlugin)
            addAction("palette", tr("sidebar.changeIcon"), lambda: self.changePluginIcon(pluginId))
            addAction("eye-off", tr("sidebar.hide"), lambda: self.pluginManager.setGlobalSetting(pluginId, "hidden", True))
            menu.addSeparator()
            addAction("folder-plus", tr("sidebar.newFolder"), lambda: newFolder())
        self.execMenu(menu, tree.viewport().mapToGlobal(point))

    def execMenu(self, menu, globalPosition):
        return menu.exec(globalPosition)

    # windows --------------------------------------------------------------
    def trayAvailable(self):
        return bool(self.tray and self.tray.available)

    def showMainWindow(self, pageKey=None):
        if pageKey:
            self.mainWindow.showPage(pageKey, animated=self.mainWindow.isVisible())
        self.mainWindow.bringToFront()

    def toggleMainWindow(self, pageKey=None):
        window = self.mainWindow
        visible = window.isVisible() and not window.isMinimized()
        if visible and window.isActiveWindow() and (pageKey is None or window.currentKey == pageKey):
            window.saveGeometryState()
            window.hide()
            return
        self.showMainWindow(pageKey)

    def openPlugin(self, pluginId, viaHotkey=False, settings=False):
        if pluginId not in self.hosts:
            if viaHotkey:
                self.toggleMainWindow("plugins")
            return
        if viaHotkey and self.pluginManager.globalSetting(pluginId, "separateWindow"):
            window = self.detachedWindows.get(pluginId)
            if window is not None and window.isVisible() and window.isActiveWindow():
                window.close()
                return
            self.detachPlugin(pluginId)
            return
        if pluginId in self.detachedWindows and not viaHotkey:
            window = self.detachedWindows[pluginId]
            window.show()
            window.raise_()
            window.activateWindow()
            system.forceForeground(window)
            return
        if viaHotkey:
            self.toggleMainWindow(f"plugin:{pluginId}")
        else:
            self.showMainWindow(f"plugin:{pluginId}")
        if settings and pluginId in self.hosts:
            self.hosts[pluginId].showSettings(True)

    def detachPlugin(self, pluginId):
        host = self.hosts.get(pluginId)
        if host is None:
            return
        window = self.detachedWindows.get(pluginId)
        if window is None:
            from pchub.ui.plugin_host import DetachedPlaceholder, PluginWindow
            self.mainWindow.stack.removeWidget(host)
            window = PluginWindow(self, host)
            window.closed.connect(self.attachPlugin)
            self.detachedWindows[pluginId] = window
            wasCurrent = self.mainWindow.currentKey == f"plugin:{pluginId}"
            self.mainWindow.addPage(f"plugin:{pluginId}", DetachedPlaceholder(self, pluginId))
            if wasCurrent:
                self.mainWindow.showPage(f"plugin:{pluginId}", animated=False)
        window.show()
        window.raise_()
        window.activateWindow()
        system.forceForeground(window)

    def attachPlugin(self, pluginId):
        window = self.detachedWindows.pop(pluginId, None)
        host = self.hosts.get(pluginId)
        if host is None:
            return
        placeholder = self.mainWindow.pages.get(f"plugin:{pluginId}")
        wasCurrent = self.mainWindow.currentKey == f"plugin:{pluginId}"
        if window is not None:
            try:
                window.closed.disconnect()
            except (RuntimeError, TypeError):
                pass
            if window.isVisible():
                window.saveGeometryState()
                window.hide()
        host.setParent(None)
        host.inSeparateWindow = False
        host.refreshStatus()
        self.mainWindow.addPage(f"plugin:{pluginId}", host)
        if placeholder is not None and placeholder is not host:
            placeholder.deleteLater()
        if window is not None:
            window.deleteLater()
        if wasCurrent:
            self.mainWindow.showPage(f"plugin:{pluginId}", animated=False)

    # actions --------------------------------------------------------------
    def activeParent(self):
        activeWindow = QApplication.activeWindow()
        if activeWindow is not None and activeWindow.isVisible():
            return activeWindow
        if self.mainWindow is not None and self.mainWindow.isVisible():
            return self.mainWindow
        return None

    def confirm(self, title, message="", details=None, danger=False, confirmText=None):
        from pchub.ui.dialogs import confirm
        return confirm(self.activeParent(), title, message, details, danger, confirmText)

    def _pluginConfirm(self, title, message, details, danger, confirmText, iconName):
        from pchub.ui.dialogs import confirm
        return confirm(self.activeParent(), title, message, details, danger, confirmText, iconName)

    def notify(self, title, message="", sound=None):
        self.log.info("Notify: %s — %s", title, message)
        if self.appStore.get("notifications.style") == "windows" and self.tray:
            self.tray.showMessage(title, message)
        else:
            self.alerts.show(title, message, "bell")
        if sound:
            system.playSound(sound if isinstance(sound, str) else "notify")

    def invokePluginAction(self, pluginId, setting):
        record = self.pluginManager.records.get(pluginId)
        if not record or record.instance is None:
            return
        if record.status != "running":
            from pchub.ui.dialogs import showMessage
            showMessage(self.activeParent(), self.pluginManager.displayName(pluginId), tr(f"status.{record.status}"))
            return
        if setting.confirmTitle and not self.confirm(tr(setting.confirmTitle), tr(setting.confirmMessage) if setting.confirmMessage else "",
                                                     [tr(detail) for detail in setting.confirmDetails], setting.danger):
            return
        try:
            getattr(record.instance, setting.action)()
        except Exception as error:
            import traceback
            record.context.reportError(error, traceback.format_exc())

    def changePluginIcon(self, pluginId):
        from pchub.ui.dialogs import pickIcon
        iconName = pickIcon(self.activeParent(), self.pluginManager.displayIcon(pluginId))
        if iconName:
            self.pluginManager.setGlobalSetting(pluginId, "customIcon", iconName)

    def requestUninstall(self, pluginId):
        from pchub.ui.dialogs import confirm
        record = self.pluginManager.records.get(pluginId)
        if not record:
            return
        name = self.pluginManager.displayName(pluginId)
        details = [tr("plugin.uninstallBuiltinDetail") if record.builtin else tr("plugin.uninstallUserDetail")]
        accepted, removeData = confirm(self.activeParent(), tr("plugin.uninstallTitle", name=name),
                                       tr("plugin.uninstallMessage"), details, danger=not record.builtin,
                                       confirmText=tr("plugin.global.uninstallButton"), iconName="trash-2",
                                       checkboxText=tr("plugin.uninstallData"))
        if not accepted:
            return
        self._removeHost(pluginId)
        if removeData:
            self.appStore.set("tray.pinned", [ref for ref in self.appStore.get("tray.pinned", [])
                                              if not ref.startswith(f"{pluginId}:")])
        self.pluginManager.uninstall(pluginId, removeData)

    def requestAdvancedPermissions(self):
        self.setAppSetting("system.advancedPermissions", True)

    def openPluginsFolder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(userPluginsDir())))

    def installPluginFromZip(self, zipPath=None):
        from pchub.ui.dialogs import confirm, showMessage
        if not zipPath:
            zipPath, _ = QFileDialog.getOpenFileName(self.activeParent(), tr("plugins.installZip"), "", "Plugin (*.zip)")
        if not zipPath:
            return
        try:
            tempFolder, pluginRoot, pluginClass = self.pluginManager.inspectZip(zipPath)
        except Exception as error:
            showMessage(self.activeParent(), tr("plugins.installZip"), tr("plugins.installFailed", error=error), "circle-alert")
            return
        details = [(tr(pluginClass.name), f"v{pluginClass.version}"), (tr("plugin.global.author"), pluginClass.author)]
        if pluginClass.requiresAdmin:
            details.append((tr("plugin.global.adminRequired"), tr("common.yes")))
        if not confirm(self.activeParent(), tr("plugins.installTitle"), tr("plugins.installMessage"), details,
                       confirmText=tr("common.add"), iconName="package"):
            shutil.rmtree(tempFolder, ignore_errors=True)
            return
        try:
            record = self.pluginManager.installFromFolder(tempFolder, pluginRoot, pluginClass.pluginId)
            self.notify(APP_NAME, tr("plugins.installed.ok", name=self.pluginManager.displayName(record.pluginId)))
        except Exception as error:
            showMessage(self.activeParent(), tr("plugins.installZip"), tr("plugins.installFailed", error=error), "circle-alert")

    def reloadUserPluginsWithFeedback(self):
        from pchub.ui.dialogs import showMessage
        added = self.reloadUserPlugins()
        if added:
            names = ", ".join(self.pluginManager.displayName(record.pluginId) for record in added)
            self.notify(APP_NAME, tr("plugins.reloadFound", names=names))
        else:
            showMessage(self.activeParent(), tr("plugins.reload"), tr("plugins.reloadNone"), "rotate-cw")
        return added

    def createPluginFromTemplate(self, name=None):
        """Copies assets/plugin_template into the user plugins folder with a fresh id, loads it and opens it."""
        import re
        from pchub.core.paths import assetsDir
        from pchub.ui.dialogs import askText
        if name is None:
            accepted, name = askText(self.activeParent(), tr("plugins.newPluginTitle"), tr("plugins.newPluginLabel"))
            if not accepted or not name:
                return None
        baseId = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "my_plugin"
        if baseId[0].isdigit():
            baseId = f"plugin_{baseId}"
        pluginId = baseId
        counter = 2
        while pluginId in self.pluginManager.records or (userPluginsDir() / pluginId).exists():
            pluginId = f"{baseId}_{counter}"
            counter += 1
        targetFolder = userPluginsDir() / pluginId
        shutil.copytree(assetsDir() / "plugin_template", targetFolder)
        pluginFile = targetFolder / "plugin.py"
        source = pluginFile.read_text(encoding="utf-8")
        safeName = name.replace("\\", "").replace('"', "'")
        source = source.replace('pluginId = "plugin_template"', f'pluginId = "{pluginId}"')
        source = source.replace('name = T("Plugin di esempio", "Example plugin")', f'name = T("{safeName}", "{safeName}")')
        source = source.replace('"plugin_template.counter"', f'"{pluginId}.counter"')
        source = source.replace("class TemplatePlugin(", f"class {''.join(part.capitalize() for part in pluginId.split('_'))}Plugin(")
        source = source.replace("Plugin = TemplatePlugin", f"Plugin = {''.join(part.capitalize() for part in pluginId.split('_'))}Plugin")
        pluginFile.write_text(source, encoding="utf-8")
        self.reloadUserPlugins()
        if pluginId in self.hosts:
            self.openPlugin(pluginId)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(targetFolder)))
        self.notify(APP_NAME, tr("plugins.newPluginCreated", name=name))
        return pluginId

    # app settings ---------------------------------------------------------
    def appSetting(self, key):
        return self.appStore.get(key)

    def isAdmin(self):
        return system.isAdmin()

    def setAppSetting(self, key, value):
        previousValue = self.appStore.get(key)
        if key == "system.advancedPermissions":
            return self._setAdvancedPermissions(bool(value))
        if key == "general.openHotkey":
            self.appStore.set(key, value)
            self.bindAppHotkey()
            return True
        self.appStore.set(key, value)
        if key == "general.language" and value != previousValue:
            setLanguage(value)
            self._askRestart()
        elif key in ("general.startWithWindows",):
            self._applyStartup()
        return True

    def _setAdvancedPermissions(self, enabled):
        if enabled == bool(self.appStore.get("system.advancedPermissions")) and enabled == self.isAdmin():
            return True
        if enabled:
            accepted = self.confirm(tr("settings.advancedOnTitle"), tr("settings.advancedOnMessage"),
                                    [tr("settings.advancedOnDetail1"), tr("settings.advancedOnDetail2")],
                                    confirmText=tr("common.restartNow"))
            if not accepted:
                return False
            self.appStore.set("system.advancedPermissions", True)
            if self.isAdmin():
                self._applyStartup()
                for record in self.pluginManager.installedRecords():
                    if record.status == "blocked":
                        self.pluginManager.startPlugin(record.pluginId)
                return True
            self.appStore.flush()
            if system.relaunch(True, self._forwardArgs() + ["--replace", "--no-elevate"]):
                self.quit()
                return True
            self.appStore.set("system.advancedPermissions", False)
            self.notify(APP_NAME, tr("settings.elevationFailed"))
            return False
        self.appStore.set("system.advancedPermissions", False)
        self._applyStartup()
        if self.isAdmin():
            from pchub.ui.dialogs import showMessage
            showMessage(self.activeParent(), tr("settings.advancedPermissions"), tr("settings.advancedOffMessage"))
        return True

    def _askRestart(self):
        if self.confirm(tr("common.restartNow"), tr("settings.restartRequired"), confirmText=tr("common.restartNow")):
            self.restart()

    def restart(self):
        if not self.skipSaveOnQuit:
            flushAllStores()
        restartArgs = [arg for arg in self._forwardArgs() if arg != "--tray"] + ["--replace", "--no-elevate"]
        if system.relaunch(False, restartArgs):
            self.quit()

    def _applyStartup(self):
        enabled = bool(self.appStore.get("general.startWithWindows"))
        elevated = bool(self.appStore.get("system.advancedPermissions"))
        if not system.setStartup(enabled, elevated):
            self.log.warning("Could not update autostart")

    def _syncStartupState(self):
        if not isWindows:
            return
        if not self.appStore.has("general.startWithWindows"):
            self.appStore.set("general.startWithWindows", system.isStartupEnabled())
        self._applyStartup()

    def bindAppHotkey(self):
        self.hotkeys.setOwnerLabel("app:open", lambda: f"{APP_NAME} · {tr('settings.openHotkey')}")
        self.appHotkeyResult = self.hotkeys.bind("app:open", self.appStore.get("general.openHotkey"),
                                                 lambda: self.toggleMainWindow())
        self.appHotkeyStatusChanged.emit()

    def invokeAppAction(self, key):
        from pchub.ui.dialogs import confirm
        if key == "data.openFolder":
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(dataDir())))
        elif key == "data.export":
            targetPath, _ = QFileDialog.getSaveFileName(self.activeParent(), tr("settings.export"),
                                                        f"PCHub-settings-{time.strftime('%Y%m%d')}.zip", "Zip (*.zip)")
            if targetPath:
                flushAllStores()
                self.exportSettings(targetPath)
        elif key == "data.import":
            sourcePath, _ = QFileDialog.getOpenFileName(self.activeParent(), tr("settings.import"), "", "Zip (*.zip)")
            if sourcePath and confirm(self.activeParent(), tr("settings.import"), tr("settings.importMessage"),
                                      danger=True, confirmText=tr("settings.importButton")):
                self.importSettings(sourcePath)
                self.skipSaveOnQuit = True
                self.restart()
        elif key == "update.install":
            self.installUpdateFromZip()
        elif key == "update.checkNow":
            self.checkGitHubUpdates(manual=True)
        elif key == "update.openGitHub":
            from pchub import UPDATE_REPO
            QDesktopServices.openUrl(QUrl(f"https://github.com/{UPDATE_REPO}"))
        elif key == "notifications.test":
            self.alerts.show(tr("notifications.testTitle"), tr("notifications.testMessage"), "bell",
                             [(tr("notifications.testAction"), lambda: None, "check")])
        elif key == "update.revert":
            if confirm(self.activeParent(), tr("update.revert"), tr("update.revertMessage"), confirmText=tr("update.restart")):
                (dataDir() / "app-update.remove").write_text("1", encoding="utf-8")
                self.restart()
        elif key == "data.reset":
            if confirm(self.activeParent(), tr("settings.reset"), tr("settings.resetMessage"), danger=True,
                       confirmText=tr("settings.resetButton")):
                self.resetSettings()
                self.skipSaveOnQuit = True
                self.restart()

    @staticmethod
    def exportSettings(targetPath):
        root = dataDir()
        with zipfile.ZipFile(targetPath, "w", zipfile.ZIP_DEFLATED) as archive:
            if (root / "app.json").exists():
                archive.write(root / "app.json", "app.json")
            settingsFolder = root / "plugin-settings"
            if settingsFolder.exists():
                for filePath in settingsFolder.glob("*.json"):
                    archive.write(filePath, f"plugin-settings/{filePath.name}")

    @staticmethod
    def importSettings(sourcePath):
        root = dataDir()
        with zipfile.ZipFile(sourcePath) as archive:
            for member in archive.namelist():
                if member == "app.json" or (member.startswith("plugin-settings/") and member.endswith(".json")
                                            and "/" not in member[len("plugin-settings/"):] and ".." not in member):
                    targetPath = root / member
                    targetPath.parent.mkdir(parents=True, exist_ok=True)
                    targetPath.write_bytes(archive.read(member))

    @staticmethod
    def resetSettings():
        root = dataDir()
        try:
            (root / "app.json").unlink()
        except OSError:
            pass
        shutil.rmtree(root / "plugin-settings", ignore_errors=True)

    # lifecycle ------------------------------------------------------------
    def _handleInstanceMessage(self, args):
        if self.quitting or "--probe" in args:
            return
        if "--open" in args:
            index = args.index("--open")
            if index < len(args) - 1:
                self.openPlugin(args[index + 1])
                return
        if "--tray" in args:
            return
        self.showMainWindow()

    def quit(self):
        if self.quitting:
            return
        self.quitting = True
        self.qtApp.quit()

    def _clearStartupMarker(self):
        for path in (getattr(self, "startupMarker", None), dataDir() / "app-update.firstrun"):
            try:
                if path is not None:
                    path.unlink()
            except OSError:
                pass
        from pchub.core import plugin_updates
        plugin_updates.clearFirstRunMarkers()

    # quick updates -------------------------------------------------------------
    def _announceUpdateStatus(self):
        import json
        try:
            status = json.loads(os.environ.get("PCHUB_UPDATE_STATUS") or "null")
        except ValueError:
            status = None
        updateLog = os.environ.get("PCHUB_UPDATE_LOG")
        if updateLog:
            self.log.info("Updater: %s", updateLog)
        for result in getattr(self, "pluginUpdateResults", []):
            self._announcePluginUpdate(result)
        if not status:
            return
        if status.get("status") == "applied":
            self.alerts.show(tr("update.appliedTitle", version=status.get("version")), tr("update.appliedMessage"),
                             "download", timeoutSeconds=8, accent="#34D399")
        elif status.get("status") == "rolledBack":
            self.alerts.show(tr("update.rolledBackTitle"), tr("update.rolledBackMessage", version=status.get("version")),
                             "rotate-ccw", accent="#FBBF24")
        elif status.get("status") == "rejected":
            self.alerts.show(tr("update.rejectedTitle"), self._rejectionText(status.get("reason")), "circle-alert",
                             accent="#F87171")

    def _pluginDisplayName(self, pluginId):
        return self.pluginManager.displayName(pluginId) if pluginId in self.pluginManager.records else pluginId

    def _announcePluginUpdate(self, result):
        if result.get("status") == "applied":
            self.alerts.show(tr("update.pluginAppliedTitle", name=self._pluginDisplayName(result.get("pluginId")),
                                version=result.get("version")), tr("update.pluginAppliedMessage"), "puzzle",
                             timeoutSeconds=8, accent="#34D399")
        elif result.get("status") == "rolledBack":
            self.alerts.show(tr("update.rolledBackTitle"),
                             tr("update.pluginRolledBack", name=self._pluginDisplayName(result.get("pluginId")),
                                version=result.get("version")), "rotate-ccw", accent="#FBBF24")
        elif result.get("status") == "rejected":
            self.alerts.show(tr("update.rejectedTitle"), self._rejectionText(result.get("reason")), "circle-alert",
                             accent="#F87171")

    @staticmethod
    def _rejectionText(reason):
        if reason in ("needsBuild", "older", "needsHub"):
            return tr(f"update.rejected.{reason}")
        return tr("update.rejected.other", reason=reason)

    def _checkPendingUpdate(self):
        self._checkPendingPluginUpdates()
        pending = dataDir() / "updates" / "pending.zip"
        if not pending.exists():
            self.announcedPending = None
            return
        stamp = pending.stat().st_mtime
        if getattr(self, "announcedPending", None) == stamp:
            return
        self.announcedPending = stamp
        import updater_boot
        ok, result = updater_boot.validateZip(pending, VERSION, BUILD_LEVEL)
        if not ok:
            pending.unlink()
            self.alerts.show(tr("update.rejectedTitle"), self._rejectionText(result), "circle-alert", accent="#F87171")
            return
        self.alerts.show(tr("update.readyTitle"), tr("update.readyMessage", version=result.get("version")), "download",
                         [(tr("update.later"), lambda: None), (tr("update.restart"), self.restart, "rotate-cw")],
                         accent="#34D399")

    def _checkPendingPluginUpdates(self):
        from pchub.core import plugin_updates
        folder = plugin_updates.pendingFolder()
        if not folder.exists():
            return
        announced = getattr(self, "announcedPluginZips", set())
        self.announcedPluginZips = announced
        for zipPath in sorted(folder.glob("*.zip")):
            key = (zipPath.name, zipPath.stat().st_mtime)
            if key in announced:
                continue
            announced.add(key)
            ok, result = plugin_updates.validatePluginZip(zipPath, VERSION, BUILD_LEVEL)
            if not ok:
                rejected = folder / "rejected"
                rejected.mkdir(parents=True, exist_ok=True)
                shutil.move(str(zipPath), str(rejected / zipPath.name))
                self.alerts.show(tr("update.rejectedTitle"), self._rejectionText(result), "circle-alert", accent="#F87171")
                continue
            self.alerts.show(tr("update.readyTitle"),
                             tr("update.pluginReadyMessage", name=self._pluginDisplayName(result.get("pluginId")),
                                version=result.get("version")), "puzzle",
                             [(tr("update.later"), lambda: None), (tr("update.restart"), self.restart, "rotate-cw")],
                             accent="#34D399")

    # GitHub updates ---------------------------------------------------------------------------
    def _setupGitHubUpdates(self):
        from pchub import UPDATE_REPO
        from pchub.core.github_updates import GitHubUpdater
        self.githubUpdater = GitHubUpdater(UPDATE_REPO, VERSION, BUILD_LEVEL, parent=self)
        self.githubUpdater.checkFinished.connect(self._onGitHubCheck)
        self.manualUpdateCheck = False
        self.githubTimer = QTimer(self)
        self.githubTimer.setInterval(6 * 60 * 60 * 1000)
        self.githubTimer.timeout.connect(self.checkGitHubUpdates)
        self.githubTimer.start()
        if "--no-update-check" not in self.argv:
            QTimer.singleShot(25000, self.checkGitHubUpdates)

    def installedPluginVersions(self):
        from pchub.core.plugin_updates import activeUpdates
        versions = {}
        for record in self.pluginManager.records.values():
            if record.builtin and record.pluginClass is not None:
                versions[record.pluginId] = activeUpdates.get(record.pluginId) or record.pluginClass.version
        return versions

    def checkGitHubUpdates(self, manual=False):
        if not manual and not self.appStore.get("updates.autoCheck"):
            return False
        self.manualUpdateCheck = manual
        install = bool(self.appStore.get("updates.autoInstall")) or manual
        started = self.githubUpdater.check(self.installedPluginVersions(), install=install)
        if manual and started:
            self.alerts.show(tr("update.checking"), "", "refresh-cw", timeoutSeconds=3)
        return started

    def _onGitHubCheck(self, result):
        manual = self.manualUpdateCheck
        self.manualUpdateCheck = False
        self.appStore.set("updates.lastCheck", time.strftime("%Y-%m-%d %H:%M"))
        status = result.get("status")
        releasesPage = f"https://github.com/{self.githubUpdater.repository}/releases"
        if status == "downloaded":
            self._checkPendingUpdate()
            self._checkPendingPluginUpdates()
        elif status == "available":
            entry = result.get("app") or (result.get("plugins") or [None])[0]
            name = f"PC Hub {entry['version']}" if result.get("app") else \
                f"{self._pluginDisplayName(entry['pluginId'])} {entry['version']}"
            self.alerts.show(tr("update.availableTitle"), tr("update.availableMessage", name=name), "download",
                             [(tr("update.whatsNew"), lambda: QDesktopServices.openUrl(QUrl(entry.get("page") or releasesPage))),
                              (tr("update.download"), lambda: self.checkGitHubUpdates(manual=True), "download")],
                             accent="#34D399")
        elif status == "needsInstaller":
            entry = result["needsInstaller"]
            installer = entry.get("installer") or {}
            url = installer.get("browser_download_url") or entry.get("page") or releasesPage
            self.alerts.show(tr("update.installerTitle", version=entry["version"]), tr("update.installerMessage"),
                             "package", [(tr("update.download"), lambda: QDesktopServices.openUrl(QUrl(url)), "download")],
                             accent="#38BDF8")
        elif status == "error" and manual:
            self.alerts.show(tr("update.checkFailed"), result.get("error") or "", "circle-alert", accent="#F87171")
        elif status == "upToDate" and manual:
            self.alerts.show(tr("update.upToDate", version=VERSION), "", "circle-check", accent="#34D399")

    def installUpdateFromZip(self, zipPath=None):
        import updater_boot
        from pchub.ui.dialogs import showMessage
        if not zipPath:
            zipPath, _ = QFileDialog.getOpenFileName(self.activeParent(), tr("update.install"), "", "PC Hub update (*.zip)")
        if not zipPath:
            return False
        from pchub.core import plugin_updates
        if plugin_updates.isPluginZip(zipPath):
            ok, result = plugin_updates.validatePluginZip(zipPath, VERSION, BUILD_LEVEL)
            if not ok:
                showMessage(self.activeParent(), tr("update.rejectedTitle"), self._rejectionText(result), "circle-alert")
                return False
            plugin_updates.queueZip(zipPath)
            self._checkPendingPluginUpdates()
            return True
        ok, result = updater_boot.validateZip(zipPath, VERSION, BUILD_LEVEL)
        if not ok:
            showMessage(self.activeParent(), tr("update.rejectedTitle"), self._rejectionText(result), "circle-alert")
            return False
        target = dataDir() / "updates" / "pending.zip"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(zipPath, target)
        self._checkPendingUpdate()
        return True

    def _announceStartupProblems(self):
        self._reportPreviousCrash()
        for record in self.pluginManager.installedRecords():
            if record.status == "error":
                self.reportPluginProblem(record.pluginId, record.error, record.errorDetails)
        if self.safeMode and any(record.safeMode for record in self.pluginManager.records.values()):
            self.alerts.show(tr("safeMode.title"), tr("safeMode.message"), "shield-alert",
                             [(tr("safeMode.keep"), lambda: None),
                              (tr("safeMode.enableAll"), self._leaveSafeMode, "rotate-cw")], accent="#FBBF24")

    def _leaveSafeMode(self):
        for record in list(self.pluginManager.records.values()):
            if record.safeMode and self.pluginManager.globalSetting(record.pluginId, "enabled") is not False:
                newRecord = self.pluginManager.loadDormant(record.pluginId)
                if newRecord is not None:
                    self._rebuildHost(newRecord.pluginId)

    def _shutdown(self):
        self._clearStartupMarker()
        self.quitting = True
        self.log.info("Shutting down")
        try:
            if self.mainWindow is not None:
                self.mainWindow.saveGeometryState()
            for window in list(self.detachedWindows.values()):
                window.saveGeometryState()
            self.pluginManager.stopAll()
            self.alerts.closeAll()
            self.hotkeys.shutdown()
            from pchub.core.input_hooks import hookService
            hookService().shutdown()
            if self.tray:
                self.tray.hide()
        except Exception:
            self.log.exception("Error during shutdown")
        if not self.skipSaveOnQuit:
            flushAllStores()
        else:
            from pchub.core.storage import _allStores
            for store in _allStores:
                store.saveTimer.stop()
        if getattr(self, "crashGuard", None) is not None:
            self.crashGuard.end()
        self.singleInstance.release()


def main(argv=None):
    application = PCHubApp(argv or sys.argv)
    return application.run()
