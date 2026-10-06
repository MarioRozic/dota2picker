"""Counter-pick scoring.

For each candidate hero h:

    score(h) = sum over enemies e of adv(h, e)
             + sum over allies a of syn(h, a)
             + META_WEIGHT * meta(h)

adv(h, e) is how much better h does against e than you would expect from the
two heroes' overall strength. Expected win rate comes from their overall
records in log-odds space, and the observed matchup win rate is shrunk toward
that expectation so small samples can't dominate.

syn(h, a) is the same idea for h and a on the same team: how much more often
they win together than their overall strength predicts. Together these mirror
Dota Plus's "Friends and Foes" numbers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import heroes
from .stats import Record, Stats

# Pseudo-games pulling a matchup win rate toward its expectation.
MATCHUP_PRIOR_GAMES = 300
# Pseudo-games pulling a hero's bracket win rate toward 50%.
META_PRIOR_GAMES = 2000
META_WEIGHT = 0.4


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def _overall(rows: dict[int, Record]) -> float:
    games = sum(r.games for r in rows.values())
    wins = sum(r.wins for r in rows.values())
    return 0.5 if games == 0 else wins / games


@dataclass
class Draft:
    allies: list[int] = field(default_factory=list)
    enemies: list[int] = field(default_factory=list)
    bans: list[int] = field(default_factory=list)

    def unavailable(self) -> set[int]:
        return set(self.allies) | set(self.enemies) | set(self.bans)


@dataclass
class Reason:
    enemy_id: int
    advantage: float  # win-rate points, e.g. 0.031 = +3.1%


@dataclass
class Suggestion:
    hero_id: int
    score: float
    meta: float
    reasons: list[Reason]
    # one per ally; Reason.enemy_id holds the ally's id here
    synergy: list[Reason] = field(default_factory=list)

    def to_dict(self) -> dict:
        h = heroes.by_id()[self.hero_id]
        return {
            "hero": h.to_dict(),
            "score": round(self.score * 100, 2),
            "meta": round(self.meta * 100, 2),
            "reasons": [
                {
                    "enemy": heroes.by_id()[r.enemy_id].localized_name,
                    "advantage": round(r.advantage * 100, 2),
                }
                for r in self.reasons
            ],
            "synergy": [
                {
                    "ally": heroes.by_id()[r.enemy_id].localized_name,
                    "advantage": round(r.advantage * 100, 2),
                }
                for r in self.synergy
            ],
        }


class Scorer:
    def __init__(self, stats: Stats, bracket: int | None = None):
        self.stats = stats
        self.bracket = bracket
        self._overall = {h: _overall(rows) for h, rows in stats.matchups.items()}

    def advantage(self, hero: int, enemy: int) -> float:
        rec = self.stats.matchups.get(hero, {}).get(enemy)
        expected = _sigmoid(
            _logit(self._overall.get(hero, 0.5)) - _logit(self._overall.get(enemy, 0.5))
        )
        return self._shrunk_edge(rec, expected)

    def synergy(self, hero: int, ally: int) -> float:
        rec = self.stats.synergy.get(hero, {}).get(ally)
        expected = _sigmoid(
            _logit(self._overall.get(hero, 0.5)) + _logit(self._overall.get(ally, 0.5))
        )
        return self._shrunk_edge(rec, expected)

    @staticmethod
    def _shrunk_edge(rec: Record | None, expected: float) -> float:
        if rec is None or rec.games == 0:
            return 0.0
        shrunk = (rec.wins + MATCHUP_PRIOR_GAMES * expected) / (rec.games + MATCHUP_PRIOR_GAMES)
        return shrunk - expected

    def meta(self, hero: int) -> float:
        if self.bracket is None:
            return 0.0
        rec = self.stats.bracket.get(self.bracket, {}).get(hero)
        if rec is None or rec.games == 0:
            return 0.0
        return (rec.wins + META_PRIOR_GAMES * 0.5) / (rec.games + META_PRIOR_GAMES) - 0.5

    def score(self, hero: int, draft: Draft) -> Suggestion:
        reasons = [Reason(e, self.advantage(hero, e)) for e in draft.enemies]
        synergy = [Reason(a, self.synergy(hero, a)) for a in draft.allies]
        meta = self.meta(hero)
        total = (
            sum(r.advantage for r in reasons)
            + sum(r.advantage for r in synergy)
            + META_WEIGHT * meta
        )
        reasons.sort(key=lambda r: r.advantage, reverse=True)
        synergy.sort(key=lambda r: r.advantage, reverse=True)
        return Suggestion(hero, total, meta, reasons, synergy)

    def suggest(self, draft: Draft, position: int | None = None, limit: int = 5) -> dict:
        """Return the best and worst picks for this draft.

        position (1-5) keeps only heroes commonly played there.
        """
        taken = draft.unavailable()
        pool = [
            h.id
            for h in heroes.all_heroes()
            if h.id not in taken and (position is None or position in h.positions)
        ]
        ranked = sorted((self.score(h, draft) for h in pool), key=lambda s: s.score, reverse=True)
        has_draft = bool(draft.enemies or draft.allies)
        return {"best": ranked[:limit], "avoid": ranked[::-1][:3] if has_draft else []}
