"""Plays one macro in its own thread. Stopping is instant (every wait checks the stop flag) and anything the macro
was still holding down (keys, mouse buttons) is released."""
import copy
import random
import threading
import time

from pchub.core.logger import getLogger
from pchub.plugins.macros.logic import MODIFIER_VK, clickInterval, sortedMods, waitSeconds

log = getLogger("plugin.macros.runner")
TAP_HOLD_SECONDS = 0.012
MIN_LOOP_SECONDS = 0.01


class MacroRun:
    def __init__(self, macro, sender, onFinished=None, generator=None):
        self.macro = copy.deepcopy(macro)
        self.sender = sender
        self.onFinished = onFinished
        self.generator = generator or random.Random()
        self.stopEvent = threading.Event()
        self.heldKeys = []
        self.heldButtons = []
        self.iterations = 0
        self.clicks = 0
        self.startedAt = time.monotonic()
        self.thread = None
        self.error = None
        self.beforeStart = None

    # control ------------------------------------------------------------------
    def start(self):
        self.thread = threading.Thread(target=self.runBlocking, name=f"macro-{self.macro.get('id')}", daemon=True)
        self.thread.start()

    def stop(self):
        self.stopEvent.set()

    def isRunning(self):
        return self.thread is not None and self.thread.is_alive()

    def stopped(self):
        return self.stopEvent.is_set()

    def _wait(self, seconds):
        """False when stopped during the wait."""
        if seconds <= 0:
            return not self.stopEvent.is_set()
        return not self.stopEvent.wait(seconds)

    # play -----------------------------------------------------------------------
    def runBlocking(self):
        try:
            if self.beforeStart is not None:
                self.beforeStart()
            if self.macro.get("kind") == "clicker":
                self._clicker()
            else:
                self._steps()
        except Exception as error:
            self.error = error
            log.exception("Macro %s failed", self.macro.get("name"))
        finally:
            self._releaseAll()
            if self.onFinished is not None:
                try:
                    self.onFinished(self)
                except Exception:
                    log.exception("Macro finished callback failed")

    def _loops(self):
        mode = self.macro.get("mode")
        if mode == "once":
            return 1
        if mode == "repeat":
            return max(1, int(self.macro.get("repeatCount") or 1))
        return None

    def _steps(self):
        loops = self._loops()
        speed = max(0.1, float(self.macro.get("speed") or 1.0))
        steps = self.macro.get("steps") or []
        if not steps:
            return
        while not self.stopped() and (loops is None or self.iterations < loops):
            loopStarted = time.monotonic()
            for step in steps:
                if self.stopped():
                    return
                self._play(step, speed)
                if step["type"] != "wait" and not self._wait(int(self.macro.get("stepDelay") or 0) / 1000.0 / speed):
                    return
            self.iterations += 1
            if loops is not None and self.iterations >= loops:
                break
            pause = int(self.macro.get("loopDelay") or 0) / 1000.0 / speed
            pause = max(pause, MIN_LOOP_SECONDS - (time.monotonic() - loopStarted))
            if not self._wait(pause):
                return

    def _play(self, step, speed):
        stepType = step["type"]
        sender = self.sender
        if stepType == "wait":
            self._wait(waitSeconds(step, speed, self.generator))
        elif stepType == "key":
            virtualKey = int(step.get("vk") or 0)
            action = step.get("action", "tap")
            mods = [MODIFIER_VK[mod] for mod in sortedMods(step.get("mods"))]
            if action in ("tap", "down"):
                for modifierKey in mods:
                    self._keyDown(modifierKey)
                self._keyDown(virtualKey)
            if action == "tap":
                self._wait(TAP_HOLD_SECONDS)
            if action in ("tap", "up"):
                self._keyUp(virtualKey)
                for modifierKey in reversed(mods):
                    self._keyUp(modifierKey)
        elif stepType == "text":
            sender.typeText(step.get("text", ""))
        elif stepType == "click":
            if step.get("atPosition"):
                sender.moveTo(int(step.get("x", 0)), int(step.get("y", 0)))
            button = step.get("button", "left")
            action = step.get("action", "click")
            if action == "down":
                self._buttonDown(button)
            elif action == "up":
                self._buttonUp(button)
            else:
                for index in range(2 if action == "double" else 1):
                    if index and not self._wait(0.05):
                        return
                    self._buttonDown(button)
                    self._wait(TAP_HOLD_SECONDS)
                    self._buttonUp(button)
        elif stepType == "move":
            if step.get("relative"):
                sender.moveBy(int(step.get("x", 0)), int(step.get("y", 0)))
            else:
                sender.moveTo(int(step.get("x", 0)), int(step.get("y", 0)))
        elif stepType == "scroll":
            sender.scroll(int(step.get("amount", 0)))
        elif stepType == "run" and step.get("path"):
            sender.run(step["path"])

    def _clicker(self):
        clicker = self.macro.get("clicker") or {}
        button = clicker.get("button", "left")
        limit = clicker.get("limit", "none")
        limitValue = max(1, int(clicker.get("limitValue") or 1))
        holdSeconds = max(0, int(clicker.get("holdMs") or 0)) / 1000.0
        endAt = time.monotonic() + limitValue if limit == "seconds" else None
        nextClickAt = time.monotonic()
        while not self.stopped():
            if limit == "clicks" and self.clicks >= limitValue:
                break
            if endAt is not None and time.monotonic() >= endAt:
                break
            if not self._wait(nextClickAt - time.monotonic()):
                break
            if clicker.get("position") == "fixed":
                self.sender.moveTo(int(clicker.get("x", 0)), int(clicker.get("y", 0)))
            for index in range(2 if clicker.get("double") else 1):
                if index and not self._wait(0.03):
                    return
                self._buttonDown(button)
                if holdSeconds:
                    self._wait(holdSeconds)
                self._buttonUp(button)
            self.clicks += 1
            nextClickAt = max(nextClickAt + clickInterval(clicker, self.generator), time.monotonic() - 0.5)

    # bookkeeping so a stop never leaves something pressed -----------------------------------
    def _keyDown(self, virtualKey):
        self.sender.keyDown(virtualKey)
        self.heldKeys.append(virtualKey)

    def _keyUp(self, virtualKey):
        self.sender.keyUp(virtualKey)
        if virtualKey in self.heldKeys:
            self.heldKeys.remove(virtualKey)

    def _buttonDown(self, button):
        self.sender.buttonDown(button)
        self.heldButtons.append(button)

    def _buttonUp(self, button):
        self.sender.buttonUp(button)
        if button in self.heldButtons:
            self.heldButtons.remove(button)

    def _releaseAll(self):
        for virtualKey in reversed(list(self.heldKeys)):
            try:
                self.sender.keyUp(virtualKey)
            except Exception:
                pass
        for button in reversed(list(self.heldButtons)):
            try:
                self.sender.buttonUp(button)
            except Exception:
                pass
        self.heldKeys = []
        self.heldButtons = []
