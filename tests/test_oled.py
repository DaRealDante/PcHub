import math

import pytest
from conftest import processEvents

from pchub.plugins.oled_saver.logic import (MODE_AWAY, MODE_DIM, MODE_MANUAL, MODE_NORMAL, DimController,
                                            PresenceTracker, estimatePose, pickMainFace, thresholdsFor)


def faceRow(yawOffset=0.0, pitchRatio=0.55, roll=0.0, size=100.0, x=200.0, y=150.0):
    """Synthetic YuNet row: eyes 60px apart, mouth 60px below the eyes."""
    eyeA = (-30.0, 0.0)
    eyeB = (30.0, 0.0)
    nose = (yawOffset * 60.0, pitchRatio * 60.0)
    mouthA = (-22.0, 60.0)
    mouthB = (22.0, 60.0)
    angle = math.radians(roll)

    def place(point):
        rotatedX = point[0] * math.cos(angle) - point[1] * math.sin(angle)
        rotatedY = point[0] * math.sin(angle) + point[1] * math.cos(angle)
        return x + rotatedX, y + rotatedY

    points = [place(point) for point in (eyeA, eyeB, nose, mouthA, mouthB)]
    row = [x - size / 2, y - size / 2, size, size]
    for pointX, pointY in points:
        row += [pointX, pointY]
    return row + [0.95]


def test_pose_estimation_frontal_turned_and_rolled():
    frontal = estimatePose(faceRow())
    assert abs(frontal.yaw) < 1e-6 and abs(frontal.pitch - 0.55) < 1e-6
    turned = estimatePose(faceRow(yawOffset=0.5))
    assert abs(turned.yaw - 0.5) < 1e-6
    rolled = estimatePose(faceRow(yawOffset=0.3, pitchRatio=0.7, roll=25))
    assert abs(rolled.yaw - 0.3) < 1e-6 and abs(rolled.pitch - 0.7) < 1e-6, "head tilt (roll) must not change yaw/pitch"
    assert abs(rolled.roll - 25) < 1e-6


def test_pick_main_face_is_largest():
    small = faceRow(size=50)
    big = faceRow(size=180)
    assert pickMainFace([small, big]) is big
    assert pickMainFace([]) is None and pickMainFace(None) is None


def test_thresholds_get_stricter_with_sensitivity():
    lowYaw, lowDown, _ = thresholdsFor(1)
    highYaw, highDown, _ = thresholdsFor(10)
    assert lowYaw > highYaw and lowDown > highDown
    assert thresholdsFor(99) == thresholdsFor(10)


def test_tracker_confirms_presence_absence_and_distraction():
    tracker = PresenceTracker()
    tracker.update(0, estimatePose(faceRow()), confirmFrames=3)
    assert tracker.present is None
    tracker.update(1, estimatePose(faceRow()), confirmFrames=3)
    assert tracker.present is True and not tracker.distracted, "coming back is confirmed after 2 frames"
    tracker.update(2, estimatePose(faceRow()), confirmFrames=3)
    for frame in range(3, 8):
        tracker.update(frame, estimatePose(faceRow(yawOffset=0.7)), confirmFrames=3, sensitivity=5)
    assert tracker.distracted and tracker.distractedSince is not None
    since = tracker.distractedSince
    tracker.update(8, estimatePose(faceRow(yawOffset=0.7)), confirmFrames=3)
    assert tracker.distractedSince == since, "distractedSince doesn't move while still distracted"
    for frame in range(9, 14):
        tracker.update(frame, estimatePose(faceRow()), confirmFrames=3)
    assert not tracker.distracted and tracker.attentive()
    for frame in range(14, 16):
        tracker.update(frame, None, confirmFrames=3)
    assert tracker.present is True, "a couple of missed frames are not enough"
    tracker.update(16, None, confirmFrames=3)
    assert tracker.present is False and tracker.absentSince == 16


def test_tracker_look_down_option_and_calibration():
    def settle(lookDown, basePitch=0.55, pitch=0.8):
        tracker = PresenceTracker()
        for frame in range(10):
            tracker.update(frame, estimatePose(faceRow(pitchRatio=pitch)), confirmFrames=1, sensitivity=5,
                           lookDownCounts=lookDown, basePitch=basePitch)
        return tracker

    assert settle(True).distracted
    assert not settle(False).distracted
    assert not settle(True, basePitch=0.78).distracted, "calibrating with a lower webcam angle accepts that pose"


class FakeTracker:
    def __init__(self, present=None, distracted=False, distractedSince=None, absentSince=None):
        self.present = present
        self.distracted = distracted
        self.distractedSince = distractedSince
        self.absentSince = absentSince

    def attentive(self):
        return self.present is True and not self.distracted


SETTINGS = {"autoBlackout": True, "awayDelay": 10, "blackoutLevel": 100, "distraction": True, "distractionDelay": 4,
            "startDim": 40, "dimStep": 15, "dimInterval": 4, "maxDim": 85, "wakeOnLook": True}


def makeController(**overrides):
    values = dict(SETTINGS, **overrides)
    return DimController(values.get)


def test_distraction_dims_progressively_and_input_wakes():
    controller = makeController()
    tracker = FakeTracker(True, True, distractedSince=100)
    assert controller.update(102, 90, tracker)[0] == MODE_NORMAL, "not distracted long enough yet"
    mode, level = controller.update(104, 90, tracker)
    assert mode == MODE_DIM and abs(level - 0.40) < 1e-9
    assert abs(controller.update(108.1, 90, tracker)[1] - 0.55) < 1e-9
    assert abs(controller.update(112.1, 90, tracker)[1] - 0.70) < 1e-9
    assert abs(controller.update(200, 90, tracker)[1] - 0.85) < 1e-9, "never above maxDim"
    mode, level = controller.update(201, 200.5, tracker)
    assert mode == MODE_NORMAL and level == 0, "any input wakes immediately"
    assert controller.update(202, 200.5, tracker)[0] == MODE_NORMAL, "after input you must be idle again before dimming"


def test_wake_on_look_and_latch():
    controller = makeController()
    distracted = FakeTracker(True, True, distractedSince=100)
    controller.update(110, 0, distracted)
    assert controller.mode == MODE_DIM
    assert controller.update(111, 0, FakeTracker(True, False))[0] == MODE_NORMAL
    latched = makeController(wakeOnLook=False)
    latched.update(110, 0, distracted)
    mode, level = latched.update(120, 0, FakeTracker(True, False))
    assert mode == MODE_DIM and level > 0.4, "without wakeOnLook it keeps getting darker until input"
    assert latched.update(121, 120.5, FakeTracker(True, False))[0] == MODE_NORMAL


def test_away_blackout_and_return():
    controller = makeController()
    absent = FakeTracker(False, absentSince=100)
    assert controller.update(105, 0, absent)[0] == MODE_NORMAL
    mode, level = controller.update(110, 0, absent)
    assert mode == MODE_AWAY and level == 1.0
    assert controller.update(111, 0, FakeTracker(True, True, distractedSince=111))[0] == MODE_AWAY, \
        "back but looking at the phone: stay black"
    assert controller.update(112, 0, FakeTracker(True, False))[0] == MODE_NORMAL
    noAuto = makeController(autoBlackout=False)
    assert noAuto.update(500, 0, absent)[0] == MODE_NORMAL
    recentInput = makeController()
    assert recentInput.update(110, 105, absent)[0] == MODE_NORMAL, "typing means you're there even if the camera can't see you"


def test_manual_blackout_grace_and_blocked():
    controller = makeController(blackoutLevel=90)
    controller.startManual(50)
    assert controller.update(50.3, 50.2, FakeTracker())[0] == MODE_MANUAL, "releasing the hotkey doesn't wake"
    assert controller.update(60, 50.2, FakeTracker(), blocked=True) == (MODE_MANUAL, 0.9), "manual works even if paused"
    assert controller.update(61, 60.5, FakeTracker())[0] == MODE_NORMAL
    blocked = makeController()
    assert blocked.update(200, 0, FakeTracker(False, absentSince=0), blocked=True)[0] == MODE_NORMAL


def test_yunet_model_loads_and_runs(qtApp):
    cv2 = pytest.importorskip("cv2")
    import numpy
    from pchub.plugins.oled_saver.vision import MODEL_PATH, createDetector, detectFaces, framePreview
    assert MODEL_PATH.exists()
    detector = createDetector(640, 480, 0.7)
    frame = numpy.zeros((480, 640, 3), dtype=numpy.uint8)
    assert detectFaces(detector, frame) == []
    image, scale = framePreview(frame)
    assert image.width() == 360 and abs(scale - 360 / 640) < 1e-9


def makeOledPlugin(dataDir):
    from pchub.core.active_registry import ActiveRegistry
    from pchub.core.events import EventBus
    from pchub.core.hotkeys import HotkeyManager
    from pchub.core.plugin_manager import PluginManager
    from pchub.core.storage import JsonStore
    appStore = JsonStore(dataDir / "app.json")
    manager = PluginManager(appStore, ActiveRegistry(), EventBus(), HotkeyManager(), lambda: False)
    manager.discover(includeUser=False)
    manager.instantiateAll()
    return manager, manager.records["oled_saver"].instance


class FakeCamera:
    def __init__(self):
        self.running = False
        self.starts = 0

    def isRunning(self):
        return self.running

    def start(self):
        self.running = True
        self.starts += 1

    def stop(self, wait=True):
        self.running = False


def test_plugin_end_to_end_with_fake_camera(qtApp, dataDir):
    manager, plugin = makeOledPlugin(dataDir)
    events = []
    manager.events.subscribe("*", lambda name, payload: events.append(name))
    manager.startPlugin("oled_saver")
    assert manager.records["oled_saver"].status == "running"
    plugin.tickTimer.stop()
    plugin.camera.stop()
    camera = FakeCamera()
    plugin.camera = camera
    clock = {"now": 1000.0}
    lastInput = {"at": 1000.0}
    plugin.clock = lambda: clock["now"]
    plugin.lastInputProvider = lambda: lastInput["at"]
    plugin.environmentBlock = lambda now: (None,)
    plugin.tick()
    assert not camera.running, "camera stays off while you're using the PC"
    clock["now"] = 1004.0
    plugin.tick()
    assert camera.running, "camera starts after idleBeforeCamera seconds"

    def feed(row, seconds=1.0, fps=6):
        for _ in range(int(seconds * fps)):
            clock["now"] += 1.0 / fps
            plugin._onFrame({"faces": [row] if row else [], "preview": None, "scale": 1.0})
            plugin.tick()

    feed(faceRow(), 1)
    assert plugin.tracker.attentive() and plugin.controller.mode == "normal"
    feed(faceRow(yawOffset=0.8), 5)
    assert plugin.controller.mode == "dim" and plugin.overlay.target >= 0.4
    assert "oled_saver.distracted" in events
    feed(faceRow(), 1)
    assert plugin.controller.mode == "normal" and plugin.overlay.target == 0
    assert "oled_saver.back" in events
    feed(None, 12)
    assert plugin.controller.mode == "away" and plugin.overlay.target == 1.0
    lastInput["at"] = clock["now"] + 0.01
    clock["now"] += 0.1
    plugin.tick()
    assert plugin.controller.mode == "normal"
    plugin.pause(30)
    assert plugin.isPaused() and manager.activeRegistry.count() == 1
    feed(None, 15)
    assert plugin.controller.mode == "normal", "paused: never dims"
    plugin.resume()
    assert not plugin.isPaused() and manager.activeRegistry.count() == 0
    plugin.toggleManual()
    assert plugin.controller.mode == "manual" and plugin.overlay.target == 1.0
    plugin.toggleManual()
    assert plugin.controller.mode == "normal"
    processEvents(50)
    manager.stopAll()
    assert plugin.overlay is None


def test_calibration_flow(qtApp, dataDir):
    manager, plugin = makeOledPlugin(dataDir)
    manager.startPlugin("oled_saver")
    plugin.tickTimer.stop()
    plugin.camera.stop()
    plugin.camera = FakeCamera()
    clock = {"now": 10.0}
    plugin.clock = lambda: clock["now"]
    plugin.lastInputProvider = lambda: clock["now"]
    plugin.environmentBlock = lambda now: (None,)
    phases = []
    plugin.calibrationChanged.connect(lambda phase, message: phases.append(phase))
    plugin.startCalibration()
    assert plugin.camera.running, "calibrating turns the webcam on even while you use the PC"
    for _ in range(30):
        clock["now"] += 1 / 6
        plugin._onFrame({"faces": [faceRow(yawOffset=0.1, pitchRatio=0.7)], "preview": None, "scale": 1.0})
        plugin.tick()
    assert phases[-1] == "done"
    baseYaw, basePitch = plugin.calibration()
    assert abs(baseYaw - 0.1) < 1e-6 and abs(basePitch - 0.7) < 1e-6
    assert plugin.isCalibrated()
    plugin.resetCalibration()
    assert not plugin.isCalibrated()
    plugin.startCalibration()
    clock["now"] += 13
    plugin.tick()
    assert phases[-1] == "failed"
    manager.stopAll()


def test_overlay_controller_fades(qtApp):
    import time
    from pchub.plugins.oled_saver.overlay import OverlayController
    overlay = OverlayController()
    overlay.setTarget(0.8, 120)
    processEvents(250)
    assert abs(overlay.level - 0.8) < 1e-6
    assert overlay.windows and all(window.isVisible() for window in overlay.windows)
    overlay.setTarget(0.0, 0)
    assert overlay.level == 0 and not any(window.isVisible() for window in overlay.windows)
    overlay.setTarget(1.0, 0)
    assert overlay.windows[0].cursorHidden
    overlay.shutdown()


def test_screen_selection(qtApp, tmp_path, monkeypatch):
    from PySide6.QtGui import QGuiApplication
    from pchub.plugins.oled_saver.overlay import OverlayController, isScreenSelected, screenKey
    screen = QGuiApplication.primaryScreen()
    assert isScreenSelected(screen, None)
    assert isScreenSelected(screen, [screenKey(screen)])
    assert not isScreenSelected(screen, ["other|123"])
    overlay = OverlayController()
    overlay.setSelectedScreens(["other|123"])
    overlay.setTarget(1.0, 0)
    assert overlay.windows == []
    overlay.setSelectedScreens(None)
    overlay.setTarget(0.5, 0)
    assert len(overlay.windows) == len(QGuiApplication.screens())
    overlay.shutdown()


def test_plugin_screen_toggle_keeps_one(qtApp, dataDir):
    from PySide6.QtGui import QGuiApplication
    from pchub.plugins.oled_saver.screen_picker import ScreenPicker
    manager, plugin = makeOledPlugin(dataDir)
    assert plugin.selectedScreenKeys() is None
    plugin.setSetting("screens", "primary")
    assert len(plugin.selectedScreenKeys()) == 1
    plugin.setSetting("screens", "all")
    screens = QGuiApplication.screens()
    plugin.toggleScreen(screens[0])
    if len(screens) == 1:
        assert plugin.lastScreenWarning and plugin.selectedScreenKeys() is None
    picker = ScreenPicker(plugin)
    picker.resize(360, 200)
    picker.grab()
    picker.identify()
    picker._closeIdentify()


def test_look_to_wake_ignores_input_while_distracted():
    controller = makeController(lookToWake=True)
    tracker = FakeTracker(True, True, distractedSince=100)
    assert controller.update(104, 90, tracker)[0] == MODE_DIM
    assert controller.update(105, 104.5, tracker)[0] == MODE_DIM, "mouse moved but still looking away"
    assert controller.update(106, 105.5, tracker, visionOk=False)[0] == MODE_NORMAL, "camera blind -> input wakes"
    assert controller.update(111, 105.5, tracker)[0] == MODE_DIM
    tracker.distracted = False
    assert controller.update(112, 111.5, tracker)[0] == MODE_NORMAL, "looking back wakes"


def test_look_to_wake_face_lost_input_wakes():
    controller = makeController(lookToWake=True)
    tracker = FakeTracker(True, True, distractedSince=100)
    assert controller.update(104, 90, tracker)[0] == MODE_DIM
    tracker.present = False
    assert controller.update(105, 104.5, tracker)[0] == MODE_NORMAL


def test_enhance_dark_finds_more_light():
    import numpy
    from pchub.plugins.oled_saver.vision import enhanceDark, isDark
    frame = numpy.full((120, 160, 3), 20, dtype=numpy.uint8)
    assert isDark(frame)
    assert enhanceDark(frame).mean() > frame.mean() * 2


def test_coming_back_is_fast_leaving_is_careful():
    tracker = PresenceTracker()
    for frame in range(6):
        tracker.update(frame, estimatePose(faceRow(yawOffset=0.7)), confirmFrames=3)
    assert tracker.distracted
    tracker.update(6, estimatePose(faceRow()), confirmFrames=3)
    tracker.update(7, estimatePose(faceRow()), confirmFrames=3)
    assert tracker.distracted, "two frames are not enough"
    tracker.update(8, estimatePose(faceRow()), confirmFrames=3)
    assert tracker.attentive(), "three clear frames looking back wake it"
    tracker.update(9, estimatePose(faceRow(yawOffset=0.7)), confirmFrames=3)
    assert not tracker.distracted, "one frame looking away is smoothed out"


def test_jitter_while_looking_away_never_wakes():
    import random
    from pchub.plugins.oled_saver.logic import limitsFor
    generator = random.Random(4)
    tracker = PresenceTracker()
    limits = limitsFor(5, True, [(0.45, 0.55)], 0.0, 0.55)
    lookingLeft = 0.40
    for frame in range(300):
        noise = generator.gauss(0, 0.08)
        if frame % 37 == 0:
            tracker.update(frame, None, confirmFrames=3, limits=limits)
            continue
        if frame % 23 == 0:
            noise = -0.3
        tracker.update(frame, estimatePose(faceRow(yawOffset=lookingLeft + noise)), confirmFrames=3, limits=limits)
        if frame > 10:
            assert not tracker.attentive(), f"woke at frame {frame}"


def test_lost_face_keeps_distraction_and_low_score_frames_dont_wake():
    tracker = PresenceTracker()
    for frame in range(6):
        tracker.update(frame, estimatePose(faceRow(yawOffset=0.7)), confirmFrames=3)
    assert tracker.distracted
    for frame in range(6, 10):
        tracker.update(frame, None, confirmFrames=3)
    assert tracker.present is False and tracker.distracted
    for frame in range(10, 16):
        row = faceRow()
        row[-1] = 0.6
        tracker.update(frame, estimatePose(row), confirmFrames=3)
    assert tracker.distracted, "uncertain detections don't count as looking back"
    for frame in range(16, 19):
        tracker.update(frame, estimatePose(faceRow()), confirmFrames=3)
    assert tracker.attentive()


def test_calibrated_limits_follow_recorded_poses():
    from pchub.plugins.oled_saver.logic import classifyDistraction, isLookingAway, limitsFor
    standard = limitsFor(5)
    phone = (0.0, 0.55 + 0.6)
    custom = limitsFor(5, True, [phone], 0.0, 0.55)
    assert classifyDistraction(0.0, 0.6) == "down"
    assert custom["down"] > standard["down"], "phone far below -> looking at the keyboard no longer counts"
    assert custom["left"] == standard["left"] and custom["right"] == standard["right"]
    assert not isLookingAway(0.0, standard["down"] * 1.2, custom)
    assert isLookingAway(0.0, 0.5, custom)
    side = limitsFor(5, False, [(0.2, 0.55)], 0.0, 0.55)
    assert side["left"] < standard["left"] and side["down"] is None
    assert classifyDistraction(0.4, 0.0) == "left" and classifyDistraction(-0.4, 0.0) == "right"


def test_distraction_recording_flow(qtApp, dataDir):
    from pchub.plugins.oled_saver.logic import Pose
    manager, plugin = makeOledPlugin(dataDir)
    messages = []
    plugin.distractionCalibrationChanged.connect(lambda phase, message: messages.append(phase))
    clock = {"now": 100.0}
    plugin.clock = lambda: clock["now"]
    plugin.startDistractionRecording()
    clock["now"] = 103.1
    plugin._advanceDistraction(clock["now"])
    assert plugin.distractionPhase == "collecting"
    plugin.distractionSamples = [(0.0, 1.2)] * 6
    clock["now"] = 104.8
    plugin._advanceDistraction(clock["now"])
    assert messages[-1] == "done" and plugin.setting("distractionMode") == "calibrated"
    assert plugin.currentLimits()["down"] > limitsDefault()["down"]
    plugin.startDistractionRecording()
    plugin.distractionPhase = "collecting"
    plugin.distractionSamples = [(0.02, 0.57)] * 6
    assert not plugin.finishDistractionRecording() and messages[-1] == "failed"
    plugin.clearDistraction()
    assert plugin.setting("distractionMode") == "default" and plugin.distractionPoints() == []


def limitsDefault():
    from pchub.plugins.oled_saver.logic import limitsFor
    return limitsFor(5)


def test_reset_calibration_with_distraction_points(qtApp, dataDir):
    manager, plugin = makeOledPlugin(dataDir)
    plugin.context.setData("distractionPoints", [[0.0, 1.2]])
    plugin.setSetting("distractionMode", "calibrated")
    plugin.resetCalibration()
    from pchub.plugins.oled_saver.logic import DEFAULT_BASE_PITCH, DEFAULT_BASE_YAW
    assert plugin.calibration() == (DEFAULT_BASE_YAW, DEFAULT_BASE_PITCH)
    assert plugin.currentLimits()["down"] > 0
    assert plugin.distractionDirections()
