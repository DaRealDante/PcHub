import collections
import os
import platform
import threading
import time

import psutil
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView

from pchub.core.i18n import T, formatBytes, language, tr
from pchub.core.plugin_api import ActiveItem, HomeWidgetSpec, PluginBase
from pchub.core.settings_schema import Section, Slider, Toggle
from pchub.ui.theme import theme
from pchub.ui.widgets import Card, MeterBar, Sparkline, clearLayout, makeLabel, makeStableLabel

HISTORY_LENGTH = 90

TEXT = {
    "cpu": T("CPU", "CPU"),
    "ram": T("RAM", "RAM"),
    "gpu": T("GPU", "GPU"),
    "disk": T("Disco", "Disk"),
    "network": T("Rete", "Network"),
    "disks": T("Dischi", "Drives"),
    "processes": T("Processi più pesanti", "Top processes"),
    "system": T("Sistema", "System"),
    "uptime": T("Acceso da", "Uptime"),
    "cores": T("{count} core", "{count} cores"),
    "notAvailable": T("Non disponibile", "Not available"),
    "gpuNotAvailable": T("GPU NVIDIA non trovata", "NVIDIA GPU not found"),
    "download": T("Download", "Download"),
    "upload": T("Upload", "Upload"),
    "read": T("Lettura", "Read"),
    "write": T("Scrittura", "Write"),
    "process": T("Processo", "Process"),
    "battery": T("Batteria", "Battery"),
    "charging": T("in carica", "charging"),
    "free": T("{free} liberi di {total}", "{free} free of {total}"),
    "alertCpuTitle": T("CPU sotto sforzo", "CPU under heavy load"),
    "alertRamTitle": T("RAM quasi piena", "RAM almost full"),
    "alertGpuTitle": T("GPU molto calda", "GPU running hot"),
    "alertBody": T("{value} da più di {seconds} secondi", "{value} for more than {seconds} seconds"),
    "overview": T("Panoramica", "Overview"),
    "temperature": T("Temperatura", "Temperature"),
    "memory": T("Memoria", "Memory"),
}


def formatUptime(seconds):
    days, remainder = divmod(int(seconds), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days:
        return f"{days}{'g' if language() == 'it' else 'd'} {hours}h"
    return f"{hours}h {minutes:02d}m"


def formatRate(bytesPerSecond):
    return f"{formatBytes(bytesPerSecond)}/s"


class GpuReader:
    def __init__(self):
        self.available = False
        self.handles = []
        try:
            import pynvml
            pynvml.nvmlInit()
            self.nvml = pynvml
            self.handles = [pynvml.nvmlDeviceGetHandleByIndex(index) for index in range(pynvml.nvmlDeviceGetCount())]
            self.available = bool(self.handles)
        except Exception:
            self.available = False

    def read(self):
        if not self.available:
            return None
        nvml = self.nvml
        handle = self.handles[0]
        result = {}
        try:
            if getattr(self, "cachedName", None) is None:
                nameValue = nvml.nvmlDeviceGetName(handle)
                self.cachedName = nameValue.decode() if isinstance(nameValue, bytes) else nameValue
            result["name"] = self.cachedName
            utilization = nvml.nvmlDeviceGetUtilizationRates(handle)
            result["percent"] = float(utilization.gpu)
            memory = nvml.nvmlDeviceGetMemoryInfo(handle)
            result["memUsed"] = memory.used
            result["memTotal"] = memory.total
            result["temperature"] = float(nvml.nvmlDeviceGetTemperature(handle, nvml.NVML_TEMPERATURE_GPU))
            try:
                result["power"] = nvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
            except Exception:
                result["power"] = None
            try:
                result["fan"] = float(nvml.nvmlDeviceGetFanSpeed(handle))
            except Exception:
                result["fan"] = None
        except Exception:
            return None
        return result

    def close(self):
        if self.available:
            try:
                self.nvml.nvmlShutdown()
            except Exception:
                pass


def systemDriveRoot():
    if os.name == "nt":
        return (os.environ.get("SystemDrive", "C:") + "\\")
    return "/"


class Sampler:
    def __init__(self):
        self.lastNet = None
        self.lastDisk = None
        self.lastTime = None
        self.processCache = {}
        self.sampleIndex = 0
        self.gpuReader = GpuReader()
        psutil.cpu_percent(None)
        psutil.cpu_percent(None, percpu=True)
        self.cpuCount = psutil.cpu_count(logical=True) or 1
        from pchub.plugins.system_monitor.winprocs import ProcessSnapshotter
        self.snapshotter = ProcessSnapshotter(self.cpuCount)
        self.physicalCount = psutil.cpu_count(logical=False) or self.cpuCount
        self.cpuName = self._cpuName()
        self.bootTime = psutil.boot_time()

    @staticmethod
    def _cpuName():
        if os.name == "nt":
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                    return " ".join(str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).split())
            except OSError:
                pass
        try:
            with open("/proc/cpuinfo", encoding="utf-8") as cpuInfo:
                for line in cpuInfo:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
        return platform.processor() or platform.machine()

    def sample(self, includeProcesses=True):
        now = time.time()
        data = {"time": now}
        data["cpu"] = psutil.cpu_percent(None)
        data["cpuPerCore"] = psutil.cpu_percent(None, percpu=True)
        try:
            frequency = psutil.cpu_freq()
            data["cpuFreq"] = frequency.current if frequency else None
        except Exception:
            data["cpuFreq"] = None
        memory = psutil.virtual_memory()
        data["ram"] = memory.percent
        data["ramUsed"] = memory.used
        data["ramTotal"] = memory.total
        try:
            swap = psutil.swap_memory()
            data["swap"] = swap.percent
        except Exception:
            data["swap"] = None
        if now - getattr(self, "disksReadAt", 0) < 10 and getattr(self, "cachedDisks", None) is not None:
            disks = self.cachedDisks
        else:
            disks = self._readDisks()
            self.cachedDisks, self.disksReadAt = disks, now
        data["disks"] = disks
        systemRoot = systemDriveRoot().rstrip("\\/").lower()
        data["systemDisk"] = next((disk for disk in disks if disk["mount"].rstrip("\\/").lower() == systemRoot),
                                  disks[0] if disks else None)
        return self._sampleRest(data, now, includeProcesses)

    def _readDisks(self):
        """Free space barely changes: read every 10 s instead of every sample."""
        disks = []
        for partition in psutil.disk_partitions(all=False):
            if "cdrom" in partition.opts or not partition.fstype:
                continue
            try:
                usage = psutil.disk_usage(partition.mountpoint)
            except (PermissionError, OSError):
                continue
            disks.append({"mount": partition.mountpoint, "percent": usage.percent, "used": usage.used,
                          "total": usage.total, "free": usage.free})
        return disks

    def _sampleRest(self, data, now, includeProcesses):
        elapsedTime = (now - self.lastTime) if self.lastTime else None
        try:
            netCounters = psutil.net_io_counters()
        except Exception:
            netCounters = None
        try:
            diskCounters = psutil.disk_io_counters()
        except Exception:
            diskCounters = None
        if elapsedTime and netCounters and self.lastNet:
            data["netUp"] = max(0.0, (netCounters.bytes_sent - self.lastNet.bytes_sent) / elapsedTime)
            data["netDown"] = max(0.0, (netCounters.bytes_recv - self.lastNet.bytes_recv) / elapsedTime)
        else:
            data["netUp"] = data["netDown"] = 0.0
        if elapsedTime and diskCounters and self.lastDisk:
            data["diskRead"] = max(0.0, (diskCounters.read_bytes - self.lastDisk.read_bytes) / elapsedTime)
            data["diskWrite"] = max(0.0, (diskCounters.write_bytes - self.lastDisk.write_bytes) / elapsedTime)
        else:
            data["diskRead"] = data["diskWrite"] = 0.0
        self.lastNet, self.lastDisk, self.lastTime = netCounters, diskCounters, now
        data["gpu"] = self.gpuReader.read()
        data["cpuTemp"] = None
        if hasattr(psutil, "sensors_temperatures"):
            try:
                temperatures = psutil.sensors_temperatures()
                for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
                    if temperatures.get(key):
                        data["cpuTemp"] = temperatures[key][0].current
                        break
            except Exception:
                pass
        try:
            battery = psutil.sensors_battery()
            data["battery"] = {"percent": battery.percent, "plugged": battery.power_plugged} if battery else None
        except Exception:
            data["battery"] = None
        data["uptime"] = now - self.bootTime
        self.sampleIndex += 1
        if includeProcesses and self.sampleIndex % 3 == 1:
            data["processes"] = self._topProcesses()
        return data

    def _topProcesses(self):
        if self.snapshotter.available:
            try:
                return self.snapshotter.top(7)
            except Exception:
                self.snapshotter.available = False
        alive = set()
        rows = []
        for process in psutil.process_iter(["pid", "name"]):
            pid = process.info["pid"]
            if pid == 0:
                continue
            alive.add(pid)
            cached = self.processCache.get(pid)
            if cached is None:
                cached = process
                self.processCache[pid] = cached
                try:
                    cached.cpu_percent(None)
                except Exception:
                    pass
                continue
            try:
                cpuValue = cached.cpu_percent(None) / self.cpuCount
                memoryValue = cached.memory_info().rss
                rows.append({"name": process.info["name"] or str(pid), "cpu": cpuValue, "memory": memoryValue})
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        for pid in list(self.processCache):
            if pid not in alive:
                del self.processCache[pid]
        rows.sort(key=lambda row: (row["cpu"], row["memory"]), reverse=True)
        return rows[:7]


class SystemMonitorPlugin(PluginBase):
    pluginId = "system_monitor"
    name = T("Monitor PC", "PC Monitor")
    description = T("CPU, RAM, GPU, dischi e rete in tempo reale, con avvisi quando qualcosa esagera.",
                    "Live CPU, RAM, GPU, drives and network, with alerts when something goes overboard.")
    icon = "activity"
    version = "1.0.0"
    author = "PC Hub"
    settingsSchema = [
        Section(T("Monitoraggio", "Monitoring")),
        Slider("interval", T("Aggiornamento ogni", "Refresh every"), 500, 5000, 1000, step=250, suffix=" ms",
               icon="refresh-cw", pinnable=False),
        Toggle("trackProcesses", T("Mostra i processi più pesanti", "Show the heaviest processes"), True,
               icon="list-checks", pinnable=False),
        Section(T("Avvisi", "Alerts"), description=T("Ricevi una notifica quando un valore resta alto troppo a lungo.",
                                                    "Get notified when a value stays high for too long.")),
        Toggle("alertCpu", T("Avviso CPU alta", "High CPU alert"), False, icon="cpu"),
        Slider("cpuThreshold", T("Soglia CPU", "CPU threshold"), 50, 100, 90, suffix="%", visibleIf=("alertCpu", True),
               pinnable=False),
        Toggle("alertRam", T("Avviso RAM piena", "Full RAM alert"), False, icon="memory-stick"),
        Slider("ramThreshold", T("Soglia RAM", "RAM threshold"), 50, 100, 90, suffix="%", visibleIf=("alertRam", True),
               pinnable=False),
        Toggle("alertGpuTemp", T("Avviso temperatura GPU", "GPU temperature alert"), False, icon="thermometer"),
        Slider("gpuTempThreshold", T("Soglia temperatura GPU", "GPU temperature threshold"), 60, 100, 85, suffix=" °C",
               visibleIf=("alertGpuTemp", True), pinnable=False),
        Slider("alertDuration", T("Per almeno", "For at least"), 5, 120, 20, suffix=" s",
               visibleIf=lambda get: get("alertCpu") or get("alertRam") or get("alertGpuTemp"), pinnable=False),
    ]

    sampleReady = Signal(dict)

    def __init__(self, context):
        super().__init__(context)
        self.latest = None
        self.history = {key: collections.deque(maxlen=HISTORY_LENGTH)
                        for key in ("cpu", "ram", "gpu", "netUp", "netDown", "diskRead", "diskWrite", "gpuTemp")}
        self.sampler = None
        self.stopEvent = threading.Event()
        self.workerThread = None
        self.alertStates = {}
        self.pageVisible = False
        self.sampleReady.connect(self._onSample)

    def start(self):
        self.stopEvent.clear()
        if self.sampler is None:
            self.sampler = Sampler()
        self.workerThread = self.runInThread(self._loop, name="system-monitor")

    def stop(self):
        self.stopEvent.set()
        if self.workerThread is not None:
            self.workerThread.join(2)
            self.workerThread = None
        for alertKey in list(self.alertStates):
            self.context.removeActive(alertKey)
        self.alertStates = {}

    def _loop(self):
        while not self.stopEvent.is_set():
            startTime = time.time()
            data = self.sampler.sample(bool(self.setting("trackProcesses")) and self.pageVisible)
            if self.stopEvent.is_set():
                break
            self.sampleReady.emit(data)
            intervalSeconds = max(0.25, (self.setting("interval") or 1000) / 1000.0)
            self.stopEvent.wait(max(0.05, intervalSeconds - (time.time() - startTime)))

    def _onSample(self, data):
        if "processes" not in data and self.latest and "processes" in self.latest:
            data["processes"] = self.latest["processes"]
        self.latest = data
        self.history["cpu"].append(data["cpu"])
        self.history["ram"].append(data["ram"])
        gpuData = data.get("gpu")
        self.history["gpu"].append(gpuData["percent"] if gpuData else 0)
        self.history["gpuTemp"].append(gpuData["temperature"] if gpuData else 0)
        for key in ("netUp", "netDown", "diskRead", "diskWrite"):
            self.history[key].append(data[key])
        self._checkAlerts(data)

    def _checkAlerts(self, data):
        duration = self.setting("alertDuration") or 20
        gpuData = data.get("gpu") or {}
        checks = [
            ("cpu", self.setting("alertCpu"), data["cpu"], self.setting("cpuThreshold"), TEXT["alertCpuTitle"], "cpu",
             lambda value: f"{value:.0f}%"),
            ("ram", self.setting("alertRam"), data["ram"], self.setting("ramThreshold"), TEXT["alertRamTitle"],
             "memory-stick", lambda value: f"{value:.0f}%"),
            ("gpuTemp", self.setting("alertGpuTemp"), gpuData.get("temperature"), self.setting("gpuTempThreshold"),
             TEXT["alertGpuTitle"], "thermometer", lambda value: f"{value:.0f} °C"),
        ]
        now = data["time"]
        for alertKey, enabled, value, threshold, title, iconName, formatter in checks:
            state = self.alertStates.setdefault(alertKey, {"since": None, "notifiedAt": 0, "active": False})
            if not enabled or value is None or threshold is None or value < threshold:
                state["since"] = None
                if state["active"]:
                    state["active"] = False
                    self.context.removeActive(alertKey)
                continue
            if state["since"] is None:
                state["since"] = now
            if now - state["since"] >= duration:
                body = tr(TEXT["alertBody"], value=formatter(value), seconds=int(duration))
                self.context.setActive(ActiveItem(alertKey, tr(title), body, icon=iconName, accent=theme().danger))
                state["active"] = True
                if now - state["notifiedAt"] > 300:
                    state["notifiedAt"] = now
                    self.context.notify(tr(title), body, "notify")
                    self.context.emit("alert", kind=alertKey, value=value)

    def onSettingChanged(self, key, value):
        alertKeys = {"alertCpu": "cpu", "alertRam": "ram", "alertGpuTemp": "gpuTemp"}
        if key in alertKeys and not value:
            self.context.removeActive(alertKeys[key])
            self.alertStates.pop(alertKeys[key], None)

    def createPage(self):
        return MonitorPage(self)

    def homeWidgets(self):
        sizes = ["small", "wide", "tall", "large"]
        return [
            HomeWidgetSpec("system_monitor.cpu", TEXT["cpu"], lambda: MetricWidget(self, "cpu"),
                           T("Uso del processore con grafico.", "Processor usage with chart."), "cpu", "small", sizes),
            HomeWidgetSpec("system_monitor.ram", TEXT["ram"], lambda: MetricWidget(self, "ram"),
                           T("Memoria usata.", "Memory in use."), "memory-stick", "small", sizes),
            HomeWidgetSpec("system_monitor.gpu", TEXT["gpu"], lambda: MetricWidget(self, "gpu"),
                           T("Uso e temperatura della GPU NVIDIA.", "NVIDIA GPU usage and temperature."), "monitor",
                           "small", sizes),
            HomeWidgetSpec("system_monitor.disk", TEXT["disk"], lambda: MetricWidget(self, "disk"),
                           T("Spazio sul disco di sistema.", "Space on the system drive."), "hard-drive", "small",
                           ["small", "wide"]),
            HomeWidgetSpec("system_monitor.network", TEXT["network"], lambda: MetricWidget(self, "network"),
                           T("Velocità di download e upload.", "Download and upload speed."), "wifi", "small", sizes),
            HomeWidgetSpec("system_monitor.overview", TEXT["overview"], lambda: OverviewWidget(self),
                           T("CPU, RAM, GPU e disco in un colpo d'occhio.", "CPU, RAM, GPU and disk at a glance."),
                           "gauge", "wide", ["wide", "full", "small"]),
        ]


Plugin = SystemMonitorPlugin


def metricColor(kind):
    currentTheme = theme()
    return {"cpu": currentTheme.accentLight, "ram": "#38BDF8", "gpu": "#34D399", "disk": "#FBBF24",
            "network": "#F472B6"}.get(kind, currentTheme.accentLight)


class MetricWidget(QWidget):
    """Big value + subtitle + sparkline. Used on Home and on the plugin page."""

    def __init__(self, plugin, kind, parent=None, showTitle=False):
        super().__init__(parent)
        self.plugin = plugin
        self.kind = kind
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        if showTitle:
            layout.addWidget(makeLabel(tr(TEXT[kind]).upper(), "section"))
        valueRow = QHBoxLayout()
        self.valueLabel = makeStableLabel("—", "metric")
        valueRow.addWidget(self.valueLabel)
        valueRow.addStretch(1)
        self.sideLabel = makeStableLabel("", "faint")
        valueRow.addWidget(self.sideLabel, 0, Qt.AlignBottom)
        layout.addLayout(valueRow)
        self.subLabel = makeStableLabel("", "faint", True)
        layout.addWidget(self.subLabel)
        self.sparkline = Sparkline(metricColor(kind), 100 if kind in ("cpu", "ram", "gpu") else None)
        self.secondLine = None
        if kind == "disk":
            layout.addStretch(1)
            self.meter = MeterBar(metricColor(kind), 10)
            layout.addWidget(self.meter)
            self.sparkline = None
        else:
            layout.addWidget(self.sparkline, 1)
        plugin.sampleReady.connect(self.refresh)
        self.refresh()

    def refresh(self, *args):
        data = self.plugin.latest
        if not data:
            return
        history = self.plugin.history
        kind = self.kind
        if kind == "cpu":
            self.valueLabel.setText(f"{data['cpu']:.0f}%")
            frequency = data.get("cpuFreq")
            parts = [tr(TEXT["cores"], count=self.plugin.sampler.cpuCount)]
            if frequency:
                parts.insert(0, f"{frequency / 1000:.2f} GHz")
            if data.get("cpuTemp"):
                parts.append(f"{data['cpuTemp']:.0f} °C")
            self.subLabel.setText(" · ".join(parts))
            self.sparkline.setValues(history["cpu"])
        elif kind == "ram":
            self.valueLabel.setText(f"{data['ram']:.0f}%")
            self.subLabel.setText(f"{formatBytes(data['ramUsed'])} / {formatBytes(data['ramTotal'])}")
            self.sparkline.setValues(history["ram"])
        elif kind == "gpu":
            gpuData = data.get("gpu")
            if gpuData:
                self.valueLabel.setText(f"{gpuData['percent']:.0f}%")
                self.sideLabel.setText(f"{gpuData['temperature']:.0f} °C")
                self.subLabel.setText(f"{formatBytes(gpuData['memUsed'])} / {formatBytes(gpuData['memTotal'])}")
                self.sparkline.setValues(history["gpu"])
            else:
                self.valueLabel.setText("—")
                self.subLabel.setText(tr(TEXT["gpuNotAvailable"]))
        elif kind == "disk":
            disk = data.get("systemDisk")
            if disk:
                self.valueLabel.setText(f"{disk['percent']:.0f}%")
                self.sideLabel.setText(disk["mount"])
                self.subLabel.setText(tr(TEXT["free"], free=formatBytes(disk["free"]), total=formatBytes(disk["total"])))
                self.meter.setValue(disk["percent"] / 100)
        elif kind == "network":
            self.valueLabel.setText(formatRate(data["netDown"]))
            self.subLabel.setText(f"↑ {formatRate(data['netUp'])}")
            self.sparkline.setValues(history["netDown"])


class OverviewWidget(QWidget):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(14)
        layout.setVerticalSpacing(10)
        self.rows = {}
        for index, kind in enumerate(("cpu", "ram", "gpu", "disk")):
            nameLabel = makeLabel(tr(TEXT[kind]), "faint")
            valueLabel = makeStableLabel("—", "metricSmall")
            meter = MeterBar(metricColor(kind), 8)
            layout.addWidget(nameLabel, index, 0)
            layout.addWidget(meter, index, 1)
            layout.addWidget(valueLabel, index, 2, Qt.AlignRight)
            self.rows[kind] = (valueLabel, meter)
        layout.setColumnStretch(1, 1)
        plugin.sampleReady.connect(self.refresh)
        self.refresh()

    def refresh(self, *args):
        data = self.plugin.latest
        if not data:
            return
        gpuData = data.get("gpu")
        disk = data.get("systemDisk")
        values = {"cpu": data["cpu"], "ram": data["ram"], "gpu": gpuData["percent"] if gpuData else None,
                  "disk": disk["percent"] if disk else None}
        for kind, (valueLabel, meter) in self.rows.items():
            value = values[kind]
            valueLabel.setText("—" if value is None else f"{value:.0f}%")
            meter.setValue(0 if value is None else value / 100)


class MonitorPage(QWidget):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        metricsGrid = QGridLayout()
        metricsGrid.setSpacing(4)
        for index, kind in enumerate(("cpu", "ram", "gpu", "network")):
            card = Card(padding=14)
            cardLayout = QVBoxLayout(card)
            cardLayout.addWidget(MetricWidget(plugin, kind, showTitle=True))
            card.setMinimumHeight(170)
            metricsGrid.addWidget(card, 0, index)
        layout.addLayout(metricsGrid)

        middleGrid = QGridLayout()
        middleGrid.setSpacing(4)
        self.disksCard = Card(padding=16)
        disksLayout = QVBoxLayout(self.disksCard)
        disksLayout.addWidget(makeLabel(tr(TEXT["disks"]).upper(), "section"))
        self.disksListLayout = QVBoxLayout()
        self.disksListLayout.setSpacing(10)
        disksLayout.addLayout(self.disksListLayout)
        ioRow = QHBoxLayout()
        self.diskIoLabel = makeStableLabel("", "faint")
        ioRow.addWidget(self.diskIoLabel)
        disksLayout.addLayout(ioRow)
        disksLayout.addStretch(1)
        middleGrid.addWidget(self.disksCard, 0, 0)

        self.systemCard = Card(padding=16)
        systemLayout = QVBoxLayout(self.systemCard)
        systemLayout.addWidget(makeLabel(tr(TEXT["system"]).upper(), "section"))
        self.systemInfoLayout = QGridLayout()
        self.systemInfoLayout.setHorizontalSpacing(16)
        self.systemInfoLayout.setVerticalSpacing(8)
        systemLayout.addLayout(self.systemInfoLayout)
        systemLayout.addStretch(1)
        self.infoLabels = {}
        middleGrid.addWidget(self.systemCard, 0, 1)
        layout.addLayout(middleGrid)

        self.processCard = Card(padding=16)
        processLayout = QVBoxLayout(self.processCard)
        processLayout.addWidget(makeLabel(tr(TEXT["processes"]).upper(), "section"))
        self.processTable = QTableWidget(0, 3)
        self.processTable.setHorizontalHeaderLabels([tr(TEXT["process"]), "CPU", tr(TEXT["memory"])])
        self.processTable.verticalHeader().hide()
        self.processTable.setShowGrid(False)
        self.processTable.setEditTriggers(QTableWidget.NoEditTriggers)
        self.processTable.setSelectionMode(QTableWidget.NoSelection)
        self.processTable.setFocusPolicy(Qt.NoFocus)
        header = self.processTable.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.processTable.setMinimumHeight(250)
        processLayout.addWidget(self.processTable)
        layout.addWidget(self.processCard)
        plugin.sampleReady.connect(self.refresh)
        self.diskSignature = None
        self.refresh()

    def _setInfo(self, row, label, value):
        if label not in self.infoLabels:
            self.systemInfoLayout.addWidget(makeLabel(label, "faint"), row, 0)
            valueLabel = makeStableLabel(value)
            valueLabel.setWordWrap(True)
            self.systemInfoLayout.addWidget(valueLabel, row, 1)
            self.infoLabels[label] = valueLabel
        else:
            self.infoLabels[label].setText(value)

    def refresh(self, *args):
        data = self.plugin.latest
        if not data or not self.isVisible():
            return
        disks = data.get("disks", [])
        signature = tuple(disk["mount"] for disk in disks)
        if signature != self.diskSignature:
            self.diskSignature = signature
            clearLayout(self.disksListLayout)
            self.diskRows = {}
            for disk in disks:
                rowLayout = QVBoxLayout()
                rowLayout.setSpacing(4)
                topRow = QHBoxLayout()
                nameLabel = makeLabel(disk["mount"])
                valueLabel = makeStableLabel("", "faint")
                topRow.addWidget(nameLabel)
                topRow.addStretch(1)
                topRow.addWidget(valueLabel)
                rowLayout.addLayout(topRow)
                meter = MeterBar(metricColor("disk"), 8)
                rowLayout.addWidget(meter)
                self.disksListLayout.addLayout(rowLayout)
                self.diskRows[disk["mount"]] = (valueLabel, meter)
        for disk in disks:
            valueLabel, meter = self.diskRows[disk["mount"]]
            valueLabel.setText(tr(TEXT["free"], free=formatBytes(disk["free"]), total=formatBytes(disk["total"])))
            meter.setValue(disk["percent"] / 100)
            meter.setColor(theme().danger if disk["percent"] > 90 else metricColor("disk"))
        self.diskIoLabel.setText(f"{tr(TEXT['read'])} {formatRate(data['diskRead'])} · "
                                 f"{tr(TEXT['write'])} {formatRate(data['diskWrite'])}")
        sampler = self.plugin.sampler
        self._setInfo(0, tr(TEXT["cpu"]), f"{sampler.cpuName} · {tr(TEXT['cores'], count=sampler.cpuCount)}")
        gpuData = data.get("gpu")
        self._setInfo(1, tr(TEXT["gpu"]), gpuData["name"] if gpuData else tr(TEXT["gpuNotAvailable"]))
        if gpuData:
            extras = [f"{gpuData['temperature']:.0f} °C"]
            if gpuData.get("power"):
                extras.append(f"{gpuData['power']:.0f} W")
            if gpuData.get("fan") is not None:
                extras.append(f"Fan {gpuData['fan']:.0f}%")
            self._setInfo(2, tr(TEXT["temperature"]), " · ".join(extras))
        self._setInfo(3, tr(TEXT["uptime"]), formatUptime(data["uptime"]))
        self._setInfo(4, "OS", f"{platform.system()} {platform.release()}")
        if data.get("battery"):
            battery = data["battery"]
            self._setInfo(5, tr(TEXT["battery"]),
                          f"{battery['percent']:.0f}%" + (f" · {tr(TEXT['charging'])}" if battery["plugged"] else ""))
        processes = data.get("processes") or []
        self.processCard.setVisible(bool(self.plugin.setting("trackProcesses")))
        self.processTable.setRowCount(len(processes))
        for row, process in enumerate(processes):
            for column, text in enumerate((process["name"], f"{process['cpu']:.1f}%", formatBytes(process["memory"]))):
                item = self.processTable.item(row, column)
                if item is None:
                    item = QTableWidgetItem()
                    if column:
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.processTable.setItem(row, column, item)
                item.setText(text)

    def showEvent(self, event):
        super().showEvent(event)
        self.plugin.pageVisible = True
        self.refresh()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.plugin.pageVisible = False
