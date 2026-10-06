"""Counter-item suggestions for your hero against the enemy lineup.

Each enemy hero is tagged with the threats it poses (data/threats.json, most
important first), and each threat lists the items that answer it for cores
and for supports (data/counter_items.json, best first). An item's score adds
up every enemy threat it answers, so items that handle several enemies at
once rise to the top.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources

from . import heroes

# Items a ranged hero shouldn't be pointed at.
MELEE_ONLY = {"bfury", "abyssal_blade"}
# Later threats in a hero's list matter less; later items in a threat's list are weaker answers.
THREAT_WEIGHTS = (1.0, 0.7, 0.5)
ITEM_WEIGHTS = (1.0, 0.8, 0.6)


@dataclass(frozen=True)
class Item:
    key: str
    name: str
    cost: int
    img: str

    @property
    def img_url(self) -> str:
        return heroes.STEAM_CDN + self.img


@dataclass
class ItemSuggestion:
    item: Item
    score: float
    # enemy hero id -> the threats of that enemy this item answers
    answers: dict[int, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        by_id = heroes.by_id()
        return {
            "key": self.item.key,
            "name": self.item.name,
            "cost": self.item.cost,
            "img_url": self.item.img_url,
            "score": round(self.score, 2),
            "answers": [
                {"enemy": by_id[e].localized_name, "threats": reasons}
                for e, reasons in self.answers.items()
            ],
        }


def _data(name: str) -> dict:
    return json.loads(resources.files("dota2picker.data").joinpath(name).read_text())


@lru_cache(maxsize=1)
def all_items() -> dict[str, Item]:
    return {
        key: Item(key=key, name=v["dname"], cost=v["cost"] or 0, img=v["img"])
        for key, v in _data("items.json").items()
    }


@lru_cache(maxsize=1)
def threats() -> dict[str, list[str]]:
    return _data("threats.json")


@lru_cache(maxsize=1)
def counters() -> dict[str, dict]:
    return {k: v for k, v in _data("counter_items.json").items() if not k.startswith("_")}


def role_for(hero: heroes.Hero, position: int | None) -> str:
    """Positions 1-3 build like cores, 4-5 like supports."""
    position = position or (hero.positions[0] if hero.positions else 1)
    return "core" if position <= 3 else "support"


def suggest_items(
    hero_id: int, enemies: list[int], position: int | None = None, limit: int = 6
) -> list[ItemSuggestion]:
    hero = heroes.by_id()[hero_id]
    role = role_for(hero, position)
    catalogue = all_items()
    found: dict[str, ItemSuggestion] = {}
    for enemy_id in enemies:
        enemy = heroes.by_id()[enemy_id]
        for t_rank, tag in enumerate(threats().get(enemy.short_name, [])):
            rule = counters()[tag]
            for i_rank, key in enumerate(rule[role]):
                if hero.attack_type == "Ranged" and key in MELEE_ONLY:
                    continue
                weight = (
                    rule.get("weight", 1.0)
                    * THREAT_WEIGHTS[min(t_rank, 2)]
                    * ITEM_WEIGHTS[min(i_rank, 2)]
                )
                s = found.setdefault(key, ItemSuggestion(catalogue[key], 0.0))
                s.score += weight
                reasons = s.answers.setdefault(enemy_id, [])
                if rule["reason"] not in reasons:
                    reasons.append(rule["reason"])
    # Best score first; between equals, the cheaper item.
    return sorted(found.values(), key=lambda s: (-s.score, s.item.cost))[:limit]
