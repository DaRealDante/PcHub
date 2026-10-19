import datetime as dt

from pchub.plugins.commissions import logic
from test_reminders_calendar import Clock, makeManager

RATES = {"ROBUX": 3.2, "USD": 0.9}


def test_money_and_conversion():
    assert logic.toEuro(10000, "ROBUX", RATES) == 32.0
    assert logic.toEuro(100, "USD", RATES) == 90.0
    assert logic.formatMoney(1234.5, "EUR", "it") == "1.234,50 €"
    assert logic.formatMoney(25, "EUR", "it") == "25 €"
    assert logic.formatMoney(15000, "ROBUX", "it") == "R$ 15.000"
    assert logic.formatMoney(40, "USD", "en") == "$40"


def test_payments_status_and_outstanding():
    commission = logic.newCommission("Sistema combat", price=100, currency="EUR", status="progress")
    assert logic.outstanding(commission) == 100
    logic.addPayment(commission, 50, date=dt.datetime(2026, 3, 1))
    assert logic.outstanding(commission) == 50 and commission["status"] == "progress"
    logic.addPayment(commission, 50, date=dt.datetime(2026, 3, 10))
    assert logic.outstanding(commission) == 0 and commission["status"] == "paid", "fully paid -> Paid"
    assert commission["paidAt"].startswith("2026-03-10")
    cancelled = logic.newCommission("x", price=80, status="cancelled")
    assert logic.outstanding(cancelled) == 0


def test_earnings_by_year_and_month():
    paidWithPayments = logic.newCommission("A", price=200, currency="EUR")
    logic.addPayment(paidWithPayments, 120, date=dt.datetime(2026, 1, 15))
    logic.addPayment(paidWithPayments, 80, date=dt.datetime(2025, 12, 30))
    robux = logic.newCommission("B", price=10000, currency="ROBUX")
    logic.setStatus(robux, "paid", dt.datetime(2026, 2, 2))
    earned2026 = logic.earnedInYear([paidWithPayments, robux], RATES, 2026)
    assert abs(earned2026 - (120 + 32)) < 1e-9
    months = logic.monthlyEarnings([paidWithPayments, robux], RATES, 3, today=dt.date(2026, 2, 20))
    assert [(month, round(value, 2)) for year, month, value in months] == [(12, 80.0), (1, 120.0), (2, 32.0)]


def test_deadlines_progress_and_client_stats():
    now = dt.datetime(2026, 10, 18, 12, 0)
    late = logic.newCommission("Late", status="progress", deadline=dt.datetime(2026, 10, 17, 18, 0))
    soon = logic.newCommission("Soon", status="todo", deadline=dt.datetime(2026, 10, 19, 10, 0))
    done = logic.newCommission("Done", status="delivered", deadline=dt.datetime(2026, 10, 1))
    assert logic.isOverdue(late, now) and not logic.isOverdue(done, now)
    assert logic.dueSoon(soon, now, 48) and not logic.dueSoon(late, now, 48)
    soon["tasks"] = [{"text": "a", "done": True}, {"text": "b", "done": False}]
    assert logic.progress(soon) == 0.5
    late["clientId"] = soon["clientId"] = "c1"
    logic.addPayment(late, 30, date=now)
    stats = logic.clientStats("c1", [late, soon, done], RATES)
    assert stats["count"] == 2 and stats["active"] == 2 and stats["earned"] == 30


def test_csv_export():
    commission = logic.newCommission("Mappa; horror", price=50, currency="EUR", status="paid")
    text = logic.exportCsv([commission], {}, RATES, lambda status: status)
    lines = text.strip().splitlines()
    assert lines[0].startswith("Creata;Cliente") and '"Mappa; horror"' in lines[1] and "50,00" in lines[1]


def test_plugin_flow_alerts_calendar_and_active(qtApp, dataDir):
    manager = makeManager(dataDir)
    plugin = manager.records["commissions"].instance
    clock = Clock("2026-10-18T10:00")
    plugin.clock = clock
    client = plugin.addClient("Marco_RBX")
    commission = plugin.add("Sistema pet", clientId=client["id"], price=15000, currency="ROBUX",
                            deadline=dt.datetime(2026, 10, 19, 18, 0), status="progress")
    assert commission["deadlineAlertHours"] == 24
    plugin.check()
    assert not manager.alerts and manager.activeRegistry.count() == 0
    clock.now = dt.datetime(2026, 10, 18, 19, 0)
    plugin.check()
    assert len(manager.alerts) == 1 and "Sistema pet" in manager.alerts[0][0]
    assert manager.activeRegistry.count() == 1, "due within 24h shows in Active"
    plugin.check()
    assert len(manager.alerts) == 1
    clock.now = dt.datetime(2026, 10, 19, 18, 5)
    plugin.check()
    assert len(manager.alerts) == 2, "second alert when the deadline passes"
    items = plugin.calendarItems(dt.date(2026, 10, 1), dt.date(2026, 10, 31))
    assert len(items) == 1 and items[0].kind == "deadline" and "Sistema pet" in items[0].title
    calendar = manager.records["calendar"].instance
    byDay = calendar.itemsByDay(dt.date(2026, 10, 19), dt.date(2026, 10, 19))
    assert any("Sistema pet" in item.title for item in byDay[dt.date(2026, 10, 19)])
    plugin.setStatus(commission["id"], "delivered")
    assert manager.activeRegistry.count() == 0
    plugin.recordPayment(commission["id"], 15000)
    assert plugin.find(commission["id"])["status"] == "paid"
    stats = plugin.stats()
    assert abs(stats["earnedYear"] - 15000 / 1000 * plugin.setting("robuxRate")) < 1e-6
    plugin.update(commission["id"], deadline=dt.datetime(2026, 11, 1, 12, 0))
    assert plugin.find(commission["id"])["alertedKeys"] == [], "changing the deadline re-arms the alerts"
    plugin.deleteClient(client["id"])
    assert plugin.find(commission["id"])["clientId"] is None
    manager.stopAll()
