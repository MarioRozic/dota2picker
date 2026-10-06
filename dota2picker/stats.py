"""Hero meta and matchup statistics: fetching from OpenDota and local caching.

Matchups (hero vs enemy) and synergy (hero with ally) come from OpenDota's
recent public matches through its SQL explorer, the same kind of high-volume
pub data Dota Plus uses. OpenDota's /heroes/{id}/matchups endpoint only counts
pro games (a few dozen per pair), so it is used only as a fallback when the
explorer fails.

The cache is one JSON file refreshed at most once a day, so a draft never waits
on the network and we stay far inside OpenDota's free-tier limits.
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
# How many days of public matches to aggregate for matchups and synergy.
PUBLIC_MATCH_DAYS = 7

_PAIRS_SQL = """
SELECT a.h AS hero, b.h AS other, count(*) AS games,
       sum(CASE WHEN m.radiant_win THEN 1 ELSE 0 END) AS radiant_wins
FROM (SELECT radiant_win, radiant_team, {other_team} FROM public_matches
      WHERE start_time > extract(epoch from now() - interval '{days} days')) m,
     unnest(m.radiant_team) a(h), unnest(m.{other_team}) b(h)
{where}
GROUP BY 1, 2
"""
# Radiant hero vs Dire hero.
MATCHUPS_SQL = _PAIRS_SQL.format(other_team="dire_team", days=PUBLIC_MATCH_DAYS, where="")
# Two Radiant heroes on the same team; each pair once.
SYNERGY_SQL = _PAIRS_SQL.format(other_team="radiant_team", days=PUBLIC_MATCH_DAYS, where="WHERE a.h < b.h")

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
    # hero id -> ally hero id -> games/wins with both on the same team
    synergy: dict[int, dict[int, Record]] = field(default_factory=dict)
    # "public" (recent pub matches), "pro" (fallback: pro matches only) or
    # "legacy" (a cache from before public data, also pro-only)
    source: str = "public"

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
            "synergy": {
                str(h): {str(o): [r.games, r.wins] for o, r in rows.items()}
                for h, rows in self.synergy.items()
            },
            "source": self.source,
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
            synergy=rows(data.get("synergy", {})),
            source=data.get("source", "legacy"),
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


def _add(table: dict[int, dict[int, Record]], hero: int, other: int, games: int, wins: int) -> None:
    rec = table.setdefault(hero, {}).setdefault(other, Record())
    rec.games += games
    rec.wins += wins


def parse_public_matchups(rows: list[dict]) -> dict[int, dict[int, Record]]:
    """Turn explorer rows (Radiant hero, Dire hero, games, Radiant wins) into
    hero -> enemy -> Record, from both heroes' side."""
    out: dict[int, dict[int, Record]] = {}
    for r in rows:
        games, rad_wins = int(r["games"]), int(r["radiant_wins"])
        _add(out, r["hero"], r["other"], games, rad_wins)
        _add(out, r["other"], r["hero"], games, games - rad_wins)
    return out


def parse_public_synergy(rows: list[dict]) -> dict[int, dict[int, Record]]:
    """Turn explorer rows (two Radiant heroes, games, Radiant wins) into
    hero -> ally -> Record, both ways round."""
    out: dict[int, dict[int, Record]] = {}
    for r in rows:
        games, wins = int(r["games"]), int(r["radiant_wins"])
        _add(out, r["hero"], r["other"], games, wins)
        _add(out, r["other"], r["hero"], games, wins)
    return out


def _explore(client: httpx.Client, sql: str) -> list[dict]:
    resp = client.get("/explorer", params={"sql": sql})
    resp.raise_for_status()
    body = resp.json()
    if body.get("err"):
        raise httpx.HTTPError(f"OpenDota explorer: {body['err']}")
    return body["rows"]


def fetch(client: httpx.Client | None = None, sleep=time.sleep) -> Stats:
    own_client = client is None
    client = client or httpx.Client(base_url=OPENDOTA, timeout=120)
    try:
        resp = client.get("/heroStats")
        resp.raise_for_status()
        stats = Stats(fetched_at=time.time(), bracket=parse_hero_stats(resp.json()))
        try:
            sleep(REQUEST_INTERVAL_SECONDS)
            stats.matchups = parse_public_matchups(_explore(client, MATCHUPS_SQL))
            sleep(REQUEST_INTERVAL_SECONDS)
            stats.synergy = parse_public_synergy(_explore(client, SYNERGY_SQL))
            return stats
        except (httpx.HTTPError, KeyError, ValueError) as e:
            log.warning("Public-match query failed (%s); falling back to pro-match matchups", e)
        stats.matchups, stats.synergy, stats.source = {}, {}, "pro"
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
        cached = Stats.from_json(json.loads(path.read_text(encoding="utf-8")))
        # Legacy caches hold pro-only matchups; replace them right away.
        if not refresh and cached.source != "legacy" and time.time() - cached.fetched_at < max_age:
            return cached
    try:
        fresh = fetch()
    except httpx.HTTPError:
        if cached is None:
            raise
        log.warning("OpenDota refresh failed, using cache from %s", time.ctime(cached.fetched_at))
        return cached
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fresh.to_json()), encoding="utf-8")
    return fresh
