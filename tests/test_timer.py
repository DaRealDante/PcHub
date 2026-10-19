from pchub.core.active_registry import ActiveRegistry
from pchub.core.events import EventBus
from pchub.core.hotkeys import HotkeyManager
from pchub.core.plugin_manager import PluginManager
from pchub.core.storage import JsonStore


class FakeClock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


def makeTimerPlugin(dataDir):
    appStore = JsonStore(dataDir / "app.json")
    manager = PluginManager(appStore, ActiveRegistry(), EventBus(), HotkeyManager(), lambda: False)
    notifications = []
    manager.notifyHandler = lambda title, message="", sound=None: notifications.append((title, message))
    manager.discover(includeUser=False)
    manager.instantiateAll()
    plugin = manager.records["timer"].instance
    clock = FakeClock()
    plugin.clock = clock
    manager.startPlugin("timer")
    return manager, plugin, clock, notifications


def test_timer_counts_pauses_and_finishes(qtApp, dataDir):
    manager, plugin, clock, notifications = makeTimerPlugin(dataDir)
    plugin.setSetting("sound", False)
    timerId = plugin.addTimer(60, "Tea")
    timerItem = plugin.find(timerId)
    assert timerItem["state"] == "running"
    clock.now += 20
    assert round(plugin.remaining(timerItem)) == 40
    plugin.pauseTimer(timerId)
    clock.now += 100
    assert round(plugin.remaining(timerItem)) == 40, "paused timers don't move"
    plugin.startTimer(timerId)
    clock.now += 41
    plugin.tick()
    assert timerItem["state"] == "finished"
    assert notifications and notifications[-1][1] == "Tea"
    activeItems = manager.activeRegistry.items()
    assert activeItems and activeItems[0].subtitle.endswith(plugin.tr({"it": "Tempo scaduto!", "en": "Time's up!"}))
    plugin.resetTimer(timerId)
    assert timerItem["state"] == "idle" and manager.activeRegistry.count() == 0
    plugin.removeTimer(timerId)
    assert plugin.find(timerId) is None
    manager.stopAll()


def test_stopwatch_and_presets(qtApp, dataDir):
    manager, plugin, clock, notifications = makeTimerPlugin(dataDir)
    stopwatchId = plugin.addStopwatch()
    clock.now += 12.5
    assert round(plugin.elapsed(plugin.find(stopwatchId)), 1) == 12.5
    plugin.pauseTimer(stopwatchId)
    clock.now += 50
    assert round(plugin.elapsed(plugin.find(stopwatchId)), 1) == 12.5
    plugin.setSetting("presets", "1, 2.5; abc, 0, 90")
    assert plugin.presetMinutes() == [1.0, 2.5, 90.0]
    plugin.setSetting("quickMinutes", 3)
    plugin.startQuickTimer()
    assert plugin.timers[-1]["duration"] == 180
    manager.stopAll()


def test_timer_expired_while_app_closed(qtApp, dataDir):
    manager, plugin, clock, notifications = makeTimerPlugin(dataDir)
    timerId = plugin.addTimer(30, "Laundry")
    manager.stopPlugin("timer")
    clock.now += 3600
    notifications.clear()
    manager.startPlugin("timer")
    assert plugin.find(timerId)["state"] == "finished"
    assert notifications and "Laundry" in notifications[0][1]
    manager.stopAll()


def test_toggle_last_hotkey_action(qtApp, dataDir):
    manager, plugin, clock, notifications = makeTimerPlugin(dataDir)
    plugin.toggleLast()
    assert len(plugin.timers) == 1 and plugin.timers[0]["state"] == "running"
    plugin.toggleLast()
    assert plugin.timers[0]["state"] == "paused"
    manager.stopAll()
