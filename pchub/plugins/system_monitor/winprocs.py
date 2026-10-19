"""All processes in ONE system call (NtQuerySystemInformation), like Task Manager does.

psutil asks Windows about each process separately, and for protected ones (no admin) it falls back to a full system
snapshot per process: hundreds of processes -> hundreds of snapshots every refresh. This reads one snapshot."""
import ctypes
import time

from pchub.core.paths import isWindows

SYSTEM_PROCESS_INFORMATION_CLASS = 5
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004


class UNICODE_STRING(ctypes.Structure):
    _fields_ = [("Length", ctypes.c_ushort), ("MaximumLength", ctypes.c_ushort), ("Buffer", ctypes.c_void_p)]


class SYSTEM_PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("NextEntryOffset", ctypes.c_uint32), ("NumberOfThreads", ctypes.c_uint32),
                ("WorkingSetPrivateSize", ctypes.c_longlong), ("HardFaultCount", ctypes.c_uint32),
                ("NumberOfThreadsHighWatermark", ctypes.c_uint32), ("CycleTime", ctypes.c_ulonglong),
                ("CreateTime", ctypes.c_longlong), ("UserTime", ctypes.c_longlong), ("KernelTime", ctypes.c_longlong),
                ("ImageName", UNICODE_STRING), ("BasePriority", ctypes.c_int32), ("UniqueProcessId", ctypes.c_void_p),
                ("InheritedFromUniqueProcessId", ctypes.c_void_p), ("HandleCount", ctypes.c_uint32),
                ("SessionId", ctypes.c_uint32), ("UniqueProcessKey", ctypes.c_size_t), ("PeakVirtualSize", ctypes.c_size_t),
                ("VirtualSize", ctypes.c_size_t), ("PageFaultCount", ctypes.c_uint32),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t)]


def parseSnapshot(buffer):
    """[(pid, name, cpuTime100ns, memoryBytes)] from a SystemProcessInformation buffer."""
    rows = []
    offset = 0
    total = len(buffer)
    while offset + ctypes.sizeof(SYSTEM_PROCESS_INFORMATION) <= total:
        info = SYSTEM_PROCESS_INFORMATION.from_buffer(buffer, offset)
        pid = int(info.UniqueProcessId or 0)
        if pid:
            name = ""
            if info.ImageName.Buffer and info.ImageName.Length:
                name = ctypes.wstring_at(info.ImageName.Buffer, info.ImageName.Length // 2)
            memory = info.WorkingSetPrivateSize if info.WorkingSetPrivateSize > 0 else info.WorkingSetSize
            rows.append((pid, name or str(pid), info.UserTime + info.KernelTime, int(memory)))
        if not info.NextEntryOffset:
            break
        offset += info.NextEntryOffset
    return rows


class ProcessSnapshotter:
    def __init__(self, cpuCount):
        self.cpuCount = max(1, cpuCount)
        self.size = 1 << 20
        self.buffer = None
        self.lastTimes = {}
        self.lastWall = None
        self.available = isWindows
        if isWindows:
            self.ntdll = ctypes.WinDLL("ntdll")
            self.ntdll.NtQuerySystemInformation.argtypes = [ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong,
                                                            ctypes.POINTER(ctypes.c_ulong)]
            self.ntdll.NtQuerySystemInformation.restype = ctypes.c_ulong

    def _snapshot(self):
        for _attempt in range(6):
            if self.buffer is None or len(self.buffer) < self.size:
                self.buffer = ctypes.create_string_buffer(self.size)
            needed = ctypes.c_ulong(0)
            status = self.ntdll.NtQuerySystemInformation(SYSTEM_PROCESS_INFORMATION_CLASS, self.buffer, self.size,
                                                         ctypes.byref(needed))
            if status == STATUS_INFO_LENGTH_MISMATCH:
                self.size = max(self.size * 2, needed.value + 65536)
                continue
            if status != 0:
                raise OSError(f"NtQuerySystemInformation failed: 0x{status:08X}")
            return parseSnapshot(self.buffer)
        raise OSError("process list kept growing")

    def top(self, count=7):
        """Heaviest processes: [{"name", "cpu" (% of the whole CPU), "memory" (private working set)}]."""
        now = time.monotonic()
        rows = self._snapshot()
        elapsed = (now - self.lastWall) if self.lastWall else None
        result = []
        times = {}
        for pid, name, cpuTime, memory in rows:
            times[pid] = cpuTime
            previous = self.lastTimes.get(pid)
            if elapsed and previous is not None:
                cpuValue = max(0.0, (cpuTime - previous) / (elapsed * 1e7) * 100.0 / self.cpuCount)
                result.append({"name": name, "cpu": cpuValue, "memory": memory})
        self.lastTimes = times
        self.lastWall = now
        result.sort(key=lambda row: (row["cpu"], row["memory"]), reverse=True)
        return result[:count]
