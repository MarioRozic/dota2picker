"""Periodically read the draft from the screen.

The whole monitor is grabbed so black bars around the game can be trimmed
before the top bar is located.
On macOS the app needs Screen Recording permission (System Settings ->
Privacy & Security); macOS asks the first time.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

import numpy as np

from .vision import Detection, PortraitMatcher, looks_like_draft

log = logging.getLogger(__name__)

SLOTS = 10
UNKNOWN = Detection(None, 0.0)


class ScreenWatcher(threading.Thread):
    """Keeps track of the hero in each top-bar slot as the draft goes on.

    A slot changes once two captures in a row agree on something new: a
    different hero replaces the old one, and an empty slot clears it. A slot
    that can't be identified keeps what it had, and captures that don't look
    like the draft (another window in front) change nothing.
    """

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
        self.last_frame: np.ndarray | None = None
        self.last_reads: list[Detection] = []  # raw reads of last_frame, for debugging
        self.error: str | None = None
        # The web server calls reject() and reset() from its own threads.
        self._lock = threading.Lock()
        self._slots: list[Detection | None] = [None] * SLOTS
        self._rejected: list[set[int]] = [set() for _ in range(SLOTS)]  # heroes you said a slot isn't
        self._previous: list[Detection] | None = None
        self._stop = threading.Event()

    @property
    def latest(self) -> list[Detection]:
        """The hero in each slot (Radiant 1-5, then Dire 1-5); hero_id is None when there isn't one."""
        with self._lock:
            return [d or UNKNOWN for d in self._slots]

    def stop(self) -> None:
        self._stop.set()

    def grab(self, sct) -> np.ndarray:
        shot = np.asarray(sct.grab(sct.monitors[self.monitor]))[:, :, :3]  # BGRA -> BGR
        return np.ascontiguousarray(shot)

    def accept(self, reads: list[Detection]) -> None:
        """Update the slots from one capture's reads."""
        with self._lock:
            previous, self._previous = self._previous, list(reads)
            if previous is None or not looks_like_draft(reads):
                return
            for i, (d, p) in enumerate(zip(reads, previous)):
                if d.empty and p.empty:
                    self._slots[i] = None
                    self._rejected[i].clear()  # whoever shows up next is a new pick
                elif d.hero_id is not None and d.hero_id == p.hero_id and d.hero_id not in self._rejected[i]:
                    # A hero is only in one slot; an older read of it elsewhere was wrong.
                    for j, other in enumerate(self._slots):
                        if other is not None and other.hero_id == d.hero_id:
                            self._slots[j] = None
                    self._slots[i] = d

    def reject(self, hero_id: int) -> bool:
        """You said hero_id is wrong: clear its slot and read it again without that hero."""
        with self._lock:
            for i, d in enumerate(self._slots):
                if d is not None and d.hero_id == hero_id:
                    self._slots[i] = None
                    self._rejected[i].add(hero_id)
                    if self._previous is not None:
                        self._previous[i] = UNKNOWN  # a read taken before this can't confirm anything
                    return True
        return False

    def reset(self) -> None:
        """Forget all slots, for a new draft."""
        with self._lock:
            self._slots = [None] * SLOTS
            self._rejected = [set() for _ in range(SLOTS)]
            self._previous = None

    def step(self, frame: np.ndarray) -> None:
        """Read one captured frame."""
        with self._lock:
            exclude = [set(r) for r in self._rejected]
        reads = self.matcher.read(frame, exclude=exclude)
        self.last_frame, self.last_reads = frame, reads
        self.accept(reads)

    def run(self) -> None:
        import mss

        # mss 10 renamed mss.mss to mss.MSS.
        with getattr(mss, "MSS", mss.mss)() as sct:
            while not self._stop.is_set():
                if self.should_run():
                    try:
                        self.step(self.grab(sct))
                        self.error = None
                    except Exception as e:  # keep watching; surface the problem in the UI
                        log.exception("screen read failed")
                        self.error = str(e)
                self._stop.wait(self.interval)
