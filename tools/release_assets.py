"""Builds the files of a GitHub release for a tag (used by .github/workflows/release.yml, see tools/release_plan.py).

  python tools/release_assets.py v1.2.3 dist/release            -> PCHub-update-1.2.3.zip + NOTES.md
  python tools/release_assets.py plugin-oled_saver-2.3.0 dist/release -> PCHub-plugin-oled_saver-2.3.0.zip + NOTES.md

The tag must match the code (pchub.VERSION / the plugin's `version`), so a release can never carry the wrong version.
Release notes come from the matching `## <tag>` section of CHANGELOG.md. Two hidden lines are appended
(`hubVersion`, `buildLevel`): PC Hub reads them to decide what it can install by itself.
"""
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "tools"))
from pchub import BUILD_LEVEL, VERSION  # noqa: E402
import make_update  # noqa: E402


def changelogSection(tag):
    changelog = root / "CHANGELOG.md"
    if not changelog.exists():
        return ""
    text = changelog.read_text(encoding="utf-8")
    pattern = re.compile(rf"^##\s+{re.escape(tag)}\b[^\n]*\n(.*?)(?=^##\s|\Z)", re.M | re.S)
    match = pattern.search(text)
    return match.group(1).strip() if match else ""


def main(tag, outputFolder):
    outputFolder = Path(outputFolder)
    outputFolder.mkdir(parents=True, exist_ok=True)
    appMatch = re.fullmatch(r"v(\d+(?:\.\d+){1,3})", tag)
    pluginMatch = re.fullmatch(r"plugin-([A-Za-z_][A-Za-z0-9_]*)-(\d+(?:\.\d+){1,3})", tag)
    if appMatch:
        if appMatch.group(1) != VERSION:
            raise SystemExit(f"tag {tag} but pchub.VERSION is {VERSION}")
        asset = make_update.buildAppUpdate(outputFolder)
        title = f"PC Hub {VERSION}"
    elif pluginMatch:
        pluginId, version = pluginMatch.groups()
        if make_update.pluginVersion(pluginId) != version:
            raise SystemExit(f"tag {tag} but the plugin version is {make_update.pluginVersion(pluginId)}")
        asset = make_update.buildPluginUpdate(pluginId, outputFolder)
        title = f"{pluginId} {version} (plugin)"
    else:
        raise SystemExit(f"unknown tag format: {tag}")
    notes = changelogSection(tag) or "Aggiornamento automatico / automatic update."
    notes += f"\n\n<!-- hubVersion: {VERSION} -->\n<!-- buildLevel: {BUILD_LEVEL} -->\n"
    (outputFolder / "NOTES.md").write_text(notes, encoding="utf-8")
    (outputFolder / "TITLE.txt").write_text(title, encoding="utf-8")
    print(asset)
    return asset


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "dist/release")
