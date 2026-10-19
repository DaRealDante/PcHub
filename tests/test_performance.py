"""Guards for the CPU optimisations (they must not change behaviour)."""
import ctypes

import numpy


def test_map_faces_back_to_full_frame():
    from pchub.plugins.oled_saver.vision import _mapFaces
    row = [10, 20, 30, 40] + [1, 2] * 5 + [0.9]
    mapped = _mapFaces([row], 0.5, 100, 200)[0]
    assert mapped[:4] == [120, 240, 60, 80] and mapped[4:6] == [102, 204] and mapped[14] == 0.9


def test_face_finder_full_then_crop(monkeypatch):
    from pchub.plugins.oled_saver import vision
    finder = vision.FaceFinder(0.7)
    sizes = []

    def fakeDetect(image):
        height, width = image.shape[:2]
        sizes.append((width, height))
        if width == vision.ROI_WIDTH:
            return [[65, 65, 93, 93] + [110, 110] * 5 + [0.95]]
        return [[150, 100, 60, 60] + [180, 130] * 5 + [0.95]]

    monkeypatch.setattr(finder, "_detect", fakeDetect)
    frame = numpy.full((480, 640, 3), 150, numpy.uint8)
    faces = finder.find(frame, now=0.0)
    assert sizes[0] == (vision.DETECT_WIDTH, 300) and sizes[1] == (vision.ROI_WIDTH, vision.ROI_WIDTH)
    assert faces and finder.lastBox is not None
    sizes.clear()
    for index in range(5):
        finder.find(frame, now=0.1 + index * 0.1)
    assert all(size == (vision.ROI_WIDTH, vision.ROI_WIDTH) for size in sizes), "between full scans only the crop runs"
    sizes.clear()
    finder.find(frame, now=5.0)
    assert sizes[0] == (vision.DETECT_WIDTH, 300), "a full scan still happens every second"


def test_process_snapshot_parser_and_cpu_math(monkeypatch):
    from pchub.plugins.system_monitor import winprocs
    structure = winprocs.SYSTEM_PROCESS_INFORMATION
    assert structure.UniqueProcessId.offset == 80 and structure.WorkingSetSize.offset == 144, "Windows x64 layout"
    names = [ctypes.create_unicode_buffer("chrome.exe")]
    size = ctypes.sizeof(structure) + 32
    buffer = ctypes.create_string_buffer(size * 2)
    for index, (pid, memory) in enumerate(((0, 0), (77, 4096))):
        entry = structure.from_buffer(buffer, index * size)
        entry.NextEntryOffset = size if index == 0 else 0
        entry.UniqueProcessId = pid
        entry.UserTime = 5
        entry.WorkingSetPrivateSize = memory
        if pid:
            entry.ImageName.Buffer = ctypes.cast(names[0], ctypes.c_void_p)
            entry.ImageName.Length = len(names[0].value) * 2
    assert winprocs.parseSnapshot(buffer) == [(77, "chrome.exe", 5, 4096)]
    snapshotter = winprocs.ProcessSnapshotter(4)
    clock = {"now": 100.0, "times": 0}
    monkeypatch.setattr(winprocs.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(snapshotter, "_snapshot", lambda: [(77, "chrome.exe", clock["times"], 4096)])
    assert snapshotter.top() == []
    clock["now"], clock["times"] = 101.0, 2 * 10 ** 7
    top = snapshotter.top()
    assert top[0]["name"] == "chrome.exe" and abs(top[0]["cpu"] - 50.0) < 1e-6, "2 s of CPU in 1 s on 4 cores = 50%"


def test_hook_moves_only_to_who_asks():
    from pchub.core.input_hooks import HookService, MouseEvent, WM_LBUTTONDOWN, WM_MOUSEMOVE
    service = HookService()
    received = {"plain": [], "mover": []}
    service.subscribe("plain", mouseCallback=lambda event: received["plain"].append(event.message))
    service.subscribe("mover", mouseCallback=lambda event: received["mover"].append(event.message), wantsMoves=True)
    service.dispatchMouse(MouseEvent(WM_MOUSEMOVE, 1, 1))
    service.dispatchMouse(MouseEvent(WM_LBUTTONDOWN, 1, 1))
    assert received["plain"] == [WM_LBUTTONDOWN] and received["mover"] == [WM_MOUSEMOVE, WM_LBUTTONDOWN]
    assert service.lastRealInput > 0


def test_stable_label_never_shrinks(qtApp):
    from pchub.ui.widgets import makeStableLabel
    label = makeStableLabel("100%", "metric")
    wide = label.sizeHint().width()
    label.setText("1%")
    assert label.sizeHint().width() == wide


def test_timer_ticks_only_when_needed(qtApp, dataDir):
    from test_oled import makeOledPlugin
    manager, _plugin = makeOledPlugin(dataDir)
    manager.startPlugin("timer")
    timer = manager.records["timer"].instance
    assert not timer.tickTimer.isActive()
    timer.addTimer(60, "Pasta")
    assert timer.tickTimer.isActive()
    timer.pauseTimer(timer.timers[0]["id"])
    assert not timer.tickTimer.isActive()
    manager.stopAll()
