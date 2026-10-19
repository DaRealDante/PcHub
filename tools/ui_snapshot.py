"""Dev tool: boots PC Hub offscreen with a temp data dir and saves screenshots of every page.
Usage: python tools/ui_snapshot.py <outDir> [glass|clay]"""
import faulthandler
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
faulthandler.dump_traceback_later(int(os.environ.get("PCHUB_SNAP_TIMEOUT", "0")) or 10**6, exit=True)
outDir = Path(sys.argv[1] if len(sys.argv) > 1 else "snapshots")
style = sys.argv[2] if len(sys.argv) > 2 else "glass"
outDir.mkdir(parents=True, exist_ok=True)
os.environ["PCHUB_DATA_DIR"] = tempfile.mkdtemp(prefix="pchub-snap-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
Path(os.environ["PCHUB_DATA_DIR"], "app.json").write_text(json.dumps({"appearance": {"style": style}, "general": {"userName": "Ken", "language": os.environ.get("PCHUB_LANG", "it")}}))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

qtApp = QApplication(sys.argv)
from pchub.app import PCHubApp

hub = PCHubApp(["pchub", "--no-splash", "--no-user-plugins"])
steps = []


def grab(name):
    window = hub.mainWindow
    window.grab().save(str(outDir / f"{style}_{name}.png"))


def scenario():
    window = hub.mainWindow
    window.resize(1360, 860)
    timerPlugin = hub.pluginManager.records["timer"].instance
    timerPlugin.addTimer(300, "Pasta")
    timerPlugin.addTimer(1500, "Focus")
    timerPlugin.addStopwatch("Sessione")
    timerPlugin.pauseTimer(timerPlugin.timers[1]["id"])
    hub.pinService.setPinned("timer:quickStart", True)
    hub.pinService.setPinned("system_monitor:@enabled", True)
    hub.pinService.setPinned("timer:quickMinutes", True)
    macrosRecord = hub.pluginManager.records.get("macros")
    if macrosRecord is not None and macrosRecord.instance is not None:
        from pchub.plugins.macros import logic as macroLogic
        macros = macrosRecord.instance
        combo = macros.add("steps", name="Farm Roblox", trigger={"device": "key", "code": 0x70, "mods": []},
                           scope="apps", apps=["robloxplayerbeta.exe"], mode="toggle", loopDelay=200)
        steps = [dict(macroLogic.newStep("key"), vk=0x45), dict(macroLogic.newStep("wait"), ms=350, randomMs=50),
                 dict(macroLogic.newStep("click"), x=960, y=540, atPosition=True),
                 dict(macroLogic.newStep("text"), text="gg"), dict(macroLogic.newStep("key"), vk=0x43, mods=["ctrl"])]
        macros.setSteps(combo["id"], steps)
        macros.add("clicker", name="Autoclicker", trigger={"device": "mouse", "code": "x2", "mods": []})
        macros.add("steps", name="Firma email", trigger={"device": "key", "code": 0x46, "mods": ["ctrl", "alt"]})
    pages = list(window.pages)
    onlyPages = os.environ.get("PCHUB_SNAP_PAGES")
    if onlyPages:
        pages = [page for page in pages if any(part in page for part in onlyPages.split(","))]

    def showNext(index=0):
        if index >= len(pages):
            QTimer.singleShot(100, qtApp.quit)
            return
        window.showPage(pages[index], animated=False)
        QTimer.singleShot(1300, lambda: (grab(pages[index].replace(":", "_")), showNext(index + 1)))

    QTimer.singleShot(1500, showNext)


QTimer.singleShot(0, scenario)
code = hub.run()
print("exit", code)
