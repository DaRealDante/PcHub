"""Event bus + automation registry. Plugins publish events and declare triggers/actions
that a future Automations plugin (and other plugins) can use."""
from PySide6.QtCore import QObject, Signal

from pchub.core.logger import getLogger

log = getLogger("events")


class AutomationTrigger:
    def __init__(self, triggerId, name, description=None, paramsSchema=None, icon="zap"):
        self.triggerId = triggerId
        self.name = name
        self.description = description
        self.paramsSchema = paramsSchema or []
        self.icon = icon
        self.pluginId = None


class AutomationAction:
    def __init__(self, actionId, name, run, description=None, paramsSchema=None, icon="play"):
        self.actionId = actionId
        self.name = name
        self.run = run
        self.description = description
        self.paramsSchema = paramsSchema or []
        self.icon = icon
        self.pluginId = None


class EventBus(QObject):
    eventFired = Signal(str, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.subscribers = {}
        self.triggers = {}
        self.actions = {}

    def emit(self, eventName, **payload):
        self.eventFired.emit(eventName, payload)
        for callback in list(self.subscribers.get(eventName, [])) + list(self.subscribers.get("*", [])):
            try:
                callback(eventName, payload)
            except Exception:
                log.exception("Event subscriber failed for %s", eventName)

    def subscribe(self, eventName, callback):
        self.subscribers.setdefault(eventName, []).append(callback)

    def unsubscribe(self, eventName, callback):
        listeners = self.subscribers.get(eventName, [])
        if callback in listeners:
            listeners.remove(callback)

    def registerPluginAutomation(self, pluginId, triggers, actions):
        self.unregisterPluginAutomation(pluginId)
        for trigger in triggers:
            trigger.pluginId = pluginId
            self.triggers[f"{pluginId}.{trigger.triggerId}"] = trigger
        for action in actions:
            action.pluginId = pluginId
            self.actions[f"{pluginId}.{action.actionId}"] = action

    def unregisterPluginAutomation(self, pluginId):
        for registry in (self.triggers, self.actions):
            for fullId in [key for key, item in registry.items() if item.pluginId == pluginId]:
                del registry[fullId]
