"""Global hotkeys. On Windows uses RegisterHotKey in a dedicated message-loop thread."""
import queue
import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QKeySequence

from pchub.core.logger import getLogger
from pchub.core.paths import isWindows

log = getLogger("hotkeys")

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

NAMED_KEYS = {
    "space": 0x20, "tab": 0x09, "return": 0x0D, "enter": 0x0D, "esc": 0x1B, "escape": 0x1B,
    "backspace": 0x08, "ins": 0x2D, "insert": 0x2D, "del": 0x2E, "delete": 0x2E, "home": 0x24, "end": 0x23,
    "pgup": 0x21, "pageup": 0x21, "pgdown": 0x22, "pagedown": 0x22, "left": 0x25, "up": 0x26, "right": 0x27,
    "down": 0x28, "print": 0x2C, "pause": 0x13, "scrolllock": 0x91, "capslock": 0x14, "numlock": 0x90,
    "media play": 0xB3, "toggle media play/pause": 0xB3, "media pause": 0xB3, "media next": 0xB0,
    "media previous": 0xB1, "media stop": 0xB2, "volume up": 0xAF, "volume down": 0xAE, "volume mute": 0xAD,
    "menu": 0x5D,
}
NUMPAD_KEYS = {"*": 0x6A, "+": 0x6B, "-": 0x6D, ".": 0x6E, ",": 0x6E, "/": 0x6F, "enter": 0x0D, "return": 0x0D}


class HotkeyResult:
    def __init__(self, ok, reason="", conflictOwner=None):
        self.ok = ok
        self.reason = reason
        self.conflictOwner = conflictOwner

    def __bool__(self):
        return self.ok


def normalizeSequence(sequenceText):
    if not sequenceText:
        return ""
    keySequence = QKeySequence(sequenceText)
    if keySequence.isEmpty():
        return ""
    return QKeySequence(keySequence[0]).toString(QKeySequence.PortableText)


def _charToVirtualKey(character):
    if isWindows:
        import ctypes
        from ctypes import wintypes
        vkKeyScan = ctypes.windll.user32.VkKeyScanW
        vkKeyScan.argtypes = [wintypes.WCHAR]
        vkKeyScan.restype = ctypes.c_short
        scanResult = vkKeyScan(character)
        if scanResult == -1:
            return None
        return scanResult & 0xFF
    return ord(character.upper())


def parseSequence(sequenceText):
    """'Ctrl+Alt+H' -> (modifiers, virtualKey) or None."""
    normalized = normalizeSequence(sequenceText)
    if not normalized:
        return None
    if normalized.endswith("++"):
        parts = normalized[:-2].split("+") if len(normalized) > 2 else []
        parts = [part for part in parts if part] + ["+"]
    else:
        parts = normalized.split("+")
    keyName = parts[-1]
    modifierNames = [part.lower() for part in parts[:-1]]
    modifiers = 0
    isNumpad = False
    for modifierName in modifierNames:
        if modifierName == "ctrl":
            modifiers |= MOD_CONTROL
        elif modifierName == "alt":
            modifiers |= MOD_ALT
        elif modifierName == "shift":
            modifiers |= MOD_SHIFT
        elif modifierName == "meta":
            modifiers |= MOD_WIN
        elif modifierName == "num":
            isNumpad = True
        else:
            return None
    lowerKey = keyName.lower()
    virtualKey = None
    if isNumpad:
        if keyName.isdigit() and len(keyName) == 1:
            virtualKey = 0x60 + int(keyName)
        else:
            virtualKey = NUMPAD_KEYS.get(lowerKey)
    elif lowerKey.startswith("f") and lowerKey[1:].isdigit() and 1 <= int(lowerKey[1:]) <= 24:
        virtualKey = 0x70 + int(lowerKey[1:]) - 1
    elif lowerKey in NAMED_KEYS:
        virtualKey = NAMED_KEYS[lowerKey]
    elif len(keyName) == 1:
        if keyName.isalnum() and keyName.isascii():
            virtualKey = ord(keyName.upper())
        else:
            virtualKey = _charToVirtualKey(keyName)
    if virtualKey is None:
        return None
    if modifiers == 0 and not (0x70 <= virtualKey <= 0x87 or virtualKey in (0xB0, 0xB1, 0xB2, 0xB3, 0xAD, 0xAE, 0xAF, 0x13, 0x91, 0x2C)):
        return None
    return modifiers, virtualKey


class _NullBackend:
    def __init__(self, onFired):
        self.onFired = onFired

    def register(self, hotkeyId, modifiers, virtualKey):
        return True

    def unregister(self, hotkeyId):
        return True

    def shutdown(self):
        pass


class _WindowsBackend:
    WM_HOTKEY = 0x0312
    WM_APP_COMMAND = 0x8000 + 77
    WM_QUIT = 0x0012

    def __init__(self, onFired):
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        self.wintypes = wintypes
        self.onFired = onFired
        self.commandQueue = queue.Queue()
        self.threadId = None
        self.readyEvent = threading.Event()
        self.workerThread = threading.Thread(target=self._run, name="pchub-hotkeys", daemon=True)
        self.workerThread.start()
        self.readyEvent.wait(3)

    def _run(self):
        ctypes = self.ctypes
        wintypes = self.wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self.threadId = kernel32.GetCurrentThreadId()
        message = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(message), None, 0x0400, 0x0400, 0)
        self.readyEvent.set()
        while True:
            result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
            if result == 0 or result == -1:
                break
            if message.message == self.WM_HOTKEY:
                try:
                    self.onFired(int(message.wParam))
                except Exception:
                    log.exception("Hotkey callback failed")
            elif message.message == self.WM_APP_COMMAND:
                while True:
                    try:
                        command, args, resultHolder, doneEvent = self.commandQueue.get_nowait()
                    except queue.Empty:
                        break
                    if command == "register":
                        hotkeyId, modifiers, virtualKey = args
                        resultHolder.append(bool(user32.RegisterHotKey(None, hotkeyId, modifiers | MOD_NOREPEAT, virtualKey)))
                    elif command == "unregister":
                        resultHolder.append(bool(user32.UnregisterHotKey(None, args[0])))
                    doneEvent.set()

    def _call(self, command, *args):
        if not self.threadId:
            return False
        resultHolder = []
        doneEvent = threading.Event()
        self.commandQueue.put((command, args, resultHolder, doneEvent))
        self.ctypes.windll.user32.PostThreadMessageW(self.threadId, self.WM_APP_COMMAND, 0, 0)
        doneEvent.wait(2)
        return resultHolder[0] if resultHolder else False

    def register(self, hotkeyId, modifiers, virtualKey):
        return self._call("register", hotkeyId, modifiers, virtualKey)

    def unregister(self, hotkeyId):
        return self._call("unregister", hotkeyId)

    def shutdown(self):
        if self.threadId:
            self.ctypes.windll.user32.PostThreadMessageW(self.threadId, self.WM_QUIT, 0, 0)


class HotkeyManager(QObject):
    _firedFromThread = Signal(int)
    triggered = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bindings = {}
        self.nextHotkeyId = 1
        self.suspended = False
        self.ownerLabels = {}
        self._firedFromThread.connect(self._handleFired)
        backendClass = _WindowsBackend if isWindows else _NullBackend
        try:
            self.backend = backendClass(self._firedFromThread.emit)
        except Exception:
            log.exception("Hotkey backend failed, using null backend")
            self.backend = _NullBackend(self._firedFromThread.emit)

    def setOwnerLabel(self, owner, label):
        self.ownerLabels[owner] = label

    def ownerLabel(self, owner):
        labelValue = self.ownerLabels.get(owner, owner)
        return labelValue() if callable(labelValue) else labelValue

    def ownerOf(self, sequenceText):
        normalized = normalizeSequence(sequenceText)
        for owner, binding in self.bindings.items():
            if binding["sequence"] == normalized:
                return owner
        return None

    def bind(self, owner, sequenceText, callback):
        self.unbind(owner)
        normalized = normalizeSequence(sequenceText)
        if not normalized:
            return HotkeyResult(True, "empty")
        parsed = parseSequence(normalized)
        if parsed is None:
            return HotkeyResult(False, "invalid")
        existingOwner = self.ownerOf(normalized)
        if existingOwner and existingOwner != owner:
            return HotkeyResult(False, "conflictInternal", existingOwner)
        hotkeyId = self.nextHotkeyId
        self.nextHotkeyId += 1
        registered = True
        if not self.suspended:
            registered = self.backend.register(hotkeyId, parsed[0], parsed[1])
        if not registered:
            return HotkeyResult(False, "conflictSystem")
        self.bindings[owner] = {"sequence": normalized, "parsed": parsed, "callback": callback, "id": hotkeyId}
        return HotkeyResult(True)

    def unbind(self, owner):
        binding = self.bindings.pop(owner, None)
        if binding and not self.suspended:
            self.backend.unregister(binding["id"])

    def unbindPrefix(self, prefix):
        for owner in [owner for owner in self.bindings if owner.startswith(prefix)]:
            self.unbind(owner)

    def suspend(self):
        if self.suspended:
            return
        self.suspended = True
        for binding in self.bindings.values():
            self.backend.unregister(binding["id"])

    def resume(self):
        if not self.suspended:
            return
        self.suspended = False
        for binding in self.bindings.values():
            self.backend.register(binding["id"], binding["parsed"][0], binding["parsed"][1])

    def simulate(self, sequenceText):
        owner = self.ownerOf(sequenceText)
        if owner:
            self._handleFired(self.bindings[owner]["id"])
            return True
        return False

    def _handleFired(self, hotkeyId):
        for owner, binding in list(self.bindings.items()):
            if binding["id"] == hotkeyId:
                self.triggered.emit(owner)
                try:
                    binding["callback"]()
                except Exception:
                    log.exception("Hotkey action failed for %s", owner)
                break

    def shutdown(self):
        for owner in list(self.bindings):
            self.unbind(owner)
        self.backend.shutdown()
