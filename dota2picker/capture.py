"""Periodically read the draft from the screen.

The whole monitor is grabbed so black bars around the game can be trimmed
before the top bar is located.
On macOS the app needs Screen Recording permission (System Settings ->
Privacy & Security); macOS asks the first time.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import numpy as np

from .vision import Detection, PortraitMatcher, looks_like_draft

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
        self.last_frame: np.ndarray | None = None
        self.last_reads: list[Detection] = []  # raw reads of last_frame, for debugging
        self._previous: list[Detection] = []
        self.error: str | None = None
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def grab(self, sct) -> np.ndarray:
        shot = np.asarray(sct.grab(sct.monitors[self.monitor]))[:, :, :3]  # BGRA -> BGR
        return np.ascontiguousarray(shot)

    def accept(self, reads: list[Detection]) -> list[Detection]:
        """Report only slots that read the same hero on two captures in a row,
        and nothing while the screen doesn't look like the draft (e.g. while
        you're looking at another window)."""
        previous, self._previous = self._previous, reads
        if not looks_like_draft(reads) or len(previous) != len(reads):
            return [Detection(None, 0.0)] * len(reads)
        return [d if d.hero_id == p.hero_id else Detection(None, 0.0) for d, p in zip(reads, previous)]

    def run(self) -> None:
        import mss

        # mss 10 renamed mss.mss to mss.MSS.
        with getattr(mss, "MSS", mss.mss)() as sct:
            while not self._stop.is_set():
                if self.should_run():
                    try:
                        frame = self.grab(sct)
                        reads = self.matcher.read(frame)
                        self.last_frame, self.last_reads = frame, reads
                        self.latest = self.accept(reads)
                        self.error = None
                    except Exception as e:  # keep watching; surface the problem in the UI
                        log.exception("screen read failed")
                        self.error = str(e)
                self._stop.wait(self.interval)
