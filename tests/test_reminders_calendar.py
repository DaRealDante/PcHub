import datetime as dt

from conftest import processEvents


def makeManager(dataDir):
    from pchub.core.active_registry import ActiveRegistry
    from pchub.core.events import EventBus
    from pchub.core.hotkeys import HotkeyManager
    from pchub.core.plugin_manager import PluginManager
    from pchub.core.storage import JsonStore
    manager = PluginManager(JsonStore(dataDir / "app.json"), ActiveRegistry(), EventBus(), HotkeyManager(), lambda: False)
    manager.alerts = []
    manager.alertHandler = lambda title, message="", iconName="bell", actions=None, timeoutSeconds=0, accent=None, sound=None: \
        manager.alerts.append((title, message, actions)) or None
    manager.notifications = []
    manager.notifyHandler = lambda title, message="", sound=None: manager.notifications.append((title, message))
    manager.discover(includeUser=False)
    manager.instantiateAll()
    manager.startAll()
    return manager


class Clock:
    def __init__(self, text):
        self.now = dt.datetime.fromisoformat(text)

    def __call__(self):
        return self.now


def test_reminders_ring_snooze_done_and_active(qtApp, dataDir):
    manager = makeManager(dataDir)
    reminders = manager.records["reminders"].instance
    clock = Clock("2026-10-18T10:00")
    reminders.clock = clock
    reminder = reminders.add("Chiama Marco", clock.now + dt.timedelta(minutes=30))
    reminders.check()
    assert not manager.alerts
    clock.now += dt.timedelta(minutes=31)
    reminders.check()
    assert manager.alerts and manager.alerts[-1][0] == "Chiama Marco"
    assert manager.activeRegistry.count() == 1, "ringing reminders show in Active"
    reminders.check()
    assert len(manager.alerts) == 1, "doesn't ring twice"
    snoozeAction = manager.alerts[-1][2][0]
    snoozeAction[1]()
    assert manager.activeRegistry.count() == 0
    clock.now += dt.timedelta(minutes=10)
    reminders.check()
    assert len(manager.alerts) == 2
    manager.alerts[-1][2][-1][1]()
    assert reminders.find(reminder["id"])["completed"]
    assert manager.activeRegistry.count() == 0
    manager.stopAll()


def test_reminders_quick_add_and_persistence(qtApp, dataDir):
    manager = makeManager(dataDir)
    reminders = manager.records["reminders"].instance
    reminders.clock = Clock("2026-10-18T10:00")
    reminders.quickAdd("domani alle 9 dentista")
    reminders.quickAdd("solo testo")
    titles = [reminder["title"] for reminder in reminders.upcoming()]
    assert titles == ["solo testo", "dentista"]
    manager.stopAll()
    manager.records["reminders"].settingsStore.flush()
    second = makeManager(dataDir)
    assert len(second.records["reminders"].instance.reminders) == 2
    second.stopAll()


def test_calendar_merges_plugins_holidays_and_events(qtApp, dataDir):
    manager = makeManager(dataDir)
    calendar = manager.records["calendar"].instance
    reminders = manager.records["reminders"].instance
    reminders.clock = Clock("2026-10-18T08:00")
    reminders.add("Palestra", dt.datetime(2026, 10, 19, 18, 0), {"type": "weekly"})
    calendar.addEvent("Compleanno Ken", dt.datetime(2000, 10, 21), allDay=True, rule={"type": "yearly"}, notifyMinutes=None)
    calendar.addEvent("Call cliente", dt.datetime(2026, 10, 20, 15, 0))
    byDay = calendar.itemsByDay(dt.date(2026, 10, 1), dt.date(2026, 12, 31))
    titles = lambda day: [item.title for item in byDay.get(day, [])]
    assert "Palestra" in titles(dt.date(2026, 10, 19)) and "Palestra" in titles(dt.date(2026, 10, 26))
    assert titles(dt.date(2026, 10, 21)) == ["Compleanno Ken"]
    assert "Call cliente" in titles(dt.date(2026, 10, 20))
    assert "Immacolata" in titles(dt.date(2026, 12, 8))
    calendar.setSourceVisible("reminders", False)
    byDay = calendar.itemsByDay(dt.date(2026, 10, 19), dt.date(2026, 10, 19))
    assert "Palestra" not in [item.title for item in byDay.get(dt.date(2026, 10, 19), [])]
    calendar.setSourceVisible("reminders", True)
    sources = dict(calendar.sources())
    assert "reminders" in sources and "holidays" in sources
    manager.stopAll()


def test_calendar_event_alert_once(qtApp, dataDir):
    manager = makeManager(dataDir)
    calendar = manager.records["calendar"].instance
    clock = Clock("2026-10-20T14:40")
    calendar.clock = clock
    calendar.addEvent("Call cliente", dt.datetime(2026, 10, 20, 15, 0), notifyMinutes=15)
    calendar.check()
    assert not manager.alerts
    clock.now = dt.datetime(2026, 10, 20, 14, 46)
    calendar.check()
    calendar.check()
    assert len(manager.alerts) == 1 and manager.alerts[0][0] == "Call cliente"
    manager.stopAll()


def test_multi_day_all_day_event_spans_days(qtApp, dataDir):
    manager = makeManager(dataDir)
    calendar = manager.records["calendar"].instance
    calendar.addEvent("Vacanza", dt.datetime(2026, 8, 10), dt.datetime(2026, 8, 13), allDay=True, notifyMinutes=None)
    byDay = calendar.itemsByDay(dt.date(2026, 8, 1), dt.date(2026, 8, 31))
    days = sorted(day.day for day, items in byDay.items() if any(item.title == "Vacanza" for item in items))
    assert days == [10, 11, 12]
    manager.stopAll()
