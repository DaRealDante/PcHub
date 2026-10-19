"""Webcam + YuNet face detection in a background thread."""
import os
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from pchub.core.logger import getLogger

log = getLogger("plugin.oled_saver.vision")
MODEL_PATH = Path(__file__).resolve().parent / "face_detection_yunet_2023mar.onnx"
PREVIEW_WIDTH = 360
FAST_WAKE_FPS = 24
DETECT_WIDTH = 400
ROI_WIDTH = 224
FULL_SCAN_SECONDS = 1.0
_gammaTables = {}
_clahe = None


def createDetector(width, height, confidence):
    import cv2
    return cv2.FaceDetectorYN.create(model=str(MODEL_PATH), config="", input_size=(int(width), int(height)),
                                     score_threshold=float(confidence), nms_threshold=0.3, top_k=50)


def detectFaces(detector, frame):
    height, width = frame.shape[:2]
    detector.setInputSize((width, height))
    _, faces = detector.detect(frame)
    return [] if faces is None else [list(map(float, row)) for row in faces]


def enhanceDark(frame):
    """Brightens a dark webcam frame (e.g. once the screen went black and stopped lighting your face)."""
    import cv2
    import numpy
    ycrcb = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
    luma = ycrcb[:, :, 0]
    meanLuma = float(luma.mean())
    gamma = 0.45 if meanLuma < 45 else 0.65
    table = _gammaTables.get(gamma)
    if table is None:
        table = _gammaTables[gamma] = numpy.array([((value / 255.0) ** gamma) * 255 for value in range(256)],
                                                  dtype=numpy.uint8)
    luma = cv2.LUT(luma, table)
    global _clahe
    if _clahe is None:
        _clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    ycrcb[:, :, 0] = _clahe.apply(luma)
    return cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2BGR)


def isDark(frame, threshold=95):
    return float(frame[::4, ::4].mean()) < threshold


def _mapFaces(faces, scale, offsetX=0.0, offsetY=0.0):
    """Faces found in a scaled/cropped image -> coordinates in the full camera frame."""
    mapped = []
    for row in faces:
        row = list(row)
        for index in (0, 4, 6, 8, 10, 12):
            row[index] = row[index] / scale + offsetX
        for index in (1, 5, 7, 9, 11, 13):
            row[index] = row[index] / scale + offsetY
        row[2] /= scale
        row[3] /= scale
        mapped.append(row)
    return mapped


class FaceFinder:
    """Cheap face search: a small full-frame pass (DETECT_WIDTH) and, between full passes, a tiny crop around the
    face found last time. Same results as a full-size search for a person at a desk, a fraction of the CPU."""

    def __init__(self, confidence):
        self.confidence = confidence
        self.detectors = {}
        self.lastBox = None
        self.lastFullScan = 0.0
        self.preferEnhanced = False

    def setConfidence(self, confidence):
        if confidence != self.confidence:
            self.confidence = confidence
            for detector in self.detectors.values():
                detector.setScoreThreshold(float(confidence))

    def _detect(self, image):
        height, width = image.shape[:2]
        detector = self.detectors.get((width, height))
        if detector is None:
            if len(self.detectors) > 6:
                self.detectors.clear()
            detector = self.detectors[(width, height)] = createDetector(width, height, self.confidence)
        _, faces = detector.detect(image)
        return [] if faces is None else [list(map(float, row)) for row in faces]

    def _detectBest(self, image, dark):
        """Plain image first; a dark one is also tried brightened. Whichever worked last time goes first."""
        if not dark:
            return self._detect(image)
        attempts = (True, False) if self.preferEnhanced else (False, True)
        for enhanced in attempts:
            faces = self._detect(enhanceDark(image) if enhanced else image)
            if faces:
                self.preferEnhanced = enhanced
                return faces
        return []

    def _full(self, frame, dark):
        import cv2
        height, width = frame.shape[:2]
        scale = min(1.0, DETECT_WIDTH / float(width))
        small = frame if scale >= 1.0 else cv2.resize(frame, (int(width * scale), int(height * scale)),
                                                      interpolation=cv2.INTER_AREA)
        return _mapFaces(self._detectBest(small, dark), scale)

    def _aroundLast(self, frame, dark):
        """Square crop centred on the last face, resized to a fixed ROI_WIDTH square (one detector, no distortion)."""
        import cv2
        height, width = frame.shape[:2]
        boxX, boxY, boxWidth, boxHeight = self.lastBox
        side = int(min(height, width, 2.4 * max(boxWidth, boxHeight)))
        if side < 48:
            return []
        centerX, centerY = boxX + boxWidth / 2.0, boxY + boxHeight / 2.0
        left = int(min(max(0, centerX - side / 2.0), width - side))
        top = int(min(max(0, centerY - side / 2.0), height - side))
        crop = frame[top:top + side, left:left + side]
        scale = ROI_WIDTH / float(side)
        crop = cv2.resize(crop, (ROI_WIDTH, ROI_WIDTH), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
        return _mapFaces(self._detectBest(crop, dark), scale, left, top)

    def find(self, frame, now=None):
        """Faces in full-frame coordinates. The pose always comes from the same normalised crop around the face
        (face ~95 px), so it doesn't jump between passes and doesn't depend on how far you sit."""
        now = time.monotonic() if now is None else now
        dark = isDark(frame)
        if self.lastBox is not None and now - self.lastFullScan < FULL_SCAN_SECONDS:
            faces = self._aroundLast(frame, dark)
            if faces:
                self._remember(faces)
                return faces
        self.lastFullScan = now
        faces = self._full(frame, dark)
        self._remember(faces)
        if self.lastBox is None:
            return faces
        refined = self._aroundLast(frame, dark)
        if refined:
            self._remember(refined)
            return refined
        return faces

    def _remember(self, faces):
        best = None
        for row in faces:
            if best is None or row[2] * row[3] > best[2] * best[3]:
                best = row
        self.lastBox = tuple(best[:4]) if best is not None else None


def framePreview(frame):
    import cv2
    height, width = frame.shape[:2]
    scale = PREVIEW_WIDTH / float(width)
    small = cv2.resize(frame, (PREVIEW_WIDTH, max(1, int(height * scale))), interpolation=cv2.INTER_AREA)
    small = cv2.cvtColor(cv2.flip(small, 1), cv2.COLOR_BGR2RGB)
    image = QImage(small.data, small.shape[1], small.shape[0], small.strides[0], QImage.Format_RGB888).copy()
    return image, scale


class CameraWorker(QObject):
    """Emits `frameAnalyzed(dict)` for every analysed frame and `statusChanged(status, message)`.

    status: "off" | "starting" | "on" | "noCamera" | "error"
    """
    frameAnalyzed = Signal(dict)
    statusChanged = Signal(str, str)

    def __init__(self, settingsGetter, previewWanted, parent=None):
        super().__init__(parent)
        self.settings = settingsGetter
        self.previewWanted = previewWanted
        self.stopEvent = threading.Event()
        self.thread = None
        self.status = "off"
        self.relaxed = False

    def isRunning(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self):
        if self.isRunning():
            return
        self.stopEvent.clear()
        self.thread = threading.Thread(target=self._run, name="oled-camera", daemon=True)
        self.thread.start()

    def stop(self, wait=True):
        self.stopEvent.set()
        if wait and self.thread is not None:
            self.thread.join(3)
        self.thread = None
        self._setStatus("off")

    def _setStatus(self, status, message=""):
        if status != self.status:
            self.status = status
            self.statusChanged.emit(status, message)

    def _openCamera(self, cv2):
        cameraIndex = int(self.settings("cameraIndex") or 0)
        backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
        capture = cv2.VideoCapture(cameraIndex, backend)
        if not capture.isOpened():
            capture.release()
            return None
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        capture.set(cv2.CAP_PROP_FPS, 30)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return capture

    def isFast(self):
        return bool(self.relaxed and self.settings("fastWake") is not False)

    def targetFps(self):
        fps = max(1, int(self.settings("cameraFps") or 6))
        if self.relaxed and self.settings("fastWake") is not False:
            fps = max(fps, FAST_WAKE_FPS)
        return fps

    def _run(self):
        try:
            import cv2
        except ImportError as error:
            self._setStatus("error", f"OpenCV: {error}")
            return
        if not MODEL_PATH.exists():
            self._setStatus("error", "face_detection_yunet_2023mar.onnx missing")
            return
        while not self.stopEvent.is_set():
            self._setStatus("starting")
            capture = self._openCamera(cv2)
            if capture is None:
                self._setStatus("noCamera")
                self.stopEvent.wait(8)
                continue
            finder = None
            failures = 0
            self._setStatus("on")
            lastAnalysisAt = 0.0
            try:
                cv2.setNumThreads(1)
            except Exception:
                pass
            try:
                while not self.stopEvent.is_set():
                    interval = 1.0 / self.targetFps()
                    if self.isFast():
                        # waking up: read every frame so the newest one is always ready
                        grabbed = capture.grab()
                        if grabbed and time.monotonic() - lastAnalysisAt < interval - 0.004:
                            self.stopEvent.wait(0.002)
                            continue
                    else:
                        remaining = lastAnalysisAt + interval - time.monotonic()
                        if remaining > 0:
                            self.stopEvent.wait(min(remaining, 0.05))
                            continue
                        grabbed = capture.grab() and capture.grab()
                    if not grabbed:
                        failures += 1
                        if failures > 15:
                            break
                        self.stopEvent.wait(0.1)
                        continue
                    ok, frame = capture.retrieve()
                    if not ok or frame is None:
                        failures += 1
                        if failures > 15:
                            break
                        continue
                    failures = 0
                    lastAnalysisAt = time.monotonic()
                    confidence = (self.settings("confidence") or 70) / 100.0 - (0.12 if self.relaxed else 0.0)
                    confidence = round(max(0.3, min(0.99, confidence)), 2)
                    if finder is None:
                        finder = FaceFinder(confidence)
                    finder.setConfidence(confidence)
                    faces = finder.find(frame, lastAnalysisAt)
                    result = {"time": time.monotonic(), "faces": faces, "width": frame.shape[1],
                              "height": frame.shape[0], "preview": None, "scale": 1.0}
                    if self.previewWanted():
                        result["preview"], result["scale"] = framePreview(frame)
                    self.frameAnalyzed.emit(result)
            except Exception as error:
                log.exception("Camera loop failed")
                self._setStatus("error", str(error))
                self.stopEvent.wait(5)
            finally:
                capture.release()
        self._setStatus("off")
