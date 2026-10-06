import json

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


def fake_opendota(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/heroStats":
        return httpx.Response(200, json=[{"id": 1, "5_pick": 10, "5_win": 6}])
    hero_id = int(request.url.path.split("/")[3])
    return httpx.Response(200, json=[{"hero_id": 2 if hero_id != 2 else 1, "games_played": 8, "wins": 4}])


def test_fetch_and_cache_roundtrip(tmp_path, monkeypatch):
    client = httpx.Client(base_url=stats.OPENDOTA, transport=httpx.MockTransport(fake_opendota))
    data = stats.fetch(client, sleep=lambda s: None)
    assert data.bracket[5][1] == stats.Record(10, 6)
    assert len(data.matchups) == len(heroes.all_heroes())

    path = tmp_path / "stats.json"
    path.write_text(json.dumps(data.to_json()))
    monkeypatch.setattr(stats, "fetch", lambda: (_ for _ in ()).throw(AssertionError("should use cache")))
    assert stats.load(path).matchups[1][2] == stats.Record(8, 4)


def test_load_falls_back_to_stale_cache(tmp_path, monkeypatch):
    path = tmp_path / "stats.json"
    path.write_text(json.dumps(stats.Stats(fetched_at=0).to_json()))

    def boom():
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(stats, "fetch", boom)
    assert stats.load(path).fetched_at == 0
