"""Quick updates without rebuilding the exe.

Runs before anything from `pchub` is imported (see main.py):
1. %APPDATA%\\PC Hub\\updates\\pending.zip (if any) is validated and extracted to ...\\app-update
2. if the previous start crashed while an update was active, that update is rolled back
3. a meta-path finder makes `import pchub...` load from app-update instead of the copy frozen in the exe

An update zip contains update.json, pchub/** and assets/** (made by tools/make_update.py). It is refused when it
needs a newer build (BUILD_LEVEL) or is older than the installed build. Never edit this file in an update: it is
part of the exe.
"""
import importlib.abc
import importlib.util
import json
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path


def dataRoot():
    override = os.environ.get("PCHUB_DATA_DIR")
    if override:
        return Path(override)
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "PC Hub"
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "pchub"


def versionTuple(text):
    parts = []
    for part in str(text or "0").split("."):
        digits = "".join(character for character in part if character.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts + [0] * (4 - len(parts)))[:4]


def builtInfo():
    """VERSION / BUILD_LEVEL of the code frozen in the exe (or of the source tree when not frozen)."""
    import pchub
    info = (getattr(pchub, "VERSION", "0"), int(getattr(pchub, "BUILD_LEVEL", 1)))
    for name in [name for name in sys.modules if name == "pchub" or name.startswith("pchub.")]:
        del sys.modules[name]
    return info


def readUpdateInfo(folder):
    try:
        return json.loads((Path(folder) / "update.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def validateZip(zipPath, builtVersion, builtLevel):
    """Returns (ok, info_or_reason)."""
    try:
        with zipfile.ZipFile(zipPath) as archive:
            names = set(archive.namelist())
            if "update.json" not in names or "pchub/__init__.py" not in names:
                return False, "not a PC Hub update"
            for name in names:
                if name.startswith("/") or ".." in name.replace("\\", "/").split("/"):
                    return False, "unsafe path"
            info = json.loads(archive.read("update.json").decode("utf-8"))
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        return False, str(error)
    if int(info.get("buildLevel", 1)) > builtLevel:
        return False, "needsBuild"
    if versionTuple(info.get("version")) <= versionTuple(builtVersion):
        return False, "older"
    return True, info


def applyPending(root, builtVersion, builtLevel, log):
    pending = root / "updates" / "pending.zip"
    if not pending.exists():
        return None
    ok, result = validateZip(pending, builtVersion, builtLevel)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if not ok:
        rejectedFolder = root / "updates" / "rejected"
        rejectedFolder.mkdir(parents=True, exist_ok=True)
        shutil.move(str(pending), str(rejectedFolder / f"{stamp}.zip"))
        log(f"update rejected: {result}")
        return {"status": "rejected", "reason": result}
    newFolder = root / "app-update.new"
    shutil.rmtree(newFolder, ignore_errors=True)
    with zipfile.ZipFile(pending) as archive:
        archive.extractall(newFolder)
    current = root / "app-update"
    previous = root / "app-update.previous"
    if current.exists():
        shutil.rmtree(previous, ignore_errors=True)
        current.rename(previous)
    newFolder.rename(current)
    appliedFolder = root / "updates" / "applied"
    appliedFolder.mkdir(parents=True, exist_ok=True)
    shutil.move(str(pending), str(appliedFolder / f"{result.get('version', 'x')}-{stamp}.zip"))
    (root / "app-update.firstrun").write_text(str(result.get("version")), encoding="utf-8")
    log(f"update applied: {result.get('version')}")
    return {"status": "applied", "version": result.get("version")}


def rollbackIfCrashed(root, log):
    """The previous start never finished (startup.lock still there) on a freshly applied update: undo it."""
    firstRun = root / "app-update.firstrun"
    current = root / "app-update"
    if not (root / "startup.lock").exists() or not firstRun.exists() or not current.exists():
        return None
    brokenVersion = firstRun.read_text(encoding="utf-8").strip()
    broken = root / "app-update.broken"
    shutil.rmtree(broken, ignore_errors=True)
    current.rename(broken)
    previous = root / "app-update.previous"
    if previous.exists():
        previous.rename(current)
    firstRun.unlink()
    log(f"update {brokenVersion} rolled back")
    return {"status": "rolledBack", "version": brokenVersion}


class OverrideFinder(importlib.abc.MetaPathFinder):
    def __init__(self, root):
        self.root = Path(root)

    def find_spec(self, fullname, path=None, target=None):
        if fullname != "pchub" and not fullname.startswith("pchub."):
            return None
        base = self.root.joinpath(*fullname.split("."))
        packageInit = base / "__init__.py"
        if packageInit.exists():
            return importlib.util.spec_from_file_location(fullname, packageInit, submodule_search_locations=[str(base)])
        moduleFile = base.with_suffix(".py")
        if moduleFile.exists():
            return importlib.util.spec_from_file_location(fullname, moduleFile)
        return None


def prepare():
    """Call once, before importing pchub. Safe: any failure falls back to the built-in code."""
    root = dataRoot()
    messages = []
    log = messages.append
    status = None
    try:
        root.mkdir(parents=True, exist_ok=True)
        builtVersion, builtLevel = builtInfo()
        frozen = getattr(sys, "frozen", False)
        if not frozen and os.environ.get("PCHUB_ALLOW_OVERRIDE") != "1":
            return None
        removeMarker = root / "app-update.remove"
        if removeMarker.exists():
            shutil.rmtree(root / "app-update", ignore_errors=True)
            removeMarker.unlink()
            log("quick update removed, back to the installed build")
        status = rollbackIfCrashed(root, log) or status
        status = applyPending(root, builtVersion, builtLevel, log) or status
        current = root / "app-update"
        info = readUpdateInfo(current) if current.exists() else None
        if info is None:
            return status
        if versionTuple(info.get("version")) <= versionTuple(builtVersion) or int(info.get("buildLevel", 1)) > builtLevel:
            shutil.rmtree(current, ignore_errors=True)
            log("stale update removed (the installed build is newer)")
            return status
        sys.meta_path.insert(0, OverrideFinder(current))
        os.environ["PCHUB_OVERRIDE_ROOT"] = str(current)
        os.environ["PCHUB_OVERRIDE_VERSION"] = str(info.get("version"))
    except Exception as error:
        log(f"updater error: {type(error).__name__}: {error}")
    finally:
        if status:
            os.environ["PCHUB_UPDATE_STATUS"] = json.dumps(status)
        if messages:
            os.environ["PCHUB_UPDATE_LOG"] = " | ".join(messages)
    return status
