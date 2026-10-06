"""Synthetic, deterministic stats so the app runs and tests pass offline."""

from __future__ import annotations

import random
import time

from . import heroes
from .stats import BRACKETS, Record, Stats


def demo_stats(seed: int = 7) -> Stats:
    rng = random.Random(seed)
    ids = [h.id for h in heroes.all_heroes()]
    strength = {h: rng.gauss(0, 0.15) for h in ids}
    stats = Stats(fetched_at=time.time())
    for b in BRACKETS.values():
        stats.bracket[b] = {}
        for h in ids:
            games = rng.randint(5_000, 60_000)
            p = 0.5 + strength[h] / 4 + rng.gauss(0, 0.01)
            stats.bracket[b][h] = Record(games, round(games * p))
    for h in ids:
        stats.matchups[h] = {}
    for i, h in enumerate(ids):
        for o in ids[i + 1 :]:
            games = rng.randint(50, 3_000)
            edge = strength[h] - strength[o] + rng.gauss(0, 0.2)
            p = 1 / (1 + 2.718281828 ** (-edge))
            wins = round(games * p)
            stats.matchups[h][o] = Record(games, wins)
            stats.matchups[o][h] = Record(games, games - wins)
    return stats
