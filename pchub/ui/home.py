import datetime
import getpass
import uuid

from PySide6.QtCore import QMimeData, QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QDrag, QPainter, QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QMenu, QPushButton, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from pchub.core.i18n import tr, language
from pchub.core.plugin_api import HomeWidgetSpec, WidgetSizes
from pchub.ui.dialogs import ThemedDialog, confirm
from pchub.ui.theme import theme, themeManager
from pchub.ui.widgets import (Card, EmptyState, FlowLayout, IconTile, IconWidget, MeterBar, clearLayout, iconButton,
                              makeButton, makeLabel, makeScrollPage, setRole, setThemedIcon, polish)

WIDGET_MIME = "application/x-pchub-home-widget"
ROW_HEIGHT = 168

DEFAULT_HOME = [
    {"type": "core.active", "size": "wide"},
    {"type": "system_monitor.cpu", "size": "small"},
    {"type": "system_monitor.ram", "size": "small"},
    {"type": "system_monitor.gpu", "size": "small"},
    {"type": "system_monitor.disk", "size": "small"},
    {"type": "core.quickActions", "size": "wide"},
    {"type": "timer.timers", "size": "wide"},
    {"type": "cleaner.quick", "size": "small"},
    {"type": "core.clock", "size": "small"},
]


def packLayout(items, columns):
    """items: [(uid, colSpan, rowSpan)] -> {uid: (row, col, rowSpan, colSpan)}. First-fit, dense."""
    occupied = set()
    positions = {}
    for uid, colSpan, rowSpan in items:
        colSpan = max(1, min(colSpan, columns))
        row = 0
        while True:
            placedColumn = None
            for column in range(columns - colSpan + 1):
                if all((row + rowOffset, column + colOffset) not in occupied
                       for rowOffset in range(rowSpan) for colOffset in range(colSpan)):
                    placedColumn = column
                    break
            if placedColumn is not None:
                for rowOffset in range(rowSpan):
                    for colOffset in range(colSpan):
                        occupied.add((row + rowOffset, placedColumn + colOffset))
                positions[uid] = (row, placedColumn, rowSpan, colSpan)
                break
            row += 1
    return positions


def greetingKey(hour):
    if 5 <= hour < 12:
        return "home.greetingMorning"
    if 12 <= hour < 18:
        return "home.greetingAfternoon"
    if 18 <= hour < 23:
        return "home.greetingEvening"
    return "home.greetingNight"


def formatLongDate(dateValue):
    if language() == "it":
        days = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
        months = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
                  "ottobre", "novembre", "dicembre"]
        return f"{days[dateValue.weekday()].capitalize()} {dateValue.day} {months[dateValue.month - 1]} {dateValue.year}"
    return dateValue.strftime("%A, %B %d, %Y").replace(" 0", " ")


class ClockWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addStretch(1)
        self.timeLabel = makeLabel("", "hero")
        layout.addWidget(self.timeLabel)
        self.dateLabel = makeLabel("", "muted", True)
        layout.addWidget(self.dateLabel)
        layout.addStretch(1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(1000)
        self.refresh()

    def refresh(self):
        if not self.isVisible() and self.timeLabel.text():
            return
        now = datetime.datetime.now()
        self.timeLabel.setText(now.strftime("%H:%M"))
        self.dateLabel.setText(formatLongDate(now))

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()


class ActiveRow(QWidget):
    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.fullId = f"{item.pluginId}:{item.itemId}"
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.setSpacing(10)
        self.tile = IconTile(item.icon or "activity", 32, item.accent)
        layout.addWidget(self.tile)
        textLayout = QVBoxLayout()
        textLayout.setSpacing(3)
        self.titleLabel = makeLabel(item.title)
        self.subtitleLabel = makeLabel(item.subtitle, "faint")
        self.progressBar = MeterBar(item.accent, 5)
        textLayout.addWidget(self.titleLabel)
        textLayout.addWidget(self.subtitleLabel)
        textLayout.addWidget(self.progressBar)
        layout.addLayout(textLayout, 1)
        self.actionsLayout = QHBoxLayout()
        self.actionsLayout.setSpacing(4)
        layout.addLayout(self.actionsLayout)
        self.actionSignature = None
        self.updateItem(item)

    def updateItem(self, item):
        self.titleLabel.setText(item.title)
        self.subtitleLabel.setText(item.subtitle or "")
        self.subtitleLabel.setVisible(bool(item.subtitle))
        self.tile.setIconName(item.icon or "activity")
        self.progressBar.setVisible(item.progress is not None)
        if item.progress is not None:
            self.progressBar.setValue(item.progress)
        signature = tuple((label, iconName) for label, iconName, _ in self._actions(item))
        if signature != self.actionSignature:
            self.actionSignature = signature
            clearLayout(self.actionsLayout)
            for label, iconName, callback in self._actions(item):
                button = iconButton(iconName or "square", tr(label), "text", 16)
                button.clicked.connect(lambda checked=False, function=callback: function())
                self.actionsLayout.addWidget(button)
        self.callbacks = [callback for _, _, callback in self._actions(item)]

    @staticmethod
    def _actions(item):
        normalized = []
        for action in item.actions:
            if len(action) == 3:
                normalized.append(action)
            else:
                normalized.append((action[0], None, action[1]))
        return normalized


class ActiveWidget(QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.rows = {}
        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(0, 0, 0, 0)
        self.mainLayout.setSpacing(2)
        self.emptyState = EmptyState("sparkles", tr("widget.activeEmpty"))
        self.mainLayout.addWidget(self.emptyState)
        self.rowsHost = QWidget()
        self.rowsLayout = QVBoxLayout(self.rowsHost)
        self.rowsLayout.setContentsMargins(0, 0, 0, 0)
        self.rowsLayout.setSpacing(2)
        scrollArea = QScrollArea()
        scrollArea.setWidgetResizable(True)
        scrollArea.setFrameShape(QFrame.NoFrame)
        scrollArea.setWidget(self.rowsHost)
        self.scrollArea = scrollArea
        self.mainLayout.addWidget(scrollArea, 1)
        app.activeRegistry.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        items = self.app.activeRegistry.items()
        currentIds = []
        for item in items:
            fullId = f"{item.pluginId}:{item.itemId}"
            currentIds.append(fullId)
            row = self.rows.get(fullId)
            if row is None:
                row = ActiveRow(item)
                self.rows[fullId] = row
            else:
                row.updateItem(item)
        for fullId in list(self.rows):
            if fullId not in currentIds:
                row = self.rows.pop(fullId)
                row.setParent(None)
                row.deleteLater()
        for index, fullId in enumerate(currentIds):
            row = self.rows[fullId]
            if self.rowsLayout.indexOf(row) != index:
                self.rowsLayout.insertWidget(index, row)
        if self.rowsLayout.count() and self.rowsLayout.itemAt(self.rowsLayout.count() - 1).spacerItem() is None:
            self.rowsLayout.addStretch(1)
        self.emptyState.setVisible(not items)
        self.scrollArea.setVisible(bool(items))


class QuickActionsWidget(QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.flowHost = QWidget()
        self.flowLayout = FlowLayout(self.flowHost, 8)
        layout.addWidget(self.flowHost)
        self.emptyLabel = makeLabel(tr("widget.quickActionsEmpty"), "faint", True)
        layout.addWidget(self.emptyLabel)
        layout.addStretch(1)
        app.pinService.changed.connect(self.rebuild)
        app.pluginManager.settingChanged.connect(self._onAnyChange)
        app.pluginManager.globalSettingChanged.connect(self._onAnyChange)
        app.pluginManager.statusChanged.connect(self._onAnyChange)
        self.buttons = []
        self.rebuild()

    def _onAnyChange(self, *args):
        self.refreshStates()

    def rebuild(self):
        while self.flowLayout.count():
            item = self.flowLayout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.buttons = []
        for pinned in self.app.pinService.items():
            button = QPushButton()
            button.setProperty("variant", "chip")
            button.setCursor(Qt.PointingHandCursor)
            iconName = pinned.icon or self.app.pluginManager.displayIcon(pinned.pluginId)
            setThemedIcon(button, iconName, "text", 15)
            if pinned.kind == "toggle":
                button.setCheckable(True)
                button.clicked.connect(lambda checked, item=pinned: item.setValue(checked))
            elif pinned.kind == "action":
                button.clicked.connect(lambda checked=False, item=pinned: item.run())
            else:
                menu = QMenu(button)
                for optionValue, optionLabel in pinned.options:
                    action = menu.addAction(optionLabel)
                    action.triggered.connect(lambda checked=False, item=pinned, value=optionValue: item.setValue(value))
                button.setMenu(menu)
            self.buttons.append((button, pinned))
            self.flowLayout.addWidget(button)
        self.emptyLabel.setVisible(not self.buttons)
        self.refreshStates()
        self.flowHost.updateGeometry()

    def refreshStates(self):
        for button, pinned in self.buttons:
            if pinned.kind == "toggle":
                button.setChecked(bool(pinned.getValue()))
                button.setText(pinned.label)
            elif pinned.kind in ("slider", "choice"):
                currentValue = pinned.getValue()
                currentLabel = next((label for value, label in pinned.options if value == currentValue),
                                    pinned.formatValue(currentValue))
                button.setText(f"{pinned.label}: {currentLabel}")
            else:
                button.setText(pinned.label)


def coreWidgetSpecs(app):
    return [
        HomeWidgetSpec("core.active", tr("widget.active"), lambda: ActiveWidget(app), tr("widget.activeDesc"), "activity",
                       "wide", ["wide", "large", "tall", "full", "small"]),
        HomeWidgetSpec("core.quickActions", tr("widget.quickActions"), lambda: QuickActionsWidget(app),
                       tr("widget.quickActionsDesc"), "zap", "wide", ["wide", "full", "large", "small"]),
        HomeWidgetSpec("core.clock", tr("widget.clock"), lambda: ClockWidget(), tr("widget.clockDesc"), "clock", "small",
                       ["small", "wide"]),
    ]


class HomeCard(Card):
    removeRequested = Signal(str)
    resizeRequested = Signal(str)
    dropped = Signal(str, str)

    def __init__(self, app, entry, spec, parent=None):
        super().__init__(parent, padding=14, hoverable=True)
        self.app = app
        self.uid = entry["uid"]
        self.spec = spec
        self.editMode = False
        self.dragStartPosition = None
        self.setAcceptDrops(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        headerLayout = QHBoxLayout()
        headerLayout.setSpacing(8)
        self.headerIcon = IconWidget(spec.icon if spec else "circle-alert", "muted", 16)
        headerLayout.addWidget(self.headerIcon)
        self.titleLabel = makeLabel((spec.name if isinstance(spec.name, str) else tr(spec.name)) if spec else tr("home.unavailable"),
                                    "section")
        headerLayout.addWidget(self.titleLabel, 1)
        self.stateChip = makeLabel("", "chip")
        self.stateChip.hide()
        headerLayout.addWidget(self.stateChip)
        self.dragHandle = IconWidget("grip-vertical", "faint", 16)
        self.resizeButton = iconButton("scaling", tr("home.resize"), "muted", 15)
        self.resizeButton.clicked.connect(lambda: self.resizeRequested.emit(self.uid))
        self.removeButton = iconButton("x", tr("home.remove"), "danger", 15)
        self.removeButton.clicked.connect(lambda: self.removeRequested.emit(self.uid))
        for control in (self.dragHandle, self.resizeButton, self.removeButton):
            control.hide()
            headerLayout.addWidget(control)
        layout.addLayout(headerLayout)
        self.content = None
        if spec is None:
            self.content = EmptyState("puzzle", tr("home.unavailable"), tr("home.unavailableText"))
        else:
            try:
                self.content = spec.factory()
            except Exception as error:
                app.log.exception("Home widget %s failed", spec.typeId)
                self.content = EmptyState("circle-alert", tr("status.error"), str(error))
        layout.addWidget(self.content, 1)
        if spec and spec.pluginId:
            app.pluginManager.statusChanged.connect(self._onStatus)
            self._onStatus(spec.pluginId)

    def _onStatus(self, pluginId):
        if not self.spec or pluginId != self.spec.pluginId:
            return
        status = self.app.pluginManager.records[pluginId].status
        inactive = status not in ("running",)
        self.stateChip.setVisible(inactive)
        if inactive:
            self.stateChip.setText(tr(f"status.{status}"))
        if self.content is not None and not self.editMode:
            self.content.setEnabled(not inactive)

    def setEditMode(self, editMode):
        self.editMode = editMode
        for control in (self.dragHandle, self.resizeButton, self.removeButton):
            control.setVisible(editMode)
        self.resizeButton.setVisible(editMode and self.spec is not None and len(self.spec.sizes) > 1)
        if self.content is not None:
            self.content.setAttribute(Qt.WA_TransparentForMouseEvents, editMode)
        self.setCursor(Qt.OpenHandCursor if editMode else Qt.ArrowCursor)

    def mousePressEvent(self, event):
        if self.editMode and event.button() == Qt.LeftButton:
            self.dragStartPosition = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self.editMode and self.dragStartPosition is not None and event.buttons() & Qt.LeftButton
                and (event.position().toPoint() - self.dragStartPosition).manhattanLength() > 8):
            drag = QDrag(self)
            mimeData = QMimeData()
            mimeData.setData(WIDGET_MIME, self.uid.encode("utf-8"))
            drag.setMimeData(mimeData)
            snapshot = self.grab()
            faded = QPixmap(snapshot.size())
            faded.setDevicePixelRatio(snapshot.devicePixelRatio())
            faded.fill(Qt.transparent)
            painter = QPainter(faded)
            painter.setOpacity(0.75)
            painter.drawPixmap(0, 0, snapshot)
            painter.end()
            drag.setPixmap(faded)
            drag.setHotSpot(self.dragStartPosition)
            self.dragStartPosition = None
            self.setSelected(False)
            drag.exec(Qt.MoveAction)
            return
        super().mouseMoveEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(WIDGET_MIME):
            sourceUid = bytes(event.mimeData().data(WIDGET_MIME)).decode("utf-8")
            if sourceUid != self.uid:
                self.setSelected(True)
                event.acceptProposedAction()
                return
        event.ignore()

    def dragLeaveEvent(self, event):
        self.setSelected(False)

    def dropEvent(self, event):
        self.setSelected(False)
        sourceUid = bytes(event.mimeData().data(WIDGET_MIME)).decode("utf-8")
        event.acceptProposedAction()
        QTimer.singleShot(0, lambda: self.dropped.emit(sourceUid, self.uid))


class WidgetCatalogDialog(ThemedDialog):
    def __init__(self, parent, specs, onAdd, pluginNameGetter):
        super().__init__(parent, 560)
        self.addHeader(tr("home.widgetCatalog"), "layout-grid", None, tr("home.widgetCatalogText"))
        scrollArea = QScrollArea()
        scrollArea.setWidgetResizable(True)
        scrollArea.setFrameShape(QFrame.NoFrame)
        scrollArea.setFixedHeight(420)
        listHost = QWidget()
        listLayout = QVBoxLayout(listHost)
        listLayout.setContentsMargins(0, 0, 6, 0)
        listLayout.setSpacing(6)
        for spec in specs:
            rowCard = Card(padding=10, hoverable=True, level=1)
            rowLayout = QHBoxLayout(rowCard)
            rowLayout.setSpacing(12)
            rowLayout.addWidget(IconTile(spec.icon, 38))
            textLayout = QVBoxLayout()
            textLayout.setSpacing(2)
            nameText = spec.name if isinstance(spec.name, str) else tr(spec.name)
            sourceText = pluginNameGetter(spec.pluginId) if spec.pluginId else "PC Hub"
            textLayout.addWidget(makeLabel(f"{nameText}"))
            textLayout.addWidget(makeLabel(f"{sourceText} · {tr(spec.description) if spec.description else ''}".strip(" ·"), "faint", True))
            rowLayout.addLayout(textLayout, 1)
            addButton = makeButton(tr("common.add"), "plus", "primary")
            addButton.clicked.connect(lambda checked=False, typeId=spec.typeId, button=addButton: self._add(typeId, button, onAdd))
            rowLayout.addWidget(addButton)
            listLayout.addWidget(rowCard)
        listLayout.addStretch(1)
        scrollArea.setWidget(listHost)
        self.bodyLayout.addWidget(scrollArea)
        closeButton = makeButton(tr("common.close"))
        closeButton.clicked.connect(self.accept)
        self.addButtons([closeButton])

    def _add(self, typeId, button, onAdd):
        onAdd(typeId)
        button.setText("✓")
        QTimer.singleShot(900, lambda: button.setText(tr("common.add")))


class HomePage(QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.editMode = False
        self.cards = {}
        self.columns = 4
        rootLayout = QVBoxLayout(self)
        rootLayout.setContentsMargins(0, 0, 0, 0)
        scrollArea, contentLayout = makeScrollPage((28, 24, 28, 28), 18)
        self.scrollArea = scrollArea
        rootLayout.addWidget(scrollArea)
        headerLayout = QHBoxLayout()
        headerLayout.setSpacing(10)
        greetingLayout = QVBoxLayout()
        greetingLayout.setSpacing(2)
        self.greetingLabel = makeLabel("", "title")
        self.dateLabel = makeLabel("", "muted")
        greetingLayout.addWidget(self.greetingLabel)
        greetingLayout.addWidget(self.dateLabel)
        headerLayout.addLayout(greetingLayout, 1)
        self.hintLabel = makeLabel(tr("home.dragHint"), "faint")
        self.hintLabel.hide()
        headerLayout.addWidget(self.hintLabel, 0, Qt.AlignVCenter)
        self.resetButton = makeButton(tr("home.resetLayout"), "rotate-ccw", "ghost")
        self.resetButton.clicked.connect(self._resetLayout)
        self.resetButton.hide()
        headerLayout.addWidget(self.resetButton, 0, Qt.AlignVCenter)
        self.addButton = makeButton(tr("home.addWidget"), "plus", "primary")
        self.addButton.clicked.connect(self.openCatalog)
        self.addButton.hide()
        headerLayout.addWidget(self.addButton, 0, Qt.AlignVCenter)
        self.customizeButton = makeButton(tr("home.customize"), "layout-grid")
        self.customizeButton.clicked.connect(lambda: self.setEditMode(not self.editMode))
        headerLayout.addWidget(self.customizeButton, 0, Qt.AlignVCenter)
        contentLayout.addLayout(headerLayout)
        self.gridHost = QWidget()
        self.gridHost.setAcceptDrops(True)
        self.gridLayout = QGridLayout(self.gridHost)
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.gridLayout.setHorizontalSpacing(4)
        self.gridLayout.setVerticalSpacing(4)
        contentLayout.addWidget(self.gridHost)
        self.emptyState = EmptyState("layout-grid", tr("home.emptyTitle"), tr("home.emptyText"))
        contentLayout.addWidget(self.emptyState)
        contentLayout.addStretch(1)
        self.greetingTimer = QTimer(self)
        self.greetingTimer.timeout.connect(self.refreshGreeting)
        self.greetingTimer.start(30000)
        app.appStore.changed.connect(self._onStoreChanged)
        app.pluginManager.pluginsChanged.connect(self.rebuild)
        self.refreshGreeting()
        self.rebuild()

    def _onStoreChanged(self, key, value):
        if key == "general.userName":
            self.refreshGreeting()

    # data -----------------------------------------------------------------
    def entries(self):
        storedEntries = self.app.appStore.get("home.widgets")
        if storedEntries is None:
            storedEntries = [dict(entry, uid=uuid.uuid4().hex[:10]) for entry in DEFAULT_HOME]
            self.app.appStore.set("home.widgets", storedEntries)
        return storedEntries

    def saveEntries(self, entries):
        self.app.appStore.set("home.widgets", entries)

    def specsById(self):
        specs = {spec.typeId: spec for spec in coreWidgetSpecs(self.app)}
        for spec in self.app.pluginManager.widgetSpecs():
            specs[spec.typeId] = spec
        return specs

    # ui -------------------------------------------------------------------
    def refreshGreeting(self):
        userName = self.app.appSetting("general.userName") or ""
        greeting = tr(greetingKey(datetime.datetime.now().hour))
        self.greetingLabel.setText(f"{greeting}, {userName}" if userName else greeting)
        self.dateLabel.setText(formatLongDate(datetime.datetime.now()))

    def rebuild(self):
        for card in self.cards.values():
            card.setParent(None)
            card.deleteLater()
        self.cards = {}
        specs = self.specsById()
        for entry in self.entries():
            card = HomeCard(self.app, entry, specs.get(entry["type"]))
            card.removeRequested.connect(self.removeWidget)
            card.resizeRequested.connect(self.cycleSize)
            card.dropped.connect(self.moveWidget)
            card.setEditMode(self.editMode)
            self.cards[entry["uid"]] = card
        self.relayout()

    def relayout(self):
        entries = self.entries()
        while self.gridLayout.count():
            self.gridLayout.takeAt(0)
        for column in range(6):
            self.gridLayout.setColumnStretch(column, 0)
            self.gridLayout.setColumnMinimumWidth(column, 0)
        items = []
        for entry in entries:
            colSpan, rowSpan = WidgetSizes.spans.get(entry.get("size", "small"), (1, 1))
            if entry.get("size") == "full":
                colSpan = self.columns
            items.append((entry["uid"], colSpan, rowSpan))
        positions = packLayout(items, self.columns)
        maxRow = 0
        for uid, (row, column, rowSpan, colSpan) in positions.items():
            card = self.cards.get(uid)
            if card is None:
                continue
            self.gridLayout.addWidget(card, row, column, rowSpan, colSpan)
            card.setMinimumHeight(ROW_HEIGHT * rowSpan - 4)
            card.show()
            maxRow = max(maxRow, row + rowSpan)
        for column in range(self.columns):
            self.gridLayout.setColumnStretch(column, 1)
        for row in range(maxRow + 1):
            self.gridLayout.setRowMinimumHeight(row, ROW_HEIGHT - 4)
        self.emptyState.setVisible(not entries)
        self.gridHost.setVisible(bool(entries))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        availableWidth = self.scrollArea.viewport().width() - 56
        newColumns = 4 if availableWidth >= 840 else 3 if availableWidth >= 600 else 2
        if newColumns != self.columns:
            self.columns = newColumns
            self.relayout()

    def setEditMode(self, editMode):
        self.editMode = editMode
        self.customizeButton.setText(tr("home.done") if editMode else tr("home.customize"))
        self.customizeButton.setProperty("variant", "primary" if editMode else None)
        setThemedIcon(self.customizeButton, "check" if editMode else "layout-grid", "accentText" if editMode else "text", 16)
        polish(self.customizeButton)
        for control in (self.addButton, self.resetButton, self.hintLabel):
            control.setVisible(editMode)
        for card in self.cards.values():
            card.setEditMode(editMode)

    def addWidget(self, typeId):
        spec = self.specsById().get(typeId)
        if spec is None:
            return
        entries = self.entries()
        entries.append({"uid": uuid.uuid4().hex[:10], "type": typeId, "size": spec.defaultSize})
        self.saveEntries(entries)
        self.rebuild()

    def removeWidget(self, uid):
        self.saveEntries([entry for entry in self.entries() if entry["uid"] != uid])
        self.rebuild()

    def cycleSize(self, uid):
        entries = self.entries()
        specs = self.specsById()
        for entry in entries:
            if entry["uid"] == uid:
                spec = specs.get(entry["type"])
                sizes = spec.sizes if spec else ["small"]
                currentIndex = sizes.index(entry.get("size")) if entry.get("size") in sizes else -1
                entry["size"] = sizes[(currentIndex + 1) % len(sizes)]
        self.saveEntries(entries)
        self.relayout()

    def moveWidget(self, sourceUid, targetUid):
        entries = self.entries()
        sourceEntry = next((entry for entry in entries if entry["uid"] == sourceUid), None)
        if sourceEntry is None or sourceUid == targetUid:
            return
        entries.remove(sourceEntry)
        targetIndex = next((index for index, entry in enumerate(entries) if entry["uid"] == targetUid), len(entries))
        entries.insert(targetIndex, sourceEntry)
        self.saveEntries(entries)
        self.relayout()

    def openCatalog(self):
        specs = list(self.specsById().values())
        dialog = WidgetCatalogDialog(self, specs, self.addWidget, self.app.pluginManager.displayName)
        dialog.exec()

    def _resetLayout(self):
        if confirm(self, tr("home.resetLayout"), tr("home.resetLayoutMessage"), confirmText=tr("home.resetLayout")):
            self.app.appStore.remove("home.widgets")
            self.rebuild()
