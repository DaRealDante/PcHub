"""Builds quick-update zips (no exe rebuild needed).

  python tools/make_update.py                 -> dist/PCHub-update-<version>.zip (whole app, new PC Hub version)
  python tools/make_update.py --plugin <id>   -> dist/PCHub-plugin-<id>-<pluginVersion>.zip (one built-in plugin,
      PC Hub keeps its version). Bump `version` in the plugin class first.

Normally you don't run this by hand: pushing a tag (`v1.2.3` or `plugin-<id>-<version>`) makes the GitHub workflow
build the zip and publish it as a release, and every PC Hub downloads it by itself.
Manual install: Settings › Install update, or drop the zip in %APPDATA%\\PC Hub\\updates\\ (pending.zip for the app,
plugins\\ for a plugin).
"""
import json
import re
import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from pchub import BUILD_LEVEL, VERSION  # noqa: E402


def includeFile(filePath):
    return filePath.is_file() and "__pycache__" not in filePath.parts and filePath.suffix != ".pyc"


def pluginVersion(pluginId):
    source = (root / "pchub" / "plugins" / pluginId / "plugin.py").read_text(encoding="utf-8")
    match = re.search(r'^\s+version\s*=\s*"([^"]+)"', source, re.M)
    return match.group(1) if match else "0"


def buildAppUpdate(outputFolder):
    outputFolder = Path(outputFolder)
    outputFolder.mkdir(parents=True, exist_ok=True)
    outputPath = outputFolder / f"PCHub-update-{VERSION}.zip"
    with zipfile.ZipFile(outputPath, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("update.json", json.dumps({"version": VERSION, "buildLevel": BUILD_LEVEL}))
        for folderName in ("pchub", "assets"):
            for filePath in sorted((root / folderName).rglob("*")):
                if includeFile(filePath):
                    archive.write(filePath, filePath.relative_to(root).as_posix())
    return outputPath


def buildPluginUpdate(pluginId, outputFolder):
    outputFolder = Path(outputFolder)
    outputFolder.mkdir(parents=True, exist_ok=True)
    pluginFolder = root / "pchub" / "plugins" / pluginId
    if not (pluginFolder / "plugin.py").exists():
        raise SystemExit(f"no built-in plugin '{pluginId}'")
    version = pluginVersion(pluginId)
    outputPath = outputFolder / f"PCHub-plugin-{pluginId}-{version}.zip"
    with zipfile.ZipFile(outputPath, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("update.json", json.dumps({"kind": "plugin", "pluginId": pluginId, "version": version,
                                                    "hubVersion": VERSION, "buildLevel": BUILD_LEVEL}))
        for filePath in sorted(pluginFolder.rglob("*")):
            if includeFile(filePath):
                archive.write(filePath, f"{pluginId}/{filePath.relative_to(pluginFolder).as_posix()}")
    return outputPath


if __name__ == "__main__":
    output = root / "dist"
    if "--plugin" in sys.argv:
        print(buildPluginUpdate(sys.argv[sys.argv.index("--plugin") + 1], output))
    else:
        print(buildAppUpdate(output))
