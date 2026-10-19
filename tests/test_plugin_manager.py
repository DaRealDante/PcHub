import textwrap
import zipfile

import pytest
from conftest import processEvents

from pchub.core.active_registry import ActiveRegistry
from pchub.core.events import EventBus
from pchub.core.hotkeys import HotkeyManager
from pchub.core.paths import userPluginsDir
from pchub.core.plugin_manager import PluginManager
from pchub.core.storage import JsonStore

GOOD_PLUGIN = '''
from pchub.core.plugin_api import PluginBase, ActiveItem
from pchub.core.settings_schema import Toggle, HotkeySetting
from . import helper

class Plugin(PluginBase):
    pluginId = "{pluginId}"
    name = {{"it": "Prova", "en": "Test"}}
    requiresAdmin = {requiresAdmin}
    settingsSchema = [Toggle("flag", "Flag", False), HotkeySetting("hk", "Hotkey", action="onHotkey", default="Ctrl+Alt+K")]

    def __init__(self, context):
        super().__init__(context)
        self.events = []

    def start(self):
        if self.setting("flag") == "explode":
            raise RuntimeError("boom")
        self.events.append("start")
        self.context.setActive(ActiveItem("thing", "Thing"))

    def stop(self):
        self.events.append("stop")

    def onSettingChanged(self, key, value):
        self.events.append(("changed", key, value))

    def onHotkey(self):
        self.events.append("hotkey")

    def crashLater(self):
        def worker():
            raise ValueError("thread crash")
        self.runInThread(worker)

    def answer(self):
        return helper.ANSWER
'''


def writeUserPlugin(folderName, pluginId=None, requiresAdmin=False, source=None):
    folder = userPluginsDir() / folderName
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plugin.py").write_text(source or GOOD_PLUGIN.format(pluginId=pluginId or folderName,
                                                                    requiresAdmin=requiresAdmin), encoding="utf-8")
    (folder / "helper.py").write_text("ANSWER = 42\n", encoding="utf-8")
    return folder


def makeManager(dataDir, isAdmin=False):
    appStore = JsonStore(dataDir / "app.json")
    hotkeys = HotkeyManager()
    manager = PluginManager(appStore, ActiveRegistry(), EventBus(), hotkeys, lambda: isAdmin)
    return manager, appStore, hotkeys


def test_user_plugin_lifecycle(qtApp, dataDir):
    writeUserPlugin("demo")
    manager, appStore, hotkeys = makeManager(dataDir)
    manager.discover()
    manager.instantiateAll()
    manager.startAll()
    record = manager.records["demo"]
    assert record.status == "running"
    assert record.instance.answer() == 42, "relative imports inside a plugin folder must work"
    assert manager.activeRegistry.count() == 1
    assert hotkeys.simulate("Ctrl+Alt+K")
    assert record.instance.events[-1] == "hotkey"
    manager.setSetting("demo", "flag", True)
    assert ("changed", "flag", True) in record.instance.events
    manager.setSetting("demo", "hk", "Ctrl+Alt+L")
    assert not hotkeys.simulate("Ctrl+Alt+K") and hotkeys.simulate("Ctrl+Alt+L")
    oldInstance = record.instance
    assert manager.restartPlugin("demo")
    assert oldInstance.events[-1] == "stop", "the old instance is stopped"
    record = manager.records["demo"]
    assert record.instance is not oldInstance and record.instance.events.count("start") == 1, \
        "restart reloads the plugin code into a fresh instance"
    manager.setEnabled("demo", False)
    assert record.status == "disabled"
    assert manager.activeRegistry.count() == 0
    assert not hotkeys.simulate("Ctrl+Alt+L"), "plugin hotkeys are released when disabled"
    manager.setEnabled("demo", True)
    assert record.status == "running"
    manager.setGlobalSetting("demo", "showInActive", False)
    assert manager.activeRegistry.count() == 0 and len(manager.activeRegistry.items(True)) == 1
    hotkeys.shutdown()


def test_open_hotkey_works_even_when_disabled(qtApp, dataDir):
    writeUserPlugin("demo")
    manager, appStore, hotkeys = makeManager(dataDir)
    opened = []
    manager.openPageHandler = lambda pluginId, viaHotkey=False: opened.append((pluginId, viaHotkey))
    manager.discover()
    manager.instantiateAll()
    manager.startAll()
    manager.setGlobalSetting("demo", "openHotkey", "Ctrl+Shift+O")
    manager.setEnabled("demo", False)
    assert hotkeys.simulate("Ctrl+Shift+O")
    assert opened == [("demo", True)]
    hotkeys.shutdown()


def test_admin_plugins_are_blocked_without_permissions(qtApp, dataDir):
    writeUserPlugin("needsadmin", requiresAdmin=True)
    manager, appStore, hotkeys = makeManager(dataDir, isAdmin=False)
    manager.discover()
    manager.instantiateAll()
    manager.startAll()
    assert manager.records["needsadmin"].status == "blocked"
    manager.isAdmin = lambda: True
    manager.startPlugin("needsadmin")
    assert manager.records["needsadmin"].status == "running"
    hotkeys.shutdown()


def test_start_errors_and_thread_crashes_are_contained(qtApp, dataDir):
    writeUserPlugin("crashy")
    manager, appStore, hotkeys = makeManager(dataDir)
    manager.discover()
    manager.instantiateAll()
    record = manager.records["crashy"]
    record.settingsStore.set("settings.flag", "explode")
    manager.setGlobalSetting("crashy", "autoRestart", False)
    manager.startAll()
    assert record.status == "error" and "boom" in record.error
    record.settingsStore.set("settings.flag", False)
    manager.startPlugin("crashy")
    assert record.status == "running"
    record.instance.crashLater()
    processEvents(300)
    assert record.status == "error" and "thread crash" in record.error
    hotkeys.shutdown()


def test_auto_restart_after_crash(qtApp, dataDir):
    writeUserPlugin("phoenix")
    manager, appStore, hotkeys = makeManager(dataDir)
    manager.discover()
    manager.instantiateAll()
    manager.startAll()
    record = manager.records["phoenix"]
    record.instance.crashLater()
    processEvents(300)
    assert record.status == "error"
    processEvents(3400)
    assert manager.records["phoenix"].status == "running", "restartable plugins come back on their own"
    hotkeys.shutdown()


def test_broken_plugin_does_not_break_others(qtApp, dataDir):
    writeUserPlugin("good")
    writeUserPlugin("broken", source="this is not python(")
    manager, appStore, hotkeys = makeManager(dataDir)
    manager.discover()
    manager.instantiateAll()
    manager.startAll()
    assert manager.records["broken"].status == "error"
    assert manager.records["good"].status == "running"
    assert manager.records["system_monitor"].status == "running"
    manager.stopAll()
    hotkeys.shutdown()


def test_uninstall_user_and_builtin_plugins(qtApp, dataDir):
    folder = writeUserPlugin("removable")
    manager, appStore, hotkeys = makeManager(dataDir)
    manager.discover()
    manager.instantiateAll()
    manager.startAll()
    assert manager.uninstall("removable", removeData=True)
    assert not folder.exists() and "removable" not in manager.records
    assert manager.uninstall("timer")
    assert manager.records["timer"].status == "uninstalled"
    assert "timer" in appStore.get("plugins.__uninstalled")
    assert "timer" not in [record.pluginId for record in manager.installedRecords()]
    assert manager.reinstall("timer")
    assert manager.records["timer"].status == "running"
    manager.stopAll()
    hotkeys.shutdown()


def test_install_from_zip_and_reject_unsafe(qtApp, dataDir, tmp_path):
    manager, appStore, hotkeys = makeManager(dataDir)
    manager.discover()
    manager.instantiateAll()
    zipPath = tmp_path / "zipped.zip"
    with zipfile.ZipFile(zipPath, "w") as archive:
        archive.writestr("zipped/plugin.py", GOOD_PLUGIN.format(pluginId="zipped", requiresAdmin=False))
        archive.writestr("zipped/helper.py", "ANSWER = 42\n")
    tempFolder, pluginRoot, pluginClass = manager.inspectZip(zipPath)
    assert pluginClass.pluginId == "zipped"
    record = manager.installFromFolder(tempFolder, pluginRoot, pluginClass.pluginId)
    assert record.status == "running" and (userPluginsDir() / "zipped" / "plugin.py").exists()
    with pytest.raises(ValueError):
        manager.inspectZip(zipPath)
    evilPath = tmp_path / "evil.zip"
    with zipfile.ZipFile(evilPath, "w") as archive:
        archive.writestr("../../escape.py", "x = 1")
    with pytest.raises(ValueError):
        manager.inspectZip(evilPath)
    emptyPath = tmp_path / "empty.zip"
    with zipfile.ZipFile(emptyPath, "w") as archive:
        archive.writestr("readme.txt", "hi")
    with pytest.raises(ValueError):
        manager.inspectZip(emptyPath)
    manager.stopAll()
    hotkeys.shutdown()


def test_plugin_template_loads_and_runs(qtApp, dataDir):
    import shutil
    from pathlib import Path
    templateFolder = Path(__file__).resolve().parents[1] / "assets" / "plugin_template"
    shutil.copytree(templateFolder, userPluginsDir() / "plugin_template")
    manager, appStore, hotkeys = makeManager(dataDir)
    manager.confirmHandler = lambda *args: True
    manager.discover()
    manager.instantiateAll()
    manager.startAll()
    record = manager.records["plugin_template"]
    assert record.status == "running", record.error
    page = record.instance.createPage()
    assert page is not None
    record.instance._tick()
    assert manager.activeRegistry.count() == 1
    assert record.widgetSpecs[0].typeId == "plugin_template.counter"
    record.widgetSpecs[0].factory()
    manager.stopAll()
    hotkeys.shutdown()
