from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from pchub import APP_NAME
from pchub.core.i18n import T, tr
from pchub.ui.icons import makeIcon
from pchub.ui.theme import theme


class TrayController:
    def __init__(self, app):
        self.app = app
        self.available = QSystemTrayIcon.isSystemTrayAvailable()
        self.trayIcon = QSystemTrayIcon(app.appIcon)
        self.trayIcon.setToolTip(APP_NAME)
        self.menu = QMenu()
        self.menu.aboutToShow.connect(self.rebuildMenu)
        self.trayIcon.setContextMenu(self.menu)
        self.trayIcon.activated.connect(self._onActivated)
        app.activeRegistry.changed.connect(self.refreshTooltip)
        self.rebuildMenu()
        if self.available:
            self.trayIcon.show()

    def _onActivated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.app.toggleMainWindow()

    def refreshTooltip(self):
        activeCount = self.app.activeRegistry.count()
        tooltip = APP_NAME if not activeCount else f"{APP_NAME} — {tr('tray.activeCount', count=activeCount)}"
        self.trayIcon.setToolTip(tooltip)

    def rebuildMenu(self):
        menu = self.menu
        menu.clear()
        textColor = theme().text.name()
        titleAction = menu.addAction(makeIcon("layout-grid", theme().accentLight.name(), 16), APP_NAME)
        titleAction.setEnabled(False)
        pinnedItems = self.app.pinService.items()
        currentPluginId = None
        for item in pinnedItems:
            if item.pluginId != currentPluginId:
                currentPluginId = item.pluginId
                menu.addSection(self.app.pluginManager.displayName(item.pluginId))
            iconName = item.icon or self.app.pluginManager.displayIcon(item.pluginId)
            if item.kind == "toggle":
                action = menu.addAction(item.label)
                action.setCheckable(True)
                action.setChecked(bool(item.getValue()))
                action.toggled.connect(lambda checked, pinned=item: pinned.setValue(checked))
            elif item.kind == "action":
                action = menu.addAction(makeIcon(iconName, textColor, 16), item.label)
                action.triggered.connect(lambda checked=False, pinned=item: pinned.run())
            else:
                currentValue = item.getValue()
                currentLabel = next((label for value, label in item.options if value == currentValue),
                                    item.formatValue(currentValue))
                subMenu = menu.addMenu(makeIcon(iconName, textColor, 16), f"{item.label}: {currentLabel}")
                for optionValue, optionLabel in item.options:
                    optionAction = subMenu.addAction(optionLabel)
                    optionAction.setCheckable(True)
                    optionAction.setChecked(optionValue == currentValue)
                    optionAction.triggered.connect(lambda checked=False, pinned=item, value=optionValue: pinned.setValue(value))
        menu.addSeparator()
        openAction = menu.addAction(makeIcon("app-window", textColor, 16), tr("tray.open"))
        openAction.triggered.connect(lambda: self.app.showMainWindow())
        settingsAction = menu.addAction(makeIcon("settings", textColor, 16), tr("tray.settings"))
        settingsAction.triggered.connect(lambda: self.app.showMainWindow("settings"))
        menu.addSeparator()
        restartAction = menu.addAction(makeIcon("rotate-cw", textColor, 16), tr(T("Riavvia PC Hub", "Restart PC Hub")))
        restartAction.triggered.connect(self.app.restart)
        quitAction = menu.addAction(makeIcon("power", theme().danger.name(), 16), tr("tray.quit"))
        quitAction.triggered.connect(self.app.quit)

    def showMessage(self, title, message):
        if self.available:
            self.trayIcon.showMessage(title, message, self.app.appIcon, 5000)

    def hide(self):
        self.trayIcon.hide()
