from fastapi.testclient import TestClient

from dota2picker import gsi
from dota2picker.demo import demo_stats
from dota2picker.server import create_app

client = TestClient(create_app(demo_stats(), gsi_token="secret"))


def test_index_and_heroes():
    assert "Dota2Picker" in client.get("/").text
    assert len(client.get("/api/heroes").json()) == 127


def test_suggest():
    res = client.post("/api/suggest", json={"enemies": [1, 2], "bracket": "divine", "position": 1})
    assert res.status_code == 200
    body = res.json()
    assert len(body["best"]) == 5 and len(body["avoid"]) == 3
    assert body["best"][0]["reasons"][0]["enemy"] in {"Anti-Mage", "Axe"}


def test_suggest_rejects_bad_position():
    assert client.post("/api/suggest", json={"position": 6}).status_code == 422


def test_suggest_rejects_unknown_hero():
    assert client.post("/api/suggest", json={"enemies": [99999]}).status_code == 400


def test_gsi_updates_game_state():
    payload = {
        "auth": {"token": "secret"},
        "map": {"game_state": "DOTA_GAMERULES_STATE_HERO_SELECTION"},
        "player": {"team_name": "radiant"},
        "hero": {"id": 26, "name": "npc_dota_hero_lion"},
    }
    assert client.post("/gsi", json=payload).status_code == 200
    body = client.get("/api/game").json()
    assert body.pop("draft_id") >= 1
    assert body == {
        "game_state": "DOTA_GAMERULES_STATE_HERO_SELECTION",
        "in_draft": True,
        "team": "radiant",
        "hero_id": 26,
    }


def test_draft_id_counts_new_drafts():
    c = TestClient(create_app(demo_stats()))

    def after(state):
        c.post("/gsi", json={"map": {"game_state": state}})
        return c.get("/api/game").json()["draft_id"]

    assert c.get("/api/game").json()["draft_id"] == 0
    assert after("DOTA_GAMERULES_STATE_HERO_SELECTION") == 1
    assert after("DOTA_GAMERULES_STATE_STRATEGY_TIME") == 1
    assert after("DOTA_GAMERULES_STATE_GAME_IN_PROGRESS") == 1
    assert after("DOTA_GAMERULES_STATE_POST_GAME") == 1
    assert after("DOTA_GAMERULES_STATE_HERO_SELECTION") == 2


def test_gsi_rejects_bad_token():
    assert client.post("/gsi", json={"auth": {"token": "nope"}}).status_code == 403


def test_gsi_cfg_render(tmp_path):
    path = gsi.install_cfg(tmp_path, "http://127.0.0.1:53000/gsi", "tok")
    text = path.read_text(encoding="utf-8")
    assert path.name == "gamestate_integration_dota2picker.cfg"
    assert '"uri"           "http://127.0.0.1:53000/gsi"' in text and '"token"     "tok"' in text


def test_game_includes_screen_reads():
    from types import SimpleNamespace

    from dota2picker.vision import Detection

    watcher = SimpleNamespace(
        latest=[Detection(14, 0.93)] + [Detection(None, 0.0)] * 8 + [Detection(26, 0.61)],
        error=None,
        reset=lambda: None,
    )
    app = create_app(demo_stats(), watcher=watcher)
    c = TestClient(app)
    screen = c.get("/api/game").json()["screen"]
    assert screen["radiant"][0] == {"hero_id": 14, "score": 0.93}
    assert screen["radiant"][1] is None
    assert screen["dire"][4] == {"hero_id": 26, "score": 0.61}

    # Without GSI the screen is always read; once GSI reports, only during the draft.
    assert app.state.screen_should_run()
    c.post("/gsi", json={"map": {"game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"}})
    assert not app.state.screen_should_run()
    c.post("/gsi", json={"map": {"game_state": "DOTA_GAMERULES_STATE_HERO_SELECTION"}})
    assert app.state.screen_should_run()


def test_items_endpoint():
    res = client.post("/api/items", json={"hero_id": 8, "enemies": [44, 32], "position": 1})
    assert res.status_code == 200
    body = res.json()
    assert body["role"] == "core"
    assert body["items"] and {"name", "cost", "img_url", "answers"} <= set(body["items"][0])
    assert client.post("/api/items", json={"hero_id": 99999}).status_code == 400
    assert client.post("/api/items", json={"hero_id": 8, "position": 9}).status_code == 422


def test_screen_reject_and_reset():
    from dota2picker.capture import ScreenWatcher
    from dota2picker.vision import Detection

    watcher = ScreenWatcher(matcher=None, should_run=lambda: True)
    reads = [Detection(14, 0.93), Detection(26, 0.61)] + [Detection(None, 0.0, empty=True)] * 8
    watcher.accept(reads)
    watcher.accept(reads)
    c = TestClient(create_app(demo_stats(), watcher=watcher))

    def radiant():
        return [r and r["hero_id"] for r in c.get("/api/game").json()["screen"]["radiant"]]

    assert radiant()[:2] == [14, 26]
    assert c.post("/api/screen/reject", json={"hero_id": 26}).json() == {"rejected": True}
    assert radiant()[:2] == [14, None]
    assert c.post("/api/screen/reject", json={"hero_id": 26}).json() == {"rejected": False}

    assert c.post("/api/screen/reset").status_code == 200
    assert radiant()[:2] == [None, None]

    # GSI entering a new draft starts the screen reader over too.
    watcher.accept(reads)
    watcher.accept(reads)
    c.post("/gsi", json={"map": {"game_state": "DOTA_GAMERULES_STATE_GAME_IN_PROGRESS"}})
    assert radiant()[:2] == [14, 26]
    c.post("/gsi", json={"map": {"game_state": "DOTA_GAMERULES_STATE_HERO_SELECTION"}})
    assert radiant()[:2] == [None, None]


def test_screen_endpoints_without_screen_reading():
    assert client.post("/api/screen/reject", json={"hero_id": 1}).status_code == 404
    assert client.post("/api/screen/reset").status_code == 404


def test_suggest_by_position():
    res = client.post("/api/suggest/positions", json={"enemies": [1, 2], "allies": [26], "limit": 3})
    assert res.status_code == 200
    body = res.json()
    assert [c["position"] for c in body["positions"]] == [1, 2, 3, 4, 5]
    from dota2picker import heroes

    for col in body["positions"]:
        assert len(col["best"]) == 3
        for s in col["best"]:
            assert col["position"] in heroes.by_id()[s["hero"]["id"]].positions
            assert s["hero"]["id"] not in {1, 2, 26}
        scores = [s["score"] for s in col["best"]]
        assert scores == sorted(scores, reverse=True)
    assert len(body["avoid"]) == 3
    assert client.post("/api/suggest/positions", json={"limit": 50}).status_code == 422
