import datetime as dt

from pchub.plugins.reminders import logic


def at(text):
    return dt.datetime.fromisoformat(text)


def test_one_off_rings_once_then_snooze_and_complete():
    now = at("2026-10-18T10:00")
    reminder = logic.newReminder("Chiama Marco", at("2026-10-18T10:30"), now=now)
    assert not logic.dueToRing(reminder, at("2026-10-18T10:29"))
    assert logic.dueToRing(reminder, at("2026-10-18T10:30"))
    logic.markRung(reminder)
    assert logic.isRinging(reminder)
    assert not logic.dueToRing(reminder, at("2026-10-18T10:40")), "rings once per occurrence"
    logic.snooze(reminder, 10, at("2026-10-18T10:40"))
    assert not logic.isRinging(reminder)
    assert not logic.dueToRing(reminder, at("2026-10-18T10:45"))
    assert logic.dueToRing(reminder, at("2026-10-18T10:50"))
    logic.markRung(reminder)
    logic.complete(reminder, at("2026-10-18T10:51"))
    assert reminder["completed"] and not logic.dueToRing(reminder, at("2026-10-19T10:00"))
    logic.reopen(reminder, at("2026-10-19T10:00"))
    assert not reminder["completed"] and logic.dueToRing(reminder, at("2026-10-19T10:00")), "reopened past reminder rings"


def test_lead_time():
    reminder = logic.newReminder("Riunione", at("2026-10-20T15:00"), leadMinutes=15, now=at("2026-10-18T10:00"))
    assert not logic.dueToRing(reminder, at("2026-10-20T14:44"))
    assert logic.dueToRing(reminder, at("2026-10-20T14:45"))


def test_repeating_complete_and_catch_up():
    reminder = logic.newReminder("Medicine", at("2026-10-01T08:00"), {"type": "daily"}, now=at("2026-10-18T07:00"))
    assert reminder["nextAt"] == "2026-10-18T08:00", "repeating reminder created in the past starts from the next one"
    assert logic.dueToRing(reminder, at("2026-10-18T08:00"))
    logic.markRung(reminder)
    logic.complete(reminder, at("2026-10-18T08:05"))
    assert reminder["nextAt"] == "2026-10-19T08:00" and not reminder["completed"]
    assert logic.dueToRing(reminder, at("2026-10-22T09:00"))
    assert reminder["nextAt"] == "2026-10-22T08:00", "missed days collapse into the latest one"
    logic.markRung(reminder)
    logic.complete(reminder, at("2026-10-22T09:00"))
    assert reminder["nextAt"] == "2026-10-23T08:00"


def test_repeat_until_ends_series():
    reminder = logic.newReminder("Corso", at("2026-10-19T18:00"), {"type": "weekly", "until": "2026-10-27"},
                                 now=at("2026-10-18T00:00"))
    logic.complete(reminder, at("2026-10-19T19:00"))
    assert reminder["nextAt"] == "2026-10-26T18:00"
    logic.complete(reminder, at("2026-10-26T19:00"))
    assert reminder["completed"]


def test_quick_parser():
    now = at("2026-10-18T10:00")
    assert logic.parseQuickReminder("chiama Marco tra 10 min", now) == ("chiama Marco", at("2026-10-18T10:10"))
    assert logic.parseQuickReminder("domani alle 9 dentista", now) == ("dentista", at("2026-10-19T09:00"))
    assert logic.parseQuickReminder("consegna commissione venerdì alle 18:30", now) == ("consegna commissione", at("2026-10-23T18:30"))
    assert logic.parseQuickReminder("pagare bolletta 25/10", now) == ("pagare bolletta", at("2026-10-25T09:00"))
    assert logic.parseQuickReminder("ricordami di stendere stasera", now) == ("stendere", at("2026-10-18T20:00"))
    assert logic.parseQuickReminder("palestra alle 8", now) == ("palestra", at("2026-10-19T08:00")), "time already passed -> tomorrow"
    assert logic.parseQuickReminder("call in 2 hours", now) == ("call", at("2026-10-18T12:00"))
    assert logic.parseQuickReminder("compra il latte", now) == ("compra il latte", None)
    assert logic.parseQuickReminder("tra mezz'ora pausa", now) == ("pausa", at("2026-10-18T10:30"))
