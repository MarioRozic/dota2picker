import httpx
from fastapi.testclient import TestClient

from dota2picker import builds, heroes, items
from dota2picker.demo import demo_stats
from dota2picker.server import create_app

by_name = {h.localized_name: h.id for h in heroes.all_heroes()}
AM = by_name["Anti-Mage"]

VALVE_AM = """
"itembuilds"
{
	"Items"
	{
		"#DOTA_Item_Build_Starting_Items"
		{
			"item"		"item_tango"
			"item"		"item_branches"
			"item"		"item_branches"
		}
		"#DOTA_Item_Build_Starting_Items_Secondary"
		{
			"item"		"item_gauntlets"
		}
		"#DOTA_Item_Build_Early_Game"
		{
			"item"		"item_recipe_wraith_band"
			"item"		"item_boots"
		}
		"#DOTA_Item_Build_Core_Items"
		{
			"item"		"item_bfury"
		}
		"#DOTA_Item_Build_Late_Items"
		{
			"item"		"item_manta"
		}
	}
}
"""

# OpenDota /scenarios/itemTimings rows: games where the item was bought by `time` seconds.
TIMINGS_AM = [
    {"hero_id": AM, "item": "power_treads", "time": 450, "games": "1200", "wins": "600"},
    {"hero_id": AM, "item": "bfury", "time": 720, "games": "500", "wins": "250"},
    {"hero_id": AM, "item": "bfury", "time": 900, "games": "900", "wins": "450"},
    {"hero_id": AM, "item": "manta", "time": 1200, "games": "300", "wins": "150"},
    {"hero_id": AM, "item": "manta", "time": 1500, "games": "600", "wins": "300"},
    {"hero_id": AM, "item": "ultimate_orb", "time": 1500, "games": "400", "wins": "200"},
    {"hero_id": AM, "item": "radiance", "time": 1200, "games": "20", "wins": "10"},
]


def keys(row):
    return [e.item.key for e in row]


def test_parse_valve_build():
    out = builds.parse_valve_build(VALVE_AM)
    assert out["start"] == ["tango", "branches", "branches"]
    assert out["early"] == ["wraith_band", "boots"]  # a recipe stands for its item
    assert out["mid"] == ["bfury"] and out["late"] == ["manta"]
    assert "gauntlets" not in sum(out.values(), [])  # secondary lists skipped


def test_every_valve_build_item_is_known():
    catalogue = items.all_items()
    for hero in heroes.all_heroes():
        build = builds.valve_builds()[hero.short_name]
        assert build["start"] and build["early"], hero.short_name
        for phase, keys_ in build.items():
            assert set(keys_) <= set(catalogue), (hero.short_name, phase)


def test_item_timings_median_minute():
    timed = builds.parse_item_timings(TIMINGS_AM)
    assert timed["bfury"].games == 1400 and timed["bfury"].minute == 15
    assert timed["power_treads"].minute == 7.5
    assert timed["manta"].minute == 25


def test_build_without_timings_is_valves():
    rows = builds.build(AM)
    assert keys(rows["start"]) == ["tango", "flask", "branches", "quelling_blade", "circlet"]
    assert rows["start"][2].count == 2
    assert "bfury" in keys(rows["mid"])


def test_timings_put_items_in_the_phase_they_are_bought():
    rows = builds.build(AM, timings=TIMINGS_AM)
    assert "power_treads" in keys(rows["early"])
    assert "bfury" in keys(rows["mid"])
    assert "manta" in keys(rows["late"])
    every = sum((keys(r) for r in rows.values()), [])
    assert "ultimate_orb" not in every  # a piece of a bigger item
    assert "radiance" not in every  # too rare
    assert len(every) == len(set(every))


def test_counter_items_are_marked_and_slotted_by_phase():
    enemies = [by_name["Lion"], by_name["Lina"], by_name["Riki"]]
    rows = builds.build(by_name["Crystal Maiden"], enemies, position=5)
    early = rows["early"]
    dust = next(e for e in early if e.item.key == "dust")
    assert by_name["Riki"] in dust.answers
    assert early[0].answers  # answers to this lineup come first
    glimmer = next(e for e in rows["mid"] if e.item.key == "glimmer_cape")
    assert glimmer.answers  # already in Valve's build: marked, not duplicated


def test_counter_item_moves_up_from_if_needed():
    # Monkey King Bar is only in Anti-Mage's "other" list; against Phantom Assassin it joins the build.
    rows = builds.build(AM, [by_name["Phantom Assassin"]], position=1)
    assert "monkey_king_bar" not in keys(rows["other"])
    assert "monkey_king_bar" in keys(rows["late"])


def test_timings_cache_downloads_once_and_survives_failure(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.url.params["hero_id"])
        return httpx.Response(200, json=TIMINGS_AM)

    client = httpx.Client(base_url="http://od", transport=httpx.MockTransport(handler))
    cache = builds.TimingsCache(tmp_path, client)
    assert cache(AM) == TIMINGS_AM
    assert cache(AM) == TIMINGS_AM
    assert calls == [str(AM)]

    def down(request):
        return httpx.Response(503)

    broken = builds.TimingsCache(tmp_path, httpx.Client(base_url="http://od", transport=httpx.MockTransport(down)))
    assert broken(by_name["Axe"]) is None


def test_build_endpoint():
    client = TestClient(create_app(demo_stats(), item_timings=lambda hero_id: TIMINGS_AM))
    res = client.post("/api/build", json={"hero_id": AM, "enemies": [by_name["Phantom Assassin"]], "position": 1})
    assert res.status_code == 200
    body = res.json()
    assert body["timings"] is True
    assert [p["key"] for p in body["phases"]][:4] == ["start", "early", "mid", "late"]
    late = next(p for p in body["phases"] if p["key"] == "late")
    mkb = next(i for i in late["items"] if i["key"] == "monkey_king_bar")
    assert mkb["answers"] == [{"enemy": "Phantom Assassin", "threats": ["evasion"]}]
    assert client.post("/api/build", json={"hero_id": 99999}).status_code == 400
