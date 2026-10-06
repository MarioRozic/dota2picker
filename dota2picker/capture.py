"""Periodically read the draft from the screen.

Only the top strip of the screen is grabbed, which keeps each read cheap.
On macOS the app needs Screen Recording permission (System Settings ->
Privacy & Security); macOS asks the first time.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import numpy as np

from .vision import SLOT_BOTTOM, Detection, PortraitMatcher

log = logging.getLogger(__name__)


class ScreenWatcher(threading.Thread):
    def __init__(
        self,
        matcher: PortraitMatcher,
        should_run: Callable[[], bool],
        monitor: int = 1,
        interval: float = 1.5,
    ):
        super().__init__(daemon=True, name="screen-watcher")
        self.matcher = matcher
        self.should_run = should_run
        self.monitor = monitor
        self.interval = interval
        self.latest: list[Detection] = []
        self.error: str | None = None
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def grab(self, sct) -> tuple[np.ndarray, int]:
        mon = sct.monitors[self.monitor]
        strip = {
            "left": mon["left"],
            "top": mon["top"],
            "width": mon["width"],
            "height": int(mon["height"] * (SLOT_BOTTOM + 0.01)) + 1,
        }
        shot = np.asarray(sct.grab(strip))[:, :, :3]  # BGRA -> BGR
        # mss returns physical pixels; on Retina screens that is 2x the logical size.
        scale = shot.shape[1] / mon["width"]
        return np.ascontiguousarray(shot), round(mon["height"] * scale)

    def run(self) -> None:
        import mss

        with mss.mss() as sct:
            while not self._stop.is_set():
                if self.should_run():
                    try:
                        image, screen_height = self.grab(sct)
                        self.latest = self.matcher.read(image, screen_height)
                        self.error = None
                    except Exception as e:  # keep watching; surface the problem in the UI
                        log.exception("screen read failed")
                        self.error = str(e)
                self._stop.wait(self.interval)
