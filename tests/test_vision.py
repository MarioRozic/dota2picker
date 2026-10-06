from pathlib import Path

import cv2
import numpy as np
import pytest

from dota2picker import heroes, vision

FIXTURES = Path(__file__).parent / "fixtures"
# Heroes in tests/fixtures/strategy_full.jpg, Radiant then Dire.
STRATEGY_PICKS = [
    "Pudge", "Dragon Knight", "Zeus", "Witch Doctor", "Juggernaut",
    "Sven", "Sniper", "Axe", "Lich", "Lion",
]


def load(name: str) -> np.ndarray:
    return cv2.imread(str(FIXTURES / name))


def ids(names):
    by_name = {h.localized_name: h.id for h in heroes.all_heroes()}
    return [by_name[n] for n in names]


def test_slot_boxes_are_symmetric_and_ordered():
    boxes = vision.slot_boxes(1920, 1080)
    assert len(boxes) == 10
    xs = [b[0] for b in boxes]
    assert xs == sorted(xs)
    # Radiant slot 1 mirrors Dire slot 5 around the centre.
    assert abs((boxes[0][0] + boxes[9][2]) - 1920) <= 2


def test_empty_draft_has_no_picks():
    assert all(vision.is_empty(s) for s in vision.crop_slots(load("draft_empty.jpg")))


def test_full_draft_slots_are_not_empty():
    assert not any(vision.is_empty(s) for s in vision.crop_slots(load("strategy_full.jpg")))


def test_crop_from_top_strip_matches_full_frame():
    image = load("strategy_full.jpg")
    h = image.shape[0]
    strip = image[: int(h * 0.08)]
    for a, b in zip(vision.crop_slots(image), vision.crop_slots(strip, screen_height=h)):
        assert a.shape == b.shape and np.array_equal(a, b)


def synthetic_portraits(image: np.ndarray) -> dict[int, np.ndarray]:
    """Stand-in 'portraits': each slot's full box, plus decoys from elsewhere on screen."""
    h, w = image.shape[:2]
    out = {}
    for hero_id, (x0, y0, x1, y1) in zip(ids(STRATEGY_PICKS), vision.slot_boxes(w, h)):
        out[hero_id] = image[y0:y1, x0:x1].copy()
    decoys = [h_.id for h_ in heroes.all_heroes() if h_.id not in out][:30]
    rng = np.random.default_rng(0)
    for hero_id in decoys:
        y = int(rng.integers(150, h - 80))
        x = int(rng.integers(0, w - 110))
        out[hero_id] = image[y : y + 62, x : x + 100].copy()
    return out


def test_matcher_reads_full_draft_with_synthetic_portraits():
    image = load("strategy_full.jpg")
    matcher = vision.PortraitMatcher(synthetic_portraits(image))
    reads = matcher.read(image)
    assert [r.hero_id for r in reads] == ids(STRATEGY_PICKS)
    assert all(r.score > 0.8 for r in reads)


def test_matcher_reports_nothing_for_empty_draft():
    matcher = vision.PortraitMatcher(synthetic_portraits(load("strategy_full.jpg")))
    assert all(r.hero_id is None for r in matcher.read(load("draft_empty.jpg")))


@pytest.mark.skipif(
    not vision.default_portrait_dir().exists(),
    reason="real hero portraits not downloaded (run the app once with screen reading on)",
)
def test_matcher_reads_full_draft_with_real_portraits():
    portraits = vision.load_portraits(vision.default_portrait_dir())
    reads = vision.PortraitMatcher(portraits).read(load("strategy_full.jpg"))
    names = [heroes.by_id()[r.hero_id].localized_name if r.hero_id else None for r in reads]
    assert names == STRATEGY_PICKS


def test_black_bars_are_trimmed():
    image = load("strategy_full.jpg")
    h, w = image.shape[:2]
    # A 16:9 screenshot shown full screen on a 16:10 screen gets bars top and bottom.
    padded = cv2.copyMakeBorder(image, 60, 60, 0, 0, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    def close(a, b):
        return all(abs(x - y) <= 3 for x, y in zip(a, b))

    assert close(vision.content_box(padded), (0, 60, w, 60 + h))
    assert close(vision.content_box(image), (0, 0, w, h))
    matcher = vision.PortraitMatcher(synthetic_portraits(image))
    assert [r.hero_id for r in matcher.read(padded)] == ids(STRATEGY_PICKS)
    # Pillarboxed on an ultrawide screen.
    side = cv2.copyMakeBorder(image, 0, 0, 200, 200, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    assert [r.hero_id for r in matcher.read(side)] == ids(STRATEGY_PICKS)


def test_scaled_screenshot_still_reads():
    image = load("strategy_full.jpg")
    matcher = vision.PortraitMatcher(synthetic_portraits(image))
    for size in [(1920, 1080), (2560, 1440), (3840, 2160), (1280, 720)]:
        scaled = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
        assert [r.hero_id for r in matcher.read(scaled)] == ids(STRATEGY_PICKS), size


def test_annotate_draws_on_top_strip():
    image = load("strategy_full.jpg")
    reads = vision.PortraitMatcher(synthetic_portraits(image)).read(image)
    out = vision.annotate(image, reads)
    assert abs(out.shape[1] - image.shape[1]) <= 3 and out.shape[0] < image.shape[0] // 5


def test_empty_slots_are_told_apart_from_unknown_ones():
    matcher = vision.PortraitMatcher(synthetic_portraits(load("strategy_full.jpg")))
    assert all(r.empty for r in matcher.read(load("draft_empty.jpg")))
    assert not any(r.empty for r in matcher.read(load("strategy_full.jpg")))


def test_excluded_hero_is_not_read_in_that_slot():
    image = load("strategy_full.jpg")
    matcher = vision.PortraitMatcher(synthetic_portraits(image))
    picks = ids(STRATEGY_PICKS)
    reads = matcher.read(image, exclude=[{picks[0]}] + [set()] * 9)
    assert reads[0].hero_id != picks[0]
    assert [r.hero_id for r in reads[1:]] == picks[1:]


def test_duplicate_read_goes_to_the_closer_match():
    image = load("strategy_full.jpg")
    matcher = vision.PortraitMatcher(synthetic_portraits(image))
    picks = ids(STRATEGY_PICKS)
    # Radiant slot 1 shows its hero faded into slot 2's (like a portrait mid
    # animation), so it reads as slot 2's hero. Slot 2 is the closer match and
    # must keep its hero.
    h, w = image.shape[:2]
    (a0, b0, a1, b1), (c0, d0, c1, d1) = vision.slot_boxes(w, h)[:2]
    image[b0:b1, a0:a1] = cv2.addWeighted(image[d0:d1, c0:c1], 0.6, image[b0:b1, a0:a1], 0.4, 0)
    assert matcher.match(vision.crop_slots(image)[0]).hero_id == picks[1]
    reads = matcher.read(image)
    assert reads[1].hero_id == picks[1]
    assert reads[0].hero_id != picks[1]
    assert [r.hero_id for r in reads[2:]] == picks[2:]
