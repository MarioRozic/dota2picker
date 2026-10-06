from dota2picker.capture import ScreenWatcher
from dota2picker.vision import Detection

NONE = Detection(None, 0.0)


def watcher():
    return ScreenWatcher(matcher=None, should_run=lambda: True)


def test_needs_two_matching_reads():
    w = watcher()
    reads = [Detection(2, 0.9), Detection(26, 0.6)] + [NONE] * 8
    assert all(d.hero_id is None for d in w.accept(reads))
    assert [d.hero_id for d in w.accept(reads)][:2] == [2, 26]


def test_changed_slot_waits_for_confirmation():
    w = watcher()
    w.accept([Detection(2, 0.9), Detection(26, 0.6)] + [NONE] * 8)
    out = w.accept([Detection(2, 0.9), Detection(31, 0.62)] + [NONE] * 8)
    assert [d.hero_id for d in out][:2] == [2, None]


def test_weak_reads_only_are_ignored():
    # e.g. the browser or desktop is on screen: nothing matches clearly.
    w = watcher()
    weak = [Detection(5, 0.6), Detection(7, 0.58)] + [NONE] * 8
    w.accept(weak)
    assert all(d.hero_id is None for d in w.accept(weak))
