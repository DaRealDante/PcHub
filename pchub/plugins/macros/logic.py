"""Pure macro logic (no Qt, no Windows): data model, key names, trigger matching, recording -> steps, descriptions.
Fully unit tested."""
import copy
import random
import uuid

from pchub.core.i18n import T, language, tr

MODIFIER_KEYS = {0x10: "shift", 0xA0: "shift", 0xA1: "shift", 0x11: "ctrl", 0xA2: "ctrl", 0xA3: "ctrl",
                 0x12: "alt", 0xA4: "alt", 0xA5: "alt", 0x5B: "win", 0x5C: "win"}
MODIFIER_ORDER = ["ctrl", "alt", "shift", "win"]
MODIFIER_VK = {"ctrl": 0xA2, "alt": 0xA4, "shift": 0xA0, "win": 0x5B}
MODIFIER_LABELS = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "win": "Win"}

KEY_NAMES = {
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Invio", 0x13: "Pausa", 0x14: "Caps Lock", 0x1B: "Esc", 0x20: "Spazio",
    0x21: "Pag Su", 0x22: "Pag Giù", 0x23: "Fine", 0x24: "Home", 0x25: "←", 0x26: "↑", 0x27: "→", 0x28: "↓",
    0x2C: "Stamp", 0x2D: "Ins", 0x2E: "Canc", 0x5D: "Menu", 0x90: "Num Lock", 0x91: "Bloc Scorr",
    0x6A: "Num *", 0x6B: "Num +", 0x6D: "Num -", 0x6E: "Num .", 0x6F: "Num /",
    0xBA: "è", 0xBB: "+", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "ù", 0xC0: "ò", 0xDB: "'", 0xDC: "\\", 0xDD: "ì",
    0xDE: "à", 0xE2: "<",
    0xAD: "Muto", 0xAE: "Volume -", 0xAF: "Volume +", 0xB0: "Traccia succ.", 0xB1: "Traccia prec.", 0xB2: "Stop",
    0xB3: "Play/Pausa",
    0x10: "Shift", 0xA0: "Shift", 0xA1: "Shift dx", 0x11: "Ctrl", 0xA2: "Ctrl", 0xA3: "Ctrl dx", 0x12: "Alt",
    0xA4: "Alt", 0xA5: "Alt Gr", 0x5B: "Win", 0x5C: "Win dx",
}
ENGLISH_KEY_NAMES = {0x0D: "Enter", 0x13: "Pause", 0x20: "Space", 0x21: "Page Up", 0x22: "Page Down", 0x23: "End",
                     0x2C: "Print", 0x2E: "Del", 0x91: "Scroll Lock", 0xAD: "Mute", 0xB0: "Next track",
                     0xB1: "Previous track", 0xB3: "Play/Pause", 0xA1: "Right Shift", 0xA3: "Right Ctrl",
                     0x5C: "Right Win"}
MOUSE_BUTTONS = ["left", "right", "middle", "x1", "x2", "wheelUp", "wheelDown"]
MOUSE_NAMES = {
    "left": T("Clic sinistro", "Left click"), "right": T("Clic destro", "Right click"),
    "middle": T("Clic centrale", "Middle click"), "x1": T("Mouse 4 (indietro)", "Mouse 4 (back)"),
    "x2": T("Mouse 5 (avanti)", "Mouse 5 (forward)"), "wheelUp": T("Rotellina su", "Wheel up"),
    "wheelDown": T("Rotellina giù", "Wheel down"),
}
BUTTON_SHORT = {"left": T("sinistro", "left"), "right": T("destro", "right"), "middle": T("centrale", "middle"),
                "x1": "Mouse 4", "x2": "Mouse 5"}

MODES = ["once", "toggle", "hold", "repeat"]
MODE_NAMES = {
    "once": T("Una volta", "Once"),
    "toggle": T("Avvia / ferma", "Start / stop"),
    "hold": T("Finché tengo premuto", "While held"),
    "repeat": T("Ripeti N volte", "Repeat N times"),
}
MODE_HINTS = {
    "once": T("Ogni volta che premi parte una volta. Se ripremi mentre va, si ferma.",
              "Runs once each press. Press again while it's running to stop it."),
    "toggle": T("Premi per farla partire in loop, ripremi per fermarla.", "Press to start looping, press again to stop."),
    "hold": T("Va in loop finché tieni premuto il tasto, si ferma quando lo lasci.",
              "Loops while you hold the key, stops when you let go."),
    "repeat": T("Parte e si ripete il numero di volte che scegli.", "Runs and repeats as many times as you choose."),
}
STEP_TYPES = ["key", "text", "click", "move", "scroll", "wait", "run"]
STEP_NAMES = {
    "key": T("Tasto", "Key"), "text": T("Scrivi testo", "Type text"), "click": T("Clic", "Click"),
    "move": T("Muovi mouse", "Move mouse"), "scroll": T("Rotellina", "Scroll"), "wait": T("Aspetta", "Wait"),
    "run": T("Apri programma", "Open program"),
}
STEP_ICONS = {"key": "keyboard", "text": "type", "click": "mouse-pointer-click", "move": "move", "scroll": "mouse",
              "wait": "hourglass", "run": "app-window"}
KEY_ACTIONS = {"tap": T("premi", "press"), "down": T("tieni giù", "hold down"), "up": T("rilascia", "release")}
CLICK_ACTIONS = {"click": T("clic", "click"), "double": T("doppio clic", "double click"),
                 "down": T("tieni premuto", "hold down"), "up": T("rilascia", "release")}


def newId():
    return uuid.uuid4().hex[:10]


def keyName(virtualKey, english=None):
    virtualKey = int(virtualKey or 0)
    if english is None:
        english = language() == "en"
    if english and virtualKey in ENGLISH_KEY_NAMES:
        return ENGLISH_KEY_NAMES[virtualKey]
    if virtualKey in KEY_NAMES:
        return KEY_NAMES[virtualKey]
    if 0x30 <= virtualKey <= 0x39 or 0x41 <= virtualKey <= 0x5A:
        return chr(virtualKey)
    if 0x60 <= virtualKey <= 0x69:
        return f"Num {virtualKey - 0x60}"
    if 0x70 <= virtualKey <= 0x87:
        return f"F{virtualKey - 0x6F}"
    return f"0x{virtualKey:02X}"


def sortedMods(mods):
    return [mod for mod in MODIFIER_ORDER if mod in set(mods or [])]


def triggerText(trigger, english=None):
    if not trigger:
        return tr(T("Nessun tasto", "No key"))
    parts = [MODIFIER_LABELS[mod] for mod in sortedMods(trigger.get("mods"))]
    if trigger.get("device") == "mouse":
        parts.append(tr(MOUSE_NAMES.get(trigger.get("code"), trigger.get("code"))))
    else:
        parts.append(keyName(trigger.get("code"), english))
    return " + ".join(parts)


def isDangerousTrigger(trigger):
    """A plain left/right click as trigger would hijack the mouse."""
    return bool(trigger and trigger.get("device") == "mouse" and trigger.get("code") in ("left", "right")
                and not trigger.get("mods"))


def defaultClicker():
    return {"button": "left", "cps": 10, "randomPercent": 15, "double": False, "position": "cursor", "x": 0, "y": 0,
            "limit": "none", "limitValue": 100, "holdMs": 15}


def newMacro(kind="steps", name=None):
    macro = {
        "id": newId(), "name": name or "", "icon": "mouse-pointer-click" if kind == "clicker" else "zap",
        "color": "#8B7CF6" if kind == "steps" else "#38BDF8", "enabled": True, "kind": kind, "trigger": None,
        "mode": "toggle" if kind == "clicker" else "once", "repeatCount": 5, "loopDelay": 0, "blockTrigger": True,
        "scope": "global", "apps": [], "steps": [], "speed": 1.0, "stepDelay": 20, "clicker": defaultClicker(),
        "runCount": 0, "lastRun": None,
    }
    return macro


def normalizeMacro(macro):
    """Fills missing fields (old saves, hand-edited json) so the rest of the code never has to check."""
    base = newMacro(macro.get("kind", "steps") if isinstance(macro, dict) else "steps")
    if not isinstance(macro, dict):
        return base
    result = copy.deepcopy(base)
    result.update({key: value for key, value in macro.items() if value is not None or key in ("trigger", "lastRun")})
    clicker = defaultClicker()
    clicker.update(result.get("clicker") or {})
    result["clicker"] = clicker
    if result["mode"] not in MODES:
        result["mode"] = base["mode"]
    result["apps"] = [str(app).strip().lower() for app in result.get("apps") or [] if str(app).strip()]
    result["steps"] = [step for step in result.get("steps") or [] if isinstance(step, dict) and step.get("type") in STEP_TYPES]
    return result


def newStep(stepType):
    defaults = {
        "key": {"vk": 0x45, "action": "tap", "mods": []},
        "text": {"text": ""},
        "click": {"button": "left", "action": "click"},
        "move": {"x": 0, "y": 0, "relative": False},
        "scroll": {"amount": -3},
        "wait": {"ms": 500, "randomMs": 0},
        "run": {"path": ""},
    }
    step = {"id": newId(), "type": stepType}
    step.update(copy.deepcopy(defaults[stepType]))
    return step


def describeStep(step, english=None):
    stepType = step.get("type")
    if stepType == "key":
        combo = " + ".join([MODIFIER_LABELS[mod] for mod in sortedMods(step.get("mods"))] + [keyName(step.get("vk"), english)])
        return f"{tr(KEY_ACTIONS.get(step.get('action'), KEY_ACTIONS['tap'])).capitalize()} {combo}"
    if stepType == "text":
        text = step.get("text", "")
        return f"{tr(STEP_NAMES['text'])}: “{text[:40]}{'…' if len(text) > 40 else ''}”"
    if stepType == "click":
        position = ""
        if step.get("x") is not None and step.get("y") is not None and step.get("atPosition"):
            position = f" @ {step['x']}, {step['y']}"
        return (f"{tr(CLICK_ACTIONS.get(step.get('action'), CLICK_ACTIONS['click'])).capitalize()} "
                f"{tr(BUTTON_SHORT.get(step.get('button'), step.get('button')))}{position}")
    if stepType == "move":
        if step.get("relative"):
            return tr(T("Sposta mouse di {x}, {y}", "Move mouse by {x}, {y}"), x=step.get("x", 0), y=step.get("y", 0))
        return tr(T("Mouse in {x}, {y}", "Mouse to {x}, {y}"), x=step.get("x", 0), y=step.get("y", 0))
    if stepType == "scroll":
        amount = int(step.get("amount", 0))
        return tr(T("Rotellina {direction} ×{count}", "Scroll {direction} ×{count}"),
                  direction=tr(T("su", "up")) if amount > 0 else tr(T("giù", "down")), count=abs(amount))
    if stepType == "wait":
        text = formatMs(step.get("ms", 0))
        if step.get("randomMs"):
            text += f" ± {formatMs(step['randomMs'])}"
        return f"{tr(STEP_NAMES['wait'])} {text}"
    if stepType == "run":
        path = str(step.get("path") or "")
        return f"{tr(STEP_NAMES['run'])}: {path.replace(chr(92), '/').rsplit('/', 1)[-1] or '…'}"
    return stepType


def formatMs(milliseconds):
    milliseconds = int(milliseconds or 0)
    if milliseconds >= 1000:
        seconds = milliseconds / 1000.0
        return f"{seconds:.1f} s".replace(".0 s", " s")
    return f"{milliseconds} ms"


def estimatedDuration(macro):
    """Milliseconds for one run of a steps macro (without random parts)."""
    total = 0
    speed = max(0.1, float(macro.get("speed") or 1.0))
    actionSteps = 0
    for step in macro.get("steps", []):
        if step["type"] == "wait":
            total += int(step.get("ms", 0)) / speed
        else:
            actionSteps += 1
    total += actionSteps * int(macro.get("stepDelay") or 0) / speed
    return int(total)


def clickInterval(clicker, generator=random):
    """Seconds until the next autoclicker click."""
    cps = max(0.1, float(clicker.get("cps") or 10))
    base = 1.0 / cps
    jitter = max(0, min(90, int(clicker.get("randomPercent") or 0))) / 100.0
    if jitter:
        base *= 1.0 + generator.uniform(-jitter, jitter)
    return max(0.001, base)


def waitSeconds(step, speed=1.0, generator=random):
    milliseconds = int(step.get("ms", 0))
    randomPart = int(step.get("randomMs", 0) or 0)
    if randomPart:
        milliseconds += generator.randint(-randomPart, randomPart)
    return max(0, milliseconds) / 1000.0 / max(0.1, float(speed or 1.0))


# matching ---------------------------------------------------------------------------
def triggerMatches(trigger, device, code, mods):
    if not trigger or trigger.get("device") != device:
        return False
    if trigger.get("code") != code:
        return False
    return set(trigger.get("mods") or []) == set(mods or [])


def appAllowed(macro, foregroundProcess):
    if macro.get("scope") != "apps":
        return True
    apps = macro.get("apps") or []
    if not apps:
        return True
    return (foregroundProcess or "").lower() in apps


def matchingMacros(macros, device, code, mods, foregroundProcess):
    return [macro for macro in macros
            if macro.get("enabled") and triggerMatches(macro.get("trigger"), device, code, mods)
            and appAllowed(macro, foregroundProcess)]


def triggerConflicts(macros, macro):
    """Other enabled macros with the same trigger whose apps overlap."""
    conflicts = []
    trigger = macro.get("trigger")
    if not trigger:
        return conflicts
    for other in macros:
        if other["id"] == macro["id"] or not other.get("enabled") or not other.get("trigger"):
            continue
        if not triggerMatches(other["trigger"], trigger.get("device"), trigger.get("code"), trigger.get("mods")):
            continue
        globalEither = macro.get("scope") != "apps" or other.get("scope") != "apps" or not macro.get("apps") \
            or not other.get("apps")
        if globalEither or set(macro["apps"]) & set(other["apps"]):
            conflicts.append(other)
    return conflicts


# recording -----------------------------------------------------------------------------
def recordingToSteps(events, recordWaits=True, recordMoves=False, minimumWaitMs=15):
    """events: list of dicts in time order:
         {"t": seconds, "kind": "key", "vk": int, "down": bool}
         {"t": seconds, "kind": "button", "button": "left", "down": bool, "x": int, "y": int}
         {"t": seconds, "kind": "wheel", "amount": int (+1 up / -1 down), "x", "y"}
         {"t": seconds, "kind": "move", "x": int, "y": int}
    Returns steps: taps (with modifiers folded in), clicks at position, scrolls, waits."""
    raw = []
    heldKeys = set()
    for event in events:
        if event["kind"] == "key":
            if event["down"]:
                if event["vk"] in heldKeys:
                    continue
                heldKeys.add(event["vk"])
            else:
                if event["vk"] not in heldKeys:
                    continue
                heldKeys.discard(event["vk"])
        raw.append(event)

    steps = []
    lastTime = raw[0]["t"] if raw else 0.0
    index = 0
    lastMoveTime = -1.0

    def addWait(eventTime):
        nonlocal lastTime
        gap = int(round((eventTime - lastTime) * 1000))
        lastTime = eventTime
        if recordWaits and gap >= minimumWaitMs:
            gap = int(round(gap / 10.0)) * 10
            if steps and steps[-1]["type"] == "wait":
                steps[-1]["ms"] += gap
            else:
                step = newStep("wait")
                step["ms"] = gap
                steps.append(step)

    while index < len(raw):
        event = raw[index]
        kind = event["kind"]
        if kind == "move":
            if recordMoves and event["t"] - lastMoveTime >= 0.04:
                addWait(event["t"])
                step = newStep("move")
                step["x"], step["y"] = int(event["x"]), int(event["y"])
                steps.append(step)
                lastMoveTime = event["t"]
            index += 1
            continue
        if kind == "wheel":
            addWait(event["t"])
            amount = event["amount"]
            following = index + 1
            while following < len(raw) and raw[following]["kind"] == "wheel" and \
                    (raw[following]["amount"] > 0) == (amount > 0) and raw[following]["t"] - raw[following - 1]["t"] < 0.25:
                amount += raw[following]["amount"]
                following += 1
            step = newStep("scroll")
            step["amount"] = amount
            steps.append(step)
            lastTime = raw[following - 1]["t"]
            index = following
            continue
        if kind == "button":
            if event["down"]:
                releaseIndex = _findRelease(raw, index, lambda other: other["kind"] == "button"
                                            and other["button"] == event["button"] and not other["down"])
                quickClick = releaseIndex is not None and _onlyMovesBetween(raw, index, releaseIndex) \
                    and raw[releaseIndex]["t"] - event["t"] < 0.5
                if quickClick:
                    previous = steps[-1] if steps else None
                    trailingWait = None
                    if previous is not None and previous["type"] == "wait" and len(steps) > 1:
                        trailingWait, previous = previous, steps[-2]
                    if previous is not None and previous["type"] == "click" and previous.get("action") == "click" \
                            and previous["button"] == event["button"] and event["t"] - previous.get("_t", -9) < 0.35 \
                            and abs(previous.get("x", 0) - int(event.get("x", 0))) < 6 \
                            and abs(previous.get("y", 0) - int(event.get("y", 0))) < 6:
                        if trailingWait is not None:
                            steps.remove(trailingWait)
                        previous["action"] = "double"
                    else:
                        addWait(event["t"])
                        step = newStep("click")
                        step.update({"button": event["button"], "action": "click", "x": int(event.get("x", 0)),
                                     "y": int(event.get("y", 0)), "atPosition": True, "_t": event["t"]})
                        steps.append(step)
                    lastTime = raw[releaseIndex]["t"]
                    raw = raw[:releaseIndex] + raw[releaseIndex + 1:]
                    index += 1
                    continue
            addWait(event["t"])
            step = newStep("click")
            step.update({"button": event["button"], "action": "down" if event["down"] else "up",
                         "x": int(event.get("x", 0)), "y": int(event.get("y", 0)), "atPosition": True})
            steps.append(step)
            index += 1
            continue
        # key
        addWait(event["t"])
        steps.append({"id": newId(), "type": "key", "vk": event["vk"], "action": "down" if event["down"] else "up",
                      "mods": []})
        index += 1
    for step in steps:
        step.pop("_t", None)
    steps = _mergeWaits(_foldKeys(steps))
    while steps and steps[-1]["type"] == "wait":
        steps.pop()
    while steps and steps[0]["type"] == "wait":
        steps.pop(0)
    return steps


def _mergeWaits(steps):
    result = []
    for step in steps:
        if step["type"] == "wait" and result and result[-1]["type"] == "wait":
            result[-1]["ms"] += step["ms"]
        else:
            result.append(step)
    return result


def _findRelease(events, startIndex, predicate):
    for index in range(startIndex + 1, len(events)):
        if predicate(events[index]):
            return index
    return None


def _onlyMovesBetween(events, startIndex, endIndex):
    return all(events[index]["kind"] == "move" for index in range(startIndex + 1, endIndex))


def _foldKeys(steps):
    """down X, up X -> tap X.  Ctrl down, tap C, Ctrl up -> tap Ctrl+C."""
    result = []
    index = 0
    while index < len(steps):
        step = steps[index]
        following = steps[index + 1] if index + 1 < len(steps) else None
        if step["type"] == "key" and step["action"] == "down" and following is not None \
                and following["type"] == "key" and following["action"] == "up" and following["vk"] == step["vk"]:
            result.append({"id": step["id"], "type": "key", "vk": step["vk"], "action": "tap", "mods": []})
            index += 2
            continue
        if step["type"] == "key" and step["action"] == "down" and following is not None and following["type"] == "wait":
            after = steps[index + 2] if index + 2 < len(steps) else None
            if after is not None and after["type"] == "key" and after["action"] == "up" and after["vk"] == step["vk"] \
                    and following["ms"] <= 250:
                result.append({"id": step["id"], "type": "key", "vk": step["vk"], "action": "tap", "mods": []})
                index += 3
                continue
        result.append(step)
        index += 1
    return _foldModifiers(result)


def _foldModifiers(steps):
    result = []
    index = 0
    while index < len(steps):
        step = steps[index]
        modifier = MODIFIER_KEYS.get(step.get("vk")) if step["type"] == "key" else None
        if modifier and step["action"] == "down":
            closing = None
            for scan in range(index + 1, len(steps)):
                candidate = steps[scan]
                if candidate["type"] == "key" and candidate["action"] == "up" and \
                        MODIFIER_KEYS.get(candidate.get("vk")) == modifier:
                    closing = scan
                    break
            if closing is not None:
                inner = steps[index + 1:closing]
                foldable = inner and all(
                    (item["type"] == "key" and item["action"] == "tap") or
                    (item["type"] == "wait" and item["ms"] <= 1500) for item in inner) \
                    and any(item["type"] == "key" for item in inner)
                if foldable:
                    for item in inner:
                        if item["type"] == "key":
                            item["mods"] = sortedMods(list(item.get("mods") or []) + [modifier])
                    folded = _foldModifiers(inner)
                    result.extend(folded)
                    index = closing + 1
                    continue
        result.append(step)
        index += 1
    return result


def duplicateMacro(macro, copySuffix=" (2)"):
    clone = copy.deepcopy(macro)
    clone["id"] = newId()
    clone["name"] = (macro.get("name") or "") + copySuffix
    clone["runCount"] = 0
    clone["lastRun"] = None
    for step in clone["steps"]:
        step["id"] = newId()
    return clone
