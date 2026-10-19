import os
import time

from conftest import processEvents

from pchub.plugins.cleaner import engine


def makeFile(path, ageDays=0, size=10):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    timestamp = time.time() - ageDays * 86400
    os.utime(path, (timestamp, timestamp))
    return path


def test_scan_respects_age_extensions_and_subfolders(tmp_path):
    root = tmp_path / "Downloads"
    makeFile(root / "old.log", 40, 100)
    makeFile(root / "new.log", 1, 100)
    makeFile(root / "old.zip", 40, 200)
    makeFile(root / "keep.docx", 40, 300)
    makeFile(root / "sub" / "deep.log", 50, 50)
    result = engine.scanFolder(str(root), 30 * 86400, ".log, zip", None, True)
    names = sorted(os.path.basename(path) for path, _ in result.files)
    assert names == ["deep.log", "old.log", "old.zip"]
    assert result.totalSize == 350
    noSub = engine.scanFolder(str(root), 30 * 86400, "log", None, False)
    assert sorted(os.path.basename(path) for path, _ in noSub.files) == ["old.log"]
    excluded = engine.scanFolder(str(root), 0, None, "docx;.zip", True)
    assert "keep.docx" not in [os.path.basename(path) for path, _ in excluded.files]
    assert "old.zip" not in [os.path.basename(path) for path, _ in excluded.files]


def test_scan_never_follows_symlinks(tmp_path):
    outside = tmp_path / "precious"
    makeFile(outside / "important.txt", 100)
    root = tmp_path / "cache"
    makeFile(root / "junk.tmp", 100)
    os.symlink(outside, root / "link")
    os.symlink(outside / "important.txt", root / "filelink.txt")
    result = engine.scanFolder(str(root), 0)
    assert [os.path.basename(path) for path, _ in result.files] == ["junk.tmp"]


def test_delete_permanent_and_recycle(tmp_path):
    root = tmp_path / "target"
    first = makeFile(root / "a.tmp", 10, 5)
    second = makeFile(root / "nested" / "b.tmp", 10, 7)
    result = engine.scanFolder(str(root), 0)
    deleted, freed, failed = engine.deleteFiles(result.files, "permanent")
    assert (deleted, freed, failed) == (2, 12, 0)
    assert not first.exists() and not second.exists()
    engine.removeEmptyDirectories(result.directories, result.roots)
    assert root.exists(), "the root folder itself is never removed"
    assert not (root / "nested").exists()
    trashed = []
    third = makeFile(root / "c.tmp", 10, 3)
    deleted, freed, failed = engine.deleteFiles([(str(third), 3)], "recycle",
                                                sendToTrash=lambda paths: trashed.extend(paths if isinstance(paths, list) else [paths]))
    assert deleted == 1 and trashed == [str(third)]


def test_cancel_stops_deletion(tmp_path):
    import threading
    root = tmp_path / "many"
    files = [makeFile(root / f"{index}.tmp", 1, 1) for index in range(20)]
    cancelEvent = threading.Event()
    cancelEvent.set()
    deleted, _, _ = engine.deleteFiles([(str(path), 1) for path in files], "permanent", cancelEvent)
    assert deleted == 0 and all(path.exists() for path in files)


def test_dangerous_paths(tmp_path, monkeypatch):
    home = os.path.expanduser("~")
    assert engine.isDangerousPath("") == "empty"
    assert engine.isDangerousPath("relative/path") == "relative"
    assert engine.isDangerousPath("/") == "root"
    assert engine.isDangerousPath(home) == "protected"
    assert engine.isDangerousPath("/usr/lib") == "system"
    assert engine.isDangerousPath(str(tmp_path / "Downloads")) is None
    from pchub.core.paths import dataDir
    assert engine.isDangerousPath(str(dataDir())) == "system"


def test_extension_normalization():
    assert engine.normalizeExtensions("log, .TMP;*.zip  bak") == [".log", ".tmp", ".zip", ".bak"]
    assert engine.normalizeExtensions("") == []


def test_cleaner_plugin_full_flow(qtApp, dataDir, tmp_path):
    from pchub.core.active_registry import ActiveRegistry
    from pchub.core.events import EventBus
    from pchub.core.hotkeys import HotkeyManager
    from pchub.core.plugin_manager import PluginManager
    from pchub.core.storage import JsonStore
    appStore = JsonStore(dataDir / "app.json")
    manager = PluginManager(appStore, ActiveRegistry(), EventBus(), HotkeyManager(), lambda: False)
    confirmations = []
    notifications = []
    manager.confirmHandler = lambda *args: confirmations.append(args) or True
    manager.notifyHandler = lambda title, message="", sound=None: notifications.append((title, message))
    manager.discover(includeUser=False)
    manager.instantiateAll()
    manager.startAll()
    cleaner = manager.records["cleaner"].instance
    for target in cleaner.targets:
        cleaner.setTargetEnabled(target.targetId, False)
    folder = tmp_path / "Downloads"
    oldFile = makeFile(folder / "setup_old.exe", 60, 1000)
    newFile = makeFile(folder / "fresh.exe", 1, 1000)
    cleaner.saveFolder({"name": "Downloads", "path": str(folder), "minAgeDays": 30, "mode": "permanent",
                        "enabled": True, "includeSubfolders": True})
    cleaner.requestClean()
    for _ in range(60):
        processEvents(50)
        if not cleaner.busy and cleaner.history():
            break
    assert confirmations, "cleaning always asks first"
    title, message, details, danger = confirmations[0][:4]
    assert danger and details and "Downloads" in details[0][0]
    assert not oldFile.exists() and newFile.exists()
    assert cleaner.history()[0]["deleted"] == 1 and cleaner.history()[0]["freed"] == 1000
    assert manager.activeRegistry.count() == 0
    confirmations.clear()
    manager.confirmHandler = lambda *args: confirmations.append(args) and False
    victim = makeFile(folder / "victim.exe", 90, 10)
    cleaner.requestClean()
    for _ in range(40):
        processEvents(50)
        if not cleaner.busy:
            break
    assert confirmations and victim.exists(), "declining the confirmation deletes nothing"
    dangerous = {"name": "Home", "path": os.path.expanduser("~"), "enabled": True}
    cleaner.saveFolder(dangerous)
    assert all(job["name"] != "Home" for job in cleaner.buildJobs()), "dangerous folders are never cleaned"
    manager.stopAll()
