from PySide6.QtCore import QByteArray, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from pchub import APP_NAME
from pchub.core import system
from pchub.core.i18n import tr
from pchub.core.settings_schema import (ActionButton, HotkeySetting, InfoRow, Section, TextInput, Toggle)
from pchub.ui.adapters import PluginGlobalAdapter, PluginSettingsAdapter
from pchub.ui.background import BackgroundWidget
from pchub.ui.settings_form import SettingsForm
from pchub.ui.theme import theme, themeManager
from pchub.ui.widgets import (AnimatedStack, Banner, EmptyState, IconTile, iconButton, makeButton, makeLabel,
                              makeScrollPage, setRole, statusChipRole, Card)


def globalSchema(app, record):
    pluginClass = record.pluginClass
    manager = app.pluginManager
    schema = [
        Section(tr("plugin.global.general")),
        Toggle("enabled", tr("plugin.global.enabled"), description=tr("plugin.global.enabledDesc"), icon="power"),
        HotkeySetting("openHotkey", tr("plugin.global.openHotkey"), action=None, description=tr("plugin.global.openHotkeyDesc"),
                      icon="keyboard"),
        Toggle("separateWindow", tr("plugin.global.separateWindow"), description=tr("plugin.global.separateWindowDesc"),
               pinnable=False, icon="app-window"),
        Toggle("alwaysOnTop", tr("plugin.global.alwaysOnTop"), visibleIf=("separateWindow", True), pinnable=False,
               icon="layers"),
        Toggle("showInActive", tr("plugin.global.showInActive"), description=tr("plugin.global.showInActiveDesc"),
               pinnable=False, icon="activity"),
    ]
    if pluginClass.restartable:
        schema.append(Toggle("autoRestart", tr("plugin.global.autoRestart"), pinnable=False, icon="refresh-cw"))
    schema += [
        Section(tr("plugin.global.appearance")),
        TextInput("customName", tr("plugin.global.customName"), placeholder=tr(pluginClass.name), icon="pencil"),
        ActionButton("changeIcon", tr("plugin.global.changeIcon"), action=None,
                     buttonText=tr("plugin.global.changeIconButton"), pinnable=False, icon="palette"),
        Toggle("hidden", tr("plugin.global.hidden"), description=tr("plugin.global.hiddenDesc"), pinnable=False,
               icon="eye-off"),
        Section(tr("plugin.global.info")),
        InfoRow("infoVersion", tr("plugin.global.version"), lambda: pluginClass.version, icon="tag"),
        InfoRow("infoAuthor", tr("plugin.global.author"), lambda: pluginClass.author, icon="user"),
        InfoRow("infoSource", tr("plugin.global.source"),
                lambda: tr("plugin.global.builtin") if record.builtin else tr("plugin.global.userPlugin"), icon="package"),
        InfoRow("infoAdmin", tr("plugin.global.adminRequired"),
                lambda: tr("common.yes") if pluginClass.requiresAdmin else tr("common.no"), icon="shield"),
        InfoRow("infoRestartable", tr("plugin.global.restartable"),
                lambda: tr("common.yes") if pluginClass.restartable else tr("common.no"), icon="rotate-cw"),
        Section(tr("plugin.global.danger")),
        ActionButton("uninstall", tr("plugin.global.uninstall"), action=None, description=tr("plugin.global.uninstallDesc"),
                     buttonText=tr("plugin.global.uninstallButton"), danger=True, pinnable=False, icon="trash-2"),
    ]
    return schema


class PluginPageHost(QWidget):
    """Header (icon, title, status, restart, pop-out, gear) + plugin content / settings."""
    detachRequested = Signal(str)

    def __init__(self, app, record, parent=None):
        super().__init__(parent)
        self.app = app
        self.record = record
        self.pluginId = record.pluginId
        self.inSeparateWindow = False
        manager = app.pluginManager
        rootLayout = QVBoxLayout(self)
        rootLayout.setContentsMargins(28, 22, 28, 0)
        rootLayout.setSpacing(14)

        headerLayout = QHBoxLayout()
        headerLayout.setSpacing(14)
        self.iconTile = IconTile(manager.displayIcon(self.pluginId), 46)
        headerLayout.addWidget(self.iconTile)
        titleLayout = QVBoxLayout()
        titleLayout.setSpacing(2)
        titleRow = QHBoxLayout()
        titleRow.setSpacing(10)
        self.titleLabel = makeLabel(manager.displayName(self.pluginId), "title")
        titleRow.addWidget(self.titleLabel)
        self.statusChip = makeLabel("", "chip")
        titleRow.addWidget(self.statusChip, 0, Qt.AlignVCenter)
        titleRow.addStretch(1)
        titleLayout.addLayout(titleRow)
        self.descriptionLabel = makeLabel(tr(record.pluginClass.description), "muted", True)
        titleLayout.addWidget(self.descriptionLabel)
        headerLayout.addLayout(titleLayout, 1)
        self.restartButton = makeButton(tr("plugin.restart"), "rotate-cw", tooltip=tr("plugin.restartTip"))
        self.restartButton.clicked.connect(lambda: manager.restartPlugin(self.pluginId))
        headerLayout.addWidget(self.restartButton)
        self.popOutButton = iconButton("square-arrow-out-up-right", tr("plugin.popOut"), "muted", 18)
        self.popOutButton.clicked.connect(lambda: self.detachRequested.emit(self.pluginId))
        headerLayout.addWidget(self.popOutButton)
        self.gearButton = iconButton("settings", tr("plugin.settingsTip"), "muted", 19, checkable=True)
        self.gearButton.toggled.connect(self._toggleSettings)
        headerLayout.addWidget(self.gearButton)
        rootLayout.addLayout(headerLayout)

        self.bodyStack = AnimatedStack()
        rootLayout.addWidget(self.bodyStack, 1)

        self.contentPage = QWidget()
        contentLayout = QVBoxLayout(self.contentPage)
        contentLayout.setContentsMargins(0, 0, 0, 0)
        contentLayout.setSpacing(12)
        self.banner = Banner("circle-alert", "", theme().warning, " ", self._bannerAction)
        self.bannerDisableButton = makeButton(tr("plugin.disable"), "power")
        self.bannerDisableButton.clicked.connect(lambda: manager.setEnabled(self.pluginId, False))
        self.bannerUninstallButton = makeButton(tr("plugin.global.uninstallButton"), "trash-2", "danger")
        self.bannerUninstallButton.clicked.connect(lambda: app.requestUninstall(self.pluginId))
        self.bannerDetailsButton = makeButton(tr("plugin.errorDetails"), "file-text", "ghost")
        self.bannerDetailsButton.clicked.connect(lambda: app.showPluginErrorDetails(self.pluginId))
        bannerLayout = self.banner.layout()
        bannerLayout.insertWidget(bannerLayout.count() - 1, self.bannerDetailsButton)
        bannerLayout.insertWidget(bannerLayout.count() - 1, self.bannerUninstallButton)
        bannerLayout.insertWidget(bannerLayout.count() - 1, self.bannerDisableButton)
        self.banner.hide()
        contentLayout.addWidget(self.banner)
        self.pluginWidget = None
        try:
            self.pluginWidget = record.instance.createPage() if record.instance else None
        except Exception as error:
            app.reportPluginProblem(self.pluginId, error, "createPage")
            self.pluginWidget = EmptyState("circle-alert", tr("status.error"), f"{type(error).__name__}: {error}")
        self.specificForm = None
        specificSchema = record.schema
        if self.pluginWidget is None:
            scrollArea, scrollLayout = makeScrollPage((0, 4, 0, 24))
            if specificSchema:
                self.specificForm = SettingsForm(specificSchema, PluginSettingsAdapter(app, self.pluginId))
                scrollLayout.addWidget(self.specificForm)
            else:
                scrollLayout.addWidget(EmptyState("puzzle", manager.displayName(self.pluginId), ""))
            scrollLayout.addStretch(1)
            contentLayout.addWidget(scrollArea, 1)
        elif getattr(self.pluginWidget, "noScroll", False):
            contentLayout.addWidget(self.pluginWidget, 1)
        else:
            scrollArea, scrollLayout = makeScrollPage((0, 4, 0, 24))
            scrollLayout.addWidget(self.pluginWidget)
            scrollLayout.addStretch(1)
            contentLayout.addWidget(scrollArea, 1)
        self.bodyStack.addWidget(self.contentPage)

        settingsScroll, settingsLayout = makeScrollPage((0, 4, 0, 24))
        backButton = makeButton(tr("plugin.backToContent"), "chevron-left", "ghost")
        backButton.clicked.connect(lambda: self.gearButton.setChecked(False))
        settingsLayout.addLayout(_leftAligned(backButton))
        settingsLayout.addWidget(SettingsForm(globalSchema(app, record), PluginGlobalAdapter(app, self.pluginId)))
        if self.pluginWidget is not None and specificSchema and not getattr(record.pluginClass, "settingsInPage", False):
            specificTitle = makeLabel(tr("plugin.global.specific"), "subtitle")
            specificTitle.setContentsMargins(4, 14, 0, 0)
            settingsLayout.addWidget(specificTitle)
            settingsLayout.addWidget(SettingsForm(specificSchema, PluginSettingsAdapter(app, self.pluginId)))
        settingsLayout.addStretch(1)
        self.settingsPage = settingsScroll
        self.bodyStack.addWidget(self.settingsPage)

        manager.statusChanged.connect(self._onStatusChanged)
        manager.globalSettingChanged.connect(self._onGlobalChanged)
        self.refreshStatus()

    def showSettings(self, show=True):
        self.gearButton.setChecked(show)

    def _toggleSettings(self, checked):
        self.bodyStack.setCurrentAnimated(self.settingsPage if checked else self.contentPage)

    def _onStatusChanged(self, pluginId):
        if pluginId == self.pluginId:
            self.refreshStatus()

    def _onGlobalChanged(self, pluginId, key, value):
        if pluginId != self.pluginId:
            return
        manager = self.app.pluginManager
        if key == "customName":
            self.titleLabel.setText(manager.displayName(pluginId))
        elif key == "customIcon":
            self.iconTile.setIconName(manager.displayIcon(pluginId))

    def refreshStatus(self):
        record = self.record
        status = record.status
        self.statusChip.setText(tr(f"status.{status}") if status != "uninstalled" else "")
        setRole(self.statusChip, statusChipRole(status))
        self.restartButton.setVisible(bool(record.pluginClass.restartable and status in ("running", "error")))
        self.popOutButton.setVisible(not self.inSeparateWindow)
        currentTheme = theme()
        bannerSpecs = {
            "disabled": ("power", tr("plugin.disabledBanner"), currentTheme.textMuted, tr("plugin.enable")),
            "blocked": ("shield-alert", tr("plugin.blockedBanner"), currentTheme.warning, tr("plugin.enableAdmin")),
            "error": ("triangle-alert", tr("plugin.errorBanner", error=record.error), currentTheme.danger,
                      tr("plugin.restart") if record.pluginClass.restartable else None),
        }
        spec = bannerSpecs.get(status)
        errorState = status == "error"
        for button in (self.bannerDisableButton, self.bannerUninstallButton, self.bannerDetailsButton):
            button.setVisible(errorState)
        if spec:
            iconName, text, color, buttonText = spec
            self.banner.iconWidget.setIconName(iconName)
            self.banner.iconWidget.setRole(color)
            self.banner.setTint(color)
            self.banner.setText(text)
            if self.banner.button:
                self.banner.button.setVisible(bool(buttonText))
                if buttonText:
                    self.banner.button.setText(buttonText)
            self.banner.show()
        else:
            self.banner.hide()
        if self.pluginWidget is not None:
            self.pluginWidget.setEnabled(status in ("running", "stopped"))

    def _bannerAction(self):
        status = self.record.status
        if status == "disabled":
            self.app.pluginManager.setEnabled(self.pluginId, True)
        elif status == "blocked":
            self.app.requestAdvancedPermissions()
        elif status == "error":
            self.app.pluginManager.restartPlugin(self.pluginId)


def _leftAligned(widget):
    rowLayout = QHBoxLayout()
    rowLayout.setContentsMargins(0, 0, 0, 0)
    rowLayout.addWidget(widget)
    rowLayout.addStretch(1)
    return rowLayout


class DetachedPlaceholder(QWidget):
    def __init__(self, app, pluginId, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.addStretch(1)
        card = Card(padding=26, hoverable=False)
        cardLayout = QVBoxLayout(card)
        cardLayout.setSpacing(10)
        cardLayout.addWidget(IconTile(app.pluginManager.displayIcon(pluginId), 52), 0, Qt.AlignHCenter)
        titleLabel = makeLabel(tr("plugin.detachedTitle"), "subtitle")
        titleLabel.setAlignment(Qt.AlignCenter)
        cardLayout.addWidget(titleLabel)
        textLabel = makeLabel(tr("plugin.detachedText"), "muted", True)
        textLabel.setAlignment(Qt.AlignCenter)
        cardLayout.addWidget(textLabel)
        attachButton = makeButton(tr("plugin.attachBack"), "minimize-2", "primary")
        attachButton.clicked.connect(lambda: app.attachPlugin(pluginId))
        cardLayout.addWidget(attachButton, 0, Qt.AlignHCenter)
        layout.addWidget(card, 0, Qt.AlignHCenter)
        layout.addStretch(2)


class PluginWindow(QWidget):
    closed = Signal(str)

    def __init__(self, app, host):
        super().__init__(None, Qt.Window)
        self.app = app
        self.host = host
        self.pluginId = host.pluginId
        self.setWindowTitle(f"{app.pluginManager.displayName(self.pluginId)} — {APP_NAME}")
        self.setWindowIcon(app.appIcon)
        self.background = BackgroundWidget(self)
        backgroundLayout = QVBoxLayout(self.background)
        backgroundLayout.setContentsMargins(0, 0, 0, 0)
        backgroundLayout.addWidget(host)
        outerLayout = QVBoxLayout(self)
        outerLayout.setContentsMargins(0, 0, 0, 0)
        outerLayout.addWidget(self.background)
        host.inSeparateWindow = True
        host.refreshStatus()
        self.applyAlwaysOnTop()
        savedGeometry = app.pluginManager.globalSetting(self.pluginId, "windowGeometry")
        if savedGeometry:
            self.restoreGeometry(QByteArray.fromBase64(savedGeometry.encode("ascii")))
        else:
            self.resize(760, 640)
        themeManager().changed.connect(self._applyFrame)

    def applyAlwaysOnTop(self):
        onTop = bool(self.app.pluginManager.globalSetting(self.pluginId, "alwaysOnTop"))
        wasVisible = self.isVisible()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, onTop)
        if wasVisible:
            self.show()

    def _applyFrame(self):
        system.applyWindowFrame(self, theme().windowColor.name())

    def showEvent(self, event):
        super().showEvent(event)
        self._applyFrame()

    def saveGeometryState(self):
        self.app.pluginManager.setGlobalSetting(self.pluginId, "windowGeometry",
                                                bytes(self.saveGeometry().toBase64()).decode("ascii"))

    def hideEvent(self, event):
        self.saveGeometryState()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.saveGeometryState()
        self.closed.emit(self.pluginId)
        super().closeEvent(event)


class PluginErrorHost(QWidget):
    """Page shown for a plugin that can't even build its page (or failed to load): says what broke and lets the
    user disable or uninstall it. Exposes the same small API the app uses on PluginPageHost."""
    detachRequested = Signal(str)

    def __init__(self, app, record, errorText, detailsText=""):
        super().__init__()
        self.app = app
        self.record = record
        self.pluginId = record.pluginId
        self.inSeparateWindow = False
        self.pluginWidget = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(14)
        headerLayout = QHBoxLayout()
        headerLayout.setSpacing(14)
        dormant = record.dormant or (record.status == "disabled" and record.instance is None)
        headerLayout.addWidget(IconTile(app.pluginManager.displayIcon(self.pluginId) if dormant else "triangle-alert", 46,
                                        None if dormant else theme().danger))
        titleLayout = QVBoxLayout()
        titleLayout.setSpacing(2)
        titleLayout.addWidget(makeLabel(app.pluginManager.displayName(self.pluginId), "title"))
        dormant = record.dormant or (record.status == "disabled" and record.instance is None)
        titleLayout.addWidget(makeLabel(tr("status.disabled") if dormant else tr("plugin.brokenSubtitle"), "muted", True))
        headerLayout.addLayout(titleLayout, 1)
        layout.addLayout(headerLayout)
        card = Card(padding=18, hoverable=False, tint=None if dormant else theme().danger)
        cardLayout = QVBoxLayout(card)
        cardLayout.setSpacing(10)
        if dormant:
            cardLayout.addWidget(makeLabel(tr("plugin.safeModeMessage") if record.safeMode else tr("plugin.dormantMessage"),
                                           None, True))
        else:
            cardLayout.addWidget(makeLabel(tr("plugin.brokenMessage"), None, True))
            errorLabel = makeLabel(errorText, "error", True)
            errorLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
            cardLayout.addWidget(errorLabel)
        buttonRow = QHBoxLayout()
        buttonRow.addStretch(1)
        if not dormant and (record.pluginClass is None or record.pluginClass.restartable):
            retryButton = makeButton(tr("plugin.enableRetry"), "rotate-cw")
            retryButton.clicked.connect(lambda: app.retryBrokenPlugin(self.pluginId))
            buttonRow.addWidget(retryButton)
        if detailsText:
            detailsButton = makeButton(tr("plugin.errorDetails"), "file-text", "ghost")
            detailsButton.clicked.connect(lambda: app.showPluginErrorDetails(self.pluginId))
            buttonRow.addWidget(detailsButton)
        uninstallButton = makeButton(tr("plugin.global.uninstallButton"), "trash-2", "danger")
        uninstallButton.clicked.connect(lambda: app.requestUninstall(self.pluginId))
        buttonRow.addWidget(uninstallButton)
        if app.pluginManager.globalSetting(self.pluginId, "enabled") and not dormant:
            disableButton = makeButton(tr("plugin.disable"), "power", "primary")
            disableButton.clicked.connect(lambda: app.disableBrokenPlugin(self.pluginId))
            buttonRow.addWidget(disableButton)
        else:
            enableButton = makeButton(tr("plugin.enableRetry"), "rotate-cw", "primary")
            enableButton.clicked.connect(lambda: app.retryBrokenPlugin(self.pluginId))
            buttonRow.addWidget(enableButton)
        cardLayout.addLayout(buttonRow)
        layout.addWidget(card)
        layout.addStretch(1)

    def refreshStatus(self):
        pass

    def showSettings(self, show=True):
        pass
