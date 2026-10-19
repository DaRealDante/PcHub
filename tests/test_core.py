import json

from conftest import processEvents

from pchub.core import i18n
from pchub.core.hotkeys import (MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, HotkeyManager, normalizeSequence,
                                parseSequence)
from pchub.core.settings_schema import Section, Slider, Toggle, schemaDefaults
from pchub.core.storage import JsonStore
from pchub.ui.home import packLayout, greetingKey
from pchub.ui.sidebar import syncLayout


def test_store_dotted_keys_defaults_and_persistence(qtApp, tmp_path):
    storePath = tmp_path / "store.json"
    store = JsonStore(storePath, defaults={"general": {"language": "auto", "nested": {"value": 1}}})
    assert store.get("general.language") == "auto"
    assert store.get("general.nested.value") == 1
    assert store.get("missing.key", "fallback") == "fallback"
    store.set("general.language", "it")
    store.set("plugins.timer.enabled", False)
    store.flush()
    saved = json.loads(storePath.read_text(encoding="utf-8"))
    assert saved["general"]["language"] == "it"
    assert saved["plugins"]["timer"]["enabled"] is False
    reloaded = JsonStore(storePath, defaults={"general": {"language": "auto"}})
    assert reloaded.get("general.language") == "it"
    assert reloaded.get("plugins.timer.enabled") is False
    reloaded.remove("plugins.timer")
    assert reloaded.get("plugins.timer.enabled", "gone") == "gone"


def test_store_returns_copies_and_debounces(qtApp, tmp_path):
    store = JsonStore(tmp_path / "copy.json", saveDelayMs=30)
    store.set("list", [1, 2])
    value = store.get("list")
    value.append(3)
    assert store.get("list") == [1, 2]
    assert not (tmp_path / "copy.json").exists()
    processEvents(120)
    assert (tmp_path / "copy.json").exists()


def test_store_recovers_from_corrupt_file(qtApp, tmp_path):
    corruptPath = tmp_path / "bad.json"
    corruptPath.write_text("{ not json", encoding="utf-8")
    store = JsonStore(corruptPath, defaults={"a": 1})
    assert store.get("a") == 1
    assert (tmp_path / "bad.corrupt.json").exists()


def test_i18n_translation_and_formatting():
    i18n.setLanguage("it")
    assert i18n.tr("nav.settings") == "Impostazioni"
    assert i18n.tr({"it": "Ciao", "en": "Hi"}) == "Ciao"
    assert i18n.tr("plugin.uninstallTitle", name="Timer") == "Disinstallare Timer?"
    assert i18n.tr("unknown.key") == "unknown.key"
    assert i18n.formatBytes(1536) == "1,5 KB"
    assert i18n.formatNumber(12345) == "12.345"
    i18n.setLanguage("en")
    assert i18n.tr("nav.settings") == "Settings"
    assert i18n.formatBytes(1536) == "1.5 KB"
    assert i18n.formatDuration(3725) == "1:02:05"
    assert i18n.formatDuration(65) == "01:05"
    for languageCode in ("it", "en"):
        assert set(i18n.STRINGS[languageCode]) == set(i18n.STRINGS["it"]), "IT and EN must have the same keys"
    i18n.setLanguage("it")


def test_hotkey_parsing(qtApp):
    assert parseSequence("Ctrl+Alt+H") == (MOD_CONTROL | MOD_ALT, ord("H"))
    assert parseSequence("Shift+Meta+F5") == (MOD_SHIFT | MOD_WIN, 0x74)
    assert parseSequence("F13") == (0, 0x7C)
    assert parseSequence("Ctrl+Space") == (MOD_CONTROL, 0x20)
    assert parseSequence("Ctrl+Num+5") == (MOD_CONTROL, 0x65)
    assert parseSequence("H") is None, "single letters without modifiers must be rejected"
    assert parseSequence("") is None
    assert parseSequence("Ctrl+Alt+Del") == (MOD_CONTROL | MOD_ALT, 0x2E)
    assert normalizeSequence("ctrl+alt+h") == "Ctrl+Alt+H"


def test_hotkey_manager_conflicts_and_simulation(qtApp):
    manager = HotkeyManager()
    fired = []
    assert manager.bind("one", "Ctrl+Alt+J", lambda: fired.append("one")).ok
    conflict = manager.bind("two", "Ctrl+Alt+J", lambda: fired.append("two"))
    assert not conflict.ok and conflict.reason == "conflictInternal" and conflict.conflictOwner == "one"
    assert manager.bind("bad", "J", lambda: None).reason == "invalid"
    assert manager.bind("empty", "", lambda: None).ok
    assert manager.simulate("Ctrl+Alt+J")
    assert fired == ["one"]
    manager.suspend()
    manager.resume()
    assert manager.simulate("ctrl+alt+j")
    manager.unbind("one")
    assert not manager.simulate("Ctrl+Alt+J")
    assert manager.bind("two", "Ctrl+Alt+J", lambda: fired.append("two")).ok
    manager.shutdown()


def test_schema_helpers():
    schema = [Section("A"), Toggle("on", "On", True), Slider("level", "Level", 0, 100, 40, step=5),
              Toggle("child", "Child", visibleIf=("on", True))]
    assert schemaDefaults(schema) == {"on": True, "level": 40, "child": False}
    assert schema[3].isVisible({"on": True}.get)
    assert not schema[3].isVisible({"on": False}.get)
    assert schema[2].trayValues() == [0, 25, 50, 75, 100]


def test_pack_layout_dense_first_fit():
    positions = packLayout([("a", 2, 1), ("b", 1, 1), ("c", 1, 1), ("d", 2, 2), ("e", 1, 1)], 4)
    assert positions["a"] == (0, 0, 1, 2)
    assert positions["b"] == (0, 2, 1, 1)
    assert positions["c"] == (0, 3, 1, 1)
    assert positions["d"] == (1, 0, 2, 2)
    assert positions["e"] == (1, 2, 1, 1)
    clamped = packLayout([("wide", 4, 1)], 2)
    assert clamped["wide"] == (0, 0, 1, 2)


def test_sync_layout_keeps_folders_and_order():
    stored = [
        {"type": "folder", "id": "f1", "name": "Tools", "children": [{"type": "plugin", "id": "timer"},
                                                                       {"type": "plugin", "id": "ghost"}]},
        {"type": "plugin", "id": "cleaner"},
        {"type": "plugin", "id": "cleaner"},
    ]
    synced = syncLayout(stored, ["cleaner", "timer", "system_monitor"])
    assert synced[0]["type"] == "folder" and [child["id"] for child in synced[0]["children"]] == ["timer"]
    assert [node["id"] for node in synced[1:]] == ["cleaner", "system_monitor"]


def test_greeting_hours():
    assert greetingKey(8) == "home.greetingMorning"
    assert greetingKey(15) == "home.greetingAfternoon"
    assert greetingKey(20) == "home.greetingEvening"
    assert greetingKey(2) == "home.greetingNight"
