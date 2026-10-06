import json
import time

import httpx

from dota2picker import heroes, stats


def test_parse_hero_stats():
    out = stats.parse_hero_stats([{"id": 1, "1_pick": 100, "1_win": 55, "8_pick": 10, "8_win": 4}])
    assert out[1][1] == stats.Record(100, 55)
    assert out[8][1] == stats.Record(10, 4)
    assert out[3][1] == stats.Record(0, 0)


def test_parse_matchups():
    out = stats.parse_matchups([{"hero_id": 2, "games_played": 30, "wins": 17}])
    assert out == {2: stats.Record(30, 17)}


def test_parse_public_matchups_fills_both_sides():
    out = stats.parse_public_matchups([
        {"hero": 1, "other": 2, "games": 100, "wins": 60},
        {"hero": 2, "other": 1, "games": 50, "wins": 20},
    ])
    # AM on Radiant won 60/100; AM on Dire won 30/50.
    assert out[1][2] == stats.Record(150, 90)
    assert out[2][1] == stats.Record(150, 60)


def test_parse_public_synergy_is_symmetric():
    out = stats.parse_public_synergy([{"hero": 1, "other": 2, "games": "40", "wins": "25"}])
    assert out[1][2] == out[2][1] == stats.Record(40, 25)


def fake_opendota(request: httpx.Request, explorer_ok: bool = True) -> httpx.Response:
    path = request.url.path
    if path == "/api/heroStats":
        return httpx.Response(200, json=[{"id": 1, "5_pick": 10, "5_win": 6}])
    if path == "/api/explorer":
        if not explorer_ok:
            return httpx.Response(400, json={"err": "statement timeout"})
        sql = request.url.params["sql"]
        if "max(match_id)" in sql:
            return httpx.Response(200, json={"rows": [{"max_id": 9_000_000_000}], "err": None})
        assert "match_id > " in sql and "start_time" not in sql
        row = {"hero": 1, "other": 2, "games": 100, "wins": 55}
        return httpx.Response(200, json={"rows": [row], "err": None})
    hero_id = int(path.split("/")[3])
    return httpx.Response(200, json=[{"hero_id": 2 if hero_id != 2 else 1, "games_played": 8, "wins": 4}])


def client(**kw) -> httpx.Client:
    return httpx.Client(
        base_url=stats.OPENDOTA, transport=httpx.MockTransport(lambda r: fake_opendota(r, **kw))
    )


def test_fetch_uses_public_matches_and_caches(tmp_path, monkeypatch):
    data = stats.fetch(client(), sleep=lambda s: None)
    assert data.source == "public"
    assert data.bracket[5][1] == stats.Record(10, 6)
    # Every id window adds its games.
    n = stats.PUBLIC_MATCH_WINDOWS
    assert data.matchups[2][1] == stats.Record(100 * n, 45 * n)
    assert data.synergy[2][1] == stats.Record(100 * n, 55 * n)

    path = tmp_path / "stats.json"
    path.write_text(json.dumps(data.to_json()))
    monkeypatch.setattr(stats, "fetch", lambda: (_ for _ in ()).throw(AssertionError("should use cache")))
    cached = stats.load(path)
    assert cached.matchups[1][2] == stats.Record(100 * n, 55 * n)
    assert cached.synergy[1][2] == stats.Record(100 * n, 55 * n)


def test_fetch_falls_back_to_pro_matchups():
    data = stats.fetch(client(explorer_ok=False), sleep=lambda s: None)
    assert data.source == "pro"
    assert len(data.matchups) == len(heroes.all_heroes())
    assert data.matchups[1][2] == stats.Record(8, 4)
    assert data.synergy == {}


def test_legacy_pro_only_cache_is_refreshed(tmp_path, monkeypatch):
    legacy = stats.Stats(fetched_at=time.time()).to_json()
    del legacy["synergy"], legacy["source"]
    path = tmp_path / "stats.json"
    path.write_text(json.dumps(legacy))
    fresh = stats.Stats(fetched_at=time.time())
    monkeypatch.setattr(stats, "fetch", lambda: fresh)
    assert stats.load(path) is fresh


def test_load_falls_back_to_stale_cache(tmp_path, monkeypatch):
    path = tmp_path / "stats.json"
    path.write_text(json.dumps(stats.Stats(fetched_at=0).to_json()))

    def boom():
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(stats, "fetch", boom)
    assert stats.load(path).fetched_at == 0
