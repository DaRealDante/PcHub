import time

from PySide6.QtCore import QObject, Signal


class ActiveItem:
    """Something 'running' a plugin wants to show in Home > Active (timer, cleanup, alert…)."""

    def __init__(self, itemId, title, subtitle="", icon=None, progress=None, actions=None, accent=None):
        self.itemId = itemId
        self.title = title
        self.subtitle = subtitle
        self.icon = icon
        self.progress = progress
        self.actions = list(actions or [])
        self.accent = accent
        self.pluginId = None
        self.startedAt = time.time()


class ActiveRegistry(QObject):
    changed = Signal()

    def __init__(self, visibilityChecker=None, parent=None):
        super().__init__(parent)
        self.itemsById = {}
        self.visibilityChecker = visibilityChecker or (lambda pluginId: True)

    def setItem(self, pluginId, item):
        item.pluginId = pluginId
        fullId = f"{pluginId}:{item.itemId}"
        existingItem = self.itemsById.get(fullId)
        if existingItem:
            item.startedAt = existingItem.startedAt
        self.itemsById[fullId] = item
        self.changed.emit()

    def removeItem(self, pluginId, itemId):
        if self.itemsById.pop(f"{pluginId}:{itemId}", None) is not None:
            self.changed.emit()

    def clearPlugin(self, pluginId):
        removedIds = [fullId for fullId, item in self.itemsById.items() if item.pluginId == pluginId]
        for fullId in removedIds:
            del self.itemsById[fullId]
        if removedIds:
            self.changed.emit()

    def items(self, includeHidden=False):
        visibleItems = [item for item in self.itemsById.values()
                        if includeHidden or self.visibilityChecker(item.pluginId)]
        return sorted(visibleItems, key=lambda item: item.startedAt)

    def count(self):
        return len(self.items())
