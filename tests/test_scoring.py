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


def test_role_filter():
    result = Scorer(demo_stats()).suggest(Draft(enemies=[AM]), role="Support", limit=20)
    assert all("Support" in heroes.by_id()[s.hero_id].roles for s in result["best"])


def test_no_enemies_means_no_avoid_list():
    assert Scorer(demo_stats(), bracket=5).suggest(Draft())["avoid"] == []
