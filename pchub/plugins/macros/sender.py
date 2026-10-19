"""Sends keyboard/mouse input. Windows: SendInput with scan codes (works in most games) and PC Hub's signature in
dwExtraInfo, so PC Hub's own hooks (macro triggers, OLED Saver) can tell these events apart from real ones."""
import ctypes

from pchub.core.input_hooks import PCHUB_SIGNATURE
from pchub.core.paths import isWindows

EXTENDED_KEYS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C, 0x5D, 0x6F, 0x90, 0xA3, 0xA5,
                 0x2C, 0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB2, 0xB3}
MEDIA_KEYS = {0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB2, 0xB3}
BUTTON_FLAGS = {"left": (0x0002, 0x0004, 0), "right": (0x0008, 0x0010, 0), "middle": (0x0020, 0x0040, 0),
                "x1": (0x0080, 0x0100, 1), "x2": (0x0080, 0x0100, 2)}


class FakeSender:
    """Records what would be sent (tests and other platforms)."""

    def __init__(self):
        self.actions = []
        self.position = (0, 0)

    def keyDown(self, virtualKey):
        self.actions.append(("keyDown", virtualKey))

    def keyUp(self, virtualKey):
        self.actions.append(("keyUp", virtualKey))

    def typeText(self, text):
        self.actions.append(("text", text))

    def buttonDown(self, button):
        self.actions.append(("buttonDown", button))

    def buttonUp(self, button):
        self.actions.append(("buttonUp", button))

    def scroll(self, amount):
        self.actions.append(("scroll", amount))

    def moveTo(self, x, y):
        self.position = (x, y)
        self.actions.append(("moveTo", x, y))

    def moveBy(self, deltaX, deltaY):
        self.position = (self.position[0] + deltaX, self.position[1] + deltaY)
        self.actions.append(("moveBy", deltaX, deltaY))

    def cursorPosition(self):
        return self.position

    def run(self, path):
        self.actions.append(("run", path))


if isWindows:
    from ctypes import wintypes

    ULONG_PTR = ctypes.c_size_t

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

    class _InputUnion(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("union", _InputUnion)]

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    _user32.SendInput.restype = wintypes.UINT
    _user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    _user32.MapVirtualKeyW.restype = wintypes.UINT
    _user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    _user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]


class WindowsSender:
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004
    KEYEVENTF_SCANCODE = 0x0008

    def __init__(self, useScanCodes=True):
        self.useScanCodes = useScanCodes

    def _send(self, *inputs):
        array = (INPUT * len(inputs))(*inputs)
        _user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT))

    def _keyInput(self, virtualKey, up):
        flags = self.KEYEVENTF_KEYUP if up else 0
        scanCode = 0
        if virtualKey in EXTENDED_KEYS:
            flags |= self.KEYEVENTF_EXTENDEDKEY
        if self.useScanCodes and virtualKey not in MEDIA_KEYS:
            scanCode = _user32.MapVirtualKeyW(virtualKey, 0) & 0xFF
            if scanCode:
                flags |= self.KEYEVENTF_SCANCODE
        item = INPUT(type=1)
        item.union.ki = KEYBDINPUT(virtualKey, scanCode, flags, 0, PCHUB_SIGNATURE)
        return item

    def keyDown(self, virtualKey):
        self._send(self._keyInput(int(virtualKey), False))

    def keyUp(self, virtualKey):
        self._send(self._keyInput(int(virtualKey), True))

    def typeText(self, text):
        inputs = []
        for character in str(text).replace("\r\n", "\n"):
            if character == "\n":
                inputs += [self._keyInput(0x0D, False), self._keyInput(0x0D, True)]
                continue
            encoded = character.encode("utf-16-le")
            for offset in range(0, len(encoded), 2):
                unit = int.from_bytes(encoded[offset:offset + 2], "little")
                for up in (False, True):
                    item = INPUT(type=1)
                    item.union.ki = KEYBDINPUT(0, unit, self.KEYEVENTF_UNICODE | (self.KEYEVENTF_KEYUP if up else 0), 0,
                                               PCHUB_SIGNATURE)
                    inputs.append(item)
        for start in range(0, len(inputs), 200):
            self._send(*inputs[start:start + 200])

    def _mouse(self, flags, data=0, deltaX=0, deltaY=0):
        item = INPUT(type=0)
        item.union.mi = MOUSEINPUT(deltaX, deltaY, data & 0xFFFFFFFF, flags, 0, PCHUB_SIGNATURE)
        self._send(item)

    def buttonDown(self, button):
        downFlag, _upFlag, data = BUTTON_FLAGS.get(button, BUTTON_FLAGS["left"])
        self._mouse(downFlag, data)

    def buttonUp(self, button):
        _downFlag, upFlag, data = BUTTON_FLAGS.get(button, BUTTON_FLAGS["left"])
        self._mouse(upFlag, data)

    def scroll(self, amount):
        self._mouse(0x0800, int(amount) * 120)

    def moveTo(self, x, y):
        _user32.SetCursorPos(int(x), int(y))

    def moveBy(self, deltaX, deltaY):
        self._mouse(0x0001, 0, int(deltaX), int(deltaY))

    def cursorPosition(self):
        point = wintypes.POINT()
        _user32.GetCursorPos(ctypes.byref(point))
        return point.x, point.y

    def run(self, path):
        from pchub.core.winapi import openPath
        openPath(path)


def createSender(useScanCodes=True):
    return WindowsSender(useScanCodes) if isWindows else FakeSender()
