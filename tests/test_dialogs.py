import os
from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDropEvent
from conftest import processEvents

SHOTS = Path(os.environ.get("PCHUB_SHOTS", "/tmp/claude-0/shots"))


def snap(widget, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    widget.grab().save(str(SHOTS / f"dialog_{name}.png"))


def test_confirm_dialog_renders_details(qtApp):
    from pchub.ui.dialogs import ConfirmDialog
    dialog = ConfirmDialog(None, "Eliminare questi file?", "Stai per liberare 2,1 GB eliminando 1.240 file da:",
                           [("File temporanei", "1.200 file · 1,9 GB · definitivo"),
                            ("Downloads vecchi", "40 file · 200 MB · nel Cestino")],
                           danger=True, confirmText="Elimina 2,1 GB", checkboxText="Non chiedere più")
    dialog.show()
    processEvents(250)
    snap(dialog, "confirm")
    assert dialog.confirmButton.text() == "Elimina 2,1 GB"
    dialog.confirmButton.click()
    from PySide6.QtWidgets import QDialog
    assert dialog.result() == QDialog.Accepted
    longDialog = ConfirmDialog(None, "Many", "", [f"item {index}" for index in range(60)])
    longDialog.show()
    processEvents(50)
    longDialog.reject()


def test_folder_dialog_validation(qtApp, tmp_path):
    from pchub.plugins.cleaner.plugin import FolderDialog
    dialog = FolderDialog(None)
    dialog.show()
    dialog.pathEdit.setText(os.path.expanduser("~"))
    assert not dialog.saveButton.isEnabled() and dialog.errorLabel.text()
    dialog.pathEdit.setText("/")
    assert not dialog.saveButton.isEnabled()
    dialog.pathEdit.setText(str(tmp_path / "nope"))
    assert not dialog.saveButton.isEnabled()
    target = tmp_path / "Downloads"
    target.mkdir()
    dialog.pathEdit.setText(str(target))
    assert dialog.saveButton.isEnabled() and not dialog.errorLabel.isVisible()
    dialog.extensionsEdit.setText(".exe, .msi")
    dialog.ageSpin.setValue(14)
    processEvents(200)
    snap(dialog, "folder")
    dialog.saveButton.click()
    assert dialog.folder["path"] == str(target) and dialog.folder["minAgeDays"] == 14
    assert dialog.folder["mode"] == "recycle", "custom folders go to the Recycle Bin by default"


def test_preview_and_icon_picker(qtApp, tmp_path):
    from pchub.plugins.cleaner.engine import ScanResult
    from pchub.plugins.cleaner.plugin import PreviewDialog
    from pchub.ui.dialogs import IconPickerDialog
    result = ScanResult("x")
    result.files = [(str(tmp_path / f"file{index}.tmp"), index * 1000) for index in range(700)]
    result.totalSize = sum(size for _, size in result.files)
    preview = PreviewDialog(None, "Temp", result)
    preview.show()
    processEvents(100)
    snap(preview, "preview")
    preview.accept()
    picker = IconPickerDialog(None, "timer")
    picker.show()
    picker.searchEdit.setText("trash")
    processEvents(100)
    visible = [name for name, button in picker.iconButtons.items() if button.isVisibleTo(picker)]
    assert visible and all("trash" in name for name in visible)
    snap(picker, "icons")
    picker.iconButtons["trash-2"].click()
    assert picker.selectedIcon == "trash-2"


def test_sidebar_drop_event_moves_item(qtApp):
    from pchub.ui.sidebar import SidebarTree, KIND_ROLE
    tree = SidebarTree()
    tree.resize(250, 400)
    tree.show()
    tree.populate([{"type": "folder", "id": "f", "name": "Folder", "children": []},
                   {"type": "plugin", "id": "a"}, {"type": "plugin", "id": "b"}], lambda value: value, lambda value: "puzzle")
    processEvents(50)
    folderItem = tree.topLevelItem(0)
    sourceItem = tree.findPluginItem("b")
    tree.dragSourceItem = sourceItem
    folderRect = tree.visualItemRect(folderItem)
    mimeData = QMimeData()
    dropEvent = QDropEvent(QPointF(folderRect.center()), Qt.MoveAction, mimeData, Qt.LeftButton, Qt.NoModifier)
    edited = []
    tree.layoutEdited.connect(lambda: edited.append(True))
    tree.dropEvent(dropEvent)
    assert edited and folderItem.child(0).text(0) == "b"
    tree.dragSourceItem = tree.findPluginItem("a")
    aboveFolder = QDropEvent(QPointF(folderRect.center().x(), folderRect.top() + 2), Qt.MoveAction, mimeData,
                             Qt.LeftButton, Qt.NoModifier)
    tree.dropEvent(aboveFolder)
    assert tree.topLevelItem(0).text(0) == "a"
    nodes = tree.serialize()
    assert nodes[0] == {"type": "plugin", "id": "a"} and nodes[1]["children"] == [{"type": "plugin", "id": "b"}]
    tree.dragSourceItem = None
    tree.close()
