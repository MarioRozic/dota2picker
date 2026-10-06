"""Static hero metadata (snapshot of odota/dotaconstants heroes.json)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

STEAM_CDN = "https://cdn.cloudflare.steamstatic.com"


@dataclass(frozen=True)
class Hero:
    id: int
    name: str  # internal name, e.g. npc_dota_hero_antimage (what GSI reports)
    localized_name: str
    primary_attr: str
    roles: tuple[str, ...]
    img: str
    icon: str

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
        }


@lru_cache(maxsize=1)
def all_heroes() -> tuple[Hero, ...]:
    raw = json.loads(resources.files("dota2picker.data").joinpath("heroes.json").read_text())
    return tuple(
        Hero(
            id=h["id"],
            name=h["name"],
            localized_name=h["localized_name"],
            primary_attr=h["primary_attr"],
            roles=tuple(h["roles"]),
            img=h["img"],
            icon=h["icon"],
        )
        for h in raw
    )


@lru_cache(maxsize=1)
def by_id() -> dict[int, Hero]:
    return {h.id: h for h in all_heroes()}


@lru_cache(maxsize=1)
def by_name() -> dict[str, Hero]:
    return {h.name: h for h in all_heroes()}
