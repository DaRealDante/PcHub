from pchub.core.i18n import tr
from pchub.ui.settings_form import FormAdapter

PINNABLE_KINDS = ("toggle", "slider", "choice", "button")


def hotkeyErrorText(result, hotkeyManager):
    if result is None or result.ok:
        return None
    if result.reason == "invalid":
        return tr("hotkey.invalid")
    if result.reason == "conflictInternal":
        return tr("hotkey.conflictInternal", owner=hotkeyManager.ownerLabel(result.conflictOwner))
    return tr("hotkey.conflictSystem")


class PluginSettingsAdapter(FormAdapter):
    def __init__(self, app, pluginId):
        super().__init__()
        self.app = app
        self.pluginId = pluginId
        app.pluginManager.settingChanged.connect(self._onSettingChanged)
        app.pluginManager.hotkeyStatusChanged.connect(self._onHotkeyStatus)
        app.pinService.changed.connect(self.pinsChanged)

    def _onSettingChanged(self, pluginId, key, value):
        if pluginId == self.pluginId:
            self.valueChanged.emit(key, value)

    def _onHotkeyStatus(self, owner):
        prefix = f"plugin:{self.pluginId}:"
        if owner.startswith(prefix):
            self.hotkeyStatusChanged.emit(owner[len(prefix):])

    def get(self, key):
        return self.app.pluginManager.getSetting(self.pluginId, key)

    def set(self, key, value):
        self.app.pluginManager.setSetting(self.pluginId, key, value)

    def pinRef(self, setting):
        return f"{self.pluginId}:{setting.key}" if setting.kind in PINNABLE_KINDS else None

    def isPinned(self, ref):
        return self.app.pinService.isPinned(ref)

    def togglePin(self, ref):
        self.app.pinService.togglePin(ref)

    def hotkeyError(self, key):
        result = self.app.pluginManager.hotkeyStatus.get(f"plugin:{self.pluginId}:{key}")
        return hotkeyErrorText(result, self.app.hotkeys)

    def invokeAction(self, setting):
        self.app.invokePluginAction(self.pluginId, setting)

    def confirm(self, title, message, details, danger):
        return self.app.confirm(title, message, details, danger)


class PluginGlobalAdapter(FormAdapter):
    def __init__(self, app, pluginId):
        super().__init__()
        self.app = app
        self.pluginId = pluginId
        app.pluginManager.globalSettingChanged.connect(self._onGlobalChanged)
        app.pluginManager.hotkeyStatusChanged.connect(self._onHotkeyStatus)
        app.pinService.changed.connect(self.pinsChanged)

    def _onGlobalChanged(self, pluginId, key, value):
        if pluginId == self.pluginId:
            self.valueChanged.emit(key, value)

    def _onHotkeyStatus(self, owner):
        if owner == f"open:{self.pluginId}":
            self.hotkeyStatusChanged.emit("openHotkey")

    def get(self, key):
        return self.app.pluginManager.globalSetting(self.pluginId, key)

    def set(self, key, value):
        self.app.pluginManager.setGlobalSetting(self.pluginId, key, value)

    def pinRef(self, setting):
        return f"{self.pluginId}:@enabled" if setting.key == "enabled" else None

    def isPinned(self, ref):
        return self.app.pinService.isPinned(ref)

    def togglePin(self, ref):
        self.app.pinService.togglePin(ref)

    def hotkeyError(self, key):
        if key != "openHotkey":
            return None
        return hotkeyErrorText(self.app.pluginManager.hotkeyStatus.get(f"open:{self.pluginId}"), self.app.hotkeys)

    def invokeAction(self, setting):
        if setting.key == "changeIcon":
            self.app.changePluginIcon(self.pluginId)
        elif setting.key == "uninstall":
            self.app.requestUninstall(self.pluginId)

    def confirm(self, title, message, details, danger):
        return self.app.confirm(title, message, details, danger)


class AppSettingsAdapter(FormAdapter):
    def __init__(self, app):
        super().__init__()
        self.app = app
        app.appStore.changed.connect(self._onStoreChanged)
        app.appHotkeyStatusChanged.connect(self._onAppHotkeyStatus)

    def _onAppHotkeyStatus(self):
        self.hotkeyStatusChanged.emit("general.openHotkey")

    def _onStoreChanged(self, key, value):
        self.valueChanged.emit(key, value)

    def get(self, key):
        return self.app.appSetting(key)

    def set(self, key, value):
        accepted = self.app.setAppSetting(key, value)
        if accepted is False:
            self.valueChanged.emit(key, self.get(key))

    def hotkeyError(self, key):
        if key == "general.openHotkey":
            return hotkeyErrorText(self.app.appHotkeyResult, self.app.hotkeys)
        return None

    def invokeAction(self, setting):
        self.app.invokeAppAction(setting.key)

    def confirm(self, title, message, details, danger):
        return self.app.confirm(title, message, details, danger)
