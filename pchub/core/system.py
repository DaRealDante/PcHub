"""OS integration: admin rights, autostart, dark title bar, foreground, sounds."""
import os
import subprocess
import tempfile

from pchub import APP_NAME
from pchub.core.logger import getLogger
from pchub.core.paths import isWindows, executableCommand

log = getLogger("system")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
TASK_NAME = "PC Hub"
_appMutex = None


def _noWindowFlags():
    return 0x08000000 if isWindows else 0


def isAdmin():
    if not isWindows:
        try:
            return os.geteuid() == 0
        except AttributeError:
            return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _quoteArgs(args):
    return subprocess.list2cmdline(args)


def relaunch(asAdmin=False, extraArgs=None):
    program, args = executableCommand(extraArgs)
    if isWindows:
        import ctypes
        verb = "runas" if asAdmin else "open"
        result = ctypes.windll.shell32.ShellExecuteW(None, verb, program, _quoteArgs(args), None, 1)
        return result > 32
    try:
        subprocess.Popen([program] + args, start_new_session=True)
        return True
    except OSError:
        return False


def startupCommandLine():
    program, args = executableCommand(["--tray"])
    return _quoteArgs([program] + args)


def _readRunKey():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as runKey:
            value, _ = winreg.QueryValueEx(runKey, APP_NAME)
            return value
    except OSError:
        return None


def _writeRunKey(enabled):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as runKey:
            if enabled:
                winreg.SetValueEx(runKey, APP_NAME, 0, winreg.REG_SZ, startupCommandLine())
            else:
                try:
                    winreg.DeleteValue(runKey, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError as error:
        log.error("Run key write failed: %s", error)
        return False


def _taskExists():
    try:
        completed = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME], capture_output=True,
                                   creationflags=_noWindowFlags())
        return completed.returncode == 0
    except OSError:
        return False


def _createElevatedTask():
    program, args = executableCommand(["--tray"])
    userId = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".strip("\\")
    escape = lambda text: (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))
    taskXml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>{escape(APP_NAME)} autostart</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{escape(userId)}</UserId><Delay>PT3S</Delay></LogonTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>{escape(userId)}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>5</Priority>
  </Settings>
  <Actions Context="Author"><Exec><Command>{escape(program)}</Command><Arguments>{escape(_quoteArgs(args))}</Arguments></Exec></Actions>
</Task>"""
    xmlPath = os.path.join(tempfile.gettempdir(), "pchub-task.xml")
    try:
        with open(xmlPath, "w", encoding="utf-16") as fileHandle:
            fileHandle.write(taskXml)
        completed = subprocess.run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", xmlPath, "/F"],
                                   capture_output=True, creationflags=_noWindowFlags())
        if completed.returncode != 0:
            log.error("schtasks create failed: %s", completed.stderr.decode(errors="ignore"))
        return completed.returncode == 0
    except OSError as error:
        log.error("schtasks create failed: %s", error)
        return False
    finally:
        try:
            os.remove(xmlPath)
        except OSError:
            pass


def _deleteTask():
    try:
        subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True,
                       creationflags=_noWindowFlags())
    except OSError:
        pass


def isStartupEnabled():
    if not isWindows:
        return False
    return bool(_readRunKey()) or _taskExists()


def setStartup(enabled, elevated):
    """elevated=True uses a Task Scheduler entry (no UAC prompt at boot); needs admin."""
    if not isWindows:
        return True
    if not enabled:
        _writeRunKey(False)
        if isAdmin():
            _deleteTask()
        return True
    if elevated and isAdmin():
        if _createElevatedTask():
            _writeRunKey(False)
            return True
    if isAdmin():
        _deleteTask()
    return _writeRunKey(True)


def createAppMutex():
    global _appMutex
    if isWindows and _appMutex is None:
        try:
            import ctypes
            _appMutex = ctypes.windll.kernel32.CreateMutexW(None, False, "PCHubAppMutex")
        except Exception:
            pass


def applyWindowFrame(widget, captionHex, textHex="#EDEFF7"):
    """Dark title bar colored like the app (Windows 10 20H1+ / 11)."""
    if not isWindows:
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        darkFlag = ctypes.c_int(1)
        for attribute in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(darkFlag), 4) == 0:
                break

        def colorRef(hexColor):
            hexColor = hexColor.lstrip("#")
            red, green, blue = int(hexColor[0:2], 16), int(hexColor[2:4], 16), int(hexColor[4:6], 16)
            return ctypes.c_int(red | (green << 8) | (blue << 16))

        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(colorRef(captionHex)), 4)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(colorRef(captionHex)), 4)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(colorRef(textHex)), 4)
        cornerPreference = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(cornerPreference), 4)
    except Exception:
        log.debug("DWM frame styling unavailable")


def forceForeground(widget):
    if not isWindows:
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        user32 = ctypes.windll.user32
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def playSound(kind="notify"):
    if not isWindows:
        return
    try:
        import winsound
        alias = {"notify": "SystemAsterisk", "alarm": "SystemExclamation", "done": "SystemAsterisk"}.get(kind, "SystemAsterisk")
        winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
    except Exception:
        pass
