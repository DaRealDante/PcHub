"""A broken plugin must never take PC Hub down, and the user must see which plugin broke."""
import os
import sys

import pytest
from conftest import processEvents

BAD_SETTINGS_PLUGIN = '''
from pchub.core.i18n import T
from pchub.core.plugin_api import PluginBase
from pchub.core.settings_schema import NumberInput, Slider, Toggle, Setting

class WeirdSetting(Setting):
    kind = "weird"
    def hasValue(self):
        raise RuntimeError("bad declaration")

class Plugin(PluginBase):
    pluginId = "badsettings"
    name = T("Impostazioni strane", "Weird settings")
    settingsSchema = [
        NumberInput("count", T("Quanti", "How many"), 1, 10, 3, suffix=T("elementi", "items")),
        Slider("level", T("Livello", "Level"), 0, 10, 5, suffix=T(" punti", " points")),
        Toggle("flag", T("Flag", "Flag"), True),
    ]
'''

BROKEN_INIT_PLUGIN = '''
from pchub.core.plugin_api import PluginBase

class Plugin(PluginBase):
    pluginId = "brokeninit"
    name = {"it": "Rotto", "en": "Broken"}

    def __init__(self, context):
        super().__init__(context)
        raise ValueError("init exploded")
'''

BROKEN_PAGE_PLUGIN = '''
from PySide6.QtWidgets import QPushButton
from pchub.core.plugin_api import PluginBase

class Plugin(PluginBase):
    pluginId = "brokenpage"
    name = {"it": "Pagina rotta", "en": "Broken page"}

    def createPage(self):
        raise KeyError("missing widget")
'''

BUTTON_CRASH_PLUGIN = '''
from PySide6.QtWidgets import QPushButton
from pchub.core.plugin_api import PluginBase

class Plugin(PluginBase):
    pluginId = "buttoncrash"
    name = {"it": "Bottone", "en": "Button"}

    def createPage(self):
        self.button = QPushButton("boom")
        self.button.clicked.connect(self.explode)
        return self.button

    def explode(self):
        return 1 / 0
'''


def writePlugin(folderName, source):
    from pchub.core.paths import userPluginsDir
    folder = userPluginsDir() / folderName
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plugin.py").write_text(source, encoding="utf-8")
    return folder


@pytest.fixture()
def makeHub(qtApp, tmp_path, monkeypatch):
    hubs = []
    monkeypatch.setenv("PCHUB_DATA_DIR", str(tmp_path / "data"))
    from pchub.app import PCHubApp
    import pchub.ui.dialogs as dialogs

    def build(*extraArgs):
        hub = PCHubApp(["pchub", "--no-splash", *extraArgs])
        alertsShown = []
        assert hub.setup()
        originalShow = hub.alerts.show

        def recordAlert(title, message="", iconName="bell", actions=None, *args, **kwargs):
            alertsShown.append((title, message, [action[0] for action in actions or []], actions))
            return originalShow(title, message, iconName, actions, *args, **kwargs)

        hub.alerts.show = recordAlert
        hub.alertsShown = alertsShown
        hubs.append(hub)
        return hub

    yield build
    for hub in hubs:
        hub.alerts.closeAll()
        hub._shutdown()
    sys.excepthook = sys.__excepthook__


def test_translated_suffix_and_bad_setting_do_not_crash(makeHub):
    writePlugin("badsettings", BAD_SETTINGS_PLUGIN.replace(
        'Toggle("flag", T("Flag", "Flag"), True),', 'Toggle("flag", T("Flag", "Flag"), True), WeirdSetting("odd", "Odd"),'))
    hub = makeHub()
    record = hub.pluginManager.records["badsettings"]
    if record.status == "error":
        assert "bad declaration" in record.error
        assert "badsettings" in hub.hosts, "even a plugin that can't start gets a page explaining the problem"
        return
    host = hub.hosts["badsettings"]
    hub.mainWindow.showPage("plugin:badsettings", animated=False)
    host.showSettings(True)
    processEvents(50)


def test_translated_suffix_renders(makeHub):
    writePlugin("badsettings", BAD_SETTINGS_PLUGIN)
    hub = makeHub()
    assert hub.pluginManager.records["badsettings"].status == "running"
    form = hub.hosts["badsettings"].specificForm
    assert form.rows["count"].control.suffix() in ("elementi", "items")
    assert form.rows["level"].valueLabel.text() in ("5 punti", "5 points")


def test_broken_init_gets_error_page_and_can_be_disabled(makeHub):
    writePlugin("brokeninit", BROKEN_INIT_PLUGIN)
    hub = makeHub()
    record = hub.pluginManager.records["brokeninit"]
    assert record.status == "error" and "init exploded" in record.error
    from pchub.ui.plugin_host import PluginErrorHost
    assert isinstance(hub.hosts["brokeninit"], PluginErrorHost)
    assert hub.mainWindow.sidebar.tree.findPluginItem("brokeninit") is not None, "visible in the sidebar with a red dot"
    processEvents(1400)
    assert any("Rotto" in title or "Broken" in title for title, *_ in hub.alertsShown), "the user is told which plugin broke"
    title, message, labels, actions = next(alert for alert in hub.alertsShown if "Rotto" in alert[0] or "Broken" in alert[0])
    assert len(labels) == 3, "Details / Delete / Disable"
    actions[-1][1]()
    assert hub.pluginManager.globalSetting("brokeninit", "enabled") is False
    assert record.status == "disabled"


def test_disabled_user_plugin_is_not_imported_and_can_be_reenabled(makeHub):
    writePlugin("brokeninit", BROKEN_INIT_PLUGIN.replace('raise ValueError("init exploded")', "pass"))
    hub = makeHub()
    hub.pluginManager.setEnabled("brokeninit", False)
    hub.appStore.flush()
    hub._shutdown()
    second = makeHub()
    record = second.pluginManager.records["brokeninit"]
    assert record.dormant and record.instance is None and record.status == "disabled"
    assert second.pluginManager.displayName("brokeninit") in ("Rotto", "Broken"), "name remembered without importing"
    second.retryBrokenPlugin("brokeninit")
    assert second.pluginManager.records["brokeninit"].status == "running"
    from pchub.ui.plugin_host import PluginPageHost
    assert isinstance(second.hosts["brokeninit"], PluginPageHost)


def test_broken_page_reports_problem(makeHub):
    writePlugin("brokenpage", BROKEN_PAGE_PLUGIN)
    hub = makeHub()
    assert hub.pluginManager.records["brokenpage"].status == "running", "the engine keeps working"
    processEvents(50)
    assert any("Pagina rotta" in title or "Broken page" in title for title, *_ in hub.alertsShown)


def test_uncaught_exception_is_attributed_to_plugin(makeHub):
    writePlugin("buttoncrash", BUTTON_CRASH_PLUGIN)
    hub = makeHub()
    try:
        hub.pluginManager.records["buttoncrash"].instance.explode()
    except ZeroDivisionError:
        hub.handleUncaughtException(*sys.exc_info())
    processEvents(50)
    record = hub.pluginManager.records["buttoncrash"]
    assert "ZeroDivisionError" in record.problem
    assert any("Bottone" in title or "Button" in title for title, *_ in hub.alertsShown)
    try:
        raise RuntimeError("core problem")
    except RuntimeError:
        before = len(hub.alertsShown)
        hub.handleUncaughtException(*sys.exc_info())
    assert len(hub.alertsShown) == before, "errors outside plugins are only logged"


def test_safe_mode_after_crashed_startup(makeHub):
    writePlugin("brokeninit", BROKEN_INIT_PLUGIN.replace('raise ValueError("init exploded")', "pass"))
    from pchub.core.paths import dataDir
    (dataDir() / "startup.lock").write_text("x")
    hub = makeHub()
    assert hub.safeMode
    record = hub.pluginManager.records["brokeninit"]
    assert record.dormant and record.safeMode
    processEvents(1400)
    assert any("sicura" in title or "safe" in title.lower() for title, *_ in hub.alertsShown)
    hub._leaveSafeMode()
    assert hub.pluginManager.records["brokeninit"].status == "running"


def test_new_plugin_from_template_and_reload(makeHub, monkeypatch):
    from PySide6.QtGui import QDesktopServices
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: True)
    hub = makeHub()
    pluginId = hub.createPluginFromTemplate("Il Mio Plugin!")
    assert pluginId == "il_mio_plugin"
    record = hub.pluginManager.records[pluginId]
    assert record.status == "running", record.error
    assert hub.pluginManager.displayName(pluginId) == "Il Mio Plugin!"
    assert hub.createPluginFromTemplate("Il Mio Plugin!") == "il_mio_plugin_2"
    writePlugin("dropped", BUTTON_CRASH_PLUGIN.replace('"buttoncrash"', '"dropped"'))
    added = hub.reloadUserPlugins()
    assert [record.pluginId for record in added] == ["dropped"]
    assert "dropped" in hub.hosts and hub.mainWindow.sidebar.tree.findPluginItem("dropped") is not None
    assert hub.reloadUserPlugins() == []
