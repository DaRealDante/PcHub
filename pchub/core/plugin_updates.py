"""Updates for a single built-in plugin (or a brand-new built-in plugin), without changing PC Hub's version.

A plugin update zip (tools/make_update.py --plugin <id>) holds update.json
({"kind": "plugin", "pluginId", "version", "hubVersion", "buildLevel"}) and the whole plugin folder under <id>/.

- Dropped in %APPDATA%\\PC Hub\\updates\\plugins\\*.zip (or installed from Settings) it is applied at the next start.
- It lives in %APPDATA%\\PC Hub\\plugin-updates\\<id>\\ and `import pchub.plugins.<id>...` loads from there.
- It's dropped automatically when PC Hub itself gets a newer version (every hub release already contains it).
- If PC Hub crashed on the first start with a new plugin update, the previous one comes back.
"""
import importlib.abc
import importlib.util
import json
import shutil
import sys
import time
import zipfile
from pathlib import Path

from pchub.core.logger import getLogger
from pchub.core.paths import dataDir

log = getLogger("plugin_updates")


def versionTuple(text):
    parts = []
    for part in str(text or "0").split("."):
        digits = "".join(character for character in part if character.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts + [0] * (4 - len(parts)))[:4]


def updatesRoot():
    return Path(dataDir()) / "plugin-updates"


def pendingFolder():
    return Path(dataDir()) / "updates" / "plugins"


def readInfo(folder):
    try:
        return json.loads((Path(folder) / "update.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def zipInfo(zipPath):
    """update.json of any update zip, or None."""
    try:
        with zipfile.ZipFile(zipPath) as archive:
            return json.loads(archive.read("update.json").decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return None


def isPluginZip(zipPath):
    info = zipInfo(zipPath)
    return bool(info and info.get("kind") == "plugin")


def validatePluginZip(zipPath, hubVersion, buildLevel):
    """(ok, info_or_reason). Reasons: 'needsHub', 'needsBuild', 'older', 'unsafe path', other text."""
    try:
        with zipfile.ZipFile(zipPath) as archive:
            info = json.loads(archive.read("update.json").decode("utf-8"))
            pluginId = str(info.get("pluginId") or "")
            if info.get("kind") != "plugin" or not pluginId.isidentifier():
                return False, "not a plugin update"
            names = archive.namelist()
            for name in names:
                parts = name.replace("\\", "/").split("/")
                if name.startswith("/") or ".." in parts:
                    return False, "unsafe path"
                if name != "update.json" and parts[0] != pluginId:
                    return False, "unsafe path"
            if f"{pluginId}/plugin.py" not in names or f"{pluginId}/__init__.py" not in names:
                return False, "plugin.py missing"
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as error:
        return False, str(error)
    if int(info.get("buildLevel", 1)) > int(buildLevel):
        return False, "needsBuild"
    if versionTuple(info.get("hubVersion")) > versionTuple(hubVersion):
        return False, "needsHub"
    current = readInfo(updatesRoot() / pluginId)
    if current and versionTuple(current.get("version")) >= versionTuple(info.get("version")) \
            and versionTuple(current.get("hubVersion")) >= versionTuple(info.get("hubVersion")):
        return False, "older"
    return True, info


def applyZip(zipPath, info):
    root = updatesRoot()
    root.mkdir(parents=True, exist_ok=True)
    pluginId = info["pluginId"]
    staging = root / f"{pluginId}.new"
    shutil.rmtree(staging, ignore_errors=True)
    with zipfile.ZipFile(zipPath) as archive:
        archive.extractall(staging)
    extracted = staging / pluginId
    (extracted / "update.json").write_text(json.dumps(info), encoding="utf-8")
    target = root / pluginId
    previous = root / f"{pluginId}.previous"
    shutil.rmtree(previous, ignore_errors=True)
    if target.exists():
        target.rename(previous)
    extracted.rename(target)
    shutil.rmtree(staging, ignore_errors=True)
    (root / f"{pluginId}.firstrun").write_text(str(info.get("version")), encoding="utf-8")


def rollbackCrashed(results):
    """Called when the previous start never finished: undo plugin updates applied right before it."""
    root = updatesRoot()
    for marker in root.glob("*.firstrun"):
        pluginId = marker.stem
        broken = root / pluginId
        shutil.rmtree(root / f"{pluginId}.broken", ignore_errors=True)
        if broken.exists():
            broken.rename(root / f"{pluginId}.broken")
        previous = root / f"{pluginId}.previous"
        if previous.exists():
            previous.rename(broken)
        version = marker.read_text(encoding="utf-8").strip()
        marker.unlink()
        log.warning("Plugin update %s %s rolled back after a crash", pluginId, version)
        results.append({"status": "rolledBack", "pluginId": pluginId, "version": version})


def clearFirstRunMarkers():
    for marker in updatesRoot().glob("*.firstrun"):
        try:
            marker.unlink()
        except OSError:
            pass


class PluginUpdateFinder(importlib.abc.MetaPathFinder):
    """Serves `pchub.plugins.<id>` and its submodules from plugin-updates/<id>/."""

    def __init__(self, folders):
        self.folders = dict(folders)

    def find_spec(self, fullname, path=None, target=None):
        parts = fullname.split(".")
        if len(parts) < 3 or parts[0] != "pchub" or parts[1] != "plugins" or parts[2] not in self.folders:
            return None
        base = self.folders[parts[2]].joinpath(*parts[3:]) if len(parts) > 3 else self.folders[parts[2]]
        packageInit = base / "__init__.py"
        if packageInit.exists():
            return importlib.util.spec_from_file_location(fullname, packageInit, submodule_search_locations=[str(base)])
        moduleFile = base.with_suffix(".py")
        if moduleFile.exists():
            return importlib.util.spec_from_file_location(fullname, moduleFile)
        return None


_finder = None
activeUpdates = {}


def prepare(hubVersion, buildLevel, crashedLastTime=False):
    """Run before plugins are imported. Returns a list of status dicts for the UI. Never raises."""
    global _finder
    results = []
    try:
        root = updatesRoot()
        if crashedLastTime and root.exists():
            rollbackCrashed(results)
        pending = pendingFolder()
        for zipPath in sorted(pending.glob("*.zip")) if pending.exists() else []:
            ok, info = validatePluginZip(zipPath, hubVersion, buildLevel)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            if ok:
                applyZip(zipPath, info)
                destination = pending / "applied"
                results.append({"status": "applied", "pluginId": info["pluginId"], "version": info.get("version")})
            else:
                destination = pending / "rejected"
                results.append({"status": "rejected", "reason": info, "file": zipPath.name})
            destination.mkdir(parents=True, exist_ok=True)
            shutil.move(str(zipPath), str(destination / f"{zipPath.stem}-{stamp}.zip"))
        folders = {}
        for folder in sorted(root.iterdir()) if root.exists() else []:
            if not folder.is_dir() or "." in folder.name:
                continue
            info = readInfo(folder)
            if info is None:
                continue
            if versionTuple(info.get("hubVersion")) < versionTuple(hubVersion) or \
                    int(info.get("buildLevel", 1)) > int(buildLevel):
                shutil.rmtree(folder, ignore_errors=True)
                log.info("Plugin update %s %s dropped: PC Hub %s already contains it", folder.name,
                         info.get("version"), hubVersion)
                continue
            folders[folder.name] = folder
            activeUpdates[folder.name] = info.get("version")
        if _finder is not None and _finder in sys.meta_path:
            sys.meta_path.remove(_finder)
        if folders:
            _finder = PluginUpdateFinder(folders)
            sys.meta_path.insert(0, _finder)
            log.info("Plugin updates active: %s", ", ".join(f"{key} {activeUpdates[key]}" for key in folders))
    except Exception:
        log.exception("Plugin updates failed, using the built-in plugins")
    return results


def queueZip(zipPath):
    """Copies a plugin update zip to the pending folder (applied at the next start)."""
    info = zipInfo(zipPath) or {}
    folder = pendingFolder()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{info.get('pluginId', 'plugin')}-{info.get('version', 'x')}.zip"
    shutil.copyfile(zipPath, target)
    return target
