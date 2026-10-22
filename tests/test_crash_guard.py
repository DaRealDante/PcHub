"""A native crash (no Python exception) must leave a trace and be reported on the next start."""
import json
import os
import sys
import threading
import time

from conftest import processEvents
from test_robustness import makeHub, writePlugin  # noqa: F401  (fixture)

DUMP = '''PC Hub 1.1.7 · started 2026-10-22 03:00:00 · pid 42
Windows fatal exception: code 0x800706ba

Thread 0x00001111 (most recent call first):
  File "C:\\Program Files\\PC Hub\\_internal\\pchub\\app.py", line 60 in run

Windows fatal exception: access violation

Thread 0x00002222 (most recent call first):
  File "C:\\Program Files\\PC Hub\\_internal\\pchub\\app.py", line 60 in run

Current thread 0x00003333 (most recent call first):
  File "ENGINEFILE", line 12 in process
  File "PLUGINFILE", line 30 in _loop
  File "C:\\Python\\threading.py", line 1012 in run

Thread 0x00004444 (most recent call first):
  File "C:\\Program Files\\PC Hub\\_internal\\pchub\\core\\input_hooks.py", line 230 in _run
'''

CRASHY_PLUGIN = '''
from pchub.core.plugin_api import PluginBase

class Plugin(PluginBase):
    pluginId = "crashy"
    name = {"it": "Crashone", "en": "Crashy"}
'''


def test_parse_dump_takes_the_last_error_and_the_crashed_thread():
    from pchub.core.crash_guard import parseDump
    dump = parseDump(DUMP)
    assert dump["error"] == "access violation"
    assert [frame[2] for frame in dump["frames"]] == ["process", "_loop", "run"]
    assert "input_hooks" not in "".join(frame[0] for frame in dump["frames"])
    assert parseDump("PC Hub started\n") is None


def test_session_file_tracks_clean_and_unclean_exit(dataDir):
    from pchub.core.crash_guard import CrashGuard
    guard = CrashGuard("1.0")
    assert guard.begin() is None
    data = json.loads((dataDir / "session.json").read_text())
    assert data["clean"] is False and data["pid"] == os.getpid()
    guard.end()
    assert CrashGuard("1.0").begin() is None, "a clean exit is not a crash"
    third = CrashGuard("1.0")
    previous = third.begin()
    assert previous is not None and previous["version"] == "1.0", "the previous run never called end()"
    third.end()


def test_reboot_is_not_a_crash(dataDir, monkeypatch):
    from pchub.core import crash_guard
    dataDir.mkdir(parents=True, exist_ok=True)
    (dataDir / "session.json").write_text(json.dumps({"clean": False, "aliveAt": time.time() - 3600, "version": "1"}))
    monkeypatch.setattr(crash_guard, "bootTime", lambda: time.time() - 60)
    assert crash_guard.CrashGuard("1").begin() is None


def test_thread_exception_is_logged_and_forwarded(dataDir):
    from pchub.core.crash_guard import CrashGuard
    guard = CrashGuard("1.0")
    guard.begin()
    received = []
    guard.threadErrorHandler = lambda error, tracebackObject, details: received.append((error, details))
    thread = threading.Thread(target=lambda: 1 / 0)
    thread.start()
    thread.join()
    guard.end()
    assert received and isinstance(received[0][0], ZeroDivisionError)
    assert "ZeroDivisionError" in received[0][1]


def test_previous_native_crash_is_blamed_on_the_plugin(makeHub):
    from pchub.core.paths import dataDir, logsDir, userPluginsDir
    writePlugin("crashy", CRASHY_PLUGIN)
    (dataDir() / "session.json").write_text(json.dumps({"clean": False, "aliveAt": time.time() - 30,
                                                         "version": "1.1.7", "memoryMb": 300}))
    root = userPluginsDir().resolve()
    dumpText = DUMP.replace("ENGINEFILE", str(root / "crashy" / "engine.py")).replace("PLUGINFILE", str(root / "crashy" / "plugin.py"))
    (logsDir() / "crash.log").write_text(dumpText, encoding="utf-8")
    hub = makeHub()
    processEvents(1400)
    record = hub.pluginManager.records["crashy"]
    assert "access violation" in record.problem
    assert "engine.py" in record.problemDetails
    titles = [title for title, *_ in hub.alertsShown]
    assert any("improvviso" in title or "unexpectedly" in title for title in titles)
    assert sum(1 for title in titles if "Crash" in title) == 0, "one alert, not two"
    assert (logsDir() / "crash-last.log").exists()
    crashText = (logsDir() / "crash.log").read_text(encoding="utf-8")
    assert "started" in crashText and "access violation" not in crashText


def test_unknown_crash_without_dump_is_still_reported(makeHub):
    from pchub.core.paths import dataDir
    (dataDir() / "session.json").write_text(json.dumps({"clean": False, "aliveAt": time.time() - 30, "version": "1"}))
    hub = makeHub()
    processEvents(1400)
    assert any("improvviso" in title or "unexpectedly" in title for title, *_ in hub.alertsShown)


def test_clean_shutdown_is_not_reported(makeHub):
    hub = makeHub()
    hub._shutdown()
    second = makeHub()
    processEvents(1400)
    assert not any("improvviso" in title or "unexpectedly" in title for title, *_ in second.alertsShown)
