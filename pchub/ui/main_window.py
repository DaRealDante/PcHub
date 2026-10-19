from PySide6.QtCore import QByteArray, Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from pchub import APP_NAME
from pchub.core import system
from pchub.core.i18n import tr
from pchub.ui.background import BackgroundWidget
from pchub.ui.sidebar import SidebarPanel
from pchub.ui.theme import theme, themeManager
from pchub.ui.widgets import AnimatedStack


class MainWindow(QWidget):
    def __init__(self, app):
        super().__init__(None, Qt.Window)
        self.app = app
        self.pages = {}
        self.currentKey = None
        self.trayHintShown = bool(app.appStore.get("ui.trayHintShown", False))
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app.appIcon)
        self.setMinimumSize(980, 620)
        self.background = BackgroundWidget(self)
        outerLayout = QVBoxLayout(self)
        outerLayout.setContentsMargins(0, 0, 0, 0)
        outerLayout.addWidget(self.background)
        rootLayout = QHBoxLayout(self.background)
        rootLayout.setContentsMargins(12, 12, 0, 6)
        rootLayout.setSpacing(0)
        self.sidebar = SidebarPanel()
        self.sidebar.navigate.connect(self.showPage)
        rootLayout.addWidget(self.sidebar)
        self.stack = AnimatedStack()
        rootLayout.addWidget(self.stack, 1)
        geometryText = app.appStore.get("ui.mainGeometry")
        if geometryText:
            self.restoreGeometry(QByteArray.fromBase64(geometryText.encode("ascii")))
        else:
            self.resize(1280, 820)
        themeManager().changed.connect(self._applyFrame)

    def addPage(self, key, widget):
        oldWidget = self.pages.get(key)
        if oldWidget is widget:
            return
        if oldWidget is not None:
            self.stack.removeWidget(oldWidget)
        self.pages[key] = widget
        self.stack.addWidget(widget)

    def removePage(self, key):
        widget = self.pages.pop(key, None)
        if widget is not None:
            self.stack.removeWidget(widget)
        if self.currentKey == key:
            self.showPage("home")
        return widget

    def showPage(self, key, animated=True):
        widget = self.pages.get(key)
        if widget is None:
            key = "home"
            widget = self.pages.get("home")
        if widget is None:
            return
        self.currentKey = key
        if animated:
            self.stack.setCurrentAnimated(widget)
        else:
            self.stack.setCurrentWidget(widget)
        self.sidebar.setCurrent(key)
        self.app.appStore.set("ui.lastPage", key)

    def bringToFront(self):
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()
        system.forceForeground(self)

    def _applyFrame(self):
        system.applyWindowFrame(self, theme().windowColor.name())

    def showEvent(self, event):
        super().showEvent(event)
        self._applyFrame()

    def saveGeometryState(self):
        self.app.appStore.set("ui.mainGeometry", bytes(self.saveGeometry().toBase64()).decode("ascii"))

    def closeEvent(self, event):
        self.saveGeometryState()
        if self.app.appSetting("general.closeToTray") and self.app.trayAvailable() and not self.app.quitting:
            event.ignore()
            self.hide()
            if not self.trayHintShown:
                self.trayHintShown = True
                self.app.appStore.set("ui.trayHintShown", True)
                self.app.notify("PC Hub", tr("tray.stillRunning"))
            return
        event.accept()
        if not self.app.quitting:
            self.app.quit()
