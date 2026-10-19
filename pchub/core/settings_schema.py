"""Declarative settings. The core builds the UI, tray pins and hotkeys from these."""


class Setting:
    kind = "base"
    defaultPinnable = False

    def __init__(self, key, label, default=None, description=None, pinnable=None, visibleIf=None,
                 requiresRestart=False, confirmOn=None, confirmTitle=None, confirmMessage=None, confirmDetails=None,
                 icon=None):
        self.key = key
        self.label = label
        self.default = default
        self.description = description
        self.pinnable = self.defaultPinnable if pinnable is None else pinnable
        self.visibleIf = visibleIf
        self.requiresRestart = requiresRestart
        self.confirmOn = confirmOn
        self.confirmTitle = confirmTitle
        self.confirmMessage = confirmMessage
        self.confirmDetails = confirmDetails or []
        self.icon = icon

    def isVisible(self, valueGetter):
        if self.visibleIf is None:
            return True
        if callable(self.visibleIf):
            return bool(self.visibleIf(valueGetter))
        dependencyKey, expectedValue = self.visibleIf
        currentValue = valueGetter(dependencyKey)
        if isinstance(expectedValue, (list, tuple, set)):
            return currentValue in expectedValue
        return currentValue == expectedValue

    def hasValue(self):
        return True


class Section(Setting):
    kind = "section"
    _counter = 0

    def __init__(self, label, description=None, visibleIf=None, icon=None):
        Section._counter += 1
        super().__init__(f"__section{Section._counter}", label, description=description, visibleIf=visibleIf, icon=icon)

    def hasValue(self):
        return False


class Toggle(Setting):
    kind = "toggle"
    defaultPinnable = True

    def __init__(self, key, label, default=False, **kwargs):
        super().__init__(key, label, default=default, **kwargs)


class Slider(Setting):
    kind = "slider"
    defaultPinnable = True

    def __init__(self, key, label, minimum=0, maximum=100, default=50, step=1, suffix="", traySteps=None,
                 formatter=None, **kwargs):
        super().__init__(key, label, default=default, **kwargs)
        self.minimum = minimum
        self.maximum = maximum
        self.step = step
        self.suffix = suffix
        self.formatter = formatter
        self.traySteps = traySteps

    def formatValue(self, value):
        if self.formatter:
            return self.formatter(value)
        from pchub.core.i18n import tr
        return f"{value}{tr(self.suffix) if self.suffix else ''}"

    def trayValues(self):
        if self.traySteps:
            return list(self.traySteps)
        spanValue = self.maximum - self.minimum
        values = [self.minimum + round(spanValue * fraction / self.step) * self.step for fraction in (0, 0.25, 0.5, 0.75, 1)]
        return sorted(set(values))


class Choice(Setting):
    kind = "choice"
    defaultPinnable = True

    def __init__(self, key, label, options, default=None, **kwargs):
        super().__init__(key, label, default=default if default is not None else options[0][0], **kwargs)
        self.options = list(options)


class TextInput(Setting):
    kind = "text"

    def __init__(self, key, label, default="", placeholder=None, **kwargs):
        super().__init__(key, label, default=default, **kwargs)
        self.placeholder = placeholder


class NumberInput(Setting):
    kind = "number"

    def __init__(self, key, label, minimum=0, maximum=9999, default=0, suffix="", decimals=0, step=None, **kwargs):
        super().__init__(key, label, default=default, **kwargs)
        self.minimum = minimum
        self.maximum = maximum
        self.suffix = suffix
        self.decimals = decimals
        self.step = step


class HotkeySetting(Setting):
    """When the hotkey fires, the core calls plugin.<action>()."""
    kind = "hotkey"

    def __init__(self, key, label, action, default="", **kwargs):
        super().__init__(key, label, default=default, **kwargs)
        self.action = action


class FolderSetting(Setting):
    kind = "folder"

    def __init__(self, key, label, default="", **kwargs):
        super().__init__(key, label, default=default, **kwargs)


class ActionButton(Setting):
    """A button that calls plugin.<action>(). Pinnable as a tray action."""
    kind = "button"
    defaultPinnable = True

    def __init__(self, key, label, action, buttonText=None, danger=False, **kwargs):
        super().__init__(key, label, default=None, **kwargs)
        self.action = action
        self.buttonText = buttonText
        self.danger = danger

    def hasValue(self):
        return False


class InfoRow(Setting):
    kind = "info"

    def __init__(self, key, label, valueGetter, **kwargs):
        super().__init__(key, label, **kwargs)
        self.valueGetter = valueGetter

    def hasValue(self):
        return False


class CustomRow(Setting):
    """A row whose control is built by a factory(parentWidget) -> QWidget."""
    kind = "custom"

    def __init__(self, key, label, factory, **kwargs):
        super().__init__(key, label, **kwargs)
        self.factory = factory

    def hasValue(self):
        return False


def schemaDefaults(schema):
    return {setting.key: setting.default for setting in schema if setting.hasValue()}


def findSetting(schema, key):
    for setting in schema:
        if setting.key == key:
            return setting
    return None
