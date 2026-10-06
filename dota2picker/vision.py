"""Read hero picks from the top bar of a Dota 2 screenshot.

The top bar is centred and scales with screen height, so slot positions are
expressed in units of the screen height, measured from the horizontal
centre. Each slot is matched against the official hero portraits (downloaded
once from Valve's CDN) with normalised cross-correlation over a few scales,
because the top bar shows a slightly cropped and rescaled portrait.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from . import heroes

log = logging.getLogger(__name__)

# Geometry, in multiples of screen height, measured on 16:9 screenshots.
SLOT_INNER = 0.186  # centre of the slot nearest the clock, from screen centre
SLOT_PITCH = 0.1148  # distance between neighbouring slot centres
SLOT_WIDTH = 0.094
SLOT_TOP = 0.006
SLOT_BOTTOM = 0.064
# Keep the middle of each slot: the edges are slanted and the corners carry
# level badges and colour bars.
INNER_X = (0.18, 0.82)
INNER_Y = (0.12, 0.88)

# Everything is compared at this slot width in pixels; small is fast and
# still distinctive.
WORK_WIDTH = 48
SCALES = (1.0, 1.1, 1.2, 1.3, 1.45)
MIN_SCORE = 0.55
EMPTY_STD = 12.0


@dataclass
class Detection:
    hero_id: int | None
    score: float


def slot_boxes(width: int, height: int) -> list[tuple[int, int, int, int]]:
    """Ten (x0, y0, x1, y1) boxes: Radiant slots 1-5, then Dire slots 1-5."""
    cx = width / 2
    boxes = []
    for side in (-1, 1):
        for i in range(5):
            # Radiant counts from the far left towards the clock; Dire from the clock outwards.
            k = 4 - i if side < 0 else i
            centre = cx + side * (SLOT_INNER + k * SLOT_PITCH) * height
            half = SLOT_WIDTH * height / 2
            boxes.append(
                (
                    round(centre - half),
                    round(SLOT_TOP * height),
                    round(centre + half),
                    round(SLOT_BOTTOM * height),
                )
            )
    return boxes


def crop_slots(image: np.ndarray, screen_height: int | None = None) -> list[np.ndarray]:
    """Crop the ten slots. Pass screen_height when image is only the top strip of the screen."""
    w = image.shape[1]
    h = screen_height or image.shape[0]
    out = []
    for x0, y0, x1, y1 in slot_boxes(w, h):
        slot = image[y0:y1, x0:x1]
        sh, sw = slot.shape[:2]
        out.append(
            slot[
                int(sh * INNER_Y[0]) : int(sh * INNER_Y[1]),
                int(sw * INNER_X[0]) : int(sw * INNER_X[1]),
            ]
        )
    return out


def _work_scale(slot_inner: np.ndarray) -> np.ndarray:
    """Resize an inner slot crop to the working resolution."""
    full_w = WORK_WIDTH * (INNER_X[1] - INNER_X[0])
    f = full_w / slot_inner.shape[1]
    return cv2.resize(slot_inner, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)


def is_empty(slot_inner: np.ndarray) -> bool:
    """Unpicked slots are a flat dark-grey gradient."""
    hsv = cv2.cvtColor(slot_inner, cv2.COLOR_BGR2HSV)
    return float(slot_inner.std()) < EMPTY_STD or float(hsv[..., 1].mean()) < 25


class PortraitMatcher:
    def __init__(self, portraits: dict[int, np.ndarray]):
        """portraits: hero id -> BGR image of the full (16:9) hero portrait."""
        self.templates: dict[int, list[np.ndarray]] = {}
        for hero_id, img in portraits.items():
            variants = []
            for s in SCALES:
                w = round(WORK_WIDTH * s)
                h = round(img.shape[0] * w / img.shape[1])
                variants.append(cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA))
            self.templates[hero_id] = variants
        # Slots rarely change between reads, so remember recent results by a coarse signature.
        self._cache: dict[tuple[bytes, frozenset[int]], Detection] = {}

    def match(self, slot_inner: np.ndarray, exclude: set[int] = frozenset()) -> Detection:
        if is_empty(slot_inner):
            return Detection(None, 0.0)
        key = ((cv2.resize(slot_inner, (12, 6), interpolation=cv2.INTER_AREA) // 16).tobytes(), frozenset(exclude))
        if key not in self._cache:
            if len(self._cache) > 256:
                self._cache.clear()
            self._cache[key] = self._match(slot_inner, exclude)
        return self._cache[key]

    def _match(self, slot_inner: np.ndarray, exclude: set[int]) -> Detection:
        patch = _work_scale(slot_inner)
        ph, pw = patch.shape[:2]
        best_id, best = None, -1.0
        for hero_id, variants in self.templates.items():
            if hero_id in exclude:
                continue
            for t in variants:
                if t.shape[0] < ph or t.shape[1] < pw:
                    continue
                score = float(cv2.matchTemplate(t, patch, cv2.TM_CCOEFF_NORMED).max())
                if score > best:
                    best_id, best = hero_id, score
        if best < MIN_SCORE:
            return Detection(None, best)
        return Detection(best_id, best)

    def read(self, image: np.ndarray, screen_height: int | None = None) -> list[Detection]:
        """Detect all ten slots (Radiant 1-5, then Dire 1-5)."""
        found: list[Detection] = []
        for slot in crop_slots(image, screen_height):
            # A hero can only be picked once, so don't offer earlier slots' heroes again.
            taken = {d.hero_id for d in found if d.hero_id is not None}
            found.append(self.match(slot, exclude=taken))
        return found


def load_portraits(cache_dir: Path, client=None) -> dict[int, np.ndarray]:
    """Load hero portraits, downloading any missing ones from Valve's CDN."""
    import httpx

    cache_dir.mkdir(parents=True, exist_ok=True)
    out: dict[int, np.ndarray] = {}
    own_client = client is None
    client = client or httpx.Client(timeout=20)
    try:
        for hero in heroes.all_heroes():
            path = cache_dir / f"{hero.short_name}.png"
            if not path.exists():
                resp = client.get(hero.img_url)
                resp.raise_for_status()
                path.write_bytes(resp.content)
            img = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if img is None:
                log.warning("unreadable portrait %s", path)
                continue
            out[hero.id] = img
    finally:
        if own_client:
            client.close()
    return out


def default_portrait_dir() -> Path:
    return Path.home() / ".dota2picker" / "portraits"
