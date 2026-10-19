"""Writes build/version_info.txt (Windows exe metadata) from pchub.VERSION."""
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from pchub import APP_NAME, AUTHOR, VERSION

parts = [int(part) for part in VERSION.split(".")] + [0] * 4
versionTuple = tuple(parts[:4])
content = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers={versionTuple}, prodvers={versionTuple}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041004B0', [
      StringStruct('CompanyName', '{AUTHOR}'),
      StringStruct('FileDescription', '{APP_NAME}'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', 'PCHub'),
      StringStruct('LegalCopyright', '(c) {AUTHOR}'),
      StringStruct('OriginalFilename', '{APP_NAME}.exe'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [0x0410, 1200, 0x0409, 1200])])
  ]
)
"""
(root / "build" / "version_info.txt").write_text(content, encoding="utf-8")
print(f"version_info.txt -> {VERSION}")
