from fastapi.testclient import TestClient

from dota2picker import gsi
from dota2picker.demo import demo_stats
from dota2picker.server import create_app

client = TestClient(create_app(demo_stats(), gsi_token="secret"))


def test_index_and_heroes():
    assert "Dota2Picker" in client.get("/").text
    assert len(client.get("/api/heroes").json()) == 127


def test_suggest():
    res = client.post("/api/suggest", json={"enemies": [1, 2], "bracket": "divine", "role": "Carry"})
    assert res.status_code == 200
    body = res.json()
    assert len(body["best"]) == 5 and len(body["avoid"]) == 3
    assert body["best"][0]["reasons"][0]["enemy"] in {"Anti-Mage", "Axe"}


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
    assert client.get("/api/game").json() == {
        "game_state": "DOTA_GAMERULES_STATE_HERO_SELECTION",
        "in_draft": True,
        "team": "radiant",
        "hero_id": 26,
    }


def test_gsi_rejects_bad_token():
    assert client.post("/gsi", json={"auth": {"token": "nope"}}).status_code == 403


def test_gsi_cfg_render(tmp_path):
    path = gsi.install_cfg(tmp_path, "http://127.0.0.1:53000/gsi", "tok")
    text = path.read_text()
    assert path.name == "gamestate_integration_dota2picker.cfg"
    assert '"uri"           "http://127.0.0.1:53000/gsi"' in text and '"token"     "tok"' in text
