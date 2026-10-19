import datetime
import uuid

from PySide6.QtCore import QPoint, QRectF, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QMenu, QPlainTextEdit,
                               QSizeGrip, QVBoxLayout, QWidget)

from pchub.core.dates import formatWhen, parseDateTime, toIso
from pchub.core.i18n import T, tr
from pchub.core.plugin_api import HomeWidgetSpec, PluginBase, TrayEntry
from pchub.core.settings_schema import HotkeySetting, Section, Slider, Toggle
from pchub.ui.dialogs import confirm
from pchub.ui.pickers import ColorSwatches
from pchub.ui.theme import mix, roundedPath, shadowImage, theme, withAlpha
from pchub.ui.widgets import (Card, EmptyState, IconWidget, clearLayout, iconButton, makeButton, makeLabel)

NOTE_COLORS = ["#2A2D45", "#4C3F91", "#1E4E79", "#1F5F4A", "#7A5A12", "#7C2D37", "#6B2F6B", "#374151"]
TEXT = {
    "new": T("Nuova nota", "New note"),
    "search": T("Cerca nelle note…", "Search notes…"),
    "empty": T("Nessuna nota", "No notes"),
    "emptyText": T("Premi Nuova nota o la hotkey per scrivere al volo.", "Press New note or the hotkey to jot something down."),
    "untitled": T("Senza titolo", "Untitled"),
    "titlePlaceholder": T("Titolo", "Title"),
    "bodyPlaceholder": T("Scrivi qui… si salva da sola.", "Write here… it saves by itself."),
    "pin": T("Fissa in alto", "Pin to top"),
    "unpin": T("Togli da in alto", "Unpin"),
    "sticky": T("Attacca sul desktop", "Stick on desktop"),
    "unsticky": T("Stacca dal desktop", "Remove from desktop"),
    "delete": T("Elimina", "Delete"),
    "deleteTitle": T("Eliminare la nota?", "Delete the note?"),
    "color": T("Colore", "Color"),
    "saved": T("Salvata {when}", "Saved {when}"),
    "chars": T("{count} caratteri", "{count} characters"),
    "quickTitle": T("Nota al volo", "Quick note"),
    "selectNote": T("Scegli una nota a sinistra o creane una nuova.", "Pick a note on the left or create a new one."),
    "pinned": T("Fissate", "Pinned"),
    "others": T("Altre", "Others"),
}


def noteTitle(note):
    title = (note.get("title") or "").strip()
    if title:
        return title
    firstLine = (note.get("body") or "").strip().split("\n", 1)[0]
    return firstLine[:60] or tr(TEXT["untitled"])


class NotesPlugin(PluginBase):
    pluginId = "notes"
    name = T("Note", "Notes")
    description = T("Note veloci che si salvano da sole, anche attaccate sul desktop come post-it.",
                    "Quick notes that save by themselves, even stuck on the desktop like sticky notes.")
    icon = "notebook-pen"
    version = "1.0.0"
    author = "PC Hub"
    settingsSchema = [
        Section(T("Scorciatoie", "Shortcuts")),
        HotkeySetting("quickHotkey", T("Nota al volo", "Quick note"), action="quickNote", default="Ctrl+Alt+N",
                      icon="keyboard", description=T("Apre un post-it nuovo da qualsiasi programma.",
                                                     "Opens a new sticky note from any program.")),
        Section(T("Post-it sul desktop", "Desktop sticky notes")),
        Toggle("stickyOnTop", T("Sempre in primo piano", "Always on top"), False, icon="layers"),
        Slider("stickyOpacity", T("Trasparenza dei post-it", "Sticky note opacity"), 40, 100, 96, suffix="%", icon="eye",
               pinnable=False),
        Slider("fontSize", T("Dimensione testo", "Text size"), 10, 22, 13, suffix=" px", icon="type", pinnable=False),
    ]

    notesChanged = Signal()
    noteUpdated = Signal(str)

    def __init__(self, context):
        super().__init__(context)
        self.notes = list(context.getData("notes", []) or [])
        self.stickyWindows = {}
        self.saveTimer = QTimer(self)
        self.saveTimer.setSingleShot(True)
        self.saveTimer.setInterval(600)
        self.saveTimer.timeout.connect(self.save)

    def start(self):
        for note in self.notes:
            if note.get("sticky"):
                self.showSticky(note["id"])

    def stop(self):
        self.save()
        for window in list(self.stickyWindows.values()):
            window.closeQuietly()
        self.stickyWindows = {}

    def save(self):
        self.saveTimer.stop()
        self.context.setData("notes", self.notes)

    def onSettingChanged(self, key, value):
        for window in self.stickyWindows.values():
            window.applySettings()
        self.notesChanged.emit()

    # model -----------------------------------------------------------------
    def find(self, noteId):
        return next((note for note in self.notes if note["id"] == noteId), None)

    def add(self, title="", body="", color=None, sticky=False):
        now = toIso(datetime.datetime.now().replace(microsecond=0))
        note = {"id": uuid.uuid4().hex[:10], "title": title, "body": body, "color": color or NOTE_COLORS[0],
                "pinned": False, "sticky": sticky, "createdAt": now, "updatedAt": now, "geometry": None}
        self.notes.insert(0, note)
        self.save()
        self.notesChanged.emit()
        return note

    def update(self, noteId, emitList=True, **fields):
        note = self.find(noteId)
        if note is None:
            return
        changed = any(note.get(key) != value for key, value in fields.items())
        if not changed:
            return
        note.update(fields)
        if "title" in fields or "body" in fields:
            note["updatedAt"] = toIso(datetime.datetime.now().replace(microsecond=0))
        self.saveTimer.start()
        self.noteUpdated.emit(noteId)
        if emitList:
            self.notesChanged.emit()

    def delete(self, noteId):
        window = self.stickyWindows.pop(noteId, None)
        if window is not None:
            window.closeQuietly()
        self.notes = [note for note in self.notes if note["id"] != noteId]
        self.save()
        self.notesChanged.emit()

    def ordered(self, query=""):
        words = query.lower().split()
        visible = [note for note in self.notes
                   if all(word in (note.get("title", "") + " " + note.get("body", "")).lower() for word in words)]
        return sorted(visible, key=lambda note: (not note.get("pinned"), note.get("updatedAt") or ""), reverse=False) \
            if False else sorted(visible, key=lambda note: (0 if note.get("pinned") else 1, _negated(note.get("updatedAt"))))

    # sticky notes -----------------------------------------------------------
    def showSticky(self, noteId):
        note = self.find(noteId)
        if note is None:
            return
        window = self.stickyWindows.get(noteId)
        if window is None:
            window = StickyNoteWindow(self, noteId)
            self.stickyWindows[noteId] = window
        if not note.get("sticky"):
            self.update(noteId, sticky=True)
        window.show()
        window.raise_()

    def hideSticky(self, noteId):
        window = self.stickyWindows.pop(noteId, None)
        if window is not None:
            window.closeQuietly()
        self.update(noteId, sticky=False)

    def quickNote(self):
        note = self.add(sticky=True)
        self.showSticky(note["id"])
        window = self.stickyWindows.get(note["id"])
        if window is not None:
            window.activateWindow()
            window.editor.setFocus()

    def createPage(self):
        return NotesPage(self)

    def homeWidgets(self):
        return [HomeWidgetSpec("notes.recent", T("Note", "Notes"), lambda: NotesHomeWidget(self),
                               T("Le note fissate o più recenti, con una nota veloce.", "Pinned or recent notes, plus a quick note."),
                               "notebook-pen", "wide", ["wide", "tall", "large", "small"])]

    def trayEntries(self):
        return [TrayEntry("quick", TEXT["quickTitle"], self.quickNote, icon="sticky-note")]


Plugin = NotesPlugin


def _negated(isoText):
    """Sort key that puts the most recent first."""
    try:
        return -datetime.datetime.fromisoformat(isoText).timestamp()
    except (TypeError, ValueError):
        return 0


class StickyNoteWindow(QWidget):
    """A post-it on the desktop. Drag the top bar to move, corner to resize. Text syncs with the Notes page."""

    def __init__(self, plugin, noteId):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint)
        self.plugin = plugin
        self.noteId = noteId
        self.dragOffset = None
        self.quiet = False
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(200, 160)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(4)
        topRow = QHBoxLayout()
        topRow.setSpacing(2)
        self.titleLabel = makeLabel("", "faint")
        topRow.addWidget(self.titleLabel, 1)
        colorButton = iconButton("palette", tr(TEXT["color"]), "muted", 14)
        colorButton.clicked.connect(self._colorMenu)
        topRow.addWidget(colorButton)
        openButton = iconButton("external-link", None, "muted", 14)
        openButton.clicked.connect(self._openInApp)
        topRow.addWidget(openButton)
        closeButton = iconButton("x", tr(TEXT["unsticky"]), "muted", 14)
        closeButton.clicked.connect(lambda: plugin.hideSticky(noteId))
        topRow.addWidget(closeButton)
        layout.addLayout(topRow)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(tr(TEXT["bodyPlaceholder"]))
        self.editor.setStyleSheet("QPlainTextEdit { background: transparent; border: none; padding: 0px; }")
        layout.addWidget(self.editor, 1)
        gripRow = QHBoxLayout()
        gripRow.addStretch(1)
        gripRow.addWidget(QSizeGrip(self))
        layout.addLayout(gripRow)
        note = plugin.find(noteId) or {}
        self.editor.setPlainText(note.get("body", ""))
        self.editor.textChanged.connect(self._onText)
        plugin.noteUpdated.connect(self._onNoteUpdated)
        geometry = note.get("geometry")
        if geometry:
            self.setGeometry(*geometry)
        else:
            self.resize(280, 240)
            screen = self.screen().availableGeometry() if self.screen() else None
            if screen is not None:
                offset = 30 * (len(plugin.stickyWindows) % 6)
                self.move(screen.right() - 320 - offset, screen.top() + 60 + offset)
        self.applySettings()
        self._refreshTitle()

    def applySettings(self):
        onTop = bool(self.plugin.setting("stickyOnTop"))
        if bool(self.windowFlags() & Qt.WindowStaysOnTopHint) != onTop:
            visible = self.isVisible()
            self.setWindowFlag(Qt.WindowStaysOnTopHint, onTop)
            if visible:
                self.show()
        self.setWindowOpacity(max(0.4, (self.plugin.setting("stickyOpacity") or 96) / 100.0))
        font = self.editor.font()
        font.setPixelSize(int(self.plugin.setting("fontSize") or 13))
        self.editor.setFont(font)
        self.update()

    def _refreshTitle(self):
        note = self.plugin.find(self.noteId)
        if note is not None:
            self.titleLabel.setText(noteTitle(note))

    def _onText(self):
        self.plugin.update(self.noteId, emitList=False, body=self.editor.toPlainText())
        self._refreshTitle()
        self.plugin.notesChanged.emit()

    def _onNoteUpdated(self, noteId):
        if noteId != self.noteId:
            return
        note = self.plugin.find(noteId)
        if note is None:
            return
        if note.get("body", "") != self.editor.toPlainText():
            cursor = self.editor.textCursor().position()
            self.editor.blockSignals(True)
            self.editor.setPlainText(note.get("body", ""))
            cursorObject = self.editor.textCursor()
            cursorObject.setPosition(min(cursor, len(note.get("body", ""))))
            self.editor.setTextCursor(cursorObject)
            self.editor.blockSignals(False)
        self._refreshTitle()
        self.update()

    def _colorMenu(self):
        menu = QMenu(self)
        for index, colorHex in enumerate(NOTE_COLORS):
            action = menu.addAction(f"● {index + 1}")
            action.triggered.connect(lambda checked=False, value=colorHex: self.plugin.update(self.noteId, color=value))
        menu.exec(self.mapToGlobal(QPoint(self.width() - 60, 30)))

    def _openInApp(self):
        self.plugin.context.openPage()
        page = getattr(self.plugin, "page", None)
        if page is not None:
            page.selectNote(self.noteId)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        note = self.plugin.find(self.noteId) or {}
        baseColor = QColor(note.get("color") or NOTE_COLORS[0])
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = roundedPath(rect, 14)
        painter.fillPath(path, mix(baseColor, QColor("#0B0D19"), 0.15))
        painter.fillPath(roundedPath(QRectF(rect.x(), rect.y(), rect.width(), 34), 14), withAlpha(QColor("#FFFFFF"), 0.06))
        painter.setPen(QPen(withAlpha(mix(baseColor, QColor("#FFFFFF"), 0.5), 0.6), 1))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and event.position().y() < 34:
            self.dragOffset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self.dragOffset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.dragOffset)

    def mouseReleaseEvent(self, event):
        if self.dragOffset is not None:
            self.dragOffset = None
            self._saveGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(400, self._saveGeometry)

    def _saveGeometry(self):
        if self.quiet:
            return
        geometry = self.geometry()
        self.plugin.update(self.noteId, emitList=False, geometry=[geometry.x(), geometry.y(), geometry.width(), geometry.height()])

    def closeQuietly(self):
        self.quiet = True
        try:
            self.plugin.noteUpdated.disconnect(self._onNoteUpdated)
        except (RuntimeError, TypeError):
            pass
        self.close()
        self.deleteLater()


class NotesPage(QWidget):
    noScroll = True

    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        plugin.page = self
        self.currentId = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 14)
        layout.setSpacing(4)
        listCard = Card(padding=12, hoverable=False)
        listCard.setFixedWidth(320)
        listLayout = QVBoxLayout(listCard)
        listLayout.setSpacing(8)
        topRow = QHBoxLayout()
        self.searchEdit = QLineEdit()
        self.searchEdit.setPlaceholderText(tr(TEXT["search"]))
        self.searchEdit.textChanged.connect(self.rebuildList)
        topRow.addWidget(self.searchEdit, 1)
        newButton = iconButton("plus", tr(TEXT["new"]), "accent", 18)
        newButton.clicked.connect(self.newNote)
        topRow.addWidget(newButton)
        listLayout.addLayout(topRow)
        self.listWidget = QListWidget()
        self.listWidget.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.listWidget.currentItemChanged.connect(self._onCurrentChanged)
        self.listWidget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.listWidget.customContextMenuRequested.connect(self._listMenu)
        listLayout.addWidget(self.listWidget, 1)
        layout.addWidget(listCard)
        self.editorCard = Card(padding=18, hoverable=False)
        editorLayout = QVBoxLayout(self.editorCard)
        editorLayout.setSpacing(8)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        self.titleEdit = QLineEdit()
        self.titleEdit.setPlaceholderText(tr(TEXT["titlePlaceholder"]))
        self.titleEdit.setStyleSheet("QLineEdit { font-size: 20px; font-weight: 700; background: transparent; border: none; padding: 2px; }")
        self.titleEdit.textEdited.connect(self._onTitle)
        toolbar.addWidget(self.titleEdit, 1)
        self.colorPicker = ColorSwatches(NOTE_COLORS[0], NOTE_COLORS)
        self.colorPicker.colorChanged.connect(self._onColor)
        toolbar.addWidget(self.colorPicker)
        self.pinButton = iconButton("pin", tr(TEXT["pin"]), "muted", 16, checkable=True)
        self.pinButton.clicked.connect(self._onPin)
        toolbar.addWidget(self.pinButton)
        self.stickyButton = iconButton("sticky-note", tr(TEXT["sticky"]), "muted", 16, checkable=True)
        self.stickyButton.clicked.connect(self._onSticky)
        toolbar.addWidget(self.stickyButton)
        deleteButton = iconButton("trash-2", tr(TEXT["delete"]), "danger", 16)
        deleteButton.clicked.connect(self._onDelete)
        toolbar.addWidget(deleteButton)
        editorLayout.addLayout(toolbar)
        self.bodyEdit = QPlainTextEdit()
        self.bodyEdit.setPlaceholderText(tr(TEXT["bodyPlaceholder"]))
        self.bodyEdit.setStyleSheet("QPlainTextEdit { background: transparent; border: none; padding: 2px; }")
        self.bodyEdit.textChanged.connect(self._onBody)
        editorLayout.addWidget(self.bodyEdit, 1)
        self.statusLabel = makeLabel("", "faint")
        editorLayout.addWidget(self.statusLabel)
        self.emptyState = EmptyState("notebook-pen", tr(TEXT["empty"]), tr(TEXT["selectNote"]))
        editorLayout.addWidget(self.emptyState)
        layout.addWidget(self.editorCard, 1)
        plugin.notesChanged.connect(self.rebuildList)
        plugin.noteUpdated.connect(self._onNoteUpdated)
        self.applyFont()
        self.rebuildList()
        ordered = plugin.ordered()
        self.selectNote(ordered[0]["id"] if ordered else None)

    def applyFont(self):
        font = self.bodyEdit.font()
        font.setPixelSize(int(self.plugin.setting("fontSize") or 13) + 1)
        self.bodyEdit.setFont(font)

    def rebuildList(self, *args):
        self.listWidget.blockSignals(True)
        self.listWidget.clear()
        currentRow = None
        for note in self.plugin.ordered(self.searchEdit.text()):
            body = " ".join((note.get("body") or "").split())
            preview = body[:70] + ("…" if len(body) > 70 else "")
            updated = parseDateTime(note.get("updatedAt"))
            prefix = "📌 " if note.get("pinned") else ""
            item = QListWidgetItem(f"{prefix}{noteTitle(note)}\n{preview or ' '}")
            item.setData(Qt.UserRole, note["id"])
            item.setToolTip(formatWhen(updated) if updated else "")
            item.setSizeHint(QSize(260, 56))
            self.listWidget.addItem(item)
            if note["id"] == self.currentId:
                currentRow = self.listWidget.count() - 1
        if currentRow is not None:
            self.listWidget.setCurrentRow(currentRow)
        self.listWidget.blockSignals(False)
        self.applyFont()
        if self.currentId and self.plugin.find(self.currentId) is None:
            self.selectNote(None)

    def selectNote(self, noteId):
        self.currentId = noteId
        note = self.plugin.find(noteId) if noteId else None
        for widget in (self.titleEdit, self.bodyEdit, self.colorPicker, self.pinButton, self.stickyButton, self.statusLabel):
            widget.setVisible(note is not None)
        self.emptyState.setVisible(note is None)
        if note is None:
            return
        self.titleEdit.setText(note.get("title", ""))
        self.bodyEdit.blockSignals(True)
        self.bodyEdit.setPlainText(note.get("body", ""))
        self.bodyEdit.blockSignals(False)
        self.colorPicker.setValue(note.get("color"))
        self.pinButton.setChecked(bool(note.get("pinned")))
        self.stickyButton.setChecked(bool(note.get("sticky")))
        self._refreshStatus(note)
        for row in range(self.listWidget.count()):
            if self.listWidget.item(row).data(Qt.UserRole) == noteId:
                self.listWidget.blockSignals(True)
                self.listWidget.setCurrentRow(row)
                self.listWidget.blockSignals(False)

    def _refreshStatus(self, note):
        updated = parseDateTime(note.get("updatedAt"))
        self.statusLabel.setText(f"{tr(TEXT['saved'], when=formatWhen(updated)) if updated else ''} · "
                                 f"{tr(TEXT['chars'], count=len(note.get('body', '')))}")

    def _onCurrentChanged(self, current, previous):
        if current is not None:
            self.selectNote(current.data(Qt.UserRole))

    def newNote(self):
        note = self.plugin.add()
        self.selectNote(note["id"])
        self.titleEdit.setFocus()

    def _onTitle(self, text):
        if self.currentId:
            self.plugin.update(self.currentId, title=text)

    def _onBody(self):
        if self.currentId:
            self.plugin.update(self.currentId, emitList=False, body=self.bodyEdit.toPlainText())
            note = self.plugin.find(self.currentId)
            if note:
                self._refreshStatus(note)
                self._updateListItem(note)

    def _updateListItem(self, note):
        for row in range(self.listWidget.count()):
            item = self.listWidget.item(row)
            if item.data(Qt.UserRole) == note["id"]:
                body = " ".join((note.get("body") or "").split())
                prefix = "📌 " if note.get("pinned") else ""
                item.setText(f"{prefix}{noteTitle(note)}\n{body[:70] + ('…' if len(body) > 70 else '') or ' '}")

    def _onNoteUpdated(self, noteId):
        if noteId == self.currentId:
            note = self.plugin.find(noteId)
            if note and note.get("body", "") != self.bodyEdit.toPlainText() and not self.bodyEdit.hasFocus():
                self.bodyEdit.blockSignals(True)
                self.bodyEdit.setPlainText(note.get("body", ""))
                self.bodyEdit.blockSignals(False)
            if note:
                self.stickyButton.setChecked(bool(note.get("sticky")))

    def _onColor(self, value):
        if self.currentId:
            self.plugin.update(self.currentId, color=value)

    def _onPin(self, checked):
        if self.currentId:
            self.plugin.update(self.currentId, pinned=checked)

    def _onSticky(self, checked):
        if self.currentId:
            if checked:
                self.plugin.showSticky(self.currentId)
            else:
                self.plugin.hideSticky(self.currentId)

    def _onDelete(self):
        note = self.plugin.find(self.currentId) if self.currentId else None
        if note and confirm(self, tr(TEXT["deleteTitle"]), "", [noteTitle(note)], danger=True, confirmText=tr(TEXT["delete"])):
            self.plugin.delete(note["id"])
            ordered = self.plugin.ordered()
            self.selectNote(ordered[0]["id"] if ordered else None)

    def _listMenu(self, point):
        item = self.listWidget.itemAt(point)
        if item is None:
            return
        noteId = item.data(Qt.UserRole)
        note = self.plugin.find(noteId)
        menu = QMenu(self)
        menu.addAction(tr(TEXT["unpin"] if note.get("pinned") else TEXT["pin"]),
                       lambda: self.plugin.update(noteId, pinned=not note.get("pinned")))
        menu.addAction(tr(TEXT["unsticky"] if note.get("sticky") else TEXT["sticky"]),
                       lambda: self.plugin.hideSticky(noteId) if note.get("sticky") else self.plugin.showSticky(noteId))
        menu.addSeparator()
        menu.addAction(tr(TEXT["delete"]), lambda: (self.selectNote(noteId), self._onDelete()))
        menu.exec(self.listWidget.viewport().mapToGlobal(point))


class NotesHomeWidget(QWidget):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.quickEdit = QLineEdit()
        self.quickEdit.setPlaceholderText(tr(T("Nota veloce e Invio…", "Quick note and Enter…")))
        self.quickEdit.returnPressed.connect(self._add)
        layout.addWidget(self.quickEdit)
        self.rowsLayout = QVBoxLayout()
        self.rowsLayout.setSpacing(4)
        layout.addLayout(self.rowsLayout)
        layout.addStretch(1)
        plugin.notesChanged.connect(self.refresh)
        self.refresh()

    def _add(self):
        text = self.quickEdit.text().strip()
        if text:
            self.plugin.add(body=text)
            self.quickEdit.clear()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh()

    def refresh(self):
        clearLayout(self.rowsLayout)
        capacity = max(1, (self.height() - 40) // 24)
        notes = self.plugin.ordered()[:capacity]
        if not notes:
            self.rowsLayout.addWidget(makeLabel(tr(TEXT["empty"]), "faint"))
        for note in notes:
            rowLayout = QHBoxLayout()
            rowLayout.setSpacing(8)
            dot = QWidget()
            dot.setFixedSize(8, 8)
            dot.setStyleSheet(f"background: {mix(QColor(note.get('color') or NOTE_COLORS[0]), QColor('#FFFFFF'), 0.35).name()}; border-radius: 4px;")
            rowLayout.addWidget(dot)
            rowLayout.addWidget(makeLabel(("📌 " if note.get("pinned") else "") + noteTitle(note)), 1)
            self.rowsLayout.addLayout(rowLayout)
