"""Hero meta and matchup statistics: fetching from OpenDota and local caching.

The cache is one JSON file refreshed at most once a day, so a draft never waits
on the network and we stay far inside OpenDota's free-tier limits
(~130 calls per refresh).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from . import heroes

log = logging.getLogger(__name__)

OPENDOTA = "https://api.opendota.com/api"
CACHE_TTL_SECONDS = 24 * 3600
# OpenDota's free tier allows ~60 calls/minute; stay a little under it.
REQUEST_INTERVAL_SECONDS = 1.1

# OpenDota rank brackets in /heroStats: 1 = Herald ... 8 = Immortal.
BRACKETS = {
    "herald": 1,
    "guardian": 2,
    "crusader": 3,
    "archon": 4,
    "legend": 5,
    "ancient": 6,
    "divine": 7,
    "immortal": 8,
}


def default_cache_path() -> Path:
    return Path.home() / ".dota2picker" / "stats.json"


@dataclass
class Record:
    games: int = 0
    wins: int = 0


@dataclass
class Stats:
    fetched_at: float
    # bracket number -> hero id -> picks/wins in that bracket
    bracket: dict[int, dict[int, Record]] = field(default_factory=dict)
    # hero id -> opponent hero id -> games/wins of the first hero vs the second
    matchups: dict[int, dict[int, Record]] = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "fetched_at": self.fetched_at,
            "bracket": {
                str(b): {str(h): [r.games, r.wins] for h, r in rows.items()}
                for b, rows in self.bracket.items()
            },
            "matchups": {
                str(h): {str(o): [r.games, r.wins] for o, r in rows.items()}
                for h, rows in self.matchups.items()
            },
        }

    @classmethod
    def from_json(cls, data: dict) -> Stats:
        def rows(d: dict) -> dict[int, dict[int, Record]]:
            return {
                int(k): {int(h): Record(*gw) for h, gw in v.items()} for k, v in d.items()
            }

        return cls(
            fetched_at=data["fetched_at"],
            bracket=rows(data["bracket"]),
            matchups=rows(data["matchups"]),
        )


def parse_hero_stats(payload: list[dict]) -> dict[int, dict[int, Record]]:
    """Turn OpenDota /heroStats into bracket -> hero -> Record."""
    out: dict[int, dict[int, Record]] = {b: {} for b in BRACKETS.values()}
    for row in payload:
        for b in BRACKETS.values():
            picks = row.get(f"{b}_pick") or 0
            wins = row.get(f"{b}_win") or 0
            out[b][row["id"]] = Record(picks, wins)
    return out


def parse_matchups(payload: list[dict]) -> dict[int, Record]:
    """Turn OpenDota /heroes/{id}/matchups into opponent -> Record."""
    return {row["hero_id"]: Record(row["games_played"], row["wins"]) for row in payload}


def fetch(client: httpx.Client | None = None, sleep=time.sleep) -> Stats:
    own_client = client is None
    client = client or httpx.Client(base_url=OPENDOTA, timeout=30)
    try:
        resp = client.get("/heroStats")
        resp.raise_for_status()
        stats = Stats(fetched_at=time.time(), bracket=parse_hero_stats(resp.json()))
        for hero in heroes.all_heroes():
            sleep(REQUEST_INTERVAL_SECONDS)
            resp = client.get(f"/heroes/{hero.id}/matchups")
            resp.raise_for_status()
            stats.matchups[hero.id] = parse_matchups(resp.json())
        return stats
    finally:
        if own_client:
            client.close()


def load(path: Path | None = None, refresh: bool = False, max_age: float = CACHE_TTL_SECONDS) -> Stats:
    """Return cached stats, refreshing from OpenDota when stale or missing.

    If the refresh fails but an old cache exists, the old cache is used.
    """
    path = path or default_cache_path()
    cached = None
    if path.exists():
        cached = Stats.from_json(json.loads(path.read_text()))
        if not refresh and time.time() - cached.fetched_at < max_age:
            return cached
    try:
        fresh = fetch()
    except httpx.HTTPError:
        if cached is None:
            raise
        log.warning("OpenDota refresh failed, using cache from %s", time.ctime(cached.fetched_at))
        return cached
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fresh.to_json()))
    return fresh
