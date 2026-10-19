import random
import time

from pchub.plugins.macros import logic
from pchub.plugins.macros.runner import MacroRun
from pchub.plugins.macros.sender import FakeSender


def keyEvent(t, vk, down):
    return {"t": t, "kind": "key", "vk": vk, "down": down}


def test_key_names_and_trigger_text():
    assert logic.keyName(0x41) == "A" and logic.keyName(0x70) == "F1" and logic.keyName(0x63) == "Num 3"
    assert logic.keyName(0x20, english=True) == "Space"
    trigger = {"device": "key", "code": 0x46, "mods": ["shift", "ctrl"]}
    assert logic.triggerText(trigger, english=True) == "Ctrl + Shift + F"
    assert logic.isDangerousTrigger({"device": "mouse", "code": "left", "mods": []})
    assert not logic.isDangerousTrigger({"device": "mouse", "code": "x1", "mods": []})


def test_matching_by_mods_and_app():
    macro = logic.newMacro()
    macro["trigger"] = {"device": "mouse", "code": "x1", "mods": []}
    macro["scope"] = "apps"
    macro["apps"] = ["robloxplayerbeta.exe"]
    macros = [macro]
    assert logic.matchingMacros(macros, "mouse", "x1", [], "RobloxPlayerBeta.exe") == [macro]
    assert logic.matchingMacros(macros, "mouse", "x1", [], "chrome.exe") == []
    assert logic.matchingMacros(macros, "mouse", "x1", ["ctrl"], "robloxplayerbeta.exe") == []
    macro["enabled"] = False
    assert logic.matchingMacros(macros, "mouse", "x1", [], "robloxplayerbeta.exe") == []


def test_conflicts_only_when_apps_overlap():
    first, second = logic.newMacro(), logic.newMacro()
    for macro in (first, second):
        macro["trigger"] = {"device": "key", "code": 0x70, "mods": []}
        macro["scope"] = "apps"
    first["apps"], second["apps"] = ["a.exe"], ["b.exe"]
    assert logic.triggerConflicts([first, second], first) == []
    second["apps"] = ["a.exe", "c.exe"]
    assert logic.triggerConflicts([first, second], first) == [second]


def test_normalize_fills_missing_fields():
    macro = logic.normalizeMacro({"id": "x", "name": "Old", "steps": [{"type": "bogus"}, {"type": "wait", "ms": 5}],
                                  "clicker": {"cps": 30}, "apps": [" Game.EXE ", ""]})
    assert macro["mode"] == "once" and macro["clicker"]["cps"] == 30 and macro["clicker"]["button"] == "left"
    assert macro["apps"] == ["game.exe"] and len(macro["steps"]) == 1


def test_recording_folds_taps_combos_waits_and_clicks():
    events = [
        keyEvent(0.00, 0xA2, True), keyEvent(0.05, 0x43, True), keyEvent(0.06, 0x43, True), keyEvent(0.10, 0x43, False),
        keyEvent(0.15, 0xA2, False),
        keyEvent(1.00, 0x45, True), keyEvent(1.08, 0x45, False),
        {"t": 2.0, "kind": "button", "button": "left", "down": True, "x": 100, "y": 200},
        {"t": 2.05, "kind": "move", "x": 101, "y": 200},
        {"t": 2.08, "kind": "button", "button": "left", "down": False, "x": 101, "y": 200},
        {"t": 2.2, "kind": "button", "button": "left", "down": True, "x": 101, "y": 200},
        {"t": 2.25, "kind": "button", "button": "left", "down": False, "x": 101, "y": 200},
        {"t": 3.0, "kind": "wheel", "amount": -1, "x": 0, "y": 0},
        {"t": 3.1, "kind": "wheel", "amount": -1, "x": 0, "y": 0},
    ]
    steps = logic.recordingToSteps(events)
    kinds = [(step["type"], step.get("action")) for step in steps]
    assert steps[0]["type"] == "key" and steps[0]["vk"] == 0x43 and steps[0]["mods"] == ["ctrl"] and \
        steps[0]["action"] == "tap", steps[0]
    assert ("key", "tap") in kinds and steps[2]["vk"] == 0x45
    clicks = [step for step in steps if step["type"] == "click"]
    assert len(clicks) == 1 and clicks[0]["action"] == "double" and clicks[0]["x"] == 100
    scrolls = [step for step in steps if step["type"] == "scroll"]
    assert len(scrolls) == 1 and scrolls[0]["amount"] == -2
    waits = [step for step in steps if step["type"] == "wait"]
    assert waits and all(step["ms"] % 10 == 0 for step in waits)
    assert steps[-1]["type"] != "wait" and steps[0]["type"] != "wait"
    noWaits = logic.recordingToSteps(events, recordWaits=False)
    assert not any(step["type"] == "wait" for step in noWaits)


def test_recording_keeps_long_hold_and_lone_modifier():
    events = [keyEvent(0.0, 0x57, True), keyEvent(1.5, 0x57, False), keyEvent(2.0, 0xA0, True), keyEvent(2.05, 0xA0, False)]
    steps = logic.recordingToSteps(events)
    assert [(step["type"], step.get("action")) for step in steps] == [("key", "down"), ("wait", None), ("key", "up"),
                                                                       ("wait", None), ("key", "tap")]


def test_describe_steps():
    step = logic.newStep("key")
    step.update({"vk": 0x43, "mods": ["ctrl"]})
    assert "Ctrl + C" in logic.describeStep(step)
    assert logic.formatMs(1500) == "1.5 s" and logic.formatMs(2000) == "2 s" and logic.formatMs(40) == "40 ms"
    for stepType in logic.STEP_TYPES:
        assert logic.describeStep(logic.newStep(stepType))


def runMacro(macro, timeout=2.0):
    sender = FakeSender()
    run = MacroRun(macro, sender, generator=random.Random(1))
    run.start()
    run.thread.join(timeout)
    return run, sender


def test_runner_plays_steps_once_and_releases_on_stop():
    macro = logic.newMacro()
    macro["stepDelay"] = 0
    macro["steps"] = [dict(logic.newStep("key"), vk=0x43, mods=["ctrl"]), dict(logic.newStep("text"), text="hi"),
                      dict(logic.newStep("click"), button="right"), dict(logic.newStep("scroll"), amount=2)]
    run, sender = runMacro(macro)
    assert sender.actions == [("keyDown", 0xA2), ("keyDown", 0x43), ("keyUp", 0x43), ("keyUp", 0xA2), ("text", "hi"),
                              ("buttonDown", "right"), ("buttonUp", "right"), ("scroll", 2)]
    held = logic.newMacro()
    held["mode"] = "toggle"
    held["steps"] = [dict(logic.newStep("key"), vk=0x57, action="down"), dict(logic.newStep("wait"), ms=5000)]
    sender = FakeSender()
    run = MacroRun(held, sender)
    run.start()
    time.sleep(0.1)
    run.stop()
    run.thread.join(1)
    assert not run.isRunning() and sender.actions[-1] == ("keyUp", 0x57), "stopping releases held keys"


def test_runner_repeat_count_and_speed():
    macro = logic.newMacro()
    macro.update({"mode": "repeat", "repeatCount": 3, "stepDelay": 0, "speed": 4.0})
    macro["steps"] = [dict(logic.newStep("key"), vk=0x31), dict(logic.newStep("wait"), ms=200)]
    started = time.monotonic()
    run, sender = runMacro(macro)
    assert run.iterations == 3 and sender.actions.count(("keyDown", 0x31)) == 3
    assert time.monotonic() - started < 0.4, "4x speed shortens waits"


def test_clicker_limits_and_rate():
    macro = logic.newMacro("clicker")
    macro["clicker"].update({"cps": 50, "randomPercent": 0, "limit": "clicks", "limitValue": 10, "holdMs": 0})
    started = time.monotonic()
    run, sender = runMacro(macro)
    elapsed = time.monotonic() - started
    assert run.clicks == 10 and sender.actions.count(("buttonDown", "left")) == 10
    assert 0.15 < elapsed < 0.6
    macro["clicker"].update({"limit": "none", "position": "fixed", "x": 5, "y": 6, "double": True})
    sender = FakeSender()
    run = MacroRun(macro, sender)
    run.start()
    time.sleep(0.15)
    run.stop()
    run.thread.join(1)
    assert ("moveTo", 5, 6) in sender.actions and run.clicks >= 3
    assert sender.actions.count(("buttonDown", "left")) == sender.actions.count(("buttonUp", "left"))


# plugin engine (hooks are dispatched by hand: same code path the Windows hook thread uses) -------------------
def makeMacrosPlugin(dataDir):
    from pchub.core.active_registry import ActiveRegistry
    from pchub.core.events import EventBus
    from pchub.core.hotkeys import HotkeyManager
    from pchub.core.plugin_manager import PluginManager
    from pchub.core.storage import JsonStore
    appStore = JsonStore(dataDir / "app.json")
    manager = PluginManager(appStore, ActiveRegistry(), EventBus(), HotkeyManager(), lambda: False)
    manager.discover(includeUser=False)
    manager.instantiateAll()
    manager.startPlugin("macros")
    plugin = manager.records["macros"].instance
    plugin.sender = FakeSender()
    plugin._foreground = lambda: (12345, "game.exe")
    return manager, plugin


def pump(qtApp, seconds=0.3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        qtApp.processEvents()
        time.sleep(0.01)


def key(vk, down):
    from pchub.core.input_hooks import KeyEvent
    return KeyEvent(vk, 0, down)


def test_trigger_runs_blocks_and_respects_apps(qtApp, dataDir):
    from pchub.core.input_hooks import hookService
    manager, plugin = makeMacrosPlugin(dataDir)
    macro = plugin.add("steps", trigger={"device": "key", "code": 0x70, "mods": []}, scope="apps", apps=["game.exe"])
    plugin.setSteps(macro["id"], [dict(logic.newStep("key"), vk=0x31)])
    assert plugin.hooked
    assert hookService().dispatchKey(key(0x70, True)) is True, "trigger key is blocked"
    assert hookService().dispatchKey(key(0x70, False)) is True
    pump(qtApp)
    assert ("keyDown", 0x31) in plugin.sender.actions and macro["runCount"] == 1
    plugin._foreground = lambda: (12345, "chrome.exe")
    assert hookService().dispatchKey(key(0x70, True)) is False, "other app: key passes through"
    hookService().dispatchKey(key(0x70, False))
    import os
    plugin._foreground = lambda: (os.getpid(), "pchub.exe")
    macro["scope"] = "global"
    assert hookService().dispatchKey(key(0x70, True)) is False, "not while using PC Hub"
    hookService().dispatchKey(key(0x70, False))
    manager.stopAll()
    assert not plugin.hooked


def test_hold_and_toggle_modes(qtApp, dataDir):
    from pchub.core.input_hooks import MouseEvent, WM_XBUTTONDOWN, WM_XBUTTONUP, hookService
    manager, plugin = makeMacrosPlugin(dataDir)
    clicker = plugin.add("clicker", trigger={"device": "mouse", "code": "x1", "mods": []}, mode="hold")
    clicker["clicker"]["cps"] = 50

    def mouse(message):
        event = MouseEvent(message, 0, 0)
        event.button = "x1"
        return event

    hookService().dispatchMouse(mouse(WM_XBUTTONDOWN))
    pump(qtApp, 0.2)
    assert plugin.isMacroRunning(clicker["id"])
    hookService().dispatchMouse(mouse(WM_XBUTTONUP))
    pump(qtApp, 0.2)
    assert not plugin.isMacroRunning(clicker["id"]) and plugin.sender.actions.count(("buttonDown", "left")) >= 3
    plugin.update(clicker["id"], mode="toggle")
    hookService().dispatchMouse(mouse(WM_XBUTTONDOWN))
    hookService().dispatchMouse(mouse(WM_XBUTTONUP))
    pump(qtApp, 0.15)
    assert plugin.isMacroRunning(clicker["id"]), "toggle keeps going after release"
    assert manager.activeRegistry.items() if hasattr(manager.activeRegistry, "items") else True
    hookService().dispatchMouse(mouse(WM_XBUTTONDOWN))
    hookService().dispatchMouse(mouse(WM_XBUTTONUP))
    pump(qtApp, 0.15)
    assert not plugin.isMacroRunning(clicker["id"])
    manager.stopAll()


def test_capture_and_recording(qtApp, dataDir):
    from pchub.core.input_hooks import MouseEvent, WM_LBUTTONDOWN, WM_LBUTTONUP, hookService
    manager, plugin = makeMacrosPlugin(dataDir)
    service = hookService()
    previous = service.available
    service.available = True
    try:
        captured = []
        plugin.captureFinished.connect(captured.append)
        assert plugin.beginCapture()
        assert service.dispatchKey(key(0xA2, True)) is False
        assert service.dispatchKey(key(0x47, True)) is True
        assert service.dispatchKey(key(0x47, False)) is True, "the captured key's release is swallowed too"
        service.dispatchKey(key(0xA2, False))
        pump(qtApp, 0.05)
        assert captured == [{"device": "key", "code": 0x47, "mods": ["ctrl"]}]
        assert plugin.beginCapture()
        service.dispatchKey(key(0x1B, True))
        pump(qtApp, 0.05)
        assert captured[-1] is None, "Esc cancels"
    finally:
        service.available = previous
    finished = []
    plugin.recordingFinished.connect(finished.append)
    plugin.startRecording(0)
    assert plugin.hooked and plugin.recording.active
    service.dispatchKey(key(0x48, True))
    service.dispatchKey(key(0x48, False))
    service.dispatchMouse(MouseEvent(WM_LBUTTONDOWN, 10, 20))
    service.dispatchMouse(MouseEvent(WM_LBUTTONUP, 10, 20))
    service.dispatchKey(key(0xA2, True))
    steps = plugin.stopRecording()
    assert [step["type"] for step in steps if step["type"] != "wait"] == ["key", "click"]
    assert finished and finished[-1] == steps
    manager.stopAll()


def test_macros_page_builds_and_edits(qtApp, dataDir):
    from pchub.plugins.macros.page import MacrosHomeWidget, MacrosPage
    manager, plugin = makeMacrosPlugin(dataDir)
    first = plugin.add("steps", name="Uno")
    for stepType in logic.STEP_TYPES:
        first["steps"].append(logic.newStep(stepType))
    plugin.add("clicker", name="Clicker")
    page = MacrosPage(plugin)
    page.resize(1100, 800)
    page.grab()
    assert page.editor is not None and page.editor.macroId == first["id"]
    page.editor.stepsSection.addStep("wait")
    assert first["steps"][-1]["type"] == "wait" and len(page.editor.stepsSection.shownSteps) == 8
    page.editor.stepsSection.moveStep(7, -1)
    assert first["steps"][6]["type"] == "wait"
    page.editor._setTrigger({"device": "key", "code": 0x71, "mods": []})
    assert first["trigger"]["code"] == 0x71
    page.editor._onTrigger({"device": "mouse", "code": "left", "mods": []})
    assert first["trigger"]["code"] == 0x71 and page.editor.triggerError.isVisibleTo(page.editor)
    page.selectMacro(plugin.macros[1]["id"])
    page.grab()
    page.editor.findChild(type(page.editor)) if False else None
    plugin.delete(plugin.macros[1]["id"])
    assert page.editor.macroId == first["id"]
    home = MacrosHomeWidget(plugin)
    home.resize(400, 200)
    home.grab()
    manager.stopAll()
