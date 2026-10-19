import os

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from pchub import VERSION
from pchub.core.i18n import tr, T
from pchub.core.settings_schema import (ActionButton, Choice, CustomRow, HotkeySetting, InfoRow, Section, Slider,
                                        TextInput, Toggle)
from pchub.ui.adapters import AppSettingsAdapter
from pchub.ui.settings_form import SettingsForm
from pchub.ui.theme import ACCENT_PRESETS, theme, themeManager
from pchub.ui.widgets import (Card, EmptyState, FlowLayout, IconTile, IconWidget, ToggleSwitch, clearLayout,
                              iconButton, makeButton, makeLabel, makeScrollPage, setRole, statusChipRole)


class AccentPicker(QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.swatches = []
        for presetName, colorHex in ACCENT_PRESETS:
            swatch = AccentSwatch(colorHex)
            swatch.clicked.connect(lambda checked=False, value=colorHex: app.setAppSetting("appearance.accent", value))
            layout.addWidget(swatch)
            self.swatches.append(swatch)
        app.appStore.changed.connect(self._onStoreChanged)
        self.refresh()

    def _onStoreChanged(self, key, value):
        if key == "appearance.accent":
            self.refresh()

    def refresh(self):
        currentAccent = (self.app.appSetting("appearance.accent") or "").upper()
        for swatch in self.swatches:
            swatch.setChecked(swatch.colorHex.upper() == currentAccent)


class AccentSwatch(QPushButton):
    def __init__(self, colorHex, parent=None):
        super().__init__(parent)
        self.colorHex = colorHex
        self.setCheckable(True)
        self.setFixedSize(26, 26)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QPushButton { background: transparent; border: none; padding: 0; }")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(3, 3, -3, -3)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self.colorHex))
        painter.drawEllipse(rect)
        if self.isChecked() or self.underMouse():
            from PySide6.QtGui import QPen
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(255, 255, 255, 230 if self.isChecked() else 110), 2))
            painter.drawEllipse(self.rect().adjusted(1, 1, -1, -1))


class PinnedManager(QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.listLayout = QVBoxLayout(self)
        self.listLayout.setContentsMargins(0, 0, 0, 0)
        self.listLayout.setSpacing(4)
        self.setMinimumWidth(320)
        app.pinService.changed.connect(self.rebuild)
        self.rebuild()

    def rebuild(self):
        clearLayout(self.listLayout)
        items = self.app.pinService.items()
        if not items:
            self.listLayout.addWidget(makeLabel(tr("settings.pinnedEmpty"), "faint", True))
            return
        for item in items:
            rowLayout = QHBoxLayout()
            rowLayout.setSpacing(6)
            rowLayout.addWidget(IconWidget(item.icon or self.app.pluginManager.displayIcon(item.pluginId), "muted", 16))
            rowLayout.addWidget(makeLabel(f"{item.label}"), 1)
            rowLayout.addWidget(makeLabel(self.app.pluginManager.displayName(item.pluginId), "faint"))
            upButton = iconButton("arrow-up", None, "muted", 14)
            upButton.clicked.connect(lambda checked=False, ref=item.ref: self.app.pinService.move(ref, -1))
            downButton = iconButton("arrow-down", None, "muted", 14)
            downButton.clicked.connect(lambda checked=False, ref=item.ref: self.app.pinService.move(ref, 1))
            removeButton = iconButton("pin-off", tr("pin.unpin"), "danger", 14)
            removeButton.clicked.connect(lambda checked=False, ref=item.ref: self.app.pinService.setPinned(ref, False))
            for button in (upButton, downButton, removeButton):
                rowLayout.addWidget(button)
            self.listLayout.addLayout(rowLayout)


def appSettingsSchema(app):
    return [
        Section(tr("settings.general")),
        Choice("general.language", tr("settings.language"),
               [("auto", tr("settings.languageAuto")), ("it", "Italiano"), ("en", "English")], icon="globe",
               pinnable=False),
        TextInput("general.userName", tr("settings.userName"), description=tr("settings.userNameDesc"), icon="user"),
        HotkeySetting("general.openHotkey", tr("settings.openHotkey"), action=None, icon="keyboard"),
        Toggle("general.startWithWindows", tr("settings.startWithWindows"), icon="power", pinnable=False),
        Toggle("general.startHidden", tr("settings.startHidden"), description=tr("settings.startHiddenDesc"),
               visibleIf=("general.startWithWindows", True), icon="eye-off", pinnable=False),
        Toggle("general.closeToTray", tr("settings.closeToTray"), description=tr("settings.closeToTrayDesc"),
               icon="minimize-2", pinnable=False),
        Toggle("general.showSplash", tr("settings.showSplash"), icon="sparkles", pinnable=False),
        Section(tr("settings.appearance")),
        Choice("appearance.style", tr("settings.style"),
               [("glass", tr("settings.styleGlass")), ("clay", tr("settings.styleClay"))], icon="palette", pinnable=False),
        CustomRow("appearance.accent", tr("settings.accent"), lambda parent: AccentPicker(app), icon="droplet"),
        Slider("appearance.glassOpacity", tr("settings.glassOpacity"), 2, 20, 7, suffix="%",
               visibleIf=("appearance.style", "glass"), icon="layers", pinnable=False),
        Toggle("appearance.animations", tr("settings.animations"), description=tr("settings.animationsDesc"),
               icon="wand-sparkles", pinnable=False),
        Toggle("appearance.mouseEffects", tr("settings.mouseEffects"), description=tr("settings.mouseEffectsDesc"),
               icon="mouse-pointer-click", pinnable=False),
        Toggle("appearance.parallax", tr("settings.parallax"), description=tr("settings.parallaxDesc"), icon="move",
               pinnable=False),
        Slider("appearance.effectStrength", tr("settings.effectStrength"), 0, 100, 60, suffix="%",
               visibleIf=lambda get: get("appearance.mouseEffects") or get("appearance.parallax"), icon="gauge",
               pinnable=False),
        Section(tr("settings.system")),
        Toggle("system.advancedPermissions", tr("settings.advancedPermissions"),
               description=tr("settings.advancedPermissionsDesc"), icon="shield", pinnable=False),
        InfoRow("system.adminStatus", tr("settings.adminStatus"),
                lambda: tr("common.yes") if app.isAdmin() else tr("common.no"), icon="shield-check"),
        Section(tr("notifications.section")),
        Choice("notifications.style", tr("notifications.style"),
               [("pchub", tr("notifications.stylePCHub")), ("windows", tr("notifications.styleWindows"))],
               icon="bell", pinnable=False, description=tr("notifications.styleDesc")),
        Slider("notifications.seconds", tr("notifications.seconds"), 3, 30, 8, suffix=" s", icon="timer",
               pinnable=False, description=tr("notifications.secondsDesc")),
        Toggle("notifications.keepImportant", tr("notifications.keepImportant"),
               description=tr("notifications.keepImportantDesc"), icon="pin", pinnable=False),
        ActionButton("notifications.test", tr("notifications.test"), action=None,
                     buttonText=tr("notifications.testButton"), icon="bell-ring", pinnable=False),
        Section(tr("settings.tray")),
        CustomRow("tray.manager", tr("settings.pinnedItems"), lambda parent: PinnedManager(app), icon="pin"),
        Section(tr("settings.data")),
        ActionButton("data.openFolder", tr("settings.openDataFolder"), action=None,
                     buttonText=tr("settings.openDataFolderButton"), icon="folder-open", pinnable=False),
        ActionButton("data.export", tr("settings.export"), action=None, buttonText=tr("settings.exportButton"),
                     icon="upload", pinnable=False),
        ActionButton("data.import", tr("settings.import"), action=None, buttonText=tr("settings.importButton"),
                     icon="download", pinnable=False),
        ActionButton("data.reset", tr("settings.reset"), action=None, buttonText=tr("settings.resetButton"),
                     danger=True, icon="rotate-ccw", pinnable=False),
        Section(tr("settings.about")),
        InfoRow("about.version", tr("settings.version"),
                lambda: f"{VERSION} · {tr('update.quick')}" if os.environ.get("PCHUB_OVERRIDE_ROOT") else VERSION, icon="tag"),
        Toggle("updates.autoCheck", tr("update.autoCheck"), description=tr("update.autoCheckDesc"), icon="refresh-cw",
               pinnable=False),
        Toggle("updates.autoInstall", tr("update.autoInstall"), description=tr("update.autoInstallDesc"),
               icon="download", pinnable=False, visibleIf=("updates.autoCheck", True)),
        ActionButton("update.checkNow", tr("update.checkNow"), action=None, buttonText=tr("update.checkNowButton"),
                     icon="search", pinnable=False, description=tr("update.checkNowDesc")),
        InfoRow("updates.lastCheckInfo", tr("update.lastCheck"), lambda: app.appStore.get("updates.lastCheck") or "—",
                icon="history"),
        ActionButton("update.openGitHub", tr("update.github"), action=None, buttonText="GitHub", icon="globe",
                     pinnable=False, description=tr("update.githubDesc")),
        ActionButton("update.install", tr("update.install"), action=None, description=tr("update.installDesc"),
                     buttonText=tr("update.installButton"), icon="download", pinnable=False),
        ActionButton("update.revert", tr("update.revert"), action=None, description=tr("update.revertDesc"),
                     buttonText=tr("update.revertButton"), icon="rotate-ccw", pinnable=False,
                     visibleIf=lambda get: bool(os.environ.get("PCHUB_OVERRIDE_ROOT"))),
    ]


class AppSettingsPage(QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        scrollArea, contentLayout = makeScrollPage((28, 22, 28, 28), 14)
        layout.addWidget(scrollArea)
        headerLayout = QHBoxLayout()
        headerLayout.setSpacing(14)
        headerLayout.addWidget(IconTile("settings", 46))
        titleLayout = QVBoxLayout()
        titleLayout.setSpacing(2)
        titleLayout.addWidget(makeLabel(tr("settings.title"), "title"))
        titleLayout.addWidget(makeLabel(tr("settings.subtitle"), "muted"))
        headerLayout.addLayout(titleLayout, 1)
        self.restartButton = makeButton(tr(T("Riavvia PC Hub", "Restart PC Hub")), "rotate-cw", "ghost")
        self.restartButton.clicked.connect(app.restart)
        headerLayout.addWidget(self.restartButton)
        contentLayout.addLayout(headerLayout)
        self.form = SettingsForm(appSettingsSchema(app), AppSettingsAdapter(app))
        contentLayout.addWidget(self.form)
        contentLayout.addStretch(1)


class PluginCard(Card):
    def __init__(self, app, record, parent=None):
        super().__init__(parent, padding=14, hoverable=True)
        self.app = app
        manager = app.pluginManager
        pluginId = record.pluginId
        layout = QHBoxLayout(self)
        layout.setSpacing(14)
        layout.addWidget(IconTile(manager.displayIcon(pluginId), 44), 0, Qt.AlignTop)
        textLayout = QVBoxLayout()
        textLayout.setSpacing(4)
        titleRow = QHBoxLayout()
        titleRow.setSpacing(8)
        titleRow.addWidget(makeLabel(manager.displayName(pluginId), "subtitle"))
        if record.pluginClass:
            titleRow.addWidget(makeLabel(f"v{record.pluginClass.version}", "chip"))
            if record.pluginClass.requiresAdmin:
                titleRow.addWidget(makeLabel(tr("plugins.admin"), "chipWarning"))
        titleRow.addWidget(makeLabel(tr("plugin.global.builtin") if record.builtin else tr("plugins.user"), "chip"))
        if record.installed and manager.globalSetting(pluginId, "hidden"):
            titleRow.addWidget(makeLabel(tr("plugins.hiddenBadge"), "chip"))
        if record.installed:
            statusChip = makeLabel(tr(f"status.{record.status}"), statusChipRole(record.status))
            titleRow.addWidget(statusChip)
        titleRow.addStretch(1)
        textLayout.addLayout(titleRow)
        descriptionText = tr(record.pluginClass.description) if record.pluginClass else record.error
        textLayout.addWidget(makeLabel(descriptionText, "danger" if not record.pluginClass else "muted", True))
        if record.status == "error" and record.error and record.pluginClass:
            textLayout.addWidget(makeLabel(record.error, "error", True))
        layout.addLayout(textLayout, 1)
        actionsLayout = QHBoxLayout()
        actionsLayout.setSpacing(6)
        if not record.installed:
            reinstallButton = makeButton(tr("plugins.reinstall"), "download", "primary")
            reinstallButton.clicked.connect(lambda: app.pluginManager.reinstall(pluginId))
            actionsLayout.addWidget(reinstallButton)
        else:
            if record.status == "error" or getattr(record, "problem", None):
                detailsButton = makeButton(tr("plugin.errorDetails"), "file-text", "ghost")
                detailsButton.clicked.connect(lambda: app.showPluginErrorDetails(pluginId))
                actionsLayout.addWidget(detailsButton)
            if manager.globalSetting(pluginId, "hidden"):
                showButton = makeButton(tr("plugins.show"), "eye", "ghost")
                showButton.clicked.connect(lambda: manager.setGlobalSetting(pluginId, "hidden", False))
                actionsLayout.addWidget(showButton)
            openButton = makeButton(tr("common.open"), "external-link", "ghost")
            openButton.clicked.connect(lambda: app.openPlugin(pluginId))
            actionsLayout.addWidget(openButton)
            enabledToggle = ToggleSwitch(bool(manager.globalSetting(pluginId, "enabled")) and record.status != "error")
            enabledToggle.toggled.connect(lambda checked: app.retryBrokenPlugin(pluginId) if checked else app.disableBrokenPlugin(pluginId))
            actionsLayout.addWidget(enabledToggle)
            uninstallButton = iconButton("trash-2", tr("plugin.global.uninstallButton"), "danger", 16)
            uninstallButton.clicked.connect(lambda: app.requestUninstall(pluginId))
            actionsLayout.addWidget(uninstallButton)
        layout.addLayout(actionsLayout)


class PluginsPage(QWidget):
    def dragEnterEvent(self, event):
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        if any(url.toLocalFile().lower().endswith(".zip") for url in urls):
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            localPath = url.toLocalFile()
            if localPath.lower().endswith(".zip"):
                QTimer.singleShot(0, lambda path=localPath: self.app.installPluginFromZip(path))
        event.acceptProposedAction()

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        scrollArea, self.contentLayout = makeScrollPage((28, 22, 28, 28), 12)
        layout.addWidget(scrollArea)
        headerLayout = QHBoxLayout()
        headerLayout.setSpacing(14)
        headerLayout.addWidget(IconTile("puzzle", 46))
        titleLayout = QVBoxLayout()
        titleLayout.setSpacing(2)
        titleLayout.addWidget(makeLabel(tr("plugins.title"), "title"))
        titleLayout.addWidget(makeLabel(tr("plugins.subtitle"), "muted"))
        headerLayout.addLayout(titleLayout, 1)
        reloadButton = makeButton(tr("plugins.reload"), "rotate-cw", "ghost", tooltip=tr("plugins.reloadTip"))
        reloadButton.clicked.connect(app.reloadUserPluginsWithFeedback)
        headerLayout.addWidget(reloadButton)
        folderButton = makeButton(tr("plugins.openFolder"), "folder-open")
        folderButton.clicked.connect(app.openPluginsFolder)
        headerLayout.addWidget(folderButton)
        newButton = makeButton(tr("plugins.newPlugin"), "plus")
        newButton.clicked.connect(lambda: app.createPluginFromTemplate())
        headerLayout.addWidget(newButton)
        installButton = makeButton(tr("plugins.installZip"), "package", "primary")
        installButton.clicked.connect(lambda: app.installPluginFromZip())
        headerLayout.addWidget(installButton)
        self.contentLayout.addLayout(headerLayout)
        howCard = Card(padding=14, hoverable=False)
        howLayout = QHBoxLayout(howCard)
        howLayout.setSpacing(18)
        howLayout.addWidget(IconWidget("info", "accent", 20), 0, Qt.AlignTop)
        stepsLayout = QVBoxLayout()
        stepsLayout.setSpacing(4)
        stepsLayout.addWidget(makeLabel(tr("plugins.howTitle"), "subtitle"))
        for iconName, key in (("package", "plugins.howZip"), ("folder-open", "plugins.howFolder"), ("plus", "plugins.howNew")):
            stepRow = QHBoxLayout()
            stepRow.setSpacing(8)
            stepRow.addWidget(IconWidget(iconName, "muted", 15))
            stepRow.addWidget(makeLabel(tr(key), "muted", True), 1)
            stepsLayout.addLayout(stepRow)
        howLayout.addLayout(stepsLayout, 1)
        self.contentLayout.addWidget(howCard)
        self.setAcceptDrops(True)
        self.listHost = QWidget()
        self.listLayout = QVBoxLayout(self.listHost)
        self.listLayout.setContentsMargins(0, 0, 0, 0)
        self.listLayout.setSpacing(0)
        self.contentLayout.addWidget(self.listHost)
        self.contentLayout.addStretch(1)
        manager = app.pluginManager
        manager.pluginsChanged.connect(self.rebuild)
        manager.statusChanged.connect(self._onStatusChanged)
        manager.globalSettingChanged.connect(self._onGlobalChanged)
        self.rebuildTimer = QTimer(self)
        self.rebuildTimer.setSingleShot(True)
        self.rebuildTimer.setInterval(60)
        self.rebuildTimer.timeout.connect(self.rebuild)
        self.rebuild()

    def _onStatusChanged(self, pluginId):
        self.rebuildTimer.start()

    def _onGlobalChanged(self, pluginId, key, value):
        if key in ("hidden", "enabled", "customName", "customIcon"):
            self.rebuildTimer.start()

    def rebuild(self):
        clearLayout(self.listLayout)
        manager = self.app.pluginManager
        installedRecords = manager.installedRecords()
        sectionLabel = makeLabel(f"{tr('plugins.installed').upper()} · {len(installedRecords)}", "section")
        sectionLabel.setContentsMargins(6, 6, 0, 0)
        self.listLayout.addWidget(sectionLabel)
        for record in installedRecords:
            self.listLayout.addWidget(PluginCard(self.app, record))
        uninstalledRecords = manager.uninstalledRecords()
        if uninstalledRecords:
            sectionLabel = makeLabel(f"{tr('plugins.uninstalled').upper()} · {len(uninstalledRecords)}", "section")
            sectionLabel.setContentsMargins(6, 14, 0, 0)
            self.listLayout.addWidget(sectionLabel)
            for record in uninstalledRecords:
                self.listLayout.addWidget(PluginCard(self.app, record))
