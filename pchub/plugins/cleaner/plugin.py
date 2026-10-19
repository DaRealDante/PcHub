import datetime
import os
import threading
import time
import uuid

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLineEdit, QListWidget,
                               QListWidgetItem, QSpinBox, QVBoxLayout, QWidget)

from pchub.core.i18n import T, formatBytes, formatNumber, tr, language
from pchub.core.plugin_api import ActiveItem, HomeWidgetSpec, PluginBase
from pchub.core.settings_schema import ActionButton, Section, Slider, Toggle
from pchub.plugins.cleaner import engine
from pchub.ui.dialogs import ThemedDialog, confirm, showMessage
from pchub.ui.theme import theme
from pchub.ui.widgets import (Card, EmptyState, IconTile, IconWidget, MeterBar, ToggleSwitch, clearLayout, divider,
                              iconButton, makeButton, makeLabel)

TEXT = {
    "title": T("Pulizia", "Cleanup"),
    "scan": T("Analizza", "Scan"),
    "clean": T("Pulisci", "Clean"),
    "cleanNow": T("Pulisci ora", "Clean now"),
    "cancel": T("Annulla", "Cancel"),
    "scanning": T("Analisi in corso…", "Scanning…"),
    "scanningItem": T("Analizzo: {name}", "Scanning: {name}"),
    "cleaning": T("Pulizia in corso…", "Cleaning…"),
    "cleaningItem": T("Pulisco: {name}", "Cleaning: {name}"),
    "idleHint": T("Premi Analizza per vedere quanto spazio puoi liberare.", "Press Scan to see how much space you can free."),
    "scanDone": T("Puoi liberare {size} ({count} file)", "You can free {size} ({count} files)"),
    "nothing": T("Niente da pulire", "Nothing to clean"),
    "nothingText": T("Le voci selezionate sono già pulite.", "The selected items are already clean."),
    "lastClean": T("Ultima pulizia: {when}", "Last cleanup: {when}"),
    "never": T("mai", "never"),
    "totalFreed": T("Totale liberato: {size}", "Total freed: {size}"),
    "systemItems": T("Elementi di sistema", "System items"),
    "customFolders": T("Cartelle personalizzate", "Custom folders"),
    "customHint": T("Aggiungi cartelle tue (es. Download) con regole su età ed estensioni dei file.",
                    "Add your own folders (e.g. Downloads) with rules on file age and extensions."),
    "addFolder": T("Aggiungi cartella", "Add folder"),
    "history": T("Cronologia", "History"),
    "noHistory": T("Nessuna pulizia ancora.", "No cleanups yet."),
    "historyRow": T("Liberati {size} · {count} file", "Freed {size} · {count} files"),
    "historyFailed": T(" · {failed} in uso", " · {failed} in use"),
    "auto": T("automatica", "automatic"),
    "admin": T("Admin", "Admin"),
    "adminHint": T("Senza Permessi Avanzati pulisce solo in parte", "Without Advanced Permissions it only partly cleans"),
    "preview": T("Vedi i file", "See files"),
    "confirmTitle": T("Eliminare questi file?", "Delete these files?"),
    "confirmMessage": T("Stai per liberare {size} eliminando {count} file da:",
                        "You're about to free {size} by deleting {count} files from:"),
    "confirmButton": T("Elimina {size}", "Delete {size}"),
    "modeRecycle": T("nel Cestino", "to Recycle Bin"),
    "modePermanent": T("definitivo", "permanent"),
    "recycleItems": T("{count} elementi · {size}", "{count} items · {size}"),
    "doneTitle": T("Pulizia completata", "Cleanup complete"),
    "doneBody": T("Liberati {size} · {count} file eliminati", "Freed {size} · {count} files deleted"),
    "doneSkipped": T(" · {failed} file in uso lasciati", " · {failed} in-use files left"),
    "files": T("{count} file · {size}", "{count} files · {size}"),
    "folderDialogTitle": T("Cartella da pulire", "Folder to clean"),
    "folderName": T("Nome", "Name"),
    "folderPath": T("Cartella", "Folder"),
    "olderThan": T("Elimina file più vecchi di", "Delete files older than"),
    "days": T(" giorni", " days"),
    "dateField": T("In base alla data di", "Based on the date of"),
    "dateModified": T("ultima modifica", "last modification"),
    "dateCreated": T("creazione", "creation"),
    "dateAccessed": T("ultimo accesso", "last access"),
    "extensions": T("Solo queste estensioni", "Only these extensions"),
    "extensionsHint": T("es. .log, .tmp, .zip (vuoto = tutti i file)", "e.g. .log, .tmp, .zip (empty = all files)"),
    "excludeExtensions": T("Escludi estensioni", "Exclude extensions"),
    "excludeHint": T("es. .docx, .psd", "e.g. .docx, .psd"),
    "includeSubfolders": T("Includi le sottocartelle", "Include subfolders"),
    "deleteEmpty": T("Elimina le cartelle rimaste vuote", "Delete folders left empty"),
    "mode": T("Dove vanno i file", "Where files go"),
    "toRecycle": T("Nel Cestino (recuperabili)", "To Recycle Bin (recoverable)"),
    "toPermanent": T("Eliminazione definitiva", "Permanent delete"),
    "invalidFolder": {
        "empty": T("Scegli una cartella.", "Pick a folder."),
        "relative": T("Usa un percorso completo.", "Use a full path."),
        "root": T("Non puoi pulire un'intera unità.", "You can't clean an entire drive."),
        "protected": T("Questa cartella è protetta: scegline una più specifica.", "This folder is protected: pick a more specific one."),
        "system": T("Le cartelle di sistema e dei programmi non si possono pulire.", "System and program folders can't be cleaned."),
        "missing": T("La cartella non esiste.", "The folder doesn't exist."),
    },
    "ruleAll": T("tutti i file", "all files"),
    "ruleAge": T("più vecchi di {days} g", "older than {days} d"),
    "ruleOnly": T("solo {ext}", "only {ext}"),
    "ruleExclude": T("tranne {ext}", "except {ext}"),
    "removeFolderTitle": T("Rimuovere questa cartella dalla lista?", "Remove this folder from the list?"),
    "removeFolderMessage": T("I file nella cartella non vengono toccati.", "Files in the folder are not touched."),
    "previewTitle": T("File che verranno eliminati", "Files that will be deleted"),
    "previewMore": T("…e altri {count}", "…and {count} more"),
    "ago": T("{value} fa", "{value} ago"),
    "justNow": T("poco fa", "just now"),
}


def timeAgo(timestamp):
    if not timestamp:
        return tr(TEXT["never"])
    seconds = max(0, time.time() - timestamp)
    if seconds < 90:
        return tr(TEXT["justNow"])
    if seconds < 3600:
        value = f"{int(seconds // 60)} min"
    elif seconds < 86400:
        value = f"{int(seconds // 3600)} h"
    else:
        days = int(seconds // 86400)
        value = f"{days} {'g' if language() == 'it' else 'd'}"
    return tr(TEXT["ago"], value=value)


class CleanerPlugin(PluginBase):
    pluginId = "cleaner"
    name = T("Pulizia", "Cleaner")
    description = T("Libera spazio: Temp, cache, log, Cestino e cartelle tue con regole su età ed estensioni.",
                    "Free up space: Temp, caches, logs, Recycle Bin and your own folders with age and extension rules.")
    icon = "brush-cleaning"
    version = "1.0.0"
    author = "PC Hub"
    settingsSchema = [
        Section(T("Sicurezza", "Safety")),
        Slider("safeAgeDays", T("Età minima dei file temporanei", "Minimum age of temporary files"), 0, 30, 1,
               pinnable=False, icon="shield-check",
               description=T("I file più recenti vengono lasciati: potrebbero essere in uso.",
                             "Newer files are left alone: they might be in use."),
               formatter=lambda value: tr(T("{value} giorni", "{value} days"), value=value) if value != 1 else tr(T("1 giorno", "1 day"))),
        Section(T("Pulizia automatica", "Automatic cleanup")),
        Toggle("autoClean", T("Pulizia automatica", "Automatic cleanup"), False, icon="history",
               description=T("Pulisce le voci selezionate in background, senza chiedere.",
                             "Cleans the selected items in the background, without asking."),
               confirmOn=True, confirmTitle=T("Attivare la pulizia automatica?", "Enable automatic cleanup?"),
               confirmMessage=T("PC Hub eliminerà i file delle voci selezionate senza chiedere conferma, ogni volta che passa l'intervallo scelto.",
                                "PC Hub will delete files from the selected items without asking, every time the chosen interval passes."),
               confirmDetails=[T("Le cartelle personalizzate in modalità Cestino restano recuperabili",
                                 "Custom folders set to Recycle Bin stay recoverable"),
                               T("Puoi disattivarla in qualsiasi momento", "You can turn it off anytime")]),
        Slider("autoIntervalDays", T("Ogni", "Every"), 1, 30, 7, visibleIf=("autoClean", True), pinnable=False,
               formatter=lambda value: tr(T("{value} giorni", "{value} days"), value=value) if value != 1 else tr(T("giorno", "day"))),
        Toggle("autoNotify", T("Notifica dopo la pulizia automatica", "Notify after automatic cleanup"), True,
               visibleIf=("autoClean", True), pinnable=False, icon="bell"),
        Section(T("Azioni", "Actions")),
        ActionButton("cleanNow", T("Pulisci ora", "Clean now"), action="requestClean", buttonText=T("Pulisci", "Clean"),
                     icon="brush-cleaning", description=T("Analizza e chiede conferma prima di eliminare.",
                                                          "Scans and asks for confirmation before deleting.")),
    ]

    progressChanged = Signal(float, str)
    busyChanged = Signal(bool)
    scanFinished = Signal()
    cleanFinished = Signal(dict)
    configChanged = Signal()
    _workerDone = Signal(str, object)
    _workerProgress = Signal(float, str)

    def __init__(self, context):
        super().__init__(context)
        self.targets = engine.builtinTargets()
        self.busy = False
        self.busyKind = None
        self.cancelEvent = threading.Event()
        self.lastScan = {}
        self.lastScanTime = 0
        self.pendingConfirm = False
        self.autoMode = False
        self.progressValue = 0.0
        self.progressText = ""
        self.autoTimer = QTimer(self)
        self.autoTimer.setInterval(15 * 60 * 1000)
        self.autoTimer.timeout.connect(self.checkAutoClean)
        self._workerDone.connect(self._onWorkerDone)
        self._workerProgress.connect(self._onWorkerProgress)

    # lifecycle -----------------------------------------------------------
    def start(self):
        self.autoTimer.start()
        QTimer.singleShot(120 * 1000, self.checkAutoClean)

    def stop(self):
        self.autoTimer.stop()
        self.cancelEvent.set()

    # configuration -------------------------------------------------------
    def targetEnabled(self, targetId):
        enabledMap = self.context.getData("enabledTargets", {}) or {}
        if targetId in enabledMap:
            return bool(enabledMap[targetId])
        target = next((item for item in self.targets if item.targetId == targetId), None)
        return bool(target and target.defaultEnabled)

    def setTargetEnabled(self, targetId, enabled):
        enabledMap = self.context.getData("enabledTargets", {}) or {}
        enabledMap[targetId] = bool(enabled)
        self.context.setData("enabledTargets", enabledMap)
        self.configChanged.emit()

    def customFolders(self):
        return list(self.context.getData("customFolders", []) or [])

    def saveFolder(self, folder):
        folders = self.customFolders()
        if not folder.get("id"):
            folder["id"] = uuid.uuid4().hex[:8]
            folders.append(folder)
        else:
            folders = [folder if item["id"] == folder["id"] else item for item in folders]
        self.context.setData("customFolders", folders)
        self.lastScan.pop(f"c:{folder['id']}", None)
        self.configChanged.emit()

    def removeFolder(self, folderId):
        self.context.setData("customFolders", [item for item in self.customFolders() if item["id"] != folderId])
        self.lastScan.pop(f"c:{folderId}", None)
        self.configChanged.emit()

    def setFolderEnabled(self, folderId, enabled):
        folders = self.customFolders()
        for folder in folders:
            if folder["id"] == folderId:
                folder["enabled"] = bool(enabled)
        self.context.setData("customFolders", folders)
        self.configChanged.emit()

    def history(self):
        return list(self.context.getData("history", []) or [])

    def totalFreed(self):
        return sum(entry.get("freed", 0) for entry in self.history())

    def jobName(self, jobId):
        kind, identifier = jobId.split(":", 1)
        if kind == "b":
            target = next((item for item in self.targets if item.targetId == identifier), None)
            return tr(target.name) if target else identifier
        folder = next((item for item in self.customFolders() if item["id"] == identifier), None)
        return folder.get("name") or os.path.basename(folder["path"]) if folder else identifier

    def buildJobs(self):
        jobs = []
        safeAgeSeconds = int(self.setting("safeAgeDays") or 0) * engine.DAY_SECONDS
        for target in self.targets:
            if not self.targetEnabled(target.targetId):
                continue
            if target.kind == "recycleBin":
                jobs.append({"jobId": f"b:{target.targetId}", "kind": "recycleBin", "name": tr(target.name)})
                continue
            jobs.append({"jobId": f"b:{target.targetId}", "kind": "files" if target.filePatterns else "folder",
                         "name": tr(target.name), "paths": target.resolvePaths(),
                         "minAge": safeAgeSeconds if target.ageSensitive else 0, "extensions": None,
                         "exclude": None, "subfolders": True, "dateField": "modified", "mode": "permanent",
                         "deleteEmpty": True})
        for folder in self.customFolders():
            if not folder.get("enabled", True):
                continue
            if engine.isDangerousPath(folder.get("path")) or not os.path.isdir(folder.get("path", "")):
                continue
            jobs.append({"jobId": f"c:{folder['id']}", "kind": "folder", "name": folder.get("name") or folder["path"],
                         "paths": [folder["path"]], "minAge": int(folder.get("minAgeDays", 0)) * engine.DAY_SECONDS,
                         "extensions": folder.get("extensions"), "exclude": folder.get("excludeExtensions"),
                         "subfolders": folder.get("includeSubfolders", True), "dateField": folder.get("dateField", "modified"),
                         "mode": folder.get("mode", "recycle"), "deleteEmpty": folder.get("deleteEmptyFolders", False)})
        return jobs

    # operations ----------------------------------------------------------
    def _setBusy(self, busy, kind=None):
        self.busy = busy
        self.busyKind = kind if busy else None
        if busy:
            self.cancelEvent.clear()
            self.progressValue = 0.0
        else:
            self.context.removeActive("job")
        self.busyChanged.emit(busy)

    def cancel(self):
        self.cancelEvent.set()

    def scan(self, thenConfirm=False, auto=False):
        if self.busy:
            return False
        self.pendingConfirm = thenConfirm
        self.autoMode = auto
        jobs = self.buildJobs()
        self._setBusy(True, "scan")
        self.runInThread(self._scanWorker, jobs, name="cleaner-scan")
        return True

    def _scanWorker(self, jobs):
        results = {}
        now = time.time()
        for index, job in enumerate(jobs):
            if self.cancelEvent.is_set():
                break
            self._workerProgress.emit(index / max(1, len(jobs)), tr(TEXT["scanningItem"], name=job["name"]))
            result = engine.ScanResult(job["jobId"])
            result.mode = job.get("mode", "permanent")
            if job["kind"] == "recycleBin":
                count, size = engine.queryRecycleBin()
                result.recycleCount = count
                result.totalSize = size
            elif job["kind"] == "files":
                engine.scanFiles(job["paths"], job["minAge"], now, result)
            else:
                for path in job["paths"]:
                    engine.scanFolder(path, job["minAge"], job["extensions"], job["exclude"], job["subfolders"],
                                      job["dateField"], now, self.cancelEvent, result)
            result.deleteEmpty = job.get("deleteEmpty", False)
            result.kind = job["kind"]
            results[job["jobId"]] = result
        self._workerDone.emit("scan", results)

    def requestClean(self):
        """Full flow: scan → show what will be deleted → confirm → delete."""
        if self.busy:
            return
        self.scan(thenConfirm=True)

    def _confirmAndClean(self):
        results = {jobId: result for jobId, result in self.lastScan.items() if self._resultHasWork(result)}
        if not results:
            if not self.autoMode:
                self.context.notify(tr(TEXT["nothing"]), tr(TEXT["nothingText"]))
            return
        totalSize = sum(result.totalSize for result in results.values())
        totalCount = sum(self._resultCount(result) for result in results.values())
        if not self.autoMode:
            details = []
            for jobId, result in results.items():
                if result.kind == "recycleBin":
                    valueText = tr(TEXT["recycleItems"], count=formatNumber(result.recycleCount), size=formatBytes(result.totalSize))
                    modeText = tr(TEXT["modePermanent"])
                else:
                    valueText = tr(TEXT["files"], count=formatNumber(result.count), size=formatBytes(result.totalSize))
                    modeText = tr(TEXT["modeRecycle"]) if result.mode == "recycle" else tr(TEXT["modePermanent"])
                details.append((self.jobName(jobId), f"{valueText} · {modeText}"))
            accepted = self.context.confirm(
                tr(TEXT["confirmTitle"]),
                tr(TEXT["confirmMessage"], size=formatBytes(totalSize), count=formatNumber(totalCount)),
                details, danger=True, confirmText=tr(TEXT["confirmButton"], size=formatBytes(totalSize)),
                icon="brush-cleaning")
            if not accepted:
                return
        self.clean(list(results))

    @staticmethod
    def _resultHasWork(result):
        if getattr(result, "kind", None) == "recycleBin":
            return getattr(result, "recycleCount", 0) > 0
        return result.count > 0 or (result.deleteEmpty and bool(result.directories))

    @staticmethod
    def _resultCount(result):
        return getattr(result, "recycleCount", 0) if getattr(result, "kind", None) == "recycleBin" else result.count

    def clean(self, jobIds):
        if self.busy:
            return False
        jobs = [(jobId, self.lastScan[jobId]) for jobId in jobIds if jobId in self.lastScan]
        self._setBusy(True, "clean")
        self.runInThread(self._cleanWorker, jobs, name="cleaner-clean")
        return True

    def _cleanWorker(self, jobs):
        summary = {"deleted": 0, "freed": 0, "failed": 0, "auto": self.autoMode, "time": time.time()}
        totalFiles = max(1, sum(self._resultCount(result) for _, result in jobs))
        doneFiles = 0
        for jobId, result in jobs:
            if self.cancelEvent.is_set():
                break
            name = self.jobName(jobId)
            self._workerProgress.emit(doneFiles / totalFiles, tr(TEXT["cleaningItem"], name=name))
            if result.kind == "recycleBin":
                if engine.emptyRecycleBin():
                    summary["deleted"] += result.recycleCount
                    summary["freed"] += result.totalSize
                doneFiles += result.recycleCount
                continue

            def progress(done, total, baseDone=doneFiles, label=name):
                self._workerProgress.emit((baseDone + done) / totalFiles, tr(TEXT["cleaningItem"], name=label))

            deleted, freed, failed = engine.deleteFiles(result.files, result.mode, self.cancelEvent, progress)
            summary["deleted"] += deleted
            summary["freed"] += freed
            summary["failed"] += failed
            doneFiles += result.count
            if result.deleteEmpty:
                engine.removeEmptyDirectories(result.directories, result.roots)
        self._workerDone.emit("clean", summary)

    def _onWorkerProgress(self, fraction, text):
        self.progressValue = fraction
        self.progressText = text
        self.progressChanged.emit(fraction, text)
        title = tr(TEXT["scanning"]) if self.busyKind == "scan" else tr(TEXT["cleaning"])
        self.context.setActive(ActiveItem("job", title, text, icon="brush-cleaning", progress=fraction,
                                          actions=[(TEXT["cancel"], "x", self.cancel)]))

    def _onWorkerDone(self, kind, payload):
        cancelled = self.cancelEvent.is_set()
        self._setBusy(False)
        if kind == "scan":
            self.lastScan = payload
            self.lastScanTime = time.time()
            self.scanFinished.emit()
            if self.pendingConfirm and not cancelled:
                self.pendingConfirm = False
                self._confirmAndClean()
            self.pendingConfirm = False
            return
        summary = payload
        history = self.history()
        history.insert(0, summary)
        self.context.setData("history", history[:30])
        if summary.get("auto"):
            self.context.setData("lastAutoClean", time.time())
        self.lastScan = {}
        self.cleanFinished.emit(summary)
        self.configChanged.emit()
        body = tr(TEXT["doneBody"], size=formatBytes(summary["freed"]), count=formatNumber(summary["deleted"]))
        if summary["failed"]:
            body += tr(TEXT["doneSkipped"], failed=formatNumber(summary["failed"]))
        if not summary.get("auto") or self.setting("autoNotify"):
            self.context.notify(tr(TEXT["doneTitle"]), body, "done")
        self.context.emit("cleaned", freed=summary["freed"], deleted=summary["deleted"])
        self.autoMode = False

    def checkAutoClean(self):
        if not self.setting("autoClean") or self.busy or not self.isRunning():
            return
        lastAuto = self.context.getData("lastAutoClean", 0) or 0
        intervalSeconds = int(self.setting("autoIntervalDays") or 7) * engine.DAY_SECONDS
        if time.time() - lastAuto >= intervalSeconds:
            self.scan(thenConfirm=True, auto=True)

    # ui ------------------------------------------------------------------
    def createPage(self):
        return CleanerPage(self)

    def homeWidgets(self):
        return [HomeWidgetSpec("cleaner.quick", T("Pulizia rapida", "Quick cleanup"), lambda: CleanerHomeWidget(self),
                               T("Ultima pulizia e un tasto per liberare spazio.", "Last cleanup and a button to free space."),
                               "brush-cleaning", "small", ["small", "wide"])]

    def automationActions(self):
        from pchub.core.events import AutomationAction
        return [AutomationAction("cleanSilently", T("Pulisci senza chiedere", "Clean without asking"),
                                 lambda params=None: self.scan(thenConfirm=True, auto=True), icon="brush-cleaning")]


Plugin = CleanerPlugin


class FolderDialog(ThemedDialog):
    def __init__(self, parent, folder=None):
        super().__init__(parent, 520)
        self.folder = dict(folder or {"enabled": True, "minAgeDays": 30, "dateField": "modified", "extensions": "",
                                      "excludeExtensions": "", "includeSubfolders": True, "deleteEmptyFolders": False,
                                      "mode": "recycle", "name": "", "path": ""})
        self.addHeader(tr(TEXT["folderDialogTitle"]), "folder-open")
        self.nameEdit = QLineEdit(self.folder.get("name", ""))
        self.pathEdit = QLineEdit(self.folder.get("path", ""))
        self.pathEdit.textChanged.connect(self._validate)
        browseButton = iconButton("folder-open", tr(TEXT["folderPath"]), "text", 16)
        browseButton.clicked.connect(self._browse)
        self.ageSpin = QSpinBox()
        self.ageSpin.setRange(0, 3650)
        self.ageSpin.setSuffix(tr(TEXT["days"]))
        self.ageSpin.setValue(int(self.folder.get("minAgeDays", 30)))
        self.dateCombo = QComboBox()
        for value, label in (("modified", TEXT["dateModified"]), ("created", TEXT["dateCreated"]), ("accessed", TEXT["dateAccessed"])):
            self.dateCombo.addItem(tr(label), value)
        self.dateCombo.setCurrentIndex(max(0, self.dateCombo.findData(self.folder.get("dateField", "modified"))))
        self.extensionsEdit = QLineEdit(self.folder.get("extensions", ""))
        self.extensionsEdit.setPlaceholderText(tr(TEXT["extensionsHint"]))
        self.excludeEdit = QLineEdit(self.folder.get("excludeExtensions", ""))
        self.excludeEdit.setPlaceholderText(tr(TEXT["excludeHint"]))
        self.subfoldersToggle = ToggleSwitch(bool(self.folder.get("includeSubfolders", True)))
        self.emptyToggle = ToggleSwitch(bool(self.folder.get("deleteEmptyFolders", False)))
        self.modeCombo = QComboBox()
        self.modeCombo.addItem(tr(TEXT["toRecycle"]), "recycle")
        self.modeCombo.addItem(tr(TEXT["toPermanent"]), "permanent")
        self.modeCombo.setCurrentIndex(max(0, self.modeCombo.findData(self.folder.get("mode", "recycle"))))
        pathRow = QHBoxLayout()
        pathRow.setSpacing(6)
        pathRow.addWidget(self.pathEdit, 1)
        pathRow.addWidget(browseButton)
        self._row(tr(TEXT["folderPath"]), pathRow)
        self.errorLabel = makeLabel("", "error", True)
        self.bodyLayout.addWidget(self.errorLabel)
        self._row(tr(TEXT["folderName"]), self.nameEdit)
        self._row(tr(TEXT["olderThan"]), self.ageSpin)
        self._row(tr(TEXT["dateField"]), self.dateCombo)
        self._row(tr(TEXT["extensions"]), self.extensionsEdit)
        self._row(tr(TEXT["excludeExtensions"]), self.excludeEdit)
        self._row(tr(TEXT["includeSubfolders"]), self.subfoldersToggle, inline=True)
        self._row(tr(TEXT["deleteEmpty"]), self.emptyToggle, inline=True)
        self._row(tr(TEXT["mode"]), self.modeCombo)
        cancelButton = makeButton(tr(TEXT["cancel"]))
        cancelButton.clicked.connect(self.reject)
        self.saveButton = makeButton(tr("common.save"), "check", "primary")
        self.saveButton.clicked.connect(self._save)
        self.addButtons([cancelButton, self.saveButton])
        self._validate()

    def _row(self, label, control, inline=False):
        rowLayout = QHBoxLayout() if inline else QVBoxLayout()
        rowLayout.setSpacing(5 if not inline else 10)
        rowLayout.addWidget(makeLabel(label, "muted"))
        if inline:
            rowLayout.addStretch(1)
        if isinstance(control, (QHBoxLayout, QVBoxLayout)):
            rowLayout.addLayout(control)
        else:
            rowLayout.addWidget(control)
        self.bodyLayout.addLayout(rowLayout)

    def _browse(self):
        folderPath = QFileDialog.getExistingDirectory(self, tr(TEXT["folderPath"]), self.pathEdit.text())
        if folderPath:
            self.pathEdit.setText(os.path.normpath(folderPath))
            if not self.nameEdit.text().strip():
                self.nameEdit.setText(os.path.basename(os.path.normpath(folderPath)))

    def _validate(self):
        path = self.pathEdit.text().strip()
        reason = engine.isDangerousPath(path)
        if reason is None and not os.path.isdir(path):
            reason = "missing"
        self.errorLabel.setText(tr(TEXT["invalidFolder"][reason]) if reason else "")
        self.errorLabel.setVisible(bool(reason))
        self.saveButton.setEnabled(reason is None)
        return reason is None

    def _save(self):
        if not self._validate():
            return
        self.folder.update({
            "name": self.nameEdit.text().strip() or os.path.basename(self.pathEdit.text().strip()),
            "path": os.path.normpath(self.pathEdit.text().strip()),
            "minAgeDays": self.ageSpin.value(),
            "dateField": self.dateCombo.currentData(),
            "extensions": self.extensionsEdit.text().strip(),
            "excludeExtensions": self.excludeEdit.text().strip(),
            "includeSubfolders": self.subfoldersToggle.isChecked(),
            "deleteEmptyFolders": self.emptyToggle.isChecked(),
            "mode": self.modeCombo.currentData(),
        })
        self.accept()


class PreviewDialog(ThemedDialog):
    def __init__(self, parent, title, result):
        super().__init__(parent, 640)
        self.addHeader(tr(TEXT["previewTitle"]), "eye", None,
                       f"{title} · {tr(TEXT['files'], count=formatNumber(result.count), size=formatBytes(result.totalSize))}")
        listWidget = QListWidget()
        listWidget.setMinimumHeight(360)
        files = sorted(result.files, key=lambda item: item[1], reverse=True)
        for path, size in files[:500]:
            item = QListWidgetItem(f"{formatBytes(size):>10}   {path}")
            item.setToolTip(path)
            listWidget.addItem(item)
        if len(files) > 500:
            listWidget.addItem(QListWidgetItem(tr(TEXT["previewMore"], count=formatNumber(len(files) - 500))))
        self.bodyLayout.addWidget(listWidget)
        closeButton = makeButton(tr("common.close"), variant="primary")
        closeButton.clicked.connect(self.accept)
        self.addButtons([closeButton])


def ruleSummary(folder):
    parts = []
    if int(folder.get("minAgeDays", 0)) > 0:
        parts.append(tr(TEXT["ruleAge"], days=folder["minAgeDays"]))
    if folder.get("extensions"):
        parts.append(tr(TEXT["ruleOnly"], ext=", ".join(engine.normalizeExtensions(folder["extensions"]))))
    if folder.get("excludeExtensions"):
        parts.append(tr(TEXT["ruleExclude"], ext=", ".join(engine.normalizeExtensions(folder["excludeExtensions"]))))
    if not parts:
        parts.append(tr(TEXT["ruleAll"]))
    parts.append(tr(TEXT["modeRecycle"]) if folder.get("mode") == "recycle" else tr(TEXT["modePermanent"]))
    return " · ".join(parts)


class JobRow(QWidget):
    def __init__(self, page, jobId, iconName, title, subtitle, enabled, onToggle, chips=(), editable=False):
        super().__init__()
        self.page = page
        self.jobId = jobId
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 10, 4, 10)
        layout.setSpacing(12)
        toggle = ToggleSwitch(enabled)
        toggle.toggled.connect(onToggle)
        layout.addWidget(toggle)
        layout.addWidget(IconWidget(iconName, "muted", 18))
        textLayout = QVBoxLayout()
        textLayout.setSpacing(2)
        titleRow = QHBoxLayout()
        titleRow.setSpacing(6)
        titleRow.addWidget(makeLabel(title))
        for chipText, chipRole, chipTip in chips:
            chip = makeLabel(chipText, chipRole)
            if chipTip:
                chip.setToolTip(chipTip)
            titleRow.addWidget(chip)
        titleRow.addStretch(1)
        textLayout.addLayout(titleRow)
        textLayout.addWidget(makeLabel(subtitle, "faint", True))
        layout.addLayout(textLayout, 1)
        self.resultLabel = makeLabel("", "accent")
        layout.addWidget(self.resultLabel)
        self.previewButton = iconButton("eye", tr(TEXT["preview"]), "muted", 16)
        self.previewButton.clicked.connect(lambda: page.showPreview(jobId))
        self.previewButton.hide()
        layout.addWidget(self.previewButton)
        if editable:
            editButton = iconButton("pencil", tr("common.edit"), "muted", 16)
            editButton.clicked.connect(lambda: page.editFolder(jobId.split(":", 1)[1]))
            layout.addWidget(editButton)
            removeButton = iconButton("trash-2", tr("common.delete"), "danger", 16)
            removeButton.clicked.connect(lambda: page.removeFolder(jobId.split(":", 1)[1]))
            layout.addWidget(removeButton)

    def setResult(self, result):
        if result is None:
            self.resultLabel.setText("")
            self.previewButton.hide()
            return
        if getattr(result, "kind", None) == "recycleBin":
            self.resultLabel.setText(tr(TEXT["recycleItems"], count=formatNumber(result.recycleCount),
                                        size=formatBytes(result.totalSize)))
            self.previewButton.hide()
        else:
            self.resultLabel.setText(tr(TEXT["files"], count=formatNumber(result.count), size=formatBytes(result.totalSize)))
            self.previewButton.setVisible(result.count > 0)


class CleanerPage(QWidget):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.rows = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        summaryCard = Card(padding=18)
        summaryLayout = QVBoxLayout(summaryCard)
        summaryLayout.setSpacing(12)
        topRow = QHBoxLayout()
        topRow.setSpacing(14)
        topRow.addWidget(IconTile("brush-cleaning", 52, theme().success))
        statsLayout = QVBoxLayout()
        statsLayout.setSpacing(2)
        self.headlineLabel = makeLabel(tr(TEXT["idleHint"]), "subtitle", True)
        self.lastLabel = makeLabel("", "faint")
        statsLayout.addWidget(self.headlineLabel)
        statsLayout.addWidget(self.lastLabel)
        topRow.addLayout(statsLayout, 1)
        self.scanButton = makeButton(tr(TEXT["scan"]), "scan-search")
        self.scanButton.clicked.connect(lambda: plugin.scan())
        topRow.addWidget(self.scanButton)
        self.cleanButton = makeButton(tr(TEXT["clean"]), "brush-cleaning", "primary")
        self.cleanButton.clicked.connect(self._clean)
        topRow.addWidget(self.cleanButton)
        summaryLayout.addLayout(topRow)
        progressRow = QHBoxLayout()
        progressRow.setSpacing(10)
        self.progressBar = MeterBar(None, 8)
        self.progressLabel = makeLabel("", "faint")
        self.cancelButton = makeButton(tr(TEXT["cancel"]), "x", "ghost")
        self.cancelButton.clicked.connect(plugin.cancel)
        progressColumn = QVBoxLayout()
        progressColumn.setSpacing(4)
        progressColumn.addWidget(self.progressBar)
        progressColumn.addWidget(self.progressLabel)
        progressRow.addLayout(progressColumn, 1)
        progressRow.addWidget(self.cancelButton)
        self.progressHost = QWidget()
        self.progressHost.setLayout(progressRow)
        summaryLayout.addWidget(self.progressHost)
        layout.addWidget(summaryCard)

        self.targetsCard = Card(padding=12)
        self.targetsLayout = QVBoxLayout(self.targetsCard)
        self.targetsLayout.setSpacing(0)
        layout.addWidget(self._sectionTitle(TEXT["systemItems"]))
        layout.addWidget(self.targetsCard)

        foldersHeader = QHBoxLayout()
        foldersHeader.addWidget(self._sectionTitle(TEXT["customFolders"]))
        foldersHeader.addStretch(1)
        addButton = makeButton(tr(TEXT["addFolder"]), "folder-plus", "ghost")
        addButton.clicked.connect(lambda: self.editFolder(None))
        foldersHeader.addWidget(addButton)
        layout.addLayout(foldersHeader)
        self.foldersCard = Card(padding=12)
        self.foldersLayout = QVBoxLayout(self.foldersCard)
        self.foldersLayout.setSpacing(0)
        layout.addWidget(self.foldersCard)

        layout.addWidget(self._sectionTitle(TEXT["history"]))
        self.historyCard = Card(padding=14)
        self.historyLayout = QVBoxLayout(self.historyCard)
        self.historyLayout.setSpacing(6)
        layout.addWidget(self.historyCard)

        plugin.configChanged.connect(self.rebuild)
        plugin.busyChanged.connect(self._onBusy)
        plugin.progressChanged.connect(self._onProgress)
        plugin.scanFinished.connect(self._onScanFinished)
        plugin.cleanFinished.connect(self._onCleanFinished)
        self.rebuild()
        self._onBusy(plugin.busy)

    def _onCleanFinished(self, summary):
        self._refreshSummary()

    @staticmethod
    def _sectionTitle(text):
        label = makeLabel(tr(text).upper(), "section")
        label.setContentsMargins(6, 12, 0, 2)
        return label

    def rebuild(self):
        plugin = self.plugin
        clearLayout(self.targetsLayout)
        clearLayout(self.foldersLayout)
        self.rows = {}
        isAdmin = plugin.context.isAdmin()
        for index, target in enumerate(plugin.targets):
            chips = []
            if target.requiresAdmin:
                chips.append((tr(TEXT["admin"]), "chip" if isAdmin else "chipWarning", None if isAdmin else tr(TEXT["adminHint"])))
            if target.warning:
                chips.append((tr(target.warning), "chipWarning", None))
            row = JobRow(self, f"b:{target.targetId}", target.icon, tr(target.name), tr(target.description),
                         plugin.targetEnabled(target.targetId),
                         lambda checked, targetId=target.targetId: plugin.setTargetEnabled(targetId, checked), chips)
            if index:
                self.targetsLayout.addWidget(divider())
            self.targetsLayout.addWidget(row)
            self.rows[row.jobId] = row
        folders = plugin.customFolders()
        if not folders:
            self.foldersLayout.addWidget(EmptyState("folder-plus", tr(TEXT["customFolders"]), tr(TEXT["customHint"])))
        for index, folder in enumerate(folders):
            subtitle = f"{folder['path']}\n{ruleSummary(folder)}"
            row = JobRow(self, f"c:{folder['id']}", "folder", folder.get("name") or folder["path"], subtitle,
                         folder.get("enabled", True),
                         lambda checked, folderId=folder["id"]: plugin.setFolderEnabled(folderId, checked), editable=True)
            if index:
                self.foldersLayout.addWidget(divider())
            self.foldersLayout.addWidget(row)
            self.rows[row.jobId] = row
        self._onScanFinished()
        self._refreshSummary()

    def _refreshSummary(self):
        plugin = self.plugin
        history = plugin.history()
        lastTime = history[0]["time"] if history else None
        self.lastLabel.setText(f"{tr(TEXT['lastClean'], when=timeAgo(lastTime))} · "
                               f"{tr(TEXT['totalFreed'], size=formatBytes(plugin.totalFreed()))}")
        clearLayout(self.historyLayout)
        if not history:
            self.historyLayout.addWidget(makeLabel(tr(TEXT["noHistory"]), "faint"))
        for entry in history[:8]:
            rowLayout = QHBoxLayout()
            when = datetime.datetime.fromtimestamp(entry["time"]).strftime("%d/%m/%Y %H:%M")
            rowLayout.addWidget(IconWidget("history" if entry.get("auto") else "check", "muted", 15))
            rowLayout.addWidget(makeLabel(when, "faint"))
            text = tr(TEXT["historyRow"], size=formatBytes(entry["freed"]), count=formatNumber(entry["deleted"]))
            if entry.get("failed"):
                text += tr(TEXT["historyFailed"], failed=formatNumber(entry["failed"]))
            if entry.get("auto"):
                text += f" · {tr(TEXT['auto'])}"
            rowLayout.addWidget(makeLabel(text), 1)
            self.historyLayout.addLayout(rowLayout)

    def _onScanFinished(self):
        results = self.plugin.lastScan
        for jobId, row in self.rows.items():
            row.setResult(results.get(jobId))
        if results:
            totalSize = sum(result.totalSize for result in results.values())
            totalCount = sum(self.plugin._resultCount(result) for result in results.values())
            self.headlineLabel.setText(tr(TEXT["scanDone"], size=formatBytes(totalSize), count=formatNumber(totalCount)))
        else:
            self.headlineLabel.setText(tr(TEXT["idleHint"]))

    def _onBusy(self, busy):
        self.progressHost.setVisible(busy)
        self.scanButton.setEnabled(not busy)
        self.cleanButton.setEnabled(not busy)
        if not busy:
            self.progressBar.setValue(0)

    def _onProgress(self, fraction, text):
        self.progressBar.setValue(fraction)
        self.progressLabel.setText(text)

    def _clean(self):
        plugin = self.plugin
        if plugin.lastScan and time.time() - plugin.lastScanTime < 600:
            plugin.autoMode = False
            plugin._confirmAndClean()
        else:
            plugin.requestClean()

    def showPreview(self, jobId):
        result = self.plugin.lastScan.get(jobId)
        if result is not None:
            PreviewDialog(self, self.plugin.jobName(jobId), result).exec()

    def editFolder(self, folderId):
        folder = next((item for item in self.plugin.customFolders() if item["id"] == folderId), None) if folderId else None
        dialog = FolderDialog(self, folder)
        if dialog.exec():
            self.plugin.saveFolder(dialog.folder)

    def removeFolder(self, folderId):
        if confirm(self, tr(TEXT["removeFolderTitle"]), tr(TEXT["removeFolderMessage"]), confirmText=tr("common.delete")):
            self.plugin.removeFolder(folderId)


class CleanerHomeWidget(QWidget):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.freedLabel = makeLabel("", "metric")
        layout.addWidget(self.freedLabel)
        self.lastLabel = makeLabel("", "faint", True)
        layout.addWidget(self.lastLabel)
        layout.addStretch(1)
        self.progressBar = MeterBar(None, 6)
        self.progressBar.hide()
        layout.addWidget(self.progressBar)
        self.cleanButton = makeButton(tr(TEXT["cleanNow"]), "brush-cleaning", "primary")
        self.cleanButton.clicked.connect(plugin.requestClean)
        layout.addWidget(self.cleanButton)
        plugin.busyChanged.connect(self._onBusy)
        plugin.progressChanged.connect(self._onProgress)
        plugin.cleanFinished.connect(self._onCleanFinished)
        self.refresh()

    def _onProgress(self, fraction, text):
        self.progressBar.setValue(fraction)

    def _onCleanFinished(self, summary):
        self.refresh()

    def _onBusy(self, busy):
        self.progressBar.setVisible(busy)
        self.cleanButton.setEnabled(not busy)

    def refresh(self):
        history = self.plugin.history()
        self.freedLabel.setText(formatBytes(self.plugin.totalFreed()))
        self.lastLabel.setText(tr(TEXT["lastClean"], when=timeAgo(history[0]["time"] if history else None)))
