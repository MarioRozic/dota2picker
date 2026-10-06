"""Static hero metadata (snapshot of odota/dotaconstants heroes.json)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

STEAM_CDN = "https://cdn.cloudflare.steamstatic.com"

# Dota's five positions: 1-3 are the cores (safe lane, mid, off lane), 4-5 the supports.
POSITIONS = {1: "Carry", 2: "Mid", 3: "Offlane", 4: "Soft support", 5: "Hard support"}


@dataclass(frozen=True)
class Hero:
    id: int
    name: str  # internal name, e.g. npc_dota_hero_antimage (what GSI reports)
    localized_name: str
    primary_attr: str
    roles: tuple[str, ...]
    img: str
    icon: str
    positions: tuple[int, ...] = ()  # most played first
    attack_type: str = "Melee"  # "Melee" or "Ranged"

    @property
    def short_name(self) -> str:
        return self.name.removeprefix("npc_dota_hero_")

    @property
    def img_url(self) -> str:
        return STEAM_CDN + self.img

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "localized_name": self.localized_name,
            "primary_attr": self.primary_attr,
            "roles": list(self.roles),
            "img_url": self.img_url,
            "icon_url": STEAM_CDN + self.icon,
            "positions": list(self.positions),
            "attack_type": self.attack_type,
        }


@lru_cache(maxsize=1)
def all_heroes() -> tuple[Hero, ...]:
    data = resources.files("dota2picker.data")
    raw = json.loads(data.joinpath("heroes.json").read_text(encoding="utf-8"))
    # Hand-curated from common play; edit positions.json when the meta shifts.
    positions = json.loads(data.joinpath("positions.json").read_text(encoding="utf-8"))
    return tuple(
        Hero(
            id=h["id"],
            name=h["name"],
            localized_name=h["localized_name"],
            primary_attr=h["primary_attr"],
            roles=tuple(h["roles"]),
            img=h["img"],
            icon=h["icon"],
            positions=tuple(positions.get(h["name"].removeprefix("npc_dota_hero_"), ())),
            attack_type=h["attack_type"],
        )
        for h in raw
    )


@lru_cache(maxsize=1)
def by_id() -> dict[int, Hero]:
    return {h.id: h for h in all_heroes()}


@lru_cache(maxsize=1)
def by_name() -> dict[str, Hero]:
    return {h.name: h for h in all_heroes()}
