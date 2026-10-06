from dota2picker import heroes
from dota2picker.demo import demo_stats
from dota2picker.scoring import Draft, Scorer
from dota2picker.stats import Record, Stats

AM, AXE, BANE, LION = 1, 2, 3, 26


def two_hero_stats(games: int, wins: int) -> Stats:
    """AM and Axe are equally strong overall; AM beats Axe `wins` of `games`."""
    s = Stats(fetched_at=0)
    s.matchups = {
        AM: {AXE: Record(games, wins), BANE: Record(games, games - wins)},
        AXE: {AM: Record(games, games - wins), BANE: Record(games, wins)},
        BANE: {AM: Record(games, wins), AXE: Record(games, games - wins)},
    }
    return s


def test_advantage_sign_and_symmetry():
    sc = Scorer(two_hero_stats(10_000, 6_000))
    assert sc.advantage(AM, AXE) > 0.08
    assert abs(sc.advantage(AM, AXE) + sc.advantage(AXE, AM)) < 1e-9


def test_small_samples_are_shrunk():
    big = Scorer(two_hero_stats(10_000, 6_000)).advantage(AM, AXE)
    small = Scorer(two_hero_stats(20, 12)).advantage(AM, AXE)
    assert 0 < small < big / 5


def test_synergy_rewards_heroes_that_win_together():
    s = two_hero_stats(100, 50)
    s.synergy = {AM: {AXE: Record(10_000, 6_000)}, AXE: {AM: Record(10_000, 6_000)}}
    sc = Scorer(s)
    assert sc.synergy(AM, AXE) > 0.08
    assert sc.synergy(AM, BANE) == 0.0
    # With Axe as an ally, AM gains the synergy on top of its matchups.
    with_ally = sc.score(AM, Draft(allies=[AXE], enemies=[BANE]))
    alone = sc.score(AM, Draft(enemies=[BANE]))
    assert with_ally.score > alone.score + 0.08
    assert with_ally.to_dict()["synergy"][0]["ally"] == "Axe"


def test_unknown_matchup_is_neutral():
    assert Scorer(two_hero_stats(100, 50)).advantage(AM, LION) == 0.0


def test_suggestions_skip_taken_heroes_and_rank_best_first():
    sc = Scorer(demo_stats(), bracket=8)
    draft = Draft(allies=[LION], enemies=[AM, AXE], bans=[BANE])
    result = sc.suggest(draft, limit=10)
    ids = [s.hero_id for s in result["best"]]
    assert not set(ids) & {AM, AXE, BANE, LION}
    scores = [s.score for s in result["best"]]
    assert scores == sorted(scores, reverse=True)
    assert result["avoid"][0].score <= scores[-1]


def test_position_filter():
    result = Scorer(demo_stats()).suggest(Draft(enemies=[AM]), position=5, limit=20)
    assert all(5 in heroes.by_id()[s.hero_id].positions for s in result["best"])


def test_every_hero_has_a_valid_position():
    for h in heroes.all_heroes():
        assert h.positions and set(h.positions) <= set(heroes.POSITIONS), h.name


def test_no_enemies_means_no_avoid_list():
    assert Scorer(demo_stats(), bracket=5).suggest(Draft())["avoid"] == []
