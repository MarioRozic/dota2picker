"""Item builds split by game phase: what to buy at the start, early, mid and late game.

Two sources are merged:
- Valve's recommended build for each hero (data/builds.json, the Starting /
  Early / Mid / Late / Other lists in the in-game shop). Hand-picked, one per
  hero, and the only source for starting and small laning items.
- OpenDota item timings: when players buy each item costing 1400 or more, from
  public parsed games of all ranks, up to 30 minutes. Used to order the items
  and put them in the phase they're actually bought in.

Counter items for the enemy lineup (items.suggest_items) are slotted into the
phase where they're normally bought and marked with the enemies they answer.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import httpx

from . import heroes, items

log = logging.getLogger(__name__)

PHASES = ("start", "early", "mid", "late", "other")
# Minutes where each phase ends: early is up to 10 minutes, mid up to 20.
EARLY_END, MID_END = 10, 20
ROW_LIMIT = {"start": 8, "early": 4, "mid": 4, "late": 4, "other": 6}
# At most this many counter items are added to a phase row.
COUNTERS_PER_ROW = 2

VALVE_SECTIONS = {
    "Starting_Items": "start",
    "Early_Game": "early",
    "Mid_Items": "mid",
    "Core_Items": "mid",
    "Late_Items": "late",
    "Other_Items": "other",
    "Luxury": "other",
}

# Pieces of bigger items that are rarely the goal themselves. Blink Dagger and
# Ghost Scepter are pieces too, but people buy them to use.
_KEEP_PIECES = {"blink", "ghost"}

OPENDOTA = "https://api.opendota.com/api"
TIMINGS_TTL_SECONDS = 24 * 3600
# After a failed download, don't make every request wait on the network again.
RETRY_AFTER_SECONDS = 600
# An item must be bought this often (relative to the hero's most bought item) to count.
MIN_SHARE = 0.15
MIN_GAMES = 30


def parse_valve_build(text: str) -> dict[str, list[str]]:
    """Read a Valve itembuilds/default_<hero>.txt into phase -> item keys.

    Starting items keep duplicates (two Iron Branches); the other phases don't.
    A recipe stands for the item it completes.
    """
    out: dict[str, list[str]] = {p: [] for p in PHASES}
    phase = None
    for line in text.splitlines():
        section = re.search(r'"#DOTA_Item_Build_(\w+)"', line)
        if section:
            phase = VALVE_SECTIONS.get(section.group(1))  # *_Secondary lists are skipped
            continue
        item = re.search(r'"item"\s+"item_(\w+)"', line)
        if item and phase:
            key = item.group(1).removeprefix("recipe_")
            if phase == "start" or key not in out[phase]:
                out[phase].append(key)
    return out


@lru_cache(maxsize=1)
def valve_builds() -> dict[str, dict[str, list[str]]]:
    return items._data("builds.json")


@lru_cache(maxsize=1)
def _pieces() -> set[str]:
    """Items that are only a piece of a bigger item."""
    raw = items._data("items.json")
    used = {c for v in raw.values() for c in v.get("components") or []}
    return {k for k, v in raw.items() if k in used and not v.get("components")} - _KEEP_PIECES


@dataclass
class Timing:
    games: int
    minute: float  # median minute the item is bought by


def parse_item_timings(rows: list[dict]) -> dict[str, Timing]:
    """Turn OpenDota /scenarios/itemTimings rows into item -> how often and when it's bought.

    Each row counts the games where the item was bought by `time` seconds
    (7.5, 10, 12, 15, 20, 25 or 30 minutes).
    """
    by_item: dict[str, list[tuple[float, int]]] = {}
    for row in rows:
        by_item.setdefault(row["item"], []).append((int(row["time"]) / 60, int(row["games"])))
    out = {}
    for key, buckets in by_item.items():
        buckets.sort()
        total = sum(g for _, g in buckets)
        seen = 0
        for minute, games in buckets:
            seen += games
            if seen * 2 >= total:
                break
        out[key] = Timing(total, minute)
    return out


def phase_for_minute(minute: float) -> str:
    if minute <= EARLY_END:
        return "early"
    return "mid" if minute <= MID_END else "late"


class TimingsCache:
    """OpenDota item timings per hero, downloaded on first use and kept for a day."""

    def __init__(self, folder: Path | None = None, client: httpx.Client | None = None):
        self.folder = folder or Path.home() / ".dota2picker" / "item_timings"
        self.client = client
        self.failed_at = 0.0

    def __call__(self, hero_id: int) -> list[dict] | None:
        path = self.folder / f"{hero_id}.json"
        cached = None
        if path.exists():
            cached = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - cached["fetched_at"] < TIMINGS_TTL_SECONDS:
                return cached["rows"]
        if time.time() - self.failed_at < RETRY_AFTER_SECONDS:
            return cached and cached["rows"]
        try:
            client = self.client or httpx.Client(base_url=OPENDOTA, timeout=8)
            try:
                resp = client.get("/scenarios/itemTimings", params={"hero_id": hero_id})
                resp.raise_for_status()
                rows = resp.json()
            finally:
                if self.client is None:
                    client.close()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("OpenDota item timings for hero %s failed: %s", hero_id, e)
            self.failed_at = time.time()
            return cached and cached["rows"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"fetched_at": time.time(), "rows": rows}), encoding="utf-8")
        return rows


@dataclass
class BuildItem:
    item: items.Item
    count: int = 1
    minute: float | None = None  # typical minute it's bought by, from OpenDota
    # enemy hero id -> the threats of that enemy this item answers
    answers: dict[int, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        by_id = heroes.by_id()
        return {
            "key": self.item.key,
            "name": self.item.name,
            "cost": self.item.cost,
            "img_url": self.item.img_url,
            "count": self.count,
            "minute": self.minute,
            "answers": [
                {"enemy": by_id[e].localized_name, "threats": reasons}
                for e, reasons in self.answers.items()
            ],
        }


def phase_by_cost(cost: int) -> str:
    """Where a counter item with no timing data goes: cheap ones early, the rest by price."""
    if cost < 1000:
        return "early"
    return "mid" if cost <= 4500 else "late"


def build(
    hero_id: int,
    enemies: list[int] = (),
    position: int | None = None,
    timings: list[dict] | None = None,
) -> dict[str, list[BuildItem]]:
    """The hero's build by phase, with counter items for `enemies` slotted in."""
    hero = heroes.by_id()[hero_id]
    catalogue = items.all_items()
    valve = valve_builds().get(hero.short_name, {})
    timed = parse_item_timings(timings or [])
    rows: dict[str, list[BuildItem]] = {p: [] for p in PHASES}
    placed: dict[str, BuildItem] = {}

    def add(phase: str, key: str) -> BuildItem | None:
        if key not in catalogue or key in placed:
            return None
        t = timed.get(key)
        entry = BuildItem(catalogue[key], minute=t.minute if t else None)
        rows[phase].append(entry)
        placed[key] = entry
        return entry

    for key in valve.get("start", []):
        if key in placed:
            placed[key].count += 1
        else:
            add("start", key)

    # Items players really buy, most bought first, each in the phase it's bought in.
    top = max((t.games for t in timed.values()), default=0)
    popular = sorted(
        (
            (k, t)
            for k, t in timed.items()
            if k not in _pieces() and t.games >= max(MIN_GAMES, top * MIN_SHARE)
        ),
        key=lambda kt: -kt[1].games,
    )
    # Valve's early items (boots, Magic Wand) go first: the timings only start at 1400 gold.
    for key in valve.get("early", []):
        if len(rows["early"]) < ROW_LIMIT["early"]:
            add("early", key)
    for key, t in popular:
        phase = phase_for_minute(t.minute)
        if len(rows[phase]) < ROW_LIMIT[phase]:
            add(phase, key)
    # Valve's lists fill whatever the timings left empty (and everything after 30 minutes).
    for phase in ("mid", "late", "other"):
        for key in valve.get(phase, []):
            if len(rows[phase]) < ROW_LIMIT[phase]:
                add(phase, key)

    if enemies:
        added = {p: 0 for p in PHASES}
        for s in items.suggest_items(hero_id, list(enemies), position):
            entry = placed.get(s.item.key)
            if entry is not None and entry in rows["other"]:
                # A "maybe later" item that answers this lineup moves up into the build.
                rows["other"].remove(entry)
                entry = None
            if entry is None:
                t = timed.get(s.item.key)
                phase = phase_for_minute(t.minute) if t else phase_by_cost(s.item.cost)
                if added[phase] >= COUNTERS_PER_ROW:
                    phase = "other"
                added[phase] += 1
                entry = BuildItem(s.item, minute=t.minute if t else None)
                # Answers to this lineup go before the usual items.
                rows[phase].insert(added[phase] - 1, entry)
                placed[s.item.key] = entry
            entry.answers = s.answers
    return rows
