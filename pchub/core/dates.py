"""Date helpers shared by reminders, calendar, commissions and to-dos (pure, unit tested).

Recurrence rule (dict):
    {"type": "none" | "daily" | "weekdays" | "weekly" | "monthly" | "yearly" | "custom",
     "interval": 1,              # every N days/weeks/months/years
     "days": [0, 2, 4],          # custom: weekdays (0 = Monday)
     "until": "2026-12-31" | None}
"""
import calendar
import datetime

from pchub.core.i18n import T, language, tr

REPEAT_OPTIONS = [
    ("none", T("Mai", "Never")),
    ("daily", T("Ogni giorno", "Every day")),
    ("weekdays", T("Giorni feriali (lun-ven)", "Weekdays (Mon-Fri)")),
    ("weekly", T("Ogni settimana", "Every week")),
    ("monthly", T("Ogni mese", "Every month")),
    ("yearly", T("Ogni anno", "Every year")),
    ("custom", T("Giorni scelti", "Chosen days")),
]
WEEKDAY_SHORT = {"it": ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"], "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}
WEEKDAY_LONG = {"it": ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"],
                "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]}
MONTHS = {"it": ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
                 "novembre", "dicembre"],
          "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                 "November", "December"]}


def toIso(value):
    if value is None:
        return None
    return value.isoformat(timespec="minutes") if isinstance(value, datetime.datetime) else value.isoformat()


def parseDateTime(text):
    if not text:
        return None
    if isinstance(text, datetime.datetime):
        return text
    if isinstance(text, datetime.date):
        return datetime.datetime.combine(text, datetime.time())
    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError:
        return None


def parseDate(text):
    if not text:
        return None
    if isinstance(text, datetime.datetime):
        return text.date()
    if isinstance(text, datetime.date):
        return text
    try:
        return datetime.date.fromisoformat(text[:10])
    except ValueError:
        return None


def addMonths(dateValue, months, anchorDay=None):
    anchorDay = anchorDay or dateValue.day
    monthIndex = dateValue.month - 1 + months
    year = dateValue.year + monthIndex // 12
    month = monthIndex % 12 + 1
    day = min(anchorDay, calendar.monthrange(year, month)[1])
    return dateValue.replace(year=year, month=month, day=day)


def _ruleType(rule):
    return (rule or {}).get("type", "none") or "none"


def nextOccurrence(start, rule, after, inclusive=False):
    """First occurrence of a series starting at `start` that is > after (>= when inclusive). None if none."""
    ruleType = _ruleType(rule)
    interval = max(1, int((rule or {}).get("interval", 1) or 1))
    until = parseDate((rule or {}).get("until"))

    def accept(candidate):
        return candidate >= after if inclusive else candidate > after

    if ruleType == "none":
        return start if accept(start) else None
    candidate = start
    if ruleType in ("daily", "weekly"):
        stepDays = interval * (1 if ruleType == "daily" else 7)
        if not accept(candidate):
            gapDays = (after - candidate).total_seconds() / 86400.0
            skipped = max(0, int(gapDays // stepDays))
            candidate = candidate + datetime.timedelta(days=skipped * stepDays)
            while not accept(candidate):
                candidate += datetime.timedelta(days=stepDays)
    elif ruleType in ("weekdays", "custom"):
        allowedDays = set(range(5)) if ruleType == "weekdays" else set((rule or {}).get("days") or [start.weekday()])
        if not accept(candidate) and after > candidate:
            candidate = datetime.datetime.combine(after.date(), start.time())
        guard = 0
        while (not accept(candidate) or candidate.weekday() not in allowedDays or candidate < start) and guard < 800:
            candidate += datetime.timedelta(days=1)
            guard += 1
    elif ruleType in ("monthly", "yearly"):
        stepMonths = interval * (1 if ruleType == "monthly" else 12)
        count = 0
        if not accept(candidate) and after > candidate:
            monthsGap = (after.year - start.year) * 12 + (after.month - start.month)
            count = max(0, monthsGap // stepMonths - 1)
            candidate = addMonths(start, count * stepMonths, start.day)
        guard = 0
        while not accept(candidate) and guard < 2000:
            count += 1
            candidate = addMonths(start, count * stepMonths, start.day)
            guard += 1
    if until is not None and candidate.date() > until:
        return None
    return candidate


def occurrencesBetween(start, rule, rangeStart, rangeEnd, limit=500):
    """All occurrences in [rangeStart, rangeEnd)."""
    results = []
    candidate = nextOccurrence(start, rule, rangeStart, inclusive=True)
    while candidate is not None and candidate < rangeEnd and len(results) < limit:
        results.append(candidate)
        if _ruleType(rule) == "none":
            break
        candidate = nextOccurrence(start, rule, candidate)
    return results


def describeRule(rule):
    ruleType = _ruleType(rule)
    interval = max(1, int((rule or {}).get("interval", 1) or 1))
    if ruleType == "custom":
        names = WEEKDAY_SHORT[language()]
        return ", ".join(names[day] for day in sorted((rule or {}).get("days") or []))
    if interval > 1 and ruleType in ("daily", "weekly", "monthly", "yearly"):
        unit = {"daily": T("giorni", "days"), "weekly": T("settimane", "weeks"), "monthly": T("mesi", "months"),
                "yearly": T("anni", "years")}[ruleType]
        return tr(T("Ogni {count} {unit}", "Every {count} {unit}"), count=interval, unit=tr(unit))
    return tr(dict(REPEAT_OPTIONS).get(ruleType, REPEAT_OPTIONS[0][1]))


def formatDayMonth(dateValue, withWeekday=True, withYear=False):
    lang = language()
    text = f"{dateValue.day} {MONTHS[lang][dateValue.month - 1]}"
    if lang == "en":
        text = f"{MONTHS[lang][dateValue.month - 1]} {dateValue.day}"
    if withYear:
        text += f" {dateValue.year}"
    if withWeekday:
        weekday = WEEKDAY_LONG[lang][dateValue.weekday()]
        text = f"{weekday.capitalize()} {text}" if lang == "it" else f"{weekday}, {text}"
    return text


def formatRelativeDay(dateValue, today=None):
    today = today or datetime.date.today()
    delta = (dateValue - today).days
    if delta == 0:
        return tr(T("Oggi", "Today"))
    if delta == 1:
        return tr(T("Domani", "Tomorrow"))
    if delta == -1:
        return tr(T("Ieri", "Yesterday"))
    if 1 < delta < 7:
        return WEEKDAY_LONG[language()][dateValue.weekday()].capitalize()
    return formatDayMonth(dateValue, withWeekday=False, withYear=dateValue.year != today.year)


def formatWhen(dateTimeValue, allDay=False, now=None):
    now = now or datetime.datetime.now()
    dayText = formatRelativeDay(dateTimeValue.date(), now.date())
    return dayText if allDay else f"{dayText} {dateTimeValue.strftime('%H:%M')}"


def formatCountdown(target, now=None):
    now = now or datetime.datetime.now()
    seconds = int((target - now).total_seconds())
    future = seconds >= 0
    seconds = abs(seconds)
    if seconds < 60:
        value = tr(T("meno di un minuto", "less than a minute"))
    elif seconds < 3600:
        value = f"{seconds // 60} min"
    elif seconds < 86400:
        hours, minutes = divmod(seconds // 60, 60)
        value = f"{hours} h {minutes:02d}" if minutes else f"{hours} h"
    else:
        days = seconds // 86400
        value = tr(T("{count} giorni", "{count} days"), count=days) if days != 1 else tr(T("1 giorno", "1 day"))
    return tr(T("tra {value}", "in {value}"), value=value) if future else tr(T("{value} fa", "{value} ago"), value=value)


def easterSunday(year):
    remainderA = year % 19
    century, yearOfCentury = divmod(year, 100)
    remainderB, remainderC = divmod(century, 4)
    correctionF = (century + 8) // 25
    correctionG = (century - correctionF + 1) // 3
    epact = (19 * remainderA + century - remainderB - correctionG + 15) % 30
    quotientI, remainderK = divmod(yearOfCentury, 4)
    weekdayL = (32 + 2 * remainderC + 2 * quotientI - epact - remainderK) % 7
    correctionM = (remainderA + 11 * epact + 22 * weekdayL) // 451
    month, day = divmod(epact + weekdayL - 7 * correctionM + 114, 31)
    return datetime.date(year, month, day + 1)


def italianHolidays(year):
    easter = easterSunday(year)
    return {
        datetime.date(year, 1, 1): "Capodanno",
        datetime.date(year, 1, 6): "Epifania",
        easter: "Pasqua",
        easter + datetime.timedelta(days=1): "Pasquetta",
        datetime.date(year, 4, 25): "Festa della Liberazione",
        datetime.date(year, 5, 1): "Festa dei Lavoratori",
        datetime.date(year, 6, 2): "Festa della Repubblica",
        datetime.date(year, 8, 15): "Ferragosto",
        datetime.date(year, 11, 1): "Ognissanti",
        datetime.date(year, 12, 8): "Immacolata",
        datetime.date(year, 12, 25): "Natale",
        datetime.date(year, 12, 26): "Santo Stefano",
    }


def monthGrid(year, month):
    """6 weeks x 7 days of dates covering the month (Monday first)."""
    firstDay = datetime.date(year, month, 1)
    gridStart = firstDay - datetime.timedelta(days=firstDay.weekday())
    return [[gridStart + datetime.timedelta(days=week * 7 + day) for day in range(7)] for week in range(6)]
