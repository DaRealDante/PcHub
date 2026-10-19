import copy
import json
import os
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from pchub.core.logger import getLogger

log = getLogger("storage")
_allStores = []


def _splitKey(key):
    return [part for part in key.split(".") if part]


class JsonStore(QObject):
    changed = Signal(str, object)

    def __init__(self, filePath, defaults=None, saveDelayMs=400, parent=None):
        super().__init__(parent)
        self.filePath = Path(filePath)
        self.defaults = copy.deepcopy(defaults or {})
        self.data = {}
        self.saveTimer = QTimer(self)
        self.saveTimer.setSingleShot(True)
        self.saveTimer.setInterval(saveDelayMs)
        self.saveTimer.timeout.connect(self.save)
        self.load()
        _allStores.append(self)

    def load(self):
        self.data = {}
        if self.filePath.exists():
            try:
                with open(self.filePath, "r", encoding="utf-8") as fileHandle:
                    loadedData = json.load(fileHandle)
                if isinstance(loadedData, dict):
                    self.data = loadedData
            except (OSError, ValueError) as error:
                log.warning("Corrupt store %s (%s), backing up", self.filePath, error)
                try:
                    self.filePath.replace(self.filePath.with_suffix(".corrupt.json"))
                except OSError:
                    pass

    def get(self, key, default=None):
        parts = _splitKey(key)
        for source in (self.data, self.defaults):
            node = source
            found = True
            for part in parts:
                if isinstance(node, dict) and part in node:
                    node = node[part]
                else:
                    found = False
                    break
            if found:
                return copy.deepcopy(node)
        return default

    def has(self, key):
        node = self.data
        for part in _splitKey(key):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return False
        return True

    def set(self, key, value):
        parts = _splitKey(key)
        node = self.data
        for part in parts[:-1]:
            if not isinstance(node.get(part), dict):
                node[part] = {}
            node = node[part]
        if node.get(parts[-1], object()) == value:
            return
        node[parts[-1]] = copy.deepcopy(value)
        self.scheduleSave()
        self.changed.emit(key, value)

    def remove(self, key):
        parts = _splitKey(key)
        node = self.data
        for part in parts[:-1]:
            node = node.get(part)
            if not isinstance(node, dict):
                return
        if parts[-1] in node:
            del node[parts[-1]]
            self.scheduleSave()
            self.changed.emit(key, None)

    def replaceAll(self, newData):
        self.data = copy.deepcopy(newData) if isinstance(newData, dict) else {}
        self.scheduleSave()
        self.changed.emit("", None)

    def scheduleSave(self):
        self.saveTimer.start()

    def save(self):
        self.saveTimer.stop()
        try:
            self.filePath.parent.mkdir(parents=True, exist_ok=True)
            tempPath = self.filePath.with_suffix(".tmp")
            with open(tempPath, "w", encoding="utf-8") as fileHandle:
                json.dump(self.data, fileHandle, indent=2, ensure_ascii=False)
            os.replace(tempPath, self.filePath)
        except OSError as error:
            log.error("Failed to save %s: %s", self.filePath, error)

    def flush(self):
        if self.saveTimer.isActive():
            self.save()


def flushAllStores():
    for store in list(_allStores):
        try:
            store.flush()
        except RuntimeError:
            pass
