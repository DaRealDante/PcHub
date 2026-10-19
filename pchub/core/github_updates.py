"""Automatic updates from GitHub Releases (repo in pchub.UPDATE_REPO).

Release layout (made by .github/workflows/release.yml from a tag push):
- tag `v1.2.3`                 -> asset `PCHub-update-1.2.3.zip` (quick app update, see updater_boot.py)
                                  and, when built, `PCHub-Setup-1.2.3.exe` (full installer)
- tag `plugin-<id>-<version>`  -> asset `PCHub-plugin-<id>-<version>.zip` (one plugin, see core/plugin_updates.py)

The checker only reads public data (no login), verifies the download (size + sha256 when GitHub provides it, then the
same validation as a manual install) and drops it where the existing installers pick it up:
`updates/pending.zip` for the app, `updates/plugins/` for plugins. Nothing is applied until PC Hub restarts.
"""
import hashlib
import json
import re
import shutil
import threading
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from pchub.core.logger import getLogger
from pchub.core.paths import dataDir

log = getLogger("github_updates")
API_ROOT = "https://api.github.com"
APP_TAG = re.compile(r"^v(\d+(?:\.\d+){1,3})$")
PLUGIN_TAG = re.compile(r"^plugin-([A-Za-z_][A-Za-z0-9_]*)-(\d+(?:\.\d+){1,3})$")
META_LINE = re.compile(r"^\s*(?:<!--\s*)?(hubVersion|buildLevel)\s*:\s*([0-9.]+)", re.MULTILINE)


def releaseMeta(body):
    """The release workflow writes `hubVersion: x.y.z` / `buildLevel: n` in the notes (inside an HTML comment)."""
    return {key: value for key, value in META_LINE.findall(body or "")}


def versionTuple(text):
    parts = []
    for part in str(text or "0").split("."):
        digits = "".join(character for character in part if character.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts + [0] * (4 - len(parts)))[:4]


def parseReleases(releases):
    """GitHub releases JSON -> {"app": [...], "plugins": {id: [...]}} newest first, drafts/prereleases skipped."""
    result = {"app": [], "plugins": {}}
    for release in releases or []:
        if release.get("draft") or release.get("prerelease"):
            continue
        tag = release.get("tag_name") or ""
        assets = {asset.get("name"): asset for asset in release.get("assets") or []}
        appMatch = APP_TAG.match(tag)
        if appMatch:
            version = appMatch.group(1)
            meta = releaseMeta(release.get("body"))
            entry = {"version": version, "tag": tag, "notes": release.get("body") or "",
                     "buildLevel": int(meta.get("buildLevel") or 0),
                     "page": release.get("html_url"), "update": assets.get(f"PCHub-update-{version}.zip"),
                     "installer": assets.get(f"PCHub-Setup-{version}.exe")}
            result["app"].append(entry)
            continue
        pluginMatch = PLUGIN_TAG.match(tag)
        if pluginMatch:
            pluginId, version = pluginMatch.groups()
            asset = assets.get(f"PCHub-plugin-{pluginId}-{version}.zip")
            if asset:
                result["plugins"].setdefault(pluginId, []).append(
                    {"pluginId": pluginId, "version": version, "tag": tag, "notes": release.get("body") or "",
                     "hubVersion": releaseMeta(release.get("body")).get("hubVersion"),
                     "page": release.get("html_url"), "asset": asset})
    result["app"].sort(key=lambda entry: versionTuple(entry["version"]), reverse=True)
    for entries in result["plugins"].values():
        entries.sort(key=lambda entry: versionTuple(entry["version"]), reverse=True)
    return result


def planUpdates(parsed, hubVersion, buildLevel, pluginVersions, readZipInfo=None):
    """What to download. pluginVersions = {pluginId: installed version or None if not installed}.
    Returns {"app": entry|None, "needsInstaller": entry|None, "plugins": [entry, ...]}."""
    plan = {"app": None, "needsInstaller": None, "plugins": []}
    newestApp = next((entry for entry in parsed["app"] if versionTuple(entry["version"]) > versionTuple(hubVersion)), None)
    if newestApp is not None:
        needsBuild = newestApp.get("buildLevel", 0) > int(buildLevel)
        if newestApp.get("update") and not needsBuild:
            plan["app"] = newestApp
        else:
            plan["needsInstaller"] = newestApp
    if plan["app"] is None and plan["needsInstaller"] is None:
        for pluginId, entries in parsed["plugins"].items():
            usable = [entry for entry in entries
                      if entry.get("hubVersion") and versionTuple(entry["hubVersion"]) == versionTuple(hubVersion)]
            if not usable:
                continue
            installed = pluginVersions.get(pluginId)
            newest = usable[0]
            if installed is None or versionTuple(newest["version"]) > versionTuple(installed):
                plan["plugins"].append(newest)
    return plan


class GitHubUpdater(QObject):
    """Checks in a background thread; signals come back on the Qt thread."""
    checkFinished = Signal(dict)

    def __init__(self, repository, hubVersion, buildLevel, userAgent=None, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.hubVersion = hubVersion
        self.buildLevel = buildLevel
        self.userAgent = userAgent or f"PCHub/{hubVersion}"
        self.busy = False
        self.thread = None
        self.opener = urllib.request.urlopen

    # network ---------------------------------------------------------------------------------------
    def _request(self, url, accept="application/vnd.github+json"):
        request = urllib.request.Request(url, headers={"User-Agent": self.userAgent, "Accept": accept})
        return self.opener(request, timeout=30)

    def fetchReleases(self):
        with self._request(f"{API_ROOT}/repos/{self.repository}/releases?per_page=30") as response:
            return json.loads(response.read().decode("utf-8"))

    def download(self, asset, target):
        """Downloads a release asset, checking size and sha256 (GitHub's `digest`) when available."""
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".part")
        digest = hashlib.sha256()
        size = 0
        with self._request(asset["browser_download_url"], "application/octet-stream") as response, \
                open(partial, "wb") as handle:
            while True:
                chunk = response.read(1 << 16)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        expectedSize = asset.get("size")
        if expectedSize and size != expectedSize:
            partial.unlink(missing_ok=True)
            raise IOError(f"incomplete download ({size}/{expectedSize} bytes)")
        expectedDigest = str(asset.get("digest") or "")
        if expectedDigest.startswith("sha256:") and expectedDigest[7:].lower() != digest.hexdigest():
            partial.unlink(missing_ok=True)
            raise IOError("checksum mismatch")
        partial.replace(target)
        return target

    # check -------------------------------------------------------------------------------------------
    def check(self, pluginVersions, install=True):
        """Starts a check (and download when install=True). Result arrives in checkFinished."""
        if self.busy:
            return False
        self.busy = True
        self.thread = threading.Thread(target=self._run, args=(dict(pluginVersions), install), name="github-updates",
                                       daemon=True)
        self.thread.start()
        return True

    def _run(self, pluginVersions, install):
        result = {"status": "upToDate", "app": None, "plugins": [], "needsInstaller": None, "error": None}
        try:
            parsed = parseReleases(self.fetchReleases())
            plan = planUpdates(parsed, self.hubVersion, self.buildLevel, pluginVersions)
            result["needsInstaller"] = plan["needsInstaller"]
            if plan["needsInstaller"]:
                result["status"] = "needsInstaller"
            if plan["app"]:
                result["app"] = plan["app"]
                result["status"] = "available"
                if install:
                    self._installApp(plan["app"])
                    result["status"] = "downloaded"
            elif plan["plugins"]:
                result["plugins"] = plan["plugins"]
                result["status"] = "available"
                if install:
                    for entry in plan["plugins"]:
                        self._installPlugin(entry)
                    result["status"] = "downloaded"
        except Exception as error:
            log.warning("Update check failed: %s", error)
            result["status"] = "error"
            result["error"] = f"{type(error).__name__}: {error}"
        finally:
            self.busy = False
            self.checkFinished.emit(result)

    def _installApp(self, entry):
        import updater_boot
        downloads = Path(dataDir()) / "updates" / "downloads"
        zipPath = self.download(entry["update"], downloads / f"PCHub-update-{entry['version']}.zip")
        ok, info = updater_boot.validateZip(zipPath, self.hubVersion, self.buildLevel)
        if not ok:
            zipPath.unlink(missing_ok=True)
            if info == "needsBuild":
                raise RuntimeError("needsBuild")
            raise RuntimeError(f"invalid update: {info}")
        target = Path(dataDir()) / "updates" / "pending.zip"
        shutil.move(str(zipPath), str(target))

    def _installPlugin(self, entry):
        from pchub.core import plugin_updates
        downloads = Path(dataDir()) / "updates" / "downloads"
        zipPath = self.download(entry["asset"], downloads / entry["asset"]["name"])
        ok, info = plugin_updates.validatePluginZip(zipPath, self.hubVersion, self.buildLevel)
        if not ok:
            zipPath.unlink(missing_ok=True)
            if info == "older":
                return
            raise RuntimeError(f"invalid plugin update {entry['pluginId']}: {info}")
        plugin_updates.queueZip(zipPath)
        zipPath.unlink(missing_ok=True)
