import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler

from pchub.core.paths import logsDir, isFrozen

_configured = False


def setupLogging():
    global _configured
    if _configured:
        return
    _configured = True
    rootLogger = logging.getLogger("pchub")
    rootLogger.setLevel(logging.DEBUG)
    logFormat = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    try:
        fileHandler = RotatingFileHandler(logsDir() / "pchub.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        fileHandler.setFormatter(logFormat)
        fileHandler.setLevel(logging.INFO)
        rootLogger.addHandler(fileHandler)
    except OSError:
        pass
    if not isFrozen() and sys.stderr:
        streamHandler = logging.StreamHandler(sys.stderr)
        streamHandler.setFormatter(logFormat)
        streamHandler.setLevel(logging.INFO)
        rootLogger.addHandler(streamHandler)

    def handleUncaught(excType, excValue, excTraceback):
        if issubclass(excType, KeyboardInterrupt):
            sys.__excepthook__(excType, excValue, excTraceback)
            return
        rootLogger.error("Uncaught exception:\n%s", "".join(traceback.format_exception(excType, excValue, excTraceback)))

    sys.excepthook = handleUncaught


def getLogger(name: str) -> logging.Logger:
    return logging.getLogger(f"pchub.{name}")
