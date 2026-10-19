"""Builds settings UI automatically from a schema (pchub.core.settings_schema)."""
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLineEdit, QSlider, QSpinBox, QVBoxLayout,
                               QWidget, QSizePolicy)

from pchub.core.i18n import tr
from pchub.core.logger import getLogger
from pchub.core.settings_schema import Section
from pchub.ui.widgets import (Card, HotkeyEdit, IconWidget, ToggleSwitch, divider, iconButton, makeButton, makeLabel,
                              setRole)


class FormAdapter(QObject):
    """Bridges a SettingsForm to wherever values live."""
    valueChanged = Signal(str, object)
    hotkeyStatusChanged = Signal(str)
    pinsChanged = Signal()

    def get(self, key):
        raise NotImplementedError

    def set(self, key, value):
        raise NotImplementedError

    def pinRef(self, setting):
        return None

    def isPinned(self, ref):
        return False

    def togglePin(self, ref):
        pass

    def hotkeyError(self, key):
        return None

    def invokeAction(self, setting):
        pass

    def confirm(self, title, message, details, danger):
        return True


class SettingRow(QWidget):
    def __init__(self, setting, form):
        super().__init__()
        self.setting = setting
        self.form = form
        self.adapter = form.adapter
        self.control = None
        self.errorLabel = None
        self.valueLabel = None
        self.pinButton = None
        self.sliderCommitTimer = None
        outerLayout = QVBoxLayout(self)
        outerLayout.setContentsMargins(0, 0, 0, 0)
        outerLayout.setSpacing(0)
        self.divider = divider()
        outerLayout.addWidget(self.divider)
        contentLayout = QHBoxLayout()
        contentLayout.setContentsMargins(4, 12, 4, 12)
        contentLayout.setSpacing(14)
        outerLayout.addLayout(contentLayout)
        if setting.icon:
            contentLayout.addWidget(IconWidget(setting.icon, "muted", 18), 0, Qt.AlignVCenter)
        textLayout = QVBoxLayout()
        textLayout.setSpacing(3)
        self.titleLabel = makeLabel(tr(setting.label), None, True)
        textLayout.addWidget(self.titleLabel)
        if setting.description:
            textLayout.addWidget(makeLabel(tr(setting.description), "faint", True))
        if setting.kind == "hotkey":
            self.errorLabel = makeLabel("", "error", True)
            self.errorLabel.hide()
            textLayout.addWidget(self.errorLabel)
        contentLayout.addLayout(textLayout, 1)
        controlWidget = self._buildControl()
        if controlWidget is not None:
            contentLayout.addWidget(controlWidget, 0 if setting.kind not in ("slider",) else 1, Qt.AlignVCenter)
        pinRef = self.adapter.pinRef(setting) if setting.pinnable else None
        if pinRef:
            self.pinRef = pinRef
            self.pinButton = iconButton("pin", tr("pin.pin"), "faint", 16, checkable=True)
            self.pinButton.clicked.connect(self._togglePin)
            contentLayout.addWidget(self.pinButton, 0, Qt.AlignVCenter)
            self.refreshPin()
        self.refreshHotkeyError()

    def _buildControl(self):
        setting = self.setting
        kind = setting.kind
        value = self.adapter.get(setting.key) if setting.hasValue() else None
        if kind == "toggle":
            self.control = ToggleSwitch(bool(value))
            self.control.toggled.connect(self._onToggle)
            return self.control
        if kind == "slider":
            host = QWidget()
            hostLayout = QHBoxLayout(host)
            hostLayout.setContentsMargins(0, 0, 0, 0)
            hostLayout.setSpacing(10)
            self.control = QSlider(Qt.Horizontal)
            self.control.setRange(int(setting.minimum / setting.step), int(setting.maximum / setting.step))
            self.control.setValue(int(round((value if value is not None else setting.default) / setting.step)))
            self.control.setMinimumWidth(160)
            self.control.setCursor(Qt.PointingHandCursor)
            self.valueLabel = makeLabel(setting.formatValue(self._sliderValue()), "accent")
            self.valueLabel.setMinimumWidth(64)
            self.valueLabel.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.sliderCommitTimer = QTimer(self)
            self.sliderCommitTimer.setSingleShot(True)
            self.sliderCommitTimer.setInterval(160)
            self.sliderCommitTimer.timeout.connect(self._commitSlider)
            self.control.valueChanged.connect(self._onSliderMoved)
            self.control.sliderReleased.connect(self._commitSlider)
            hostLayout.addWidget(self.control, 1)
            hostLayout.addWidget(self.valueLabel)
            host.setMinimumWidth(260)
            host.setMaximumWidth(420)
            host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            return host
        if kind == "choice":
            self.control = QComboBox()
            self.control.setCursor(Qt.PointingHandCursor)
            for optionValue, optionLabel in setting.options:
                self.control.addItem(tr(optionLabel), optionValue)
            self._selectChoice(value)
            self.control.setMinimumWidth(200)
            self.control.currentIndexChanged.connect(self._onChoice)
            return self.control
        if kind == "text":
            self.control = QLineEdit(value or "")
            if setting.placeholder:
                self.control.setPlaceholderText(tr(setting.placeholder))
            self.control.setMinimumWidth(240)
            self.control.editingFinished.connect(lambda: self.adapter.set(setting.key, self.control.text()))
            return self.control
        if kind == "number":
            decimals = int(getattr(setting, "decimals", 0) or 0)
            if decimals:
                from PySide6.QtWidgets import QDoubleSpinBox
                self.control = QDoubleSpinBox()
                self.control.setDecimals(decimals)
                self.control.setRange(float(setting.minimum), float(setting.maximum))
                self.control.setSingleStep(float(getattr(setting, "step", None) or 10 ** -decimals))
                self.control.setValue(float(value or 0))
            else:
                self.control = QSpinBox()
                self.control.setRange(int(setting.minimum), int(setting.maximum))
                if getattr(setting, "step", None):
                    self.control.setSingleStep(int(setting.step))
                self.control.setValue(int(value or 0))
            if setting.suffix:
                self.control.setSuffix(tr(setting.suffix))
            self.control.setMinimumWidth(110)
            self.control.valueChanged.connect(lambda newValue: self.adapter.set(setting.key, newValue))
            return self.control
        if kind == "hotkey":
            self.control = HotkeyEdit(value or "")
            self.control.sequenceChanged.connect(lambda sequence: self.adapter.set(setting.key, sequence))
            return self.control
        if kind == "folder":
            host = QWidget()
            hostLayout = QHBoxLayout(host)
            hostLayout.setContentsMargins(0, 0, 0, 0)
            hostLayout.setSpacing(6)
            self.control = QLineEdit(value or "")
            self.control.setMinimumWidth(220)
            self.control.editingFinished.connect(lambda: self.adapter.set(setting.key, self.control.text()))
            browseButton = iconButton("folder-open", tr("common.open"), "text", 16)
            browseButton.clicked.connect(self._browseFolder)
            hostLayout.addWidget(self.control, 1)
            hostLayout.addWidget(browseButton)
            return host
        if kind == "button":
            self.control = makeButton(tr(setting.buttonText or setting.label), setting.icon if setting.buttonText else None,
                                      "danger" if setting.danger else None)
            self.control.clicked.connect(lambda: self.adapter.invokeAction(setting))
            return self.control
        if kind == "info":
            self.valueLabel = makeLabel(str(setting.valueGetter()), "muted")
            self.valueLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
            return self.valueLabel
        if kind == "custom":
            self.control = setting.factory(self)
            return self.control
        return None

    def _sliderValue(self):
        rawValue = self.control.value() * self.setting.step
        return int(rawValue) if float(self.setting.step).is_integer() else round(rawValue, 4)

    def _onSliderMoved(self, _rawValue):
        self.valueLabel.setText(self.setting.formatValue(self._sliderValue()))
        if not self.control.isSliderDown():
            self.sliderCommitTimer.start()

    def _commitSlider(self):
        self.sliderCommitTimer.stop()
        self.adapter.set(self.setting.key, self._sliderValue())

    def _selectChoice(self, value):
        index = self.control.findData(value)
        if index >= 0:
            self.control.blockSignals(True)
            self.control.setCurrentIndex(index)
            self.control.blockSignals(False)

    def _onChoice(self, index):
        self.adapter.set(self.setting.key, self.control.itemData(index))

    def _onToggle(self, checked):
        setting = self.setting
        if setting.confirmOn is not None and checked == setting.confirmOn:
            accepted = self.adapter.confirm(tr(setting.confirmTitle or setting.label),
                                            tr(setting.confirmMessage) if setting.confirmMessage else "",
                                            [tr(detail) for detail in setting.confirmDetails], False)
            if not accepted:
                self.control.setCheckedSilently(not checked)
                return
        self.adapter.set(setting.key, checked)

    def _browseFolder(self):
        folderPath = QFileDialog.getExistingDirectory(self, tr(self.setting.label), self.control.text())
        if folderPath:
            self.control.setText(folderPath)
            self.adapter.set(self.setting.key, folderPath)

    def _togglePin(self):
        self.adapter.togglePin(self.pinRef)
        self.refreshPin()

    def refreshPin(self):
        if self.pinButton:
            pinned = self.adapter.isPinned(self.pinRef)
            self.pinButton.setChecked(pinned)
            self.pinButton.setToolTip(tr("pin.unpin") if pinned else tr("pin.pin"))

    def refreshHotkeyError(self):
        if self.errorLabel is None:
            return
        errorText = self.adapter.hotkeyError(self.setting.key)
        self.errorLabel.setText(errorText or "")
        self.errorLabel.setVisible(bool(errorText))

    def updateValue(self, value):
        kind = self.setting.kind
        if self.control is None and kind != "info":
            return
        if kind == "toggle":
            self.control.setCheckedSilently(bool(value))
        elif kind == "slider":
            self.control.blockSignals(True)
            self.control.setValue(int(round((value or 0) / self.setting.step)))
            self.control.blockSignals(False)
            self.valueLabel.setText(self.setting.formatValue(self._sliderValue()))
        elif kind == "choice":
            self._selectChoice(value)
        elif kind in ("text", "folder"):
            if self.control.text() != (value or ""):
                self.control.setText(value or "")
        elif kind == "number":
            self.control.blockSignals(True)
            self.control.setValue(float(value or 0) if getattr(self.setting, "decimals", 0) else int(value or 0))
            self.control.blockSignals(False)
        elif kind == "hotkey":
            self.control.setSequence(value or "")
            self.refreshHotkeyError()
        elif kind == "info" and self.valueLabel is not None:
            self.valueLabel.setText(str(self.setting.valueGetter()))


class BrokenSettingRow(QWidget):
    """Shown instead of a setting whose declaration is invalid, so one bad setting never breaks a page."""

    def __init__(self, setting, error):
        super().__init__()
        self.setting = setting
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.divider = divider()
        layout.addWidget(self.divider)
        rowLayout = QHBoxLayout()
        rowLayout.setContentsMargins(4, 12, 4, 12)
        rowLayout.addWidget(IconWidget("triangle-alert", "danger", 18))
        try:
            labelText = tr(setting.label)
        except Exception:
            labelText = str(getattr(setting, "key", "?"))
        rowLayout.addWidget(makeLabel(f"{labelText} — {type(error).__name__}: {error}", "error", True), 1)
        layout.addLayout(rowLayout)

    def updateValue(self, value):
        pass

    def refreshPin(self):
        pass

    def refreshHotkeyError(self):
        pass


class SettingsForm(QWidget):
    def __init__(self, schema, adapter, parent=None, sectionCards=True):
        super().__init__(parent)
        self.schema = list(schema)
        self.adapter = adapter
        self.rows = {}
        self.groups = []
        self.sectionCards = sectionCards
        mainLayout = QVBoxLayout(self)
        mainLayout.setContentsMargins(0, 0, 0, 0)
        mainLayout.setSpacing(10)
        currentGroup = None
        for setting in self.schema:
            if isinstance(setting, Section) or currentGroup is None:
                titleText = tr(setting.label) if isinstance(setting, Section) else None
                currentGroup = self._createGroup(mainLayout, titleText, setting if isinstance(setting, Section) else None)
                if isinstance(setting, Section):
                    continue
            try:
                row = SettingRow(setting, self)
            except Exception as error:
                getLogger("settings").exception("Setting row '%s' failed", getattr(setting, "key", "?"))
                row = BrokenSettingRow(setting, error)
            currentGroup["layout"].addWidget(row)
            currentGroup["rows"].append(row)
            self.rows[setting.key] = row
        adapter.valueChanged.connect(self._onExternalChange)
        adapter.hotkeyStatusChanged.connect(self._onHotkeyStatus)
        adapter.pinsChanged.connect(self._refreshPins)
        self.refreshVisibility()

    def _createGroup(self, mainLayout, title, section):
        titleLabel = None
        if title:
            titleLabel = makeLabel(title.upper(), "section")
            titleLabel.setContentsMargins(6, 8, 0, 0)
            mainLayout.addWidget(titleLabel)
        container = Card(padding=6, hoverable=False) if self.sectionCards else QWidget()
        containerLayout = QVBoxLayout(container)
        if not self.sectionCards:
            containerLayout.setContentsMargins(0, 0, 0, 0)
        containerLayout.setSpacing(0)
        if section is not None and section.description:
            descriptionLabel = makeLabel(tr(section.description), "faint", True)
            descriptionLabel.setContentsMargins(4, 4, 4, 6)
            containerLayout.addWidget(descriptionLabel)
        mainLayout.addWidget(container)
        group = {"title": titleLabel, "container": container, "layout": containerLayout, "rows": [], "section": section}
        self.groups.append(group)
        return group

    def refreshVisibility(self):
        for group in self.groups:
            firstVisible = True
            anyVisible = False
            sectionVisible = group["section"] is None or group["section"].isVisible(self.adapter.get)
            for row in group["rows"]:
                visible = sectionVisible and row.setting.isVisible(self.adapter.get)
                row.setVisible(visible)
                if visible:
                    row.divider.setVisible(not firstVisible)
                    firstVisible = False
                    anyVisible = True
            group["container"].setVisible(anyVisible)
            if group["title"] is not None:
                group["title"].setVisible(anyVisible)

    def _onExternalChange(self, key, value):
        row = self.rows.get(key)
        if row is not None:
            row.updateValue(value)
        for infoRow in self.rows.values():
            if infoRow.setting.kind == "info":
                infoRow.updateValue(None)
        self.refreshVisibility()

    def _onHotkeyStatus(self, key):
        row = self.rows.get(key)
        if row is not None:
            row.refreshHotkeyError()

    def _refreshPins(self):
        for row in self.rows.values():
            row.refreshPin()
