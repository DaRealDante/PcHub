import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def makePluginZip(path, pluginId="timer", version="9.9.9", hubVersion=None, extraName=None):
    from pchub import BUILD_LEVEL, VERSION
    source = (ROOT / "pchub" / "plugins" / pluginId / "plugin.py").read_text(encoding="utf-8")
    source = source.replace('version = "1.0.0"', f'version = "{version}"', 1)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("update.json", json.dumps({"kind": "plugin", "pluginId": pluginId, "version": version,
                                                    "hubVersion": hubVersion or VERSION, "buildLevel": BUILD_LEVEL}))
        archive.writestr(f"{pluginId}/__init__.py", "")
        archive.writestr(f"{pluginId}/plugin.py", source)
        if extraName:
            archive.writestr(extraName, "x")
    return path


def runChild(dataDir, code):
    environment = dict(os.environ, PCHUB_DATA_DIR=str(dataDir), QT_QPA_PLATFORM="offscreen")
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=environment, capture_output=True, text=True,
                            timeout=60)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().splitlines()[-1]


CHILD = """
import json
from pchub import VERSION, BUILD_LEVEL
from pchub.core import plugin_updates
results = plugin_updates.prepare(VERSION, BUILD_LEVEL, {crashed})
import pchub.plugins.timer.plugin as module
print(json.dumps({{"results": results, "version": module.Plugin.version if hasattr(module, "Plugin") else None,
                  "file": module.__file__}}))
"""


def test_plugin_update_applies_without_changing_hub(tmp_path):
    pending = tmp_path / "updates" / "plugins"
    pending.mkdir(parents=True)
    makePluginZip(pending / "timer.zip")
    output = json.loads(runChild(tmp_path, CHILD.format(crashed=False)))
    assert output["results"][0]["status"] == "applied"
    assert output["version"] == "9.9.9" and "plugin-updates" in output["file"]
    output = json.loads(runChild(tmp_path, CHILD.format(crashed=False)))
    assert output["results"] == [] and output["version"] == "9.9.9", "stays active on the next start"


def test_plugin_update_rolls_back_after_crash_and_drops_when_hub_is_newer(tmp_path):
    pending = tmp_path / "updates" / "plugins"
    pending.mkdir(parents=True)
    makePluginZip(pending / "a.zip", version="2.0.0")
    runChild(tmp_path, CHILD.format(crashed=False))
    (tmp_path / "plugin-updates" / "timer.firstrun").unlink()
    makePluginZip(pending / "b.zip", version="3.0.0")
    assert json.loads(runChild(tmp_path, CHILD.format(crashed=False)))["version"] == "3.0.0"
    output = json.loads(runChild(tmp_path, CHILD.format(crashed=True)))
    assert output["results"][0]["status"] == "rolledBack" and output["version"] == "2.0.0"
    info = json.loads((tmp_path / "plugin-updates" / "timer" / "update.json").read_text())
    info["hubVersion"] = "0.0.1"
    (tmp_path / "plugin-updates" / "timer" / "update.json").write_text(json.dumps(info))
    output = json.loads(runChild(tmp_path, CHILD.format(crashed=False)))
    assert output["version"] == "1.0.0" and not (tmp_path / "plugin-updates" / "timer").exists()


def test_plugin_zip_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("PCHUB_DATA_DIR", str(tmp_path))
    from pchub import BUILD_LEVEL, VERSION
    from pchub.core import plugin_updates
    assert plugin_updates.validatePluginZip(makePluginZip(tmp_path / "ok.zip"), VERSION, BUILD_LEVEL)[0]
    assert plugin_updates.validatePluginZip(makePluginZip(tmp_path / "hub.zip", hubVersion="99.0.0"), VERSION,
                                            BUILD_LEVEL) == (False, "needsHub")
    assert plugin_updates.validatePluginZip(makePluginZip(tmp_path / "bad.zip", extraName="pchub/app.py"), VERSION,
                                            BUILD_LEVEL) == (False, "unsafe path")
    assert plugin_updates.isPluginZip(tmp_path / "ok.zip")
