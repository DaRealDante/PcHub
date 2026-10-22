"""Leaves a trace when PC Hub dies without a Python exception (a native crash in Qt, OpenCV, a plugin's DLL...).

- faulthandler writes the stack of every thread to logs/crash.log the moment the process crashes;
- a small heartbeat file (session.json) says when PC Hub was last alive and how much memory it used;
- on the next start, a session that never reached "Shutting down" is reported, with the plugin whose code was
  running in the crashed thread when one can be found.
"""
import faulthandler
import json
import os
import re
import threading
import time

from pchub.core.logger import getLogger
from pchub.core.paths import dataDir, logsDir

log = getLogger("crash")

SESSION_FILE = "session.json"
CRASH_LOG = "crash.log"
LAST_CRASH_LOG = "crash-last.log"
HEARTBEAT_SECONDS = 60
MEMORY_LOG_SECONDS = 1800
MEMORY_WARNING_MB = 1500
CRASH_LOG_LIMIT = 4_000_000
FATAL_PATTERN = re.compile(r"^(Windows fatal exception: .*|Fatal Python error: .*)$", re.MULTILINE)
FILE_PATTERN = re.compile(r'File "([^"]+)", line (\d+) in (\S+)')


def processMemoryMb():
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / 1048576)
    except Exception:
        return None


def bootTime():
    try:
        import psutil
        return psutil.boot_time()
    except Exception:
        return None


def parseDump(text):
    """The last fatal error in a faulthandler file: {"error", "frames" (crashed thread, innermost first), "text"}."""
    matches = list(FATAL_PATTERN.finditer(text or ""))
    if not matches:
        return None
    last = matches[-1]
    block = text[last.start():]
    error = last.group(1).split(":", 1)[1].strip()
    currentStart = block.find("Current thread")
    threadBlock = block[currentStart:] if currentStart >= 0 else block
    nextThread = re.search(r"\n\s*\n(Thread|Current thread) 0x", threadBlock[1:])
    if nextThread:
        threadBlock = threadBlock[:nextThread.start() + 1]
    frames = [(fileName, int(line), function) for fileName, line, function in FILE_PATTERN.findall(threadBlock)]
    return {"error": error, "frames": frames, "text": block.strip()[:20000]}


def readDump(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return parseDump(handle.read())
    except OSError:
        return None


class CrashGuard:
    def __init__(self, version):
        self.version = version
        self.sessionPath = dataDir() / SESSION_FILE
        self.crashPath = logsDir() / CRASH_LOG
        self.lastCrashPath = logsDir() / LAST_CRASH_LOG
        self.crashFile = None
        self.startedAt = time.time()
        self.lastMemoryLogAt = 0.0
        self.memoryWarned = False
        self.previous = None
        self.threadErrorHandler = None
        self.previousThreadHook = threading.excepthook
        self.seenQtMessages = set()

    # start / stop --------------------------------------------------------
    def begin(self):
        """Call once per real (primary) process. Returns the previous unexpected end, or None."""
        self.previous = self._previousSession()
        if self.previous is not None:
            self.previous["dump"] = None
            try:
                if self.crashPath.exists() and self.crashPath.stat().st_size:
                    os.replace(self.crashPath, self.lastCrashPath)
                    self.previous["dump"] = readDump(self.lastCrashPath)
            except OSError:
                pass
            self._logPrevious()
        self._openCrashFile()
        self.heartbeat()
        self.previousThreadHook = threading.excepthook
        threading.excepthook = self._threadException
        self._installQtMessageHandler()
        return self.previous

    def end(self):
        """Clean exit: the session is over and not a crash."""
        self._writeSession(clean=True)
        if threading.excepthook == self._threadException:
            threading.excepthook = self.previousThreadHook

    def _openCrashFile(self):
        try:
            if self.crashFile is not None:
                faulthandler.disable()
                self.crashFile.close()
            self.crashFile = open(self.crashPath, "w", encoding="utf-8")
            self.crashFile.write(f"PC Hub {self.version} · started {time.strftime('%Y-%m-%d %H:%M:%S')} · "
                                 f"pid {os.getpid()}\n")
            self.crashFile.flush()
            faulthandler.enable(self.crashFile, all_threads=True)
        except (OSError, RuntimeError, ValueError) as error:
            log.warning("Crash log not available: %s", error)

    # heartbeat -------------------------------------------------------------
    def heartbeat(self):
        memory = processMemoryMb()
        self._writeSession(clean=False, memory=memory)
        now = time.time()
        if memory is not None and now - self.lastMemoryLogAt >= MEMORY_LOG_SECONDS:
            self.lastMemoryLogAt = now
            log.info("Alive · memory %s MB · threads %s", memory, threading.active_count())
        if memory is not None and memory >= MEMORY_WARNING_MB and not self.memoryWarned:
            self.memoryWarned = True
            log.warning("PC Hub is using %s MB of memory", memory)
        try:
            if self.crashFile is not None and self.crashPath.stat().st_size > CRASH_LOG_LIMIT:
                self._openCrashFile()
        except OSError:
            pass

    def _writeSession(self, clean, memory=None):
        data = {"pid": os.getpid(), "version": self.version, "startedAt": self.startedAt,
                "aliveAt": time.time(), "memoryMb": memory, "clean": clean}
        try:
            temporary = self.sessionPath.with_suffix(".tmp")
            temporary.write_text(json.dumps(data), encoding="utf-8")
            os.replace(temporary, self.sessionPath)
        except OSError:
            pass

    def _previousSession(self):
        try:
            data = json.loads(self.sessionPath.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or data.get("clean", True):
            return None
        aliveAt = float(data.get("aliveAt") or 0)
        booted = bootTime()
        if booted is not None and booted > aliveAt:
            return None  # the PC was turned off or restarted while PC Hub was running: not a crash
        return data

    def _logPrevious(self):
        previous = self.previous
        aliveText = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(previous.get("aliveAt") or 0)))
        dump = previous.get("dump")
        log.error("The previous session (PC Hub %s) ended unexpectedly · last alive %s · memory %s MB%s",
                  previous.get("version"), aliveText, previous.get("memoryMb"),
                  f"\n{dump['text']}" if dump else " · no crash dump")

    # other error sources ---------------------------------------------------
    def _threadException(self, arguments):
        if arguments.exc_type is SystemExit:
            return
        import traceback
        details = "".join(traceback.format_exception(arguments.exc_type, arguments.exc_value, arguments.exc_traceback))
        threadName = arguments.thread.name if arguments.thread is not None else "?"
        log.error("Uncaught exception in thread %s:\n%s", threadName, details)
        if self.threadErrorHandler is not None:
            try:
                self.threadErrorHandler(arguments.exc_value, arguments.exc_traceback, details)
            except Exception:
                pass

    def _installQtMessageHandler(self):
        try:
            from PySide6.QtCore import QtMsgType, qInstallMessageHandler
        except ImportError:
            return
        guard = self

        def handler(messageType, context, message):
            if messageType in (QtMsgType.QtDebugMsg, QtMsgType.QtInfoMsg):
                return
            if messageType == QtMsgType.QtWarningMsg:
                if message in guard.seenQtMessages or len(guard.seenQtMessages) > 300:
                    return
                guard.seenQtMessages.add(message)
                log.warning("Qt: %s", message)
                return
            log.error("Qt %s: %s", "fatal" if messageType == QtMsgType.QtFatalMsg else "critical", message)
            if guard.crashFile is not None:
                try:
                    guard.crashFile.write(f"Qt: {message}\n")
                    guard.crashFile.flush()
                except (OSError, ValueError):
                    pass

        self.qtHandler = handler
        qInstallMessageHandler(handler)
