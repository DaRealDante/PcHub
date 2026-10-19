"""Reminder model + scheduling (pure, unit tested) and a small natural-language parser for quick add."""
import datetime
import re
import uuid

from pchub.core.dates import nextOccurrence, parseDateTime, toIso

LEAD_OPTIONS = [0, 5, 10, 15, 30, 60, 120, 1440]


def newReminder(title, start, rule=None, notes="", leadMinutes=0, color=None, sound=True, popup=True, now=None):
    now = now or datetime.datetime.now()
    rule = rule or {"type": "none"}
    reminder = {
        "id": uuid.uuid4().hex[:10], "title": title.strip(), "notes": notes, "start": toIso(start), "rule": rule,
        "leadMinutes": int(leadMinutes), "color": color, "sound": sound, "popup": popup, "createdAt": toIso(now),
        "nextAt": None, "snoozedUntil": None, "notifiedFor": None, "completed": False, "doneHistory": [],
    }
    scheduleFirst(reminder, now)
    return reminder


def isRepeating(reminder):
    return (reminder.get("rule") or {}).get("type", "none") != "none"


def scheduleFirst(reminder, now):
    """(Re)computes nextAt after creating or editing. Past one-off reminders stay due (they ring right away)."""
    start = parseDateTime(reminder["start"])
    if isRepeating(reminder):
        occurrence = nextOccurrence(start, reminder["rule"], now, inclusive=True)
        reminder["nextAt"] = toIso(occurrence) if occurrence else None
        reminder["completed"] = occurrence is None
    else:
        reminder["nextAt"] = reminder["start"]
    reminder["snoozedUntil"] = None
    reminder["notifiedFor"] = None


def fireTime(reminder):
    if reminder.get("completed") or not reminder.get("nextAt"):
        return None
    if reminder.get("snoozedUntil"):
        return parseDateTime(reminder["snoozedUntil"])
    return parseDateTime(reminder["nextAt"]) - datetime.timedelta(minutes=int(reminder.get("leadMinutes") or 0))


def ringKey(reminder):
    return f"{reminder.get('nextAt')}|{reminder.get('snoozedUntil')}"


def isRinging(reminder):
    return not reminder.get("completed") and reminder.get("notifiedFor") == ringKey(reminder)


def catchUp(reminder, now):
    """Repeating reminders that were never acknowledged jump to the most recent passed occurrence."""
    if not isRepeating(reminder) or reminder.get("completed") or not reminder.get("nextAt"):
        return False
    start = parseDateTime(reminder["start"])
    current = parseDateTime(reminder["nextAt"])
    moved = False
    following = nextOccurrence(start, reminder["rule"], current)
    while following is not None and following <= now:
        current = following
        following = nextOccurrence(start, reminder["rule"], current)
        moved = True
    if moved:
        reminder["nextAt"] = toIso(current)
        reminder["snoozedUntil"] = None
        reminder["notifiedFor"] = None
    return moved


def dueToRing(reminder, now):
    """True when the reminder should ring now (and hasn't rung for this occurrence/snooze yet)."""
    catchUp(reminder, now)
    moment = fireTime(reminder)
    return moment is not None and now >= moment and reminder.get("notifiedFor") != ringKey(reminder)


def markRung(reminder):
    reminder["notifiedFor"] = ringKey(reminder)


def snooze(reminder, minutes, now):
    reminder["snoozedUntil"] = toIso(now + datetime.timedelta(minutes=minutes))
    reminder["notifiedFor"] = None


def complete(reminder, now):
    """Marks the current occurrence done; repeating reminders move to their next future occurrence."""
    history = reminder.setdefault("doneHistory", [])
    history.append(toIso(now))
    del history[:-50]
    reminder["snoozedUntil"] = None
    reminder["notifiedFor"] = None
    if not isRepeating(reminder):
        reminder["completed"] = True
        reminder["completedAt"] = toIso(now)
        return
    start = parseDateTime(reminder["start"])
    current = parseDateTime(reminder["nextAt"]) or now
    following = nextOccurrence(start, reminder["rule"], max(current, now))
    reminder["nextAt"] = toIso(following) if following else None
    if following is None:
        reminder["completed"] = True
        reminder["completedAt"] = toIso(now)


def reopen(reminder, now):
    reminder["completed"] = False
    reminder.pop("completedAt", None)
    scheduleFirst(reminder, now)


# quick add parser ----------------------------------------------------------------
WEEKDAY_WORDS = {
    "lunedi": 0, "lunedì": 0, "martedi": 1, "martedì": 1, "mercoledi": 2, "mercoledì": 2, "giovedi": 3, "giovedì": 3,
    "venerdi": 4, "venerdì": 4, "sabato": 5, "domenica": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
}
UNIT_MINUTES = {"min": 1, "mins": 1, "minuto": 1, "minuti": 1, "minute": 1, "minutes": 1, "m": 1,
                "ora": 60, "ore": 60, "h": 60, "hour": 60, "hours": 60,
                "giorno": 1440, "giorni": 1440, "day": 1440, "days": 1440, "g": 1440, "d": 1440}


def parseQuickReminder(text, now=None):
    """'domani alle 9 chiama Marco' -> ('chiama Marco', datetime). Returns (title, None) if no time found."""
    now = (now or datetime.datetime.now()).replace(second=0, microsecond=0)
    working = " " + text.strip() + " "
    targetDate = None
    targetTime = None
    relative = None

    def cut(match):
        nonlocal working
        working = working[:match.start()] + " " + working[match.end():]

    match = re.search(r"\b(?:tra|fra|in)\s+(\d+(?:[.,]\d+)?)\s*(minuti|minuto|minutes|minute|mins|min|m|ore|ora|hours|hour|h|giorni|giorno|days|day|g|d)\b",
                      working, re.IGNORECASE)
    if match:
        amount = float(match.group(1).replace(",", "."))
        relative = datetime.timedelta(minutes=amount * UNIT_MINUTES[match.group(2).lower()])
        cut(match)
    match = re.search(r"\b(?:tra|fra|in)\s+(?:un'|un |mezz')?(ora|oretta|hour|mezz'ora|mezzora)\b", working, re.IGNORECASE)
    if relative is None and match:
        relative = datetime.timedelta(minutes=30 if "mezz" in match.group(0).lower() else 60)
        cut(match)
    match = re.search(r"\b(dopodomani|domani|oggi|stasera|stamattina|tomorrow|today|tonight)\b", working, re.IGNORECASE)
    if match:
        word = match.group(1).lower()
        offset = {"dopodomani": 2, "domani": 1, "tomorrow": 1}.get(word, 0)
        targetDate = now.date() + datetime.timedelta(days=offset)
        if word in ("stasera", "tonight"):
            targetTime = datetime.time(20, 0)
        elif word == "stamattina":
            targetTime = datetime.time(9, 0)
        cut(match)
    match = re.search(r"\b(?:(?:il|lo|next|on)\s+)?(" + "|".join(WEEKDAY_WORDS) + r")\b", working, re.IGNORECASE)
    if match and targetDate is None:
        weekday = WEEKDAY_WORDS[match.group(1).lower()]
        daysAhead = (weekday - now.weekday()) % 7 or 7
        targetDate = now.date() + datetime.timedelta(days=daysAhead)
        cut(match)
    match = re.search(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\b", working)
    if match and targetDate is None:
        day, month = int(match.group(1)), int(match.group(2))
        year = int(match.group(3)) if match.group(3) else now.year
        if year < 100:
            year += 2000
        try:
            targetDate = datetime.date(year, month, day)
            if not match.group(3) and targetDate < now.date():
                targetDate = targetDate.replace(year=year + 1)
            cut(match)
        except ValueError:
            pass
    match = re.search(r"\b(?:alle|all'|ore|at|@)\s*(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?\b|\b(\d{1,2})[:.](\d{2})\b", working,
                      re.IGNORECASE)
    if match:
        hour = int(match.group(1) or match.group(4))
        minute = int(match.group(2) or match.group(5) or 0)
        meridiem = (match.group(3) or "").lower()
        if meridiem == "pm" and hour < 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        if 0 <= hour < 24 and 0 <= minute < 60:
            targetTime = datetime.time(hour, minute)
            cut(match)
    title = re.sub(r"\s+", " ", working).strip(" ,.-")
    title = re.sub(r"^(ricordami di|ricordami|remind me to|remind me)\s+", "", title, flags=re.IGNORECASE).strip()
    if relative is not None:
        return title, now + relative
    if targetDate is None and targetTime is None:
        return title, None
    if targetDate is None:
        targetDate = now.date()
        if datetime.datetime.combine(targetDate, targetTime) <= now:
            targetDate += datetime.timedelta(days=1)
    if targetTime is None:
        targetTime = datetime.time(9, 0)
    return title, datetime.datetime.combine(targetDate, targetTime)
