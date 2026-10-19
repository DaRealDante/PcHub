import uuid

from PySide6.QtCore import QEasingCurve, QPointF, QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QMenu, QStyle, QStyledItemDelegate, QTreeWidget, QTreeWidgetItem,
                               QTreeWidgetItemIterator, QVBoxLayout, QHBoxLayout, QWidget)

from pchub import APP_NAME
from pchub.core.i18n import tr
from pchub.ui.icons import drawIcon
from pchub.ui.theme import SurfaceState, theme, themeManager, withAlpha
from pchub.ui.widgets import Card, IconTile, LogoWidget, makeLabel, statusColor

KIND_ROLE = Qt.UserRole
ID_ROLE = Qt.UserRole + 1
ICON_ROLE = Qt.UserRole + 2


def syncLayout(layoutNodes, pluginIds):
    """Drop unknown plugins, append new ones at the end. Pure function (unit tested)."""
    knownIds = set(pluginIds)
    seenIds = set()

    def clean(nodes):
        cleanedNodes = []
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            if node.get("type") == "plugin":
                pluginId = node.get("id")
                if pluginId in knownIds and pluginId not in seenIds:
                    seenIds.add(pluginId)
                    cleanedNodes.append({"type": "plugin", "id": pluginId})
            elif node.get("type") == "folder":
                cleanedNodes.append({
                    "type": "folder", "id": node.get("id") or uuid.uuid4().hex[:8],
                    "name": node.get("name") or "Folder", "icon": node.get("icon") or "",
                    "expanded": bool(node.get("expanded", True)), "children": clean(node.get("children")),
                })
        return cleanedNodes

    resultNodes = clean(layoutNodes)
    for pluginId in pluginIds:
        if pluginId not in seenIds:
            resultNodes.append({"type": "plugin", "id": pluginId})
    return resultNodes


class SidebarDelegate(QStyledItemDelegate):
    rowHeight = 40

    def __init__(self, tree):
        super().__init__(tree)
        self.tree = tree

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), self.rowHeight)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        currentTheme = theme()
        item = self.tree.itemFromIndex(index)
        depth = 0
        parentItem = item.parent()
        while parentItem is not None:
            depth += 1
            parentItem = parentItem.parent()
        rect = QRectF(option.rect).adjusted(4 + depth * 14, 2, -6, -2)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)
        if self.tree.dragSourceItem is item:
            painter.setOpacity(0.45)
        currentTheme.paintPill(painter, rect, SurfaceState(hover=1.0 if hovered else 0.0, selected=selected))
        textColor = currentTheme.text
        if selected and currentTheme.styleId == "clay":
            textColor = currentTheme.accentText
        kind = item.data(0, KIND_ROLE)
        x = rect.left() + 10
        centerY = rect.center().y()
        iconColor = textColor if selected else currentTheme.textMuted
        if kind == "folder":
            chevronRect = QRectF(x - 2, centerY - 7, 14, 14)
            painter.save()
            painter.translate(chevronRect.center())
            painter.rotate(90 if item.isExpanded() else 0)
            painter.translate(-chevronRect.center())
            drawIcon(painter, chevronRect, "chevron-right", currentTheme.textFaint.name())
            painter.restore()
            x += 16
            folderIcon = item.data(0, ICON_ROLE) or ("folder-open" if item.isExpanded() else "folder")
            drawIcon(painter, QRectF(x, centerY - 9, 18, 18), folderIcon, iconColor.name())
        else:
            drawIcon(painter, QRectF(x, centerY - 9, 18, 18), item.data(0, ICON_ROLE) or "puzzle", iconColor.name())
        x += 28
        font = painter.font()
        font.setPixelSize(13)
        font.setWeight(QFont.DemiBold if selected or kind == "folder" else QFont.Medium)
        painter.setFont(font)
        status = self.tree.statusGetter(item.data(0, ID_ROLE)) if kind == "plugin" else None
        textRight = rect.right() - (22 if status and status != "running" else 10)
        dimmed = status in ("disabled", "stopped") and not selected
        painter.setPen(currentTheme.textMuted if dimmed else textColor)
        textRect = QRectF(x, rect.top(), textRight - x, rect.height())
        elided = painter.fontMetrics().elidedText(item.text(0), Qt.ElideRight, int(textRect.width()))
        painter.drawText(textRect, Qt.AlignVCenter | Qt.AlignLeft, elided)
        if kind == "folder" and not item.isExpanded() and item.childCount():
            painter.setPen(currentTheme.textFaint)
            countFont = painter.font()
            countFont.setPixelSize(11)
            painter.setFont(countFont)
            painter.drawText(QRectF(rect.right() - 30, rect.top(), 22, rect.height()), Qt.AlignVCenter | Qt.AlignRight,
                             str(item.childCount()))
        if status and status != "running":
            painter.setPen(Qt.NoPen)
            painter.setBrush(statusColor(status))
            painter.drawEllipse(QPointF(rect.right() - 12, centerY), 3.5, 3.5)
        painter.restore()


class SidebarTree(QTreeWidget):
    pluginActivated = Signal(str)
    layoutEdited = Signal()
    contextRequested = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.statusGetter = lambda pluginId: "running"
        self.dragSourceItem = None
        self.dropTarget = None
        self.setHeaderHidden(True)
        self.setIndentation(0)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setAnimated(True)
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WA_Hover, True)
        self.setFrameShape(QTreeWidget.NoFrame)
        self.setFocusPolicy(Qt.NoFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setItemDelegate(SidebarDelegate(self))
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda point: self.contextRequested.emit(self.itemAt(point), point))
        self.itemClicked.connect(self._onClicked)
        self.itemExpanded.connect(lambda item: self.layoutEdited.emit())
        self.itemCollapsed.connect(lambda item: self.layoutEdited.emit())
        self.setStyleSheet("QTreeWidget { background: transparent; border: none; } QTreeWidget::item { background: transparent; }"
                           "QTreeWidget::branch { background: transparent; border: none; image: none; }")
        themeManager().changed.connect(self.viewport().update)

    # model ----------------------------------------------------------------
    def _discardAllItems(self):
        """Removes every item through Python-owned takes (QTreeWidget.clear() leaves stale
        PySide wrappers behind, which crash later when Qt reuses the memory)."""

        def discard(item):
            while item.childCount():
                discard(item.takeChild(0))

        while self.topLevelItemCount():
            discard(self.takeTopLevelItem(0))

    def populate(self, layoutNodes, nameGetter, iconGetter):
        self.blockSignals(True)
        self.clearSelection()
        self._discardAllItems()

        def addNodes(parentItem, nodes):
            for node in nodes:
                if node["type"] == "plugin":
                    item = QTreeWidgetItem([nameGetter(node["id"])])
                    item.setData(0, KIND_ROLE, "plugin")
                    item.setData(0, ID_ROLE, node["id"])
                    item.setData(0, ICON_ROLE, iconGetter(node["id"]))
                    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
                    parentItem.addChild(item)
                else:
                    item = QTreeWidgetItem([node["name"]])
                    item.setData(0, KIND_ROLE, "folder")
                    item.setData(0, ID_ROLE, node["id"])
                    item.setData(0, ICON_ROLE, node.get("icon") or "")
                    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)
                    parentItem.addChild(item)
                    addNodes(item, node.get("children", []))
                    item.setExpanded(node.get("expanded", True))

        addNodes(self.invisibleRootItem(), layoutNodes)
        self.blockSignals(False)

    def serialize(self):
        def nodesOf(parentItem):
            nodes = []
            for childIndex in range(parentItem.childCount()):
                item = parentItem.child(childIndex)
                if item.data(0, KIND_ROLE) == "plugin":
                    nodes.append({"type": "plugin", "id": item.data(0, ID_ROLE)})
                else:
                    nodes.append({"type": "folder", "id": item.data(0, ID_ROLE), "name": item.text(0),
                                  "icon": item.data(0, ICON_ROLE) or "", "expanded": item.isExpanded(),
                                  "children": nodesOf(item)})
            return nodes

        return nodesOf(self.invisibleRootItem())

    def findPluginItem(self, pluginId):
        iterator = QTreeWidgetItemIterator(self)
        while iterator.value():
            item = iterator.value()
            if item.data(0, KIND_ROLE) == "plugin" and item.data(0, ID_ROLE) == pluginId:
                return item
            iterator += 1
        return None

    def selectPlugin(self, pluginId):
        self.blockSignals(True)
        item = self.findPluginItem(pluginId) if pluginId else None
        self.clearSelection()
        if item is not None:
            parentItem = item.parent()
            while parentItem is not None:
                parentItem.setExpanded(True)
                parentItem = parentItem.parent()
            item.setSelected(True)
            self.scrollToItem(item)
        self.blockSignals(False)
        self.viewport().update()

    def _onClicked(self, item, column):
        if item.data(0, KIND_ROLE) == "folder":
            item.setExpanded(not item.isExpanded())
            item.setSelected(False)
        else:
            self.pluginActivated.emit(item.data(0, ID_ROLE))

    # drag & drop ----------------------------------------------------------
    def startDrag(self, supportedActions):
        self.dragSourceItem = self.currentItem()
        try:
            super().startDrag(supportedActions)
        finally:
            self.dragSourceItem = None
            self.dropTarget = None
            self.viewport().update()

    def _computeDropTarget(self, position):
        item = self.itemAt(position)
        if item is None:
            return None, "end"
        rect = self.visualItemRect(item)
        relativeY = (position.y() - rect.top()) / max(1, rect.height())
        if item.data(0, KIND_ROLE) == "folder":
            if relativeY < 0.28:
                return item, "above"
            if relativeY > 0.72 and not item.isExpanded():
                return item, "below"
            return item, "on"
        return item, "above" if relativeY < 0.5 else "below"

    def dragMoveEvent(self, event):
        super().dragMoveEvent(event)
        source = self.dragSourceItem or self.currentItem()
        targetItem, position = self._computeDropTarget(event.position().toPoint())
        if source is None or not self.canMove(source, targetItem, position):
            self.dropTarget = None
            event.ignore()
        else:
            self.dropTarget = (targetItem, position)
            event.setDropAction(Qt.MoveAction)
            event.accept()
        self.viewport().update()

    def dragLeaveEvent(self, event):
        self.dropTarget = None
        self.viewport().update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        source = self.dragSourceItem or self.currentItem()
        targetItem, position = self._computeDropTarget(event.position().toPoint())
        moved = source is not None and self.moveItem(source, targetItem, position)
        self.dropTarget = None
        event.setDropAction(Qt.IgnoreAction)
        event.accept()
        self.viewport().update()
        if moved:
            self.layoutEdited.emit()

    def canMove(self, item, targetItem, position):
        if item is None or targetItem is item:
            return False
        newParent = self._newParent(targetItem, position)
        ancestor = newParent
        while ancestor is not None:
            if ancestor is item:
                return False
            ancestor = ancestor.parent()
        return True

    def _newParent(self, targetItem, position):
        if targetItem is None or position == "end":
            return None
        if position == "on":
            return targetItem
        return targetItem.parent()

    def moveItem(self, item, targetItem, position):
        if not self.canMove(item, targetItem, position):
            return False
        rootItem = self.invisibleRootItem()
        newParent = self._newParent(targetItem, position) or rootItem
        if position == "on" or position == "end" or targetItem is None:
            insertIndex = newParent.childCount()
        else:
            insertIndex = newParent.indexOfChild(targetItem) + (1 if position == "below" else 0)
        oldParent = item.parent() or rootItem
        oldIndex = oldParent.indexOfChild(item)
        expandedStates = self._collectExpanded(item)
        if oldParent is newParent and oldIndex < insertIndex:
            insertIndex -= 1
        takenItem = oldParent.takeChild(oldIndex)
        newParent.insertChild(insertIndex, takenItem)
        self._restoreExpanded(takenItem, expandedStates)
        if position == "on" and targetItem is not None:
            targetItem.setExpanded(True)
        return True

    def _collectExpanded(self, item):
        states = {}
        stack = [item]
        while stack:
            current = stack.pop()
            if current.data(0, KIND_ROLE) == "folder":
                states[current.data(0, ID_ROLE)] = current.isExpanded()
            stack.extend(current.child(index) for index in range(current.childCount()))
        return states

    def _restoreExpanded(self, item, states):
        stack = [item]
        while stack:
            current = stack.pop()
            if current.data(0, KIND_ROLE) == "folder":
                current.setExpanded(states.get(current.data(0, ID_ROLE), True))
            stack.extend(current.child(index) for index in range(current.childCount()))

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.dropTarget:
            return
        targetItem, position = self.dropTarget
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing)
        accent = theme().accentLight
        if targetItem is None:
            lastRect = QRect(0, 0, self.viewport().width(), 0)
            iterator = QTreeWidgetItemIterator(self)
            while iterator.value():
                itemRect = self.visualItemRect(iterator.value())
                if itemRect.isValid() and itemRect.bottom() > lastRect.bottom():
                    lastRect = itemRect
                iterator += 1
            lineY = lastRect.bottom() + 2
            painter.setPen(QPen(accent, 2.5, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(QPointF(12, lineY), QPointF(self.viewport().width() - 12, lineY))
            return
        rect = self.visualItemRect(targetItem)
        if position == "on":
            painter.setPen(QPen(accent, 1.6))
            painter.setBrush(withAlpha(accent, 0.12))
            painter.drawRoundedRect(QRectF(rect).adjusted(5, 2, -7, -2), 10, 10)
        else:
            lineY = rect.top() if position == "above" else rect.bottom()
            painter.setPen(QPen(accent, 2.5, Qt.SolidLine, Qt.RoundCap))
            painter.drawLine(QPointF(14, lineY), QPointF(rect.right() - 10, lineY))
            painter.setBrush(accent)
            painter.drawEllipse(QPointF(12, lineY), 3, 3)


class NavButton(QWidget):
    clicked = Signal()

    def __init__(self, iconName, text, parent=None):
        super().__init__(parent)
        self.iconName = iconName
        self.text = text
        self.selected = False
        self.hoverAmount = 0.0
        self.setFixedHeight(40)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.hoverAnimation = QVariantAnimation(self)
        self.hoverAnimation.setDuration(140)
        self.hoverAnimation.setEasingCurve(QEasingCurve.OutCubic)
        self.hoverAnimation.valueChanged.connect(self._setHover)
        themeManager().changed.connect(self.update)

    def _setHover(self, value):
        self.hoverAmount = float(value)
        self.update()

    def _animateHover(self, target):
        if not themeManager().animations:
            self._setHover(target)
            return
        self.hoverAnimation.stop()
        self.hoverAnimation.setStartValue(self.hoverAmount)
        self.hoverAnimation.setEndValue(float(target))
        self.hoverAnimation.start()

    def enterEvent(self, event):
        self._animateHover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animateHover(0.0)
        super().leaveEvent(event)

    def setSelected(self, selected):
        self.selected = selected
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        currentTheme = theme()
        rect = QRectF(self.rect()).adjusted(4, 2, -6, -2)
        currentTheme.paintPill(painter, rect, SurfaceState(hover=self.hoverAmount, selected=self.selected))
        textColor = currentTheme.accentText if (self.selected and currentTheme.styleId == "clay") else currentTheme.text
        iconColor = textColor if self.selected else currentTheme.textMuted
        drawIcon(painter, QRectF(rect.left() + 10, rect.center().y() - 9, 18, 18), self.iconName, iconColor.name())
        font = painter.font()
        font.setPixelSize(13)
        font.setWeight(QFont.DemiBold if self.selected else QFont.Medium)
        painter.setFont(font)
        painter.setPen(textColor)
        painter.drawText(QRectF(rect.left() + 38, rect.top(), rect.width() - 44, rect.height()),
                         Qt.AlignVCenter | Qt.AlignLeft, self.text)


class SidebarPanel(Card):
    navigate = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent, padding=10, hoverable=True, liquid=True)
        self.setFixedWidth(258)
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        headerLayout = QHBoxLayout()
        headerLayout.setContentsMargins(6, 4, 6, 10)
        headerLayout.setSpacing(10)
        self.logoTile = LogoWidget(36)
        headerLayout.addWidget(self.logoTile)
        titleLayout = QVBoxLayout()
        titleLayout.setSpacing(0)
        titleLayout.addWidget(makeLabel(APP_NAME, "subtitle"))
        titleLayout.addWidget(makeLabel(tr("app.tagline"), "faint"))
        headerLayout.addLayout(titleLayout, 1)
        layout.addLayout(headerLayout)
        self.homeButton = NavButton("house", tr("nav.home"))
        self.homeButton.clicked.connect(lambda: self.navigate.emit("home"))
        layout.addWidget(self.homeButton)
        sectionLabel = makeLabel(tr("nav.plugins").upper(), "section")
        sectionLabel.setContentsMargins(12, 10, 0, 2)
        layout.addWidget(sectionLabel)
        self.tree = SidebarTree()
        self.tree.pluginActivated.connect(lambda pluginId: self.navigate.emit(f"plugin:{pluginId}"))
        layout.addWidget(self.tree, 1)
        self.pluginsButton = NavButton("puzzle", tr("nav.plugins"))
        self.pluginsButton.clicked.connect(lambda: self.navigate.emit("plugins"))
        layout.addWidget(self.pluginsButton)
        self.settingsButton = NavButton("settings", tr("nav.settings"))
        self.settingsButton.clicked.connect(lambda: self.navigate.emit("settings"))
        layout.addWidget(self.settingsButton)

    def setCurrent(self, pageKey):
        self.homeButton.setSelected(pageKey == "home")
        self.pluginsButton.setSelected(pageKey == "plugins")
        self.settingsButton.setSelected(pageKey == "settings")
        self.tree.selectPlugin(pageKey.split(":", 1)[1] if pageKey.startswith("plugin:") else None)
