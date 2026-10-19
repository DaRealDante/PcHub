"""Pure logic for OLEDSaver (no Qt, no camera): head pose from YuNet landmarks, presence/distraction tracking
and the dimming state machine. Fully unit tested."""
import math

DEFAULT_BASE_YAW = 0.0
DEFAULT_BASE_PITCH = 0.55


class Pose:
    __slots__ = ("yaw", "pitch", "roll", "box", "landmarks", "score")

    def __init__(self, yaw, pitch, roll, box, landmarks, score):
        self.yaw = yaw
        self.pitch = pitch
        self.roll = roll
        self.box = box
        self.landmarks = landmarks
        self.score = score


def estimatePose(faceRow):
    """faceRow = YuNet output row: x, y, w, h, rightEye(x,y), leftEye, nose, rightMouth, leftMouth, score.

    yaw   = horizontal nose offset from the eyes' midpoint, in inter-eye distances (0 = facing the camera)
    pitch = nose height between the eyes (0) and the mouth (1); grows when looking down
    """
    values = [float(value) for value in faceRow[:15]]
    box = tuple(values[0:4])
    points = [(values[4], values[5]), (values[6], values[7]), (values[8], values[9]), (values[10], values[11]),
              (values[12], values[13])]
    score = values[14] if len(values) > 14 else 1.0
    eyeA, eyeB, nose, mouthA, mouthB = points
    roll = math.atan2(eyeB[1] - eyeA[1], eyeB[0] - eyeA[0])
    if abs(roll) > math.pi / 2:
        roll -= math.copysign(math.pi, roll)
    centerX = (eyeA[0] + eyeB[0]) / 2
    centerY = (eyeA[1] + eyeB[1]) / 2
    cosRoll, sinRoll = math.cos(-roll), math.sin(-roll)

    def straighten(point):
        offsetX, offsetY = point[0] - centerX, point[1] - centerY
        return offsetX * cosRoll - offsetY * sinRoll, offsetX * sinRoll + offsetY * cosRoll

    eyeA, eyeB, nose, mouthA, mouthB = [straighten(point) for point in points]
    interEye = max(1e-6, math.hypot(eyeB[0] - eyeA[0], eyeB[1] - eyeA[1]))
    mouthY = (mouthA[1] + mouthB[1]) / 2
    faceHeight = max(1e-6, mouthY)
    yaw = nose[0] / interEye
    pitch = nose[1] / faceHeight
    return Pose(yaw, pitch, math.degrees(roll), box, points, score)


def pickMainFace(faces):
    """Largest face (closest to the camera)."""
    best = None
    bestArea = -1
    for row in faces if faces is not None else []:
        area = float(row[2]) * float(row[3])
        if area > bestArea:
            best, bestArea = row, area
    return best


def thresholdsFor(sensitivity):
    """sensitivity 1 (needs a big head turn) .. 10 (tiny turn is enough)."""
    sensitivity = max(1, min(10, int(sensitivity)))
    fraction = (sensitivity - 1) / 9.0
    yawThreshold = 0.60 - fraction * 0.42
    pitchDownThreshold = 0.30 - fraction * 0.20
    pitchUpThreshold = pitchDownThreshold * 1.25
    return yawThreshold, pitchDownThreshold, pitchUpThreshold


MIN_YAW_LIMIT = 0.10
MIN_PITCH_LIMIT = 0.06
PRESENT_CONFIRM_FRAMES = 2
RETURN_FRAMES = 3
RETURN_SCALE = 0.7
RELIABLE_SCORE = 0.75


def calibratedFactor(sensitivity):
    """How far towards a recorded distraction pose you must turn: 0.75 (sens. 1) .. 0.35 (sens. 10)."""
    sensitivity = max(1, min(10, int(sensitivity)))
    return 0.75 - (sensitivity - 1) / 9.0 * 0.40


def classifyDistraction(deltaYaw, deltaPitch, sensitivity=5):
    """Which way a pose (relative to the screen pose) points: 'left' | 'right' | 'down' | 'up' (the user's left:
    positive yaw = nose towards the person's left eye)."""
    yawThreshold, downThreshold, upThreshold = thresholdsFor(sensitivity)
    yawScore = abs(deltaYaw) / yawThreshold
    pitchScore = deltaPitch / downThreshold if deltaPitch > 0 else -deltaPitch / upThreshold
    if yawScore >= pitchScore:
        return "left" if deltaYaw > 0 else "right"
    return "down" if deltaPitch > 0 else "up"


def limitsFor(sensitivity, lookDownCounts=True, distractionPoints=None, baseYaw=DEFAULT_BASE_YAW,
              basePitch=DEFAULT_BASE_PITCH):
    """Per-direction limits {left, right, down, up}; None = that direction never counts.

    distractionPoints: absolute (yaw, pitch) poses recorded while looking at a distraction (phone, other monitor).
    A recorded direction replaces the standard limit with a fraction of the way to that pose."""
    yawThreshold, downThreshold, upThreshold = thresholdsFor(sensitivity)
    limits = {"left": yawThreshold, "right": yawThreshold, "down": downThreshold if lookDownCounts else None,
              "up": upThreshold}
    calibrated = {}
    factor = calibratedFactor(sensitivity)
    for pointYaw, pointPitch in distractionPoints or []:
        deltaYaw, deltaPitch = pointYaw - baseYaw, pointPitch - basePitch
        direction = classifyDistraction(deltaYaw, deltaPitch, sensitivity)
        distance = abs(deltaYaw) if direction in ("left", "right") else abs(deltaPitch)
        minimum = MIN_YAW_LIMIT if direction in ("left", "right") else MIN_PITCH_LIMIT
        limit = max(minimum, distance * factor)
        calibrated[direction] = min(limit, calibrated.get(direction, limit))
    limits.update(calibrated)
    return limits


def isLookingAway(deltaYaw, deltaPitch, limits, scale=1.0):
    if deltaYaw > 0 and limits["left"] is not None and deltaYaw > limits["left"] * scale:
        return True
    if deltaYaw < 0 and limits["right"] is not None and -deltaYaw > limits["right"] * scale:
        return True
    if deltaPitch > 0 and limits["down"] is not None and deltaPitch > limits["down"] * scale:
        return True
    return deltaPitch < 0 and limits["up"] is not None and -deltaPitch > limits["up"] * scale


class PresenceTracker:
    """Smooths noisy per-frame detections into stable present / absent / distracted states."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.present = None
        self.hits = 0
        self.misses = 0
        self.presentSince = None
        self.absentSince = None
        self.distracted = False
        self.distractedSince = None
        self.returnStreak = 0
        self.smoothYaw = None
        self.smoothPitch = None
        self.deltaYaw = 0.0
        self.deltaPitch = 0.0
        self.lastPose = None
        self.lastFrameAt = None

    def update(self, now, pose, confirmFrames=3, sensitivity=5, lookDownCounts=True, baseYaw=DEFAULT_BASE_YAW,
               basePitch=DEFAULT_BASE_PITCH, limits=None):
        """Becoming distracted uses the smoothed pose. Coming back needs RETURN_FRAMES clear, confident frames in a
        row well inside the limits (RETURN_SCALE), so a jittery frame while you look away can't wake the screen.
        Losing the face for a moment keeps the last opinion (turned heads are often missed)."""
        self.lastFrameAt = now
        confirmFrames = max(1, int(confirmFrames))
        if pose is None:
            self.hits = 0
            self.misses += 1
            self.lastPose = None
            if self.misses >= confirmFrames and self.present is not False:
                self.present = False
                self.absentSince = now
                self.presentSince = None
                self.smoothYaw = self.smoothPitch = None
            self.returnStreak = 0
            return
        self.misses = 0
        self.hits += 1
        self.lastPose = pose
        if self.hits >= min(confirmFrames, PRESENT_CONFIRM_FRAMES) and self.present is not True:
            self.present = True
            self.presentSince = now
            self.absentSince = None
        if limits is None:
            limits = limitsFor(sensitivity, lookDownCounts)
        rawDeltaYaw = pose.yaw - baseYaw
        rawDeltaPitch = pose.pitch - basePitch
        clearlyBack = pose.score >= RELIABLE_SCORE and not isLookingAway(rawDeltaYaw, rawDeltaPitch, limits, RETURN_SCALE)
        self.returnStreak = self.returnStreak + 1 if clearlyBack else 0
        cameBack = self.distracted and self.returnStreak >= RETURN_FRAMES
        if cameBack:
            self.smoothYaw, self.smoothPitch = pose.yaw, pose.pitch
        alpha = 0.5
        self.smoothYaw = pose.yaw if self.smoothYaw is None else self.smoothYaw + (pose.yaw - self.smoothYaw) * alpha
        self.smoothPitch = pose.pitch if self.smoothPitch is None else self.smoothPitch + (pose.pitch - self.smoothPitch) * alpha
        self.deltaYaw = self.smoothYaw - baseYaw
        self.deltaPitch = self.smoothPitch - basePitch
        if not self.present:
            return
        if self.distracted:
            if cameBack:
                self._setDistracted(False, now)
        else:
            self._setDistracted(isLookingAway(self.deltaYaw, self.deltaPitch, limits), now)

    def _setDistracted(self, distracted, now):
        if distracted and not self.distracted:
            self.distractedSince = now
        elif not distracted:
            self.distractedSince = None
        self.distracted = distracted

    def attentive(self):
        return self.present is True and not self.distracted


MODE_NORMAL = "normal"
MODE_DIM = "dim"
MODE_AWAY = "away"
MODE_MANUAL = "manual"


class DimController:
    """Decides how dark the screen should be. `settings` is a callable key -> value.

    Rules
    - any real input wakes everything (and both automatic modes need you to be idle at least their delay)
    - away: no face for `awayDelay` s  -> blackout
    - distracted for `distractionDelay` s -> start at `startDim`%, +`dimStep`% every `dimInterval` s up to `maxDim`%
    - looking back at the screen wakes when `wakeOnLook` is on (otherwise only input does)
    - with `lookToWake`, input doesn't end a distraction dim: only looking back does (input still wakes if the
      camera can't see you, so you can never get stuck)
    - manual blackout stays until input arrives after a short grace period (the hotkey's own key release)
    """
    manualGrace = 0.8

    def __init__(self, settings):
        self.settings = settings
        self.mode = MODE_NORMAL
        self.level = 0.0
        self.modeStartedAt = 0.0
        self.dimStartedAt = 0.0

    def _setMode(self, mode, now):
        if mode != self.mode:
            self.mode = mode
            self.modeStartedAt = now
            if mode == MODE_DIM:
                self.dimStartedAt = now

    def startManual(self, now):
        self._setMode(MODE_MANUAL, now)
        self.level = self.settings("blackoutLevel") / 100.0
        return self.mode, self.level

    def wake(self, now):
        self._setMode(MODE_NORMAL, now)
        self.level = 0.0
        return self.mode, self.level

    def _dimLevel(self, now):
        steps = int(max(0.0, now - self.dimStartedAt) // max(0.5, self.settings("dimInterval")))
        percent = min(self.settings("maxDim"), self.settings("startDim") + steps * self.settings("dimStep"))
        return max(0.0, min(1.0, percent / 100.0))

    def update(self, now, lastInputAt, tracker, blocked=False, visionOk=True):
        setting = self.settings
        inputSinceMode = lastInputAt > self.modeStartedAt
        lookOnly = bool(setting("lookToWake") and setting("wakeOnLook") and visionOk and tracker.present is True)
        if self.mode == MODE_MANUAL:
            if lastInputAt > self.modeStartedAt + self.manualGrace:
                return self.wake(now)
            self.level = setting("blackoutLevel") / 100.0
            return self.mode, self.level
        if blocked:
            return self.wake(now)
        if inputSinceMode and (self.mode == MODE_AWAY or (self.mode == MODE_DIM and not lookOnly)):
            self.wake(now)
        idle = now - lastInputAt
        away = bool(setting("autoBlackout") and tracker.present is False and tracker.absentSince is not None
                    and now - tracker.absentSince >= setting("awayDelay") and idle >= setting("awayDelay"))
        distracted = bool(setting("distraction") and tracker.present is True and tracker.distracted
                          and tracker.distractedSince is not None
                          and now - tracker.distractedSince >= setting("distractionDelay")
                          and idle >= setting("distractionDelay"))
        if away:
            self._setMode(MODE_AWAY, now)
            self.level = setting("blackoutLevel") / 100.0
        elif self.mode == MODE_AWAY:
            backAndLooking = tracker.attentive()
            if not (backAndLooking and setting("wakeOnLook")):
                self.level = setting("blackoutLevel") / 100.0
            else:
                self.wake(now)
        elif distracted or (self.mode == MODE_DIM and (not setting("wakeOnLook") or not tracker.attentive())):
            if self.mode != MODE_DIM:
                self._setMode(MODE_DIM, now)
            self.level = self._dimLevel(now)
        else:
            self.wake(now)
        return self.mode, self.level
