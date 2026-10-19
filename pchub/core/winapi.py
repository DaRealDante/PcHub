"""Thin ctypes wrappers around the Windows APIs plugins need. Every function is safe to call on other
platforms (returns a neutral value), so plugins and tests run everywhere."""
import ctypes
import os
import time

from pchub.core.paths import isWindows

if isWindows:
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    class RECT(ctypes.Structure):
        _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]

    class XINPUT_GAMEPAD(ctypes.Structure):
        _fields_ = [("wButtons", wintypes.WORD), ("bLeftTrigger", ctypes.c_ubyte), ("bRightTrigger", ctypes.c_ubyte),
                    ("sThumbLX", ctypes.c_short), ("sThumbLY", ctypes.c_short), ("sThumbRX", ctypes.c_short),
                    ("sThumbRY", ctypes.c_short)]

    class XINPUT_STATE(ctypes.Structure):
        _fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", XINPUT_GAMEPAD)]

    user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, wintypes.UINT]
    kernel32.GetTickCount.restype = wintypes.DWORD

    _xinputGetState = None
    for _dllName in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
        try:
            _xinputDll = ctypes.WinDLL(_dllName)
            _xinputGetState = _xinputDll.XInputGetState
            _xinputGetState.argtypes = [wintypes.DWORD, ctypes.POINTER(XINPUT_STATE)]
            _xinputGetState.restype = wintypes.DWORD
            break
        except OSError:
            continue

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOPMOST = 0x00000008
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}


def idleSeconds():
    """Seconds since the last keyboard/mouse input in this session (any source)."""
    if not isWindows:
        return 0.0
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    elapsedMs = (kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
    return elapsedMs / 1000.0


class ControllerWatcher:
    """Detects XInput controller activity by watching each pad's packet number."""

    def __init__(self):
        self.lastPackets = {}
        self.lastActivity = 0.0
        self.nextScanAt = 0.0

    def poll(self):
        """Connected pads are polled every call; empty slots only every 3 s (querying a disconnected pad is slow)."""
        if not isWindows or _xinputGetState is None:
            return self.lastActivity
        state = XINPUT_STATE()
        now = time.monotonic()
        scanEmpty = now >= self.nextScanAt
        if scanEmpty:
            self.nextScanAt = now + 3.0
        for padIndex in range(4):
            if padIndex not in self.lastPackets and not scanEmpty:
                continue
            if _xinputGetState(padIndex, ctypes.byref(state)) != 0:
                self.lastPackets.pop(padIndex, None)
                continue
            packetNumber = state.dwPacketNumber
            previous = self.lastPackets.get(padIndex)
            if previous is not None and previous != packetNumber:
                gamepad = state.Gamepad
                if (gamepad.wButtons or gamepad.bLeftTrigger > 30 or gamepad.bRightTrigger > 30
                        or max(abs(gamepad.sThumbLX), abs(gamepad.sThumbLY), abs(gamepad.sThumbRX), abs(gamepad.sThumbRY)) > 8000):
                    self.lastActivity = time.monotonic()
            self.lastPackets[padIndex] = packetNumber
        return self.lastActivity


def foregroundWindow():
    return user32.GetForegroundWindow() if isWindows else None


def windowClassName(hwnd):
    if not isWindows or not hwnd:
        return ""
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def windowTitle(hwnd):
    if not isWindows or not hwnd:
        return ""
    buffer = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buffer, 512)
    return buffer.value


def windowProcessId(hwnd):
    if not isWindows or not hwnd:
        return None
    processId = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(processId))
    return processId.value or None


_processNameCache = {}


def processName(processId):
    if not processId:
        return ""
    cached = _processNameCache.get(processId)
    if cached and time.monotonic() - cached[1] < 30:
        return cached[0]
    try:
        import psutil
        name = psutil.Process(processId).name()
    except Exception:
        name = ""
    if len(_processNameCache) > 300:
        _processNameCache.clear()
    _processNameCache[processId] = (name, time.monotonic())
    return name


def foregroundProcessName():
    """Lowercase exe name of the active window, e.g. 'robloxstudiobeta.exe' ('' when unknown)."""
    hwnd = foregroundWindow()
    return processName(windowProcessId(hwnd)).lower()


def isForegroundFullscreen():
    if not isWindows:
        return False
    hwnd = foregroundWindow()
    if not hwnd or windowClassName(hwnd) in SHELL_CLASSES:
        return False
    windowRect = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(windowRect)):
        return False
    monitorInfo = MONITORINFO()
    monitorInfo.cbSize = ctypes.sizeof(MONITORINFO)
    monitor = user32.MonitorFromWindow(hwnd, 2)
    if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(monitorInfo)):
        return False
    screen = monitorInfo.rcMonitor
    return (windowRect.left <= screen.left and windowRect.top <= screen.top
            and windowRect.right >= screen.right and windowRect.bottom >= screen.bottom)


def isSessionLocked():
    """True on the lock screen / secure desktop (UAC prompt, Ctrl+Alt+Del)."""
    if not isWindows:
        return False
    desktop = user32.OpenInputDesktop(0, False, 0x0100)
    if not desktop:
        return True
    user32.CloseDesktop(desktop)
    return False


def setClickThrough(widget, enabled):
    """Lets mouse clicks pass through a window (Windows); other platforms use the Qt flag fallback."""
    if not isWindows:
        return
    hwnd = int(widget.winId())
    style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    newStyle = style | WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    newStyle = (newStyle | WS_EX_TRANSPARENT) if enabled else (newStyle & ~WS_EX_TRANSPARENT)
    if newStyle != style:
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, newStyle)


def keepTopmost(widget):
    if not isWindows:
        return
    user32.SetWindowPos(int(widget.winId()), HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


def openPath(target, arguments="", workingDirectory=None, verb="open"):
    """Opens a program, file, folder or URL like double-clicking it. Returns True on success."""
    if isWindows:
        result = ctypes.windll.shell32.ShellExecuteW(None, verb, str(target), arguments or None,
                                                     workingDirectory or None, 1)
        return result > 32
    import subprocess
    try:
        subprocess.Popen(["xdg-open", str(target)], start_new_session=True)
        return True
    except OSError:
        return False


def runningProcessNames():
    try:
        import psutil
        return {(process.info["name"] or "").lower() for process in psutil.process_iter(["name"])}
    except Exception:
        return set()


def userEnvironmentPath(path):
    return os.path.normpath(os.path.expandvars(os.path.expanduser(path)))
