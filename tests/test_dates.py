import datetime as dt

from pchub.core import dates, i18n


def at(text):
    return dt.datetime.fromisoformat(text)


def test_single_occurrence():
    start = at("2026-10-20T09:00")
    assert dates.nextOccurrence(start, {"type": "none"}, at("2026-10-19T00:00")) == start
    assert dates.nextOccurrence(start, {"type": "none"}, at("2026-10-21T00:00")) is None
    assert dates.nextOccurrence(start, None, start, inclusive=True) == start


def test_daily_weekly_interval():
    start = at("2026-10-01T08:30")
    assert dates.nextOccurrence(start, {"type": "daily"}, at("2026-10-18T10:00")) == at("2026-10-19T08:30")
    assert dates.nextOccurrence(start, {"type": "daily", "interval": 3}, at("2026-10-05T00:00")) == at("2026-10-07T08:30")
    assert dates.nextOccurrence(start, {"type": "weekly"}, at("2026-10-08T08:30")) == at("2026-10-15T08:30")
    assert dates.nextOccurrence(start, {"type": "weekly", "interval": 2}, at("2026-10-02T00:00")) == at("2026-10-15T08:30")


def test_weekdays_and_custom_days():
    friday = at("2026-10-16T18:00")
    assert dates.nextOccurrence(friday, {"type": "weekdays"}, friday) == at("2026-10-19T18:00")
    custom = {"type": "custom", "days": [1, 3]}
    assert dates.nextOccurrence(friday, custom, friday) == at("2026-10-20T18:00")
    assert dates.nextOccurrence(friday, custom, at("2026-10-20T18:00")) == at("2026-10-22T18:00")


def test_monthly_end_of_month_and_yearly_leap():
    start = at("2026-01-31T12:00")
    assert dates.nextOccurrence(start, {"type": "monthly"}, start) == at("2026-02-28T12:00")
    assert dates.nextOccurrence(start, {"type": "monthly"}, at("2026-03-01T00:00")) == at("2026-03-31T12:00"), \
        "keeps the 31st when the month has it"
    leap = at("2028-02-29T10:00")
    assert dates.nextOccurrence(leap, {"type": "yearly"}, leap) == at("2029-02-28T10:00")
    birthday = at("1999-05-12T00:00")
    assert dates.nextOccurrence(birthday, {"type": "yearly"}, at("2026-10-18T00:00")) == at("2027-05-12T00:00")


def test_until_and_occurrences_between():
    start = at("2026-10-01T09:00")
    rule = {"type": "daily", "until": "2026-10-05"}
    occurrences = dates.occurrencesBetween(start, rule, at("2026-09-01T00:00"), at("2026-12-01T00:00"))
    assert [value.day for value in occurrences] == [1, 2, 3, 4, 5]
    weekly = dates.occurrencesBetween(start, {"type": "weekly"}, at("2026-10-10T00:00"), at("2026-11-01T00:00"))
    assert [value.day for value in weekly] == [15, 22, 29]
    assert dates.occurrencesBetween(start, {"type": "none"}, at("2026-10-01T00:00"), at("2026-10-02T00:00")) == [start]


def test_easter_and_holidays():
    assert dates.easterSunday(2026) == dt.date(2026, 4, 5)
    assert dates.easterSunday(2027) == dt.date(2027, 3, 28)
    holidays = dates.italianHolidays(2026)
    assert holidays[dt.date(2026, 4, 6)] == "Pasquetta" and holidays[dt.date(2026, 12, 8)] == "Immacolata"


def test_month_grid_and_formatting():
    grid = dates.monthGrid(2026, 10)
    assert grid[0][0] == dt.date(2026, 9, 28) and len(grid) == 6 and all(len(week) == 7 for week in grid)
    i18n.setLanguage("it")
    today = dt.date(2026, 10, 18)
    assert dates.formatRelativeDay(today, today) == "Oggi"
    assert dates.formatRelativeDay(dt.date(2026, 10, 19), today) == "Domani"
    assert dates.formatRelativeDay(dt.date(2026, 10, 21), today) == "Mercoledì"
    assert dates.formatDayMonth(dt.date(2026, 10, 18)) == "Domenica 18 ottobre"
    assert dates.describeRule({"type": "custom", "days": [0, 2]}) == "Lun, Mer"
    assert dates.describeRule({"type": "weekly", "interval": 2}) == "Ogni 2 settimane"
    now = at("2026-10-18T10:00")
    assert dates.formatCountdown(at("2026-10-18T10:30"), now) == "tra 30 min"
    assert dates.formatCountdown(at("2026-10-18T07:00"), now) == "3 h fa"
