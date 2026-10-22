"""Low-level keyboard/mouse hooks (WH_KEYBOARD_LL / WH_MOUSE_LL), shared by every plugin.

One background thread owns the hooks and only exists while somebody is subscribed. Callbacks run on that
thread and MUST be fast (no UI work: emit a Qt signal instead). A callback returning True swallows the event.
Events injected by PC Hub itself carry PCHUB_SIGNATURE in dwExtraInfo so plugins can ignore them.
"""
import ctypes
import threading
import time

from pchub.core.logger import getLogger
from pchub.core.paths import isWindows

log = getLogger("hooks")

PCHUB_SIGNATURE = 0x50434855
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0100, 0x0101, 0x0104, 0x0105
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0204, 0x0205
WM_MBUTTONDOWN, WM_MBUTTONUP = 0x0207, 0x0208
WM_MOUSEWHEEL, WM_XBUTTONDOWN, WM_XBUTTONUP, WM_MOUSEHWHEEL = 0x020A, 0x020B, 0x020C, 0x020E
LLKHF_INJECTED = 0x10
LLMHF_INJECTED = 0x01


class KeyEvent:
    __slots__ = ("virtualKey", "scanCode", "isDown", "injected", "fromPCHub", "timestamp")

    def __init__(self, virtualKey, scanCode, isDown, injected=False, fromPCHub=False, timestamp=None):
        self.virtualKey = virtualKey
        self.scanCode = scanCode
        self.isDown = isDown
        self.injected = injected
        self.fromPCHub = fromPCHub
        self.timestamp = time.monotonic() if timestamp is None else timestamp


class MouseEvent:
    __slots__ = ("message", "x", "y", "wheelDelta", "button", "isDown", "injected", "fromPCHub", "timestamp")

    def __init__(self, message, x, y, wheelDelta=0, injected=False, fromPCHub=False, timestamp=None):
        self.message = message
        self.x = x
        self.y = y
        self.wheelDelta = wheelDelta
        self.injected = injected
        self.fromPCHub = fromPCHub
        self.timestamp = time.monotonic() if timestamp is None else timestamp
        self.button, self.isDown = {
            WM_LBUTTONDOWN: ("left", True), WM_LBUTTONUP: ("left", False),
            WM_RBUTTONDOWN: ("right", True), WM_RBUTTONUP: ("right", False),
            WM_MBUTTONDOWN: ("middle", True), WM_MBUTTONUP: ("middle", False),
            WM_XBUTTONDOWN: ("x", True), WM_XBUTTONUP: ("x", False),
        }.get(message, (None, False))


class HookService:
    def __init__(self):
        self.keyboardSubscribers = {}
        self.mouseSubscribers = {}
        self.moveSubscribers = set()
        self.lock = threading.Lock()
        self.thread = None
        self.threadId = None
        self.readyEvent = threading.Event()
        self.lastRealInput = 0.0
        self.available = isWindows
        self.installedHooks = (False, False)
        self.lastFailureLogAt = 0.0

    # subscriptions --------------------------------------------------------
    def subscribe(self, name, keyboardCallback=None, mouseCallback=None, wantsMoves=False):
        """Subscribing again with the same name replaces both callbacks (None = not interested).
        Mouse movement is only delivered to subscribers that ask for it (wantsMoves): every other subscriber gets
        clicks/wheel only, which keeps the hook almost free while the mouse moves (1000 Hz mice!)."""
        with self.lock:
            before = self._neededHooks()
            self.keyboardSubscribers.pop(name, None)
            self.mouseSubscribers.pop(name, None)
            self.moveSubscribers.discard(name)
            if keyboardCallback:
                self.keyboardSubscribers[name] = keyboardCallback
            if mouseCallback:
                self.mouseSubscribers[name] = mouseCallback
                if wantsMoves:
                    self.moveSubscribers.add(name)
            after = self._neededHooks()
        if self.isActive() and after != self.installedHooks:
            self._stop()
        if after != before or not self.isActive():
            self._ensureRunning()

    def _neededHooks(self):
        return (bool(self.keyboardSubscribers), bool(self.mouseSubscribers))

    def unsubscribe(self, name):
        with self.lock:
            self.keyboardSubscribers.pop(name, None)
            self.mouseSubscribers.pop(name, None)
            self.moveSubscribers.discard(name)
            empty = not self.keyboardSubscribers and not self.mouseSubscribers
            needed = self._neededHooks()
        if empty:
            self._stop()
        elif self.isActive() and needed != self.installedHooks:
            self._stop()
            self._ensureRunning()

    def isActive(self):
        return self.thread is not None and self.thread.is_alive()

    # dispatch (also used by tests) -----------------------------------------
    def dispatchKey(self, event):
        if not event.injected:
            self.lastRealInput = event.timestamp
        blocked = False
        for callback in list(self.keyboardSubscribers.values()):
            try:
                if callback(event):
                    blocked = True
            except Exception:
                log.exception("Keyboard hook subscriber failed")
        return blocked

    def dispatchMouse(self, event):
        if not event.injected:
            self.lastRealInput = event.timestamp
        blocked = False
        subscribers = self.mouseSubscribers
        if event.message == WM_MOUSEMOVE:
            subscribers = {name: callback for name, callback in subscribers.items() if name in self.moveSubscribers}
        for callback in list(subscribers.values()):
            try:
                if callback(event):
                    blocked = True
            except Exception:
                log.exception("Mouse hook subscriber failed")
        return blocked

    # thread -----------------------------------------------------------------
    def _ensureRunning(self):
        if not isWindows or self.isActive() or not any(self._neededHooks()):
            return
        self.readyEvent.clear()
        self.thread = threading.Thread(target=self._run, name="pchub-input-hooks", daemon=True)
        self.thread.start()
        self.readyEvent.wait(2)

    def _stop(self):
        if self.isActive() and self.threadId:
            ctypes.windll.user32.PostThreadMessageW(self.threadId, 0x0012, 0, 0)
            self.thread.join(2)
        self.thread = None
        self.threadId = None
        self.installedHooks = (False, False)

    def shutdown(self):
        with self.lock:
            self.keyboardSubscribers.clear()
            self.mouseSubscribers.clear()
            self.moveSubscribers.clear()
        self._stop()

    def _hookFailed(self, kind):
        now = time.monotonic()
        if now - self.lastFailureLogAt > 60:
            self.lastFailureLogAt = now
            log.exception("The %s hook failed", kind)

    def _run(self):
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ULONG_PTR = ctypes.c_size_t

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

        class MSLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

        LRESULT = ctypes.c_ssize_t
        HookProc = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HookProc, wintypes.HINSTANCE, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = LRESULT
        user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        keyboardStructPointer = ctypes.POINTER(KBDLLHOOKSTRUCT)
        monotonic = time.monotonic
        mouseStructPointer = ctypes.POINTER(MSLLHOOKSTRUCT)
        callNext = user32.CallNextHookEx

        def keyboardProc(nCode, wParam, lParam):
            try:
                if nCode == 0:
                    data = ctypes.cast(lParam, keyboardStructPointer).contents
                    event = KeyEvent(data.vkCode, data.scanCode, wParam in (WM_KEYDOWN, WM_SYSKEYDOWN),
                                     bool(data.flags & LLKHF_INJECTED), data.dwExtraInfo == PCHUB_SIGNATURE)
                    if self.dispatchKey(event):
                        return 1
            except Exception:
                self._hookFailed("keyboard")
            return callNext(None, nCode, wParam, lParam)

        def mouseProc(nCode, wParam, lParam):
            try:
                if wParam == WM_MOUSEMOVE and nCode == 0 and not self.moveSubscribers:
                    # fast path: nobody wants movement, just remember that a real person moved the mouse
                    if not ctypes.cast(lParam, mouseStructPointer).contents.flags & LLMHF_INJECTED:
                        self.lastRealInput = monotonic()
                elif nCode == 0:
                    data = ctypes.cast(lParam, mouseStructPointer).contents
                    wheel = ctypes.c_short((data.mouseData >> 16) & 0xFFFF).value if wParam in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL) else 0
                    event = MouseEvent(wParam, data.pt.x, data.pt.y, wheel, bool(data.flags & LLMHF_INJECTED),
                                       data.dwExtraInfo == PCHUB_SIGNATURE)
                    if wParam in (WM_XBUTTONDOWN, WM_XBUTTONUP):
                        event.button = "x1" if (data.mouseData >> 16) == 1 else "x2"
                    if self.dispatchMouse(event):
                        return 1
            except Exception:
                self._hookFailed("mouse")
            return callNext(None, nCode, wParam, lParam)

        keyboardProcPointer = HookProc(keyboardProc)
        mouseProcPointer = HookProc(mouseProc)
        module = kernel32.GetModuleHandleW(None)
        wantKeyboard, wantMouse = self._neededHooks()
        self.installedHooks = (wantKeyboard, wantMouse)
        keyboardHook = user32.SetWindowsHookExW(13, keyboardProcPointer, module, 0) if wantKeyboard else None
        mouseHook = user32.SetWindowsHookExW(14, mouseProcPointer, module, 0) if wantMouse else None
        if (wantKeyboard and not keyboardHook) or (wantMouse and not mouseHook):
            log.error("Could not install input hooks (error %s)", ctypes.get_last_error())
        self.threadId = kernel32.GetCurrentThreadId()
        message = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
        self.readyEvent.set()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        if keyboardHook:
            user32.UnhookWindowsHookEx(keyboardHook)
        if mouseHook:
            user32.UnhookWindowsHookEx(mouseHook)
        del keyboardProcPointer, mouseProcPointer


_service = None


def hookService():
    global _service
    if _service is None:
        _service = HookService()
    return _service
