"""Hero meta and matchup statistics: fetching from OpenDota and local caching.

Matchups (hero vs enemy) and synergy (hero with ally) come from roughly the
last day of OpenDota's public matches through its SQL explorer, the same kind of high-volume
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
# Public matches are read in windows of match ids, newest first. Filtering on
# start_time times out (it isn't indexed); a 200k-id window is about two hours
# of matches (~85k games) and its queries return in a couple of seconds.
PUBLIC_MATCH_WINDOW_IDS = 200_000
PUBLIC_MATCH_WINDOWS = 12  # ~1 day, ~1M matches
# Most window queries take 4-8 s, but some take over two minutes. Failed
# windows are skipped (up to MAX_TRIES windows are tried), and below
# MIN_WINDOWS the app falls back to the pro endpoint.
PUBLIC_MATCH_MAX_TRIES = 16
PUBLIC_MATCH_MIN_WINDOWS = 4
EXPLORER_TIMEOUT_SECONDS = 150

LATEST_MATCH_SQL = "SELECT max(match_id) AS max_id FROM public_matches"

# Radiant hero vs Dire hero; "wins" are Radiant's.
MATCHUPS_SQL = """
SELECT a.h AS hero, b.h AS other, count(*) AS games,
       sum(CASE WHEN m.radiant_win THEN 1 ELSE 0 END) AS wins
FROM (SELECT radiant_win, radiant_team, dire_team FROM public_matches
      WHERE match_id > {lo} AND match_id <= {hi}) m,
     unnest(m.radiant_team) a(h), unnest(m.dire_team) b(h)
GROUP BY 1, 2
"""

# Two heroes on the same team (either side), each pair once; "wins" are theirs.
SYNERGY_SQL = """
SELECT a.h AS hero, b.h AS other, count(*) AS games,
       sum(CASE WHEN m.win THEN 1 ELSE 0 END) AS wins
FROM (SELECT radiant_team AS team, radiant_win AS win FROM public_matches
      WHERE match_id > {lo} AND match_id <= {hi}
      UNION ALL
      SELECT dire_team, NOT radiant_win FROM public_matches
      WHERE match_id > {lo} AND match_id <= {hi}) m,
     unnest(m.team) a(h), unnest(m.team) b(h)
WHERE a.h < b.h
GROUP BY 1, 2
"""

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


def parse_public_matchups(
    rows: list[dict], out: dict[int, dict[int, Record]] | None = None
) -> dict[int, dict[int, Record]]:
    """Add explorer rows (Radiant hero, Dire hero, games, Radiant wins) to
    hero -> enemy -> Record, from both heroes' side."""
    out = {} if out is None else out
    for r in rows:
        games, rad_wins = int(r["games"]), int(r["wins"])
        _add(out, r["hero"], r["other"], games, rad_wins)
        _add(out, r["other"], r["hero"], games, games - rad_wins)
    return out


def parse_public_synergy(
    rows: list[dict], out: dict[int, dict[int, Record]] | None = None
) -> dict[int, dict[int, Record]]:
    """Add explorer rows (two teammates, games, their wins) to
    hero -> ally -> Record, both ways round."""
    out = {} if out is None else out
    for r in rows:
        games, wins = int(r["games"]), int(r["wins"])
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


def _explore_retry(client: httpx.Client, sql: str, sleep) -> list[dict]:
    """One query, retried once: the explorer sometimes takes minutes on a window."""
    try:
        return _explore(client, sql)
    except httpx.HTTPError as e:
        log.info("Explorer query failed (%s); retrying once", e)
        sleep(REQUEST_INTERVAL_SECONDS)
        return _explore(client, sql)


def fetch_public(client: httpx.Client, sleep=time.sleep) -> tuple[dict, dict]:
    """Matchups and synergy from the newest public matches, one id window at a time.

    A window whose queries still fail after a retry is skipped and an older one
    tried instead, so one slow query doesn't throw the rest away. Raises if
    fewer than PUBLIC_MATCH_MIN_WINDOWS windows come back.
    """
    hi = int(_explore_retry(client, LATEST_MATCH_SQL, sleep)[0]["max_id"])
    matchups: dict[int, dict[int, Record]] = {}
    synergy: dict[int, dict[int, Record]] = {}
    done = 0
    for _ in range(PUBLIC_MATCH_MAX_TRIES):
        if done == PUBLIC_MATCH_WINDOWS:
            break
        lo = hi - PUBLIC_MATCH_WINDOW_IDS
        try:
            sleep(REQUEST_INTERVAL_SECONDS)
            vs = _explore_retry(client, MATCHUPS_SQL.format(lo=lo, hi=hi), sleep)
            sleep(REQUEST_INTERVAL_SECONDS)
            with_ = _explore_retry(client, SYNERGY_SQL.format(lo=lo, hi=hi), sleep)
        except httpx.HTTPError as e:
            log.warning("Skipping public matches %d-%d (%s)", lo, hi, e)
        else:
            # Add a window only when both queries worked, so both tables cover the same games.
            parse_public_matchups(vs, matchups)
            parse_public_synergy(with_, synergy)
            done += 1
        hi = lo
    if done < PUBLIC_MATCH_MIN_WINDOWS:
        raise httpx.HTTPError(f"only {done} of {PUBLIC_MATCH_WINDOWS} public-match windows loaded")
    log.info("Loaded %d public-match windows", done)
    return matchups, synergy


def fetch(client: httpx.Client | None = None, sleep=time.sleep) -> Stats:
    own_client = client is None
    client = client or httpx.Client(
        base_url=OPENDOTA,
        timeout=httpx.Timeout(30, read=EXPLORER_TIMEOUT_SECONDS),
        # OpenDota's Cloudflare blocks some default library user agents.
        headers={"User-Agent": "dota2picker (+https://github.com/MarioRozic/dota2picker)"},
    )
    try:
        resp = client.get("/heroStats")
        resp.raise_for_status()
        stats = Stats(fetched_at=time.time(), bracket=parse_hero_stats(resp.json()))
        try:
            stats.matchups, stats.synergy = fetch_public(client, sleep)
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
