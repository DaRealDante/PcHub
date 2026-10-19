import logging

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from conftest import processEvents


class ErrorCollector(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture(scope="module")
def hub(qtApp, tmp_path_factory):
    import os
    os.environ["PCHUB_DATA_DIR"] = str(tmp_path_factory.mktemp("hubdata"))
    from pchub.app import PCHubApp
    collector = ErrorCollector()
    logging.getLogger("pchub").addHandler(collector)
    application = PCHubApp(["pchub", "--no-splash", "--no-user-plugins"])
    assert application.setup()
    application.mainWindow.show()
    application.mainWindow.resize(1300, 840)
    processEvents(300)
    application.errorCollector = collector
    yield application
    application._shutdown()
    logging.getLogger("pchub").removeHandler(collector)


def test_every_page_renders(hub):
    window = hub.mainWindow
    for key in list(window.pages):
        window.showPage(key, animated=True)
        processEvents(260)
        assert window.currentKey == key
        window.grab()
    from pchub.plugins import BUILTIN_PLUGINS
    assert set(hub.hosts) == {moduleName.split(".")[-2] for moduleName in BUILTIN_PLUGINS}


def test_theme_switch_is_live(hub):
    from pchub.ui.theme import theme
    hub.setAppSetting("appearance.style", "clay")
    processEvents(100)
    assert theme().styleId == "clay"
    hub.mainWindow.grab()
    hub.setAppSetting("appearance.accent", "#34D399")
    assert theme().accent.name().upper() == "#34D399"
    hub.setAppSetting("appearance.mouseEffects", False)
    hub.setAppSetting("appearance.parallax", False)
    hub.mainWindow.grab()
    hub.setAppSetting("appearance.style", "glass")
    hub.setAppSetting("appearance.mouseEffects", True)
    hub.setAppSetting("appearance.parallax", True)
    assert theme().styleId == "glass"


def test_sidebar_folders_and_drag_move(hub):
    from pchub.ui.sidebar import ID_ROLE, KIND_ROLE
    hub.appStore.set("sidebar.layout", [{"type": "folder", "id": "tools", "name": "Strumenti", "icon": "",
                                         "expanded": True, "children": []}])
    hub.refreshSidebar()
    tree = hub.mainWindow.sidebar.tree
    folderItem = tree.topLevelItem(0)
    assert folderItem.data(0, KIND_ROLE) == "folder"
    timerItem = tree.findPluginItem("timer")
    assert tree.moveItem(timerItem, folderItem, "on")
    hub._saveSidebarLayout()
    layout = hub.appStore.get("sidebar.layout")
    assert layout[0]["children"] == [{"type": "plugin", "id": "timer"}]
    assert not tree.moveItem(folderItem, folderItem, "on"), "a folder can't go inside itself"
    cleanerItem = tree.findPluginItem("cleaner")
    assert tree.moveItem(cleanerItem, folderItem, "above")
    hub._saveSidebarLayout()
    assert hub.appStore.get("sidebar.layout")[0]["id"] == "cleaner"
    hub.refreshSidebar()
    assert tree.findPluginItem("timer").parent().data(0, ID_ROLE) == "tools"


def test_home_widgets_add_resize_move_remove(hub):
    home = hub.mainWindow.pages["home"]
    home.setEditMode(True)
    startCount = len(home.entries())
    home.addWidget("system_monitor.overview")
    assert len(home.entries()) == startCount + 1 and len(home.cards) == startCount + 1
    newUid = home.entries()[-1]["uid"]
    home.cycleSize(newUid)
    assert next(entry for entry in home.entries() if entry["uid"] == newUid)["size"] != "wide"
    firstUid = home.entries()[0]["uid"]
    home.moveWidget(newUid, firstUid)
    assert home.entries()[0]["uid"] == newUid
    home.removeWidget(newUid)
    assert len(home.entries()) == startCount
    home.setEditMode(False)
    hub.mainWindow.showPage("home", animated=False)
    processEvents(100)
    hub.mainWindow.grab()


def test_detach_and_attach_plugin_window(hub):
    hub.detachPlugin("timer")
    processEvents(100)
    assert "timer" in hub.detachedWindows
    window = hub.detachedWindows["timer"]
    assert window.isVisible() and window.host is hub.hosts["timer"]
    assert hub.mainWindow.pages["plugin:timer"] is not hub.hosts["timer"]
    window.close()
    processEvents(100)
    assert "timer" not in hub.detachedWindows
    assert hub.mainWindow.pages["plugin:timer"] is hub.hosts["timer"]
    hub.pluginManager.setGlobalSetting("timer", "separateWindow", True)
    hub.openPlugin("timer", viaHotkey=True)
    processEvents(100)
    assert "timer" in hub.detachedWindows
    hub.attachPlugin("timer")
    hub.pluginManager.setGlobalSetting("timer", "separateWindow", False)


def test_disable_from_tray_pin_and_banner(hub):
    hub.pinService.setPinned("timer:@enabled", True)
    hub.pinService.setPinned("system_monitor:interval", False)
    hub.pinService.setPinned("timer:quickMinutes", True)
    hub.pinService.setPinned("cleaner:cleanNow", True)
    hub.tray.rebuildMenu()
    timerName = hub.pluginManager.displayName("timer")
    labels = [action.text() for action in hub.tray.menu.actions()]
    assert timerName in labels
    toggleAction = next(action for action in hub.tray.menu.actions() if action.text() == timerName and action.isCheckable())
    toggleAction.trigger()
    assert hub.pluginManager.records["timer"].status == "disabled"
    host = hub.hosts["timer"]
    hub.mainWindow.showPage("plugin:timer", animated=False)
    processEvents(50)
    assert host.banner.isVisible()
    host.banner.button.click()
    assert hub.pluginManager.records["timer"].status == "running"
    assert not host.banner.isVisible()


def test_uninstall_and_reinstall_builtin(hub, monkeypatch):
    import pchub.ui.dialogs as dialogs
    monkeypatch.setattr(dialogs, "confirm", lambda *args, **kwargs: (True, False))
    hub.requestUninstall("cleaner")
    assert "cleaner" not in hub.hosts
    assert hub.mainWindow.sidebar.tree.findPluginItem("cleaner") is None
    assert hub.pluginManager.records["cleaner"].status == "uninstalled"
    hub.mainWindow.showPage("plugins", animated=False)
    processEvents(50)
    hub.pluginManager.reinstall("cleaner")
    processEvents(50)
    assert "cleaner" in hub.hosts
    assert hub.mainWindow.sidebar.tree.findPluginItem("cleaner") is not None


def test_hotkey_edit_records_keys(hub):
    from pchub.ui.widgets import HotkeyEdit
    edit = HotkeyEdit("")
    edit.show()
    captured = []
    edit.sequenceChanged.connect(captured.append)
    QTest.mouseClick(edit, Qt.LeftButton)
    assert edit.recording and hub.hotkeys.suspended
    QTest.keyClick(edit, Qt.Key_J, Qt.ControlModifier | Qt.AltModifier)
    assert captured == ["Ctrl+Alt+J"] and not edit.recording and not hub.hotkeys.suspended
    QTest.mouseClick(edit, Qt.LeftButton)
    QTest.keyClick(edit, Qt.Key_Delete)
    assert captured[-1] == ""
    edit.close()


def test_app_hotkey_and_conflicts(hub):
    hub.setAppSetting("general.openHotkey", "Ctrl+Alt+Y")
    assert hub.appHotkeyResult.ok
    hub.pluginManager.setGlobalSetting("timer", "openHotkey", "Ctrl+Alt+Y")
    result = hub.pluginManager.hotkeyStatus["open:timer"]
    assert not result.ok and result.reason == "conflictInternal"
    from pchub.ui.adapters import hotkeyErrorText
    assert "PC Hub" in hotkeyErrorText(result, hub.hotkeys)
    hub.pluginManager.setGlobalSetting("timer", "openHotkey", "Ctrl+Alt+U")
    assert hub.pluginManager.hotkeyStatus["open:timer"].ok
    hub.mainWindow.hide()
    assert hub.hotkeys.simulate("Ctrl+Alt+U")
    processEvents(100)
    assert hub.mainWindow.isVisible() and hub.mainWindow.currentKey == "plugin:timer"


def test_confirm_on_toggle_is_respected(hub, monkeypatch):
    from pchub.ui.adapters import PluginSettingsAdapter
    from pchub.ui.settings_form import SettingsForm
    record = hub.pluginManager.records["cleaner"]
    form = SettingsForm(record.schema, PluginSettingsAdapter(hub, "cleaner"))
    monkeypatch.setattr(hub, "confirm", lambda *args, **kwargs: False)
    form.rows["autoClean"].control.click()
    assert hub.pluginManager.getSetting("cleaner", "autoClean") is False
    assert not form.rows["autoClean"].control.isChecked()
    monkeypatch.setattr(hub, "confirm", lambda *args, **kwargs: True)
    form.rows["autoClean"].control.click()
    assert hub.pluginManager.getSetting("cleaner", "autoClean") is True
    assert form.rows["autoIntervalDays"].isVisibleTo(form)
    hub.pluginManager.setSetting("cleaner", "autoClean", False)
    assert not form.rows["autoClean"].control.isChecked(), "external changes update the form"


def test_language_change_asks_restart(hub, monkeypatch):
    asked = []
    monkeypatch.setattr(hub, "confirm", lambda *args, **kwargs: asked.append(args) or False)
    hub.setAppSetting("general.language", "en")
    assert asked
    hub.setAppSetting("general.language", "it")
    from pchub.core.i18n import setLanguage
    setLanguage("it")


def test_advanced_permissions_decline(hub, monkeypatch):
    monkeypatch.setattr(hub, "confirm", lambda *args, **kwargs: False)
    monkeypatch.setattr(hub, "isAdmin", lambda: False)
    assert hub.setAppSetting("system.advancedPermissions", True) is False
    assert hub.appStore.get("system.advancedPermissions") is False


def test_export_import_settings(hub, tmp_path):
    from pchub.core.storage import flushAllStores
    flushAllStores()
    zipPath = tmp_path / "backup.zip"
    hub.exportSettings(str(zipPath))
    import zipfile
    names = zipfile.ZipFile(zipPath).namelist()
    assert "app.json" in names and any(name.startswith("plugin-settings/") for name in names)


def runContextAction(hub, monkeypatch, item, actionText):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMenu
    triggered = []

    def fakeExec(menu, globalPosition):
        for action in menu.actions():
            if action.text() == actionText:
                triggered.append(actionText)
                action.trigger()
                return action
        raise AssertionError(f"menu action not found: {actionText} in {[a.text() for a in menu.actions()]}")

    monkeypatch.setattr(hub, "execMenu", fakeExec)
    hub._sidebarContextMenu(item, QPoint(5, 5))
    assert triggered


def test_sidebar_context_menu_actions(hub, monkeypatch):
    import pchub.ui.dialogs as dialogs
    from pchub.core.i18n import tr
    from pchub.ui.sidebar import KIND_ROLE
    tree = hub.mainWindow.sidebar.tree
    hub.appStore.set("sidebar.layout", [])
    hub.refreshSidebar()
    monkeypatch.setattr(dialogs, "askText", lambda *args, **kwargs: (True, "Giochi"))
    runContextAction(hub, monkeypatch, None, tr("sidebar.newFolder"))
    folderNode = next(node for node in hub.appStore.get("sidebar.layout") if node["type"] == "folder")
    assert folderNode["name"] == "Giochi"
    folderItem = next(tree.topLevelItem(index) for index in range(tree.topLevelItemCount())
                      if tree.topLevelItem(index).data(0, KIND_ROLE) == "folder")
    assert tree.moveItem(tree.findPluginItem("timer"), folderItem, "on")
    hub._saveSidebarLayout()
    hub.refreshSidebar()
    folderItem = next(tree.topLevelItem(index) for index in range(tree.topLevelItemCount())
                      if tree.topLevelItem(index).data(0, KIND_ROLE) == "folder")
    monkeypatch.setattr(dialogs, "askText", lambda *args, **kwargs: (True, "Svago"))
    runContextAction(hub, monkeypatch, folderItem, tr("common.rename"))
    assert any(node.get("name") == "Svago" for node in hub.appStore.get("sidebar.layout"))
    monkeypatch.setattr(dialogs, "askText", lambda *args, **kwargs: (True, "Cronometri"))
    runContextAction(hub, monkeypatch, tree.findPluginItem("timer"), tr("common.rename"))
    assert hub.pluginManager.displayName("timer") == "Cronometri"
    assert tree.findPluginItem("timer").text(0) == "Cronometri"
    hub.pluginManager.setGlobalSetting("timer", "customName", "")
    monkeypatch.setattr(dialogs, "confirm", lambda *args, **kwargs: True)
    folderItem = next(tree.topLevelItem(index) for index in range(tree.topLevelItemCount())
                      if tree.topLevelItem(index).data(0, KIND_ROLE) == "folder")
    runContextAction(hub, monkeypatch, folderItem, tr("sidebar.deleteFolder"))
    layout = hub.appStore.get("sidebar.layout")
    assert all(node["type"] == "plugin" for node in layout)
    assert {"type": "plugin", "id": "timer"} in layout, "plugins inside a deleted folder move up"
    runContextAction(hub, monkeypatch, tree.findPluginItem("cleaner"), tr("sidebar.hide"))
    assert tree.findPluginItem("cleaner") is None
    hub.pluginManager.setGlobalSetting("cleaner", "hidden", False)
    assert tree.findPluginItem("cleaner") is not None
    runContextAction(hub, monkeypatch, tree.findPluginItem("cleaner"), tr("sidebar.pluginSettings"))
    assert hub.mainWindow.currentKey == "plugin:cleaner" and hub.hosts["cleaner"].gearButton.isChecked()
    hub.hosts["cleaner"].showSettings(False)


def test_plugin_actions_and_icon_change(hub, monkeypatch):
    import pchub.ui.dialogs as dialogs
    monkeypatch.setattr(dialogs, "pickIcon", lambda *args, **kwargs: "rocket")
    hub.changePluginIcon("timer")
    assert hub.pluginManager.displayIcon("timer") == "rocket"
    assert hub.mainWindow.sidebar.tree.findPluginItem("timer").data(0, Qt.UserRole + 2) == "rocket"
    hub.pluginManager.setGlobalSetting("timer", "customIcon", "")
    pins = hub.pinService
    pins.setPinned("timer:quickStart", True)
    item = pins.resolve("timer:quickStart")
    before = len(hub.pluginManager.records["timer"].instance.timers)
    item.run()
    assert len(hub.pluginManager.records["timer"].instance.timers) == before + 1
    sliderItem = pins.resolve("timer:quickMinutes")
    sliderItem.setValue(25)
    assert hub.pluginManager.getSetting("timer", "quickMinutes") == 25
    pins.setPinned("system_monitor:@enabled", True)
    pins.move("system_monitor:@enabled", -10)
    assert pins.refs()[0] == "system_monitor:@enabled"
    entry = pins.resolve("timer:#pauseAll")
    entry.run()
    assert all(timer["state"] != "running" for timer in hub.pluginManager.records["timer"].instance.timers)


def test_zz_no_errors_logged(hub):
    unexpected = [record for record in hub.errorCollector.records]
    assert not unexpected, [record.getMessage() for record in unexpected]
