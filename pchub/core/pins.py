"""Pinned items: settings/actions shown in the tray menu and in the Quick actions widget.

Refs:  "<pluginId>:<settingKey>"  a schema setting
       "<pluginId>:@enabled"      the plugin on/off switch
       "<pluginId>:#<entryId>"    a TrayEntry declared by the plugin
"""
from PySide6.QtCore import QObject, Signal

from pchub.core.i18n import tr
from pchub.core.settings_schema import Toggle, Slider, Choice, ActionButton, findSetting


class PinnedItem:
    def __init__(self, ref, pluginId, label, kind, getValue=None, setValue=None, run=None, options=None,
                 formatValue=None, icon=None):
        self.ref = ref
        self.pluginId = pluginId
        self.label = label
        self.kind = kind
        self.getValue = getValue
        self.setValue = setValue
        self.run = run
        self.options = options or []
        self.formatValue = formatValue or (lambda value: str(value))
        self.icon = icon


class PinService(QObject):
    changed = Signal()

    def __init__(self, appStore, pluginManager, actionInvoker, parent=None):
        super().__init__(parent)
        self.appStore = appStore
        self.pluginManager = pluginManager
        self.actionInvoker = actionInvoker
        pluginManager.pluginsChanged.connect(self.changed)

    def refs(self):
        return list(self.appStore.get("tray.pinned", []))

    def isPinned(self, ref):
        return ref in self.refs()

    def setPinned(self, ref, pinned):
        currentRefs = self.refs()
        if pinned and ref not in currentRefs:
            currentRefs.append(ref)
        elif not pinned and ref in currentRefs:
            currentRefs.remove(ref)
        else:
            return
        self.appStore.set("tray.pinned", currentRefs)
        self.changed.emit()

    def togglePin(self, ref):
        self.setPinned(ref, not self.isPinned(ref))

    def move(self, ref, offset):
        currentRefs = self.refs()
        if ref not in currentRefs:
            return
        index = currentRefs.index(ref)
        newIndex = max(0, min(len(currentRefs) - 1, index + offset))
        currentRefs.insert(newIndex, currentRefs.pop(index))
        self.appStore.set("tray.pinned", currentRefs)
        self.changed.emit()

    def resolve(self, ref):
        if ":" not in ref:
            return None
        pluginId, key = ref.split(":", 1)
        manager = self.pluginManager
        record = manager.records.get(pluginId)
        if not record or not record.installed or record.pluginClass is None:
            return None
        if key == "@enabled":
            return PinnedItem(ref, pluginId, manager.displayName(pluginId), "toggle",
                              getValue=lambda: bool(manager.globalSetting(pluginId, "enabled")),
                              setValue=lambda value: manager.setEnabled(pluginId, value),
                              icon=manager.displayIcon(pluginId))
        if key.startswith("#"):
            entry = next((item for item in record.trayEntries if item.entryId == key[1:]), None)
            if not entry:
                return None
            if entry.kind == "toggle":
                return PinnedItem(ref, pluginId, tr(entry.label), "toggle",
                                  getValue=lambda: bool(entry.checkedGetter() if entry.checkedGetter else False),
                                  setValue=lambda value: entry.callback(value), icon=entry.icon)
            return PinnedItem(ref, pluginId, tr(entry.label), "action", run=entry.callback, icon=entry.icon)
        setting = findSetting(record.schema, key)
        if setting is None:
            return None
        label = tr(setting.label)
        getValue = lambda: manager.getSetting(pluginId, key)
        setValue = lambda value: manager.setSetting(pluginId, key, value)
        if isinstance(setting, Toggle):
            return PinnedItem(ref, pluginId, label, "toggle", getValue=lambda: bool(getValue()), setValue=setValue,
                              icon=setting.icon)
        if isinstance(setting, Slider):
            return PinnedItem(ref, pluginId, label, "slider", getValue=getValue, setValue=setValue,
                              options=[(value, setting.formatValue(value)) for value in setting.trayValues()],
                              formatValue=setting.formatValue, icon=setting.icon)
        if isinstance(setting, Choice):
            return PinnedItem(ref, pluginId, label, "choice", getValue=getValue, setValue=setValue,
                              options=[(value, tr(optionLabel)) for value, optionLabel in setting.options],
                              icon=setting.icon)
        if isinstance(setting, ActionButton):
            return PinnedItem(ref, pluginId, label, "action",
                              run=lambda: self.actionInvoker(pluginId, setting), icon=setting.icon)
        return None

    def items(self):
        resolved = []
        for ref in self.refs():
            item = self.resolve(ref)
            if item:
                resolved.append(item)
        return resolved
