from dota2picker.capture import ScreenWatcher
from dota2picker.vision import Detection

NONE = Detection(None, 0.0)
EMPTY = Detection(None, 0.0, empty=True)


def watcher():
    return ScreenWatcher(matcher=None, should_run=lambda: True)


def frame(*first, rest=EMPTY):
    """Reads for the ten slots: the given ones first, then rest."""
    return list(first) + [rest] * (10 - len(first))


def heroes(w):
    return [d.hero_id for d in w.latest]


def test_needs_two_matching_reads():
    w = watcher()
    reads = frame(Detection(2, 0.9), Detection(26, 0.6))
    w.accept(reads)
    assert heroes(w) == [None] * 10
    w.accept(reads)
    assert heroes(w)[:2] == [2, 26]


def test_later_reads_replace_earlier_ones():
    w = watcher()
    w.accept(frame(Detection(2, 0.9), Detection(26, 0.6)))
    w.accept(frame(Detection(2, 0.9), Detection(26, 0.6)))
    # The slot now shows another hero: one read isn't enough, two are.
    w.accept(frame(Detection(2, 0.9), Detection(31, 0.92)))
    assert heroes(w)[:2] == [2, 26]
    w.accept(frame(Detection(2, 0.9), Detection(31, 0.92)))
    assert heroes(w)[:2] == [2, 31]
    assert w.latest[1].score == 0.92


def test_slot_that_turns_empty_clears():
    w = watcher()
    w.accept(frame(Detection(2, 0.9), Detection(26, 0.9)))
    w.accept(frame(Detection(2, 0.9), Detection(26, 0.9)))
    w.accept(frame(Detection(2, 0.9), EMPTY))
    w.accept(frame(Detection(2, 0.9), EMPTY))
    assert heroes(w)[:2] == [2, None]


def test_unreadable_slot_keeps_its_hero():
    w = watcher()
    w.accept(frame(Detection(2, 0.9), Detection(26, 0.9)))
    w.accept(frame(Detection(2, 0.9), Detection(26, 0.9)))
    # Something we can't identify (not an empty slot) doesn't wipe the pick.
    w.accept(frame(Detection(2, 0.9), Detection(None, 0.42)))
    w.accept(frame(Detection(2, 0.9), Detection(None, 0.42)))
    assert heroes(w)[:2] == [2, 26]


def test_screens_that_are_not_the_draft_change_nothing():
    # e.g. the browser or desktop is on screen: nothing matches clearly.
    w = watcher()
    w.accept(frame(Detection(2, 0.9), Detection(26, 0.9)))
    w.accept(frame(Detection(2, 0.9), Detection(26, 0.9)))
    weak = frame(Detection(5, 0.6), Detection(7, 0.58))
    w.accept(weak)
    w.accept(weak)
    w.accept(frame(rest=EMPTY))
    w.accept(frame(rest=EMPTY))
    assert heroes(w)[:2] == [2, 26]


def test_hero_is_only_kept_in_the_slot_that_reads_it_now():
    w = watcher()
    w.accept(frame(Detection(26, 0.62), Detection(None, 0.4), Detection(2, 0.9)))
    w.accept(frame(Detection(26, 0.62), Detection(None, 0.4), Detection(2, 0.9)))
    assert heroes(w)[:3] == [26, None, 2]
    w.accept(frame(Detection(None, 0.4), Detection(26, 0.95), Detection(2, 0.9)))
    w.accept(frame(Detection(None, 0.4), Detection(26, 0.95), Detection(2, 0.9)))
    assert heroes(w)[:3] == [None, 26, 2]


def test_reject_clears_the_slot_and_reads_it_again_without_that_hero():
    w = watcher()
    w.accept(frame(Detection(2, 0.9), Detection(26, 0.6)))
    w.accept(frame(Detection(2, 0.9), Detection(26, 0.6)))
    assert w.reject(26)
    assert heroes(w)[:2] == [2, None]
    assert not w.reject(26)

    seen = []

    class Matcher:
        def __init__(self, reads):
            self.reads = reads

        def read(self, image, exclude=None):
            seen.append(exclude)
            return self.reads

    # Reads taken before the reject still say 26; they mustn't bring it back.
    w.accept(frame(Detection(2, 0.9), Detection(26, 0.6)))
    w.accept(frame(Detection(2, 0.9), Detection(26, 0.6)))
    assert heroes(w)[:2] == [2, None]
    w.matcher = Matcher(frame(Detection(2, 0.9), Detection(31, 0.58)))
    image = object()
    w.step(image)
    w.step(image)
    assert seen[-1][1] == {26} and seen[-1][0] == set()
    assert heroes(w)[:2] == [2, 31]
    assert w.last_reads[1].hero_id == 31


def test_empty_slot_forgets_rejected_heroes():
    w = watcher()
    w.accept(frame(Detection(2, 0.9), Detection(26, 0.6)))
    w.accept(frame(Detection(2, 0.9), Detection(26, 0.6)))
    w.reject(26)
    w.accept(frame(Detection(2, 0.9), EMPTY))
    w.accept(frame(Detection(2, 0.9), EMPTY))
    assert w._rejected[1] == set()


def test_reset_forgets_everything():
    w = watcher()
    w.accept(frame(Detection(2, 0.9), Detection(26, 0.6)))
    w.accept(frame(Detection(2, 0.9), Detection(26, 0.6)))
    w.reject(2)
    w.reset()
    assert heroes(w) == [None] * 10
    assert all(not r for r in w._rejected)
    # A new draft needs two reads again.
    w.accept(frame(Detection(8, 0.9)))
    assert heroes(w) == [None] * 10


def test_follows_a_draft_on_screenshots():
    from test_vision import STRATEGY_PICKS, ids, load, synthetic_portraits

    from dota2picker import vision

    full, empty = load("strategy_full.jpg"), load("draft_empty.jpg")
    w = ScreenWatcher(vision.PortraitMatcher(synthetic_portraits(full)), should_run=lambda: True)
    picks = ids(STRATEGY_PICKS)

    def show(image, times=2):
        for _ in range(times):
            w.step(image)

    show(empty)
    assert heroes(w) == [None] * 10
    show(full)
    assert heroes(w) == picks
    # Radiant slot 3 goes back to empty (say, a hover that was cancelled).
    h, wd = full.shape[:2]
    x0, y0, x1, y1 = vision.slot_boxes(wd, h)[2]
    partial = full.copy()
    partial[y0:y1, x0:x1] = empty[y0:y1, x0:x1]
    show(partial)
    assert heroes(w) == picks[:2] + [None] + picks[3:]
    # You remove Radiant slot 1's hero: it's read again without that hero.
    assert w.reject(picks[0])
    show(partial, times=3)
    assert heroes(w)[0] != picks[0] and heroes(w)[1:] == picks[1:2] + [None] + picks[3:]
