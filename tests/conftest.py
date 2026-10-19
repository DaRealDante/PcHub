import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PCHUB_DATA_DIR"] = tempfile.mkdtemp(prefix="pchub-tests-")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qtApp():
    application = QApplication.instance() or QApplication(["pchub-tests"])
    from pchub.ui.fonts import loadFonts
    from pchub.ui.theme import ThemeManager, setThemeManager, themeManager
    from pchub.core.storage import JsonStore
    loadFonts()
    if themeManager() is None:
        store = JsonStore(Path(os.environ["PCHUB_DATA_DIR"]) / "theme-test.json")
        setThemeManager(ThemeManager(store))
    themeManager().apply(application)
    return application


@pytest.fixture()
def dataDir(tmp_path, monkeypatch):
    monkeypatch.setenv("PCHUB_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


def processEvents(milliseconds=50):
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()
