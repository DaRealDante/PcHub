# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for PC Hub (one-folder build, windowed). Built by build.bat.
import os
from PyInstaller.utils.hooks import collect_submodules

root = os.path.abspath(os.path.join(SPECPATH, ".."))

hiddenImports = collect_submodules("pchub") + ["updater_boot", "pynvml", "send2trash", "psutil", "cv2", "numpy", "pycaw", "pycaw.pycaw", "comtypes", "comtypes.client"]

# Non-Python files that live next to plugin code (models, images, json...) are bundled at the same path.
pluginData = []
pluginsRoot = os.path.join(root, "pchub", "plugins")
for folderPath, folderNames, fileNames in os.walk(pluginsRoot):
    folderNames[:] = [name for name in folderNames if name != "__pycache__"]
    for fileName in fileNames:
        if not fileName.endswith((".py", ".pyc")):
            relativeFolder = os.path.relpath(folderPath, root)
            pluginData.append((os.path.join(folderPath, fileName), relativeFolder))

analysis = Analysis(
    [os.path.join(root, "main.py")],
    pathex=[root],
    binaries=[],
    datas=[(os.path.join(root, "assets"), "assets")] + pluginData,
    hiddenimports=hiddenImports,
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
              "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQml",
              "PySide6.QtMultimedia", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtPdf",
              "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSensors"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="PC Hub",
    icon=os.path.join(root, "assets", "app.ico"),
    version=os.path.join(SPECPATH, "version_info.txt"),
    console=False,
    disable_windowed_traceback=False,
    uac_admin=False,
    upx=False,
)
coll = COLLECT(exe, analysis.binaries, analysis.datas, name="PC Hub", upx=False)
