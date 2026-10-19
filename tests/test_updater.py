"""Quick updates: run main-like boot in a subprocess (the import machinery must start clean)."""
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROBE = r'''
import json, os, sys
sys.path.insert(0, {root!r})
import updater_boot
status = updater_boot.prepare()
import pchub, pchub.core.paths as paths
print(json.dumps({{"version": pchub.VERSION, "file": pchub.__file__, "assets": str(paths.assetsDir()),
                   "status": status, "log": os.environ.get("PCHUB_UPDATE_LOG")}}))
'''


def makeUpdateZip(path, version, buildLevel=2, marker="X", broken=False):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("update.json", json.dumps({"version": version, "buildLevel": buildLevel}))
        source = (ROOT / "pchub" / "__init__.py").read_text(encoding="utf-8")
        source = source.replace('VERSION = "', f'MARKER = "{marker}"\nVERSION = "{version}"  # was "', 1)
        if broken:
            source += "\nraise SystemExit('broken update')\n"
        archive.writestr("pchub/__init__.py", source)
        for filePath in (ROOT / "pchub").rglob("*.py"):
            relative = filePath.relative_to(ROOT).as_posix()
            if relative != "pchub/__init__.py" and "__pycache__" not in relative:
                archive.write(filePath, relative)
        archive.writestr("assets/marker.txt", marker)


def runProbe(dataDir):
    environment = dict(os.environ, PCHUB_DATA_DIR=str(dataDir), PCHUB_ALLOW_OVERRIDE="1")
    environment.pop("PCHUB_OVERRIDE_ROOT", None)
    completed = subprocess.run([sys.executable, "-c", PROBE.format(root=str(ROOT))], capture_output=True, text=True,
                               env=environment, timeout=60)
    if completed.returncode != 0:
        return {"error": completed.stderr[-2000:], "returncode": completed.returncode}
    return json.loads(completed.stdout.strip().splitlines()[-1])


def builtVersion():
    namespace = {}
    exec((ROOT / "pchub" / "__init__.py").read_text(encoding="utf-8"), namespace)
    return namespace["VERSION"]


def bump(version, minor=1):
    parts = [int(part) for part in version.split(".")]
    parts[-1] += minor
    return ".".join(str(part) for part in parts)


def test_no_update_uses_builtin(tmp_path):
    result = runProbe(tmp_path)
    assert result["version"] == builtVersion() and "app-update" not in result["file"]


def test_pending_update_applied_and_used(tmp_path):
    newVersion = bump(builtVersion())
    (tmp_path / "updates").mkdir()
    makeUpdateZip(tmp_path / "updates" / "pending.zip", newVersion)
    result = runProbe(tmp_path)
    assert result["status"] == {"status": "applied", "version": newVersion}
    assert result["version"] == newVersion and "app-update" in result["file"]
    assert result["assets"].endswith(os.path.join("app-update", "assets"))
    assert not (tmp_path / "updates" / "pending.zip").exists()
    again = runProbe(tmp_path)
    assert again["version"] == newVersion and again["status"] is None, "the update stays active on later starts"


def test_update_needing_new_build_or_older_is_rejected(tmp_path):
    (tmp_path / "updates").mkdir()
    makeUpdateZip(tmp_path / "updates" / "pending.zip", bump(builtVersion()), buildLevel=99)
    result = runProbe(tmp_path)
    assert result["status"]["status"] == "rejected" and result["status"]["reason"] == "needsBuild"
    assert result["version"] == builtVersion()
    makeUpdateZip(tmp_path / "updates" / "pending.zip", "0.0.1")
    assert runProbe(tmp_path)["status"]["reason"] == "older"


def test_crashed_update_is_rolled_back(tmp_path):
    goodVersion = bump(builtVersion())
    badVersion = bump(builtVersion(), 2)
    (tmp_path / "updates").mkdir()
    makeUpdateZip(tmp_path / "updates" / "pending.zip", goodVersion)
    runProbe(tmp_path)
    (tmp_path / "app-update.firstrun").unlink()
    makeUpdateZip(tmp_path / "updates" / "pending.zip", badVersion, broken=True)
    crashed = runProbe(tmp_path)
    assert "error" in crashed, "the broken update crashes at import"
    (tmp_path / "startup.lock").write_text("x")
    result = runProbe(tmp_path)
    assert result["status"] == {"status": "rolledBack", "version": badVersion}
    assert result["version"] == goodVersion, "back to the previous quick update"


def test_remove_marker_goes_back_to_builtin(tmp_path):
    (tmp_path / "updates").mkdir()
    makeUpdateZip(tmp_path / "updates" / "pending.zip", bump(builtVersion()))
    runProbe(tmp_path)
    (tmp_path / "app-update.remove").write_text("1")
    result = runProbe(tmp_path)
    assert result["version"] == builtVersion() and not (tmp_path / "app-update").exists()


def test_zip_with_unsafe_paths_is_rejected(tmp_path):
    import updater_boot
    unsafe = tmp_path / "evil.zip"
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("update.json", json.dumps({"version": "99.0.0", "buildLevel": 1}))
        archive.writestr("pchub/__init__.py", "")
        archive.writestr("../outside.py", "x")
    ok, reason = updater_boot.validateZip(unsafe, "1.0.0", 2)
    assert not ok and reason == "unsafe path"
