import os
import sys
from pathlib import Path

isWindows = os.name == "nt"


def isFrozen():
    return getattr(sys, "frozen", False)


def resourceRoot() -> Path:
    if isFrozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def overrideRoot():
    """Folder of the active quick update (see updater_boot.py), or None."""
    value = os.environ.get("PCHUB_OVERRIDE_ROOT")
    return Path(value) if value else None


def assetsDir() -> Path:
    override = overrideRoot()
    if override is not None and (override / "assets").exists():
        return override / "assets"
    return resourceRoot() / "assets"


def dataDir() -> Path:
    overridePath = os.environ.get("PCHUB_DATA_DIR")
    if overridePath:
        basePath = Path(overridePath)
    elif isWindows:
        basePath = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "PC Hub"
    else:
        basePath = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "pchub"
    basePath.mkdir(parents=True, exist_ok=True)
    return basePath


def userPluginsDir() -> Path:
    pluginsPath = dataDir() / "plugins"
    pluginsPath.mkdir(parents=True, exist_ok=True)
    return pluginsPath


def pluginDataDir(pluginId: str) -> Path:
    folderPath = dataDir() / "plugin-data" / pluginId
    folderPath.mkdir(parents=True, exist_ok=True)
    return folderPath


def pluginSettingsFile(pluginId: str) -> Path:
    folderPath = dataDir() / "plugin-settings"
    folderPath.mkdir(parents=True, exist_ok=True)
    return folderPath / f"{pluginId}.json"


def logsDir() -> Path:
    folderPath = dataDir() / "logs"
    folderPath.mkdir(parents=True, exist_ok=True)
    return folderPath


def executableCommand(extraArgs=None):
    extraArgs = list(extraArgs or [])
    if isFrozen():
        return sys.executable, extraArgs
    return sys.executable, [str(resourceRoot() / "main.py")] + extraArgs
