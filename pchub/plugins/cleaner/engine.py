"""Cleaner engine: pure Python, no UI. Scans and deletes safely.

Safety rules:
- never follows symlinks / junctions (reparse points)
- builtin targets only delete *inside* their folder, never the folder itself
- custom folders are rejected if they are system / profile roots (isDangerousPath)
- files in use are skipped and counted, never forced
"""
import glob
import os
import stat
import sys
import tempfile
import time
from pathlib import Path

from pchub.core.i18n import T
from pchub.core.paths import dataDir, isWindows, resourceRoot

FILE_ATTRIBUTE_REPARSE_POINT = 0x400
DAY_SECONDS = 86400


class CleanTarget:
    def __init__(self, targetId, name, description, icon, patterns, requiresAdmin=False, kind="folder",
                 defaultEnabled=True, warning=None, ageSensitive=False, filePatterns=False):
        self.targetId = targetId
        self.name = name
        self.description = description
        self.icon = icon
        self.patterns = patterns
        self.requiresAdmin = requiresAdmin
        self.kind = kind
        self.defaultEnabled = defaultEnabled
        self.warning = warning
        self.ageSensitive = ageSensitive
        self.filePatterns = filePatterns

    def resolvePaths(self):
        resolved = []
        for pattern in self.patterns:
            expanded = os.path.expandvars(os.path.expanduser(pattern))
            if "%" in expanded:
                continue
            for match in glob.glob(expanded):
                if os.path.isdir(match) or (self.filePatterns and os.path.isfile(match)):
                    resolved.append(os.path.normpath(match))
        return sorted(set(resolved))


def builtinTargets():
    if not isWindows:
        return [
            CleanTarget("thumbnails", T("Miniature", "Thumbnails"), T("Cache delle anteprime.", "Preview cache."),
                        "file", ["~/.cache/thumbnails"], defaultEnabled=True),
        ]
    localAppData = "%LOCALAPPDATA%"
    chromiumProfiles = {
        "Chrome": rf"{localAppData}\Google\Chrome\User Data",
        "Edge": rf"{localAppData}\Microsoft\Edge\User Data",
        "Brave": rf"{localAppData}\BraveSoftware\Brave-Browser\User Data",
        "Opera": r"%APPDATA%\Opera Software\Opera Stable",
        "Opera GX": r"%APPDATA%\Opera Software\Opera GX Stable",
    }
    browserPatterns = []
    for root in chromiumProfiles.values():
        for profileGlob in (r"\*", ""):
            for cacheName in (r"Cache\Cache_Data", "Code Cache", "GPUCache"):
                browserPatterns.append(rf"{root}{profileGlob}\{cacheName}")
    browserPatterns.append(rf"{localAppData}\Mozilla\Firefox\Profiles\*\cache2")
    return [
        CleanTarget("userTemp", T("File temporanei", "Temporary files"),
                    T("La cartella Temp del tuo utente. Si riempie di installer e file lasciati dai programmi.",
                      "Your user Temp folder. It fills up with installers and files left by programs."),
                    "file", [r"%TEMP%"], ageSensitive=True),
        CleanTarget("windowsTemp", T("Temp di Windows", "Windows Temp"),
                    T("I file temporanei di sistema.", "System temporary files."), "monitor", [r"%SystemRoot%\Temp"],
                    requiresAdmin=True, ageSensitive=True),
        CleanTarget("crashDumps", T("Report di errore e crash", "Error reports and crash dumps"),
                    T("Dump e report generati quando un programma si blocca.", "Dumps and reports created when a program crashes."),
                    "triangle-alert", [rf"{localAppData}\CrashDumps", rf"{localAppData}\Microsoft\Windows\WER\ReportArchive",
                                       rf"{localAppData}\Microsoft\Windows\WER\ReportQueue",
                                       r"%ProgramData%\Microsoft\Windows\WER\ReportArchive",
                                       r"%ProgramData%\Microsoft\Windows\WER\ReportQueue"]),
        CleanTarget("directxCache", T("Cache shader DirectX", "DirectX shader cache"),
                    T("Viene ricreata in automatico.", "It's rebuilt automatically."), "layers", [rf"{localAppData}\D3DSCache"]),
        CleanTarget("gpuCache", T("Cache shader GPU (NVIDIA/AMD)", "GPU shader cache (NVIDIA/AMD)"),
                    T("Dopo la pulizia i giochi possono scattare un po' finché gli shader vengono ricompilati.",
                      "Games may stutter a bit afterwards while shaders are recompiled."),
                    "monitor", [rf"{localAppData}\NVIDIA\DXCache", rf"{localAppData}\NVIDIA\GLCache",
                                rf"{localAppData}\AMD\DxCache", rf"{localAppData}\AMD\GLCache"],
                    defaultEnabled=False, warning=T("Ricompilazione shader", "Shader rebuild")),
        CleanTarget("browserCache", T("Cache dei browser", "Browser cache"),
                    T("Chrome, Edge, Brave, Opera e Firefox. Chiudi i browser per pulire di più.",
                      "Chrome, Edge, Brave, Opera and Firefox. Close the browsers to clean more."),
                    "globe", browserPatterns, defaultEnabled=False, warning=T("Chiudi i browser", "Close browsers")),
        CleanTarget("discordCache", T("Cache di Discord", "Discord cache"),
                    T("Immagini e file in cache di Discord.", "Discord's cached images and files."), "users",
                    [r"%APPDATA%\discord\Cache\Cache_Data", r"%APPDATA%\discord\Code Cache", r"%APPDATA%\discord\GPUCache"],
                    defaultEnabled=False),
        CleanTarget("robloxLogs", T("Log di Roblox e Studio", "Roblox & Studio logs"),
                    T("I log che Roblox e Roblox Studio accumulano a ogni avvio.", "Logs Roblox and Roblox Studio pile up on every launch."),
                    "gamepad-2", [rf"{localAppData}\Roblox\logs"], ageSensitive=True),
        CleanTarget("thumbnails", T("Cache miniature di Esplora file", "File Explorer thumbnail cache"),
                    T("Le anteprime vengono rigenerate. Alcuni file restano bloccati finché Esplora è aperto.",
                      "Previews are regenerated. Some files stay locked while Explorer is open."),
                    "file", [rf"{localAppData}\Microsoft\Windows\Explorer\thumbcache_*.db",
                             rf"{localAppData}\Microsoft\Windows\Explorer\iconcache_*.db"],
                    defaultEnabled=False, filePatterns=True),
        CleanTarget("windowsUpdate", T("Download di Windows Update", "Windows Update downloads"),
                    T("Pacchetti di aggiornamento già installati.", "Update packages already installed."), "download",
                    [r"%SystemRoot%\SoftwareDistribution\Download"], requiresAdmin=True, defaultEnabled=False),
        CleanTarget("recycleBin", T("Cestino", "Recycle Bin"),
                    T("Svuota il Cestino di tutte le unità.", "Empties the Recycle Bin on every drive."), "trash-2", [],
                    kind="recycleBin", defaultEnabled=False, warning=T("Definitivo", "Permanent")),
    ]


def _protectedPaths():
    exactPaths = set()
    prefixPaths = set()
    environment = os.environ
    if isWindows:
        for variable in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "ProgramData", "PUBLIC", "HOMEDRIVE", "SystemDrive"):
            if environment.get(variable):
                exactPaths.add(environment[variable])
        profile = environment.get("USERPROFILE")
        if profile:
            for folderName in ("AppData", r"AppData\LocalLow", "Documents", "Desktop", "OneDrive"):
                exactPaths.add(os.path.join(profile, folderName))
            exactPaths.add(os.path.dirname(profile))
        for variable in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "CommonProgramFiles"):
            if environment.get(variable):
                prefixPaths.add(environment[variable])
        if environment.get("ProgramData"):
            prefixPaths.add(os.path.join(environment["ProgramData"], "Microsoft"))
        systemDrive = environment.get("SystemDrive", "C:") + "\\"
        for folderName in ("System Volume Information", "$Recycle.Bin", "Recovery", "Boot", "EFI"):
            prefixPaths.add(os.path.join(systemDrive, folderName))
    else:
        home = os.path.expanduser("~")
        exactPaths.update({home, os.path.dirname(home), os.path.join(home, ".config"), os.path.join(home, ".local")})
        prefixPaths.update({"/usr", "/bin", "/sbin", "/etc", "/boot", "/lib", "/lib64", "/proc", "/sys", "/dev",
                            "/var/lib", "/opt"})
    prefixPaths.add(str(dataDir()))
    prefixPaths.add(str(resourceRoot()))
    if getattr(sys, "frozen", False):
        prefixPaths.add(os.path.dirname(sys.executable))
    return exactPaths, prefixPaths


def _normalize(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(path))).rstrip("\\/") or os.sep


def isDangerousPath(path):
    """Returns a reason code if `path` must not be used as a custom cleaning folder, else None."""
    if not path or not str(path).strip():
        return "empty"
    path = str(path).strip()
    if not os.path.isabs(path):
        return "relative"
    normalized = _normalize(path)
    parentPath = os.path.dirname(normalized)
    if parentPath == normalized or normalized in ("/", "") or (len(normalized) <= 3 and normalized[1:2] == ":"):
        return "root"
    exactPaths, prefixPaths = _protectedPaths()
    for exactPath in exactPaths:
        if normalized == _normalize(exactPath):
            return "protected"
    for prefixPath in prefixPaths:
        prefixNormalized = _normalize(prefixPath)
        if normalized == prefixNormalized or normalized.startswith(prefixNormalized + os.sep):
            return "system"
    return None


def _isReparsePoint(entry):
    try:
        if entry.is_symlink():
            return True
        if isWindows:
            attributes = entry.stat(follow_symlinks=False).st_file_attributes
            return bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return True
    return False


def _timestamp(fileStat, dateField):
    if dateField == "created":
        return getattr(fileStat, "st_birthtime", None) or fileStat.st_ctime
    if dateField == "accessed":
        return fileStat.st_atime
    return fileStat.st_mtime


def normalizeExtensions(text):
    if not text:
        return []
    if isinstance(text, (list, tuple)):
        parts = text
    else:
        parts = str(text).replace(";", ",").replace(" ", ",").split(",")
    extensions = []
    for part in parts:
        part = part.strip().lower()
        if not part:
            continue
        if part.startswith("*."):
            part = part[1:]
        if not part.startswith("."):
            part = "." + part
        extensions.append(part)
    return extensions


class ScanResult:
    def __init__(self, targetId):
        self.targetId = targetId
        self.files = []
        self.directories = []
        self.totalSize = 0
        self.skipped = 0
        self.roots = []

    @property
    def count(self):
        return len(self.files)


def scanFolder(root, minAgeSeconds=0, extensions=None, excludeExtensions=None, includeSubfolders=True,
               dateField="modified", now=None, cancelEvent=None, result=None):
    """Collects files to delete under root (root itself is never included)."""
    now = time.time() if now is None else now
    result = result or ScanResult(None)
    extensions = normalizeExtensions(extensions)
    excludeExtensions = normalizeExtensions(excludeExtensions)
    rootPath = os.path.normpath(root)
    result.roots.append(rootPath)
    stack = [rootPath]
    while stack:
        if cancelEvent is not None and cancelEvent.is_set():
            break
        currentFolder = stack.pop()
        try:
            entries = list(os.scandir(currentFolder))
        except OSError:
            result.skipped += 1
            continue
        for entry in entries:
            if _isReparsePoint(entry):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    if includeSubfolders:
                        stack.append(entry.path)
                        result.directories.append(entry.path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                fileStat = entry.stat(follow_symlinks=False)
            except OSError:
                result.skipped += 1
                continue
            lowerName = entry.name.lower()
            if extensions and not any(lowerName.endswith(extension) for extension in extensions):
                continue
            if excludeExtensions and any(lowerName.endswith(extension) for extension in excludeExtensions):
                continue
            if minAgeSeconds > 0 and now - _timestamp(fileStat, dateField) < minAgeSeconds:
                continue
            result.files.append((entry.path, fileStat.st_size))
            result.totalSize += fileStat.st_size
    return result


def scanFiles(paths, minAgeSeconds=0, now=None, result=None):
    now = time.time() if now is None else now
    result = result or ScanResult(None)
    for filePath in paths:
        try:
            fileStat = os.stat(filePath, follow_symlinks=False)
        except OSError:
            continue
        if minAgeSeconds > 0 and now - fileStat.st_mtime < minAgeSeconds:
            continue
        result.files.append((filePath, fileStat.st_size))
        result.totalSize += fileStat.st_size
    return result


def _removeFile(filePath):
    try:
        os.remove(filePath)
        return True
    except PermissionError:
        try:
            os.chmod(filePath, stat.S_IWRITE)
            os.remove(filePath)
            return True
        except OSError:
            return False
    except FileNotFoundError:
        return True
    except OSError:
        return False


def deleteFiles(files, mode="permanent", cancelEvent=None, progressCallback=None, sendToTrash=None):
    """Returns (deletedCount, freedBytes, failedCount)."""
    deletedCount = 0
    freedBytes = 0
    failedCount = 0
    total = len(files)
    if mode == "recycle":
        if sendToTrash is None:
            from send2trash import send2trash as sendToTrash
        batchSize = 64
        for start in range(0, total, batchSize):
            if cancelEvent is not None and cancelEvent.is_set():
                break
            batch = files[start:start + batchSize]
            existing = [(path, size) for path, size in batch if os.path.lexists(path)]
            try:
                if existing:
                    sendToTrash([path for path, _ in existing])
                deletedCount += len(existing)
                freedBytes += sum(size for _, size in existing)
            except Exception:
                for path, size in existing:
                    try:
                        sendToTrash(path)
                        deletedCount += 1
                        freedBytes += size
                    except Exception:
                        failedCount += 1
            if progressCallback:
                progressCallback(min(total, start + batchSize), total)
        return deletedCount, freedBytes, failedCount
    for index, (path, size) in enumerate(files):
        if cancelEvent is not None and cancelEvent.is_set():
            break
        if _removeFile(path):
            deletedCount += 1
            freedBytes += size
        else:
            failedCount += 1
        if progressCallback and (index % 50 == 0 or index == total - 1):
            progressCallback(index + 1, total)
    return deletedCount, freedBytes, failedCount


def removeEmptyDirectories(directories, roots):
    """Removes now-empty folders (deepest first). Never removes a root."""
    protectedRoots = {os.path.normcase(os.path.normpath(root)) for root in roots}
    removedCount = 0
    for directory in sorted(set(directories), key=lambda path: path.count(os.sep), reverse=True):
        if os.path.normcase(os.path.normpath(directory)) in protectedRoots:
            continue
        try:
            os.rmdir(directory)
            removedCount += 1
        except OSError:
            pass
    return removedCount


# Recycle bin (Windows) --------------------------------------------------------
def queryRecycleBin():
    if not isWindows:
        return 0, 0
    import ctypes
    from ctypes import wintypes

    class SHQUERYRBINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]

    info = SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
    result = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
    if result != 0:
        return 0, 0
    return int(info.i64NumItems), int(info.i64Size)


def emptyRecycleBin():
    if not isWindows:
        return False
    import ctypes
    flags = 0x00000001 | 0x00000002 | 0x00000004
    result = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
    return result in (0, -2147418113)
