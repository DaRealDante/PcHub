from PySide6.QtGui import QFontDatabase

from pchub.core.logger import getLogger
from pchub.core.paths import assetsDir

log = getLogger("fonts")
_loaded = False


def loadFonts():
    global _loaded
    if _loaded:
        return
    _loaded = True
    fontsFolder = assetsDir() / "fonts"
    if not fontsFolder.exists():
        return
    for fontPath in sorted(fontsFolder.iterdir()):
        if fontPath.suffix.lower() in (".ttf", ".otf"):
            if QFontDatabase.addApplicationFont(str(fontPath)) < 0:
                log.warning("Font failed to load: %s", fontPath.name)
