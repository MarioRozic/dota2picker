"""Refresh data/items.json and data/builds.json from public game files.

    python scripts/update_item_data.py

items.json is every buyable item from odota/dotaconstants. builds.json is
Valve's recommended build for each hero (the Starting / Early / Mid / Late /
Other lists in the in-game shop), read from SteamDatabase's mirror of the
Dota 2 game files. Run it after a patch that adds items or changes builds.
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dota2picker import heroes  # noqa: E402
from dota2picker.builds import parse_valve_build  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "dota2picker" / "data"
ITEMS_URL = "https://raw.githubusercontent.com/odota/dotaconstants/master/build/items.json"
BUILD_URL = (
    "https://raw.githubusercontent.com/SteamDatabase/GameTracking-Dota2/master/"
    "game/dota/itembuilds/default_{}.txt"
)

# Misspellings and old names in Valve's build files -> the real item key.
ALIASES = {
    "assault_cuirass": "assault",
    "battle_fury": "bfury",
    "blood_stone": "bloodstone",
    "boots_of_speed": "boots",
    "branch": "branches",
    "desolater": "desolator",
    "ghost_scepter": "ghost",
    "hand_midas": "hand_of_midas",
    "helm_of_the_dominator_2": "helm_of_the_overlord",
    "mango": "enchanted_mango",
    "manta_style": "manta",
    "moonshard": "moon_shard",
    "refresher_orb": "refresher",
    "shadow_blade": "invis_sword",
    "spherer": "sphere",
    "travel_boots_1": "travel_boots",
}


def write(name: str, data: dict) -> None:
    (DATA / name).write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    with httpx.Client(timeout=30) as client:
        raw = client.get(ITEMS_URL).raise_for_status().json()
        items = {
            key: {
                "id": v["id"],
                "dname": v["dname"],
                "cost": v["cost"],
                "img": v["img"].split("?")[0],
                "components": v.get("components") or [],
            }
            for key, v in raw.items()
            if v.get("dname") and v.get("cost") is not None and not key.startswith("recipe_")
        }
        write("items.json", items)

        def build(hero: heroes.Hero) -> tuple[str, dict]:
            text = client.get(BUILD_URL.format(hero.short_name)).raise_for_status().text
            build = parse_valve_build(text)
            return hero.short_name, {
                phase: [ALIASES.get(k, k) for k in keys] for phase, keys in build.items()
            }

        with ThreadPoolExecutor(8) as pool:
            builds = dict(pool.map(build, heroes.all_heroes()))
    unknown = {k for b in builds.values() for keys in b.values() for k in keys} - set(items)
    if unknown:
        print("Items in Valve builds that dotaconstants doesn't know (dropped):", sorted(unknown))
        builds = {
            h: {phase: [k for k in keys if k in items] for phase, keys in b.items()}
            for h, b in builds.items()
        }
    write("builds.json", builds)
    print(f"Wrote {len(items)} items and {len(builds)} hero builds")


if __name__ == "__main__":
    main()
