"""Player values for the league's scoring.

Category leagues: per-game z-scores against the pool of players likely to be drafted.
Percentage categories are weighted by attempts, so a 90% FT shooter on 1 attempt a game
counts for less than one on 8. Points leagues: projected season fantasy points above the
replacement-level player.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from .constants import PERCENT_STATS
from .models import League, Player

FULL_SEASON_GP = 72  # games played at which a player gets full credit


@dataclass
class Valuation:
    value: dict[int, float]  # player id -> overall value (higher is better)
    cats: dict[int, dict[int, float]] = field(default_factory=dict)  # player id -> stat id -> z
    fpts: dict[int, float] = field(default_factory=dict)  # points leagues: fantasy points per game
    pool_size: int = 0

    def rank(self) -> list[int]:
        return sorted(self.value, key=self.value.get, reverse=True)


def games_factor(p: Player, league: League) -> float:
    if league.season_totals or not p.gp:  # roto values already count games played
        return 1.0
    return min(p.gp / FULL_SEASON_GP, 1.0)


def value_points(players: list[Player], league: League, pool_size: int) -> Valuation:
    fpts = {p.id: sum(p.avg.get(sid, 0.0) * pts for sid, pts in league.points.items()) for p in players}
    season = {p.id: fpts[p.id] * (p.gp or FULL_SEASON_GP) for p in players}
    ordered = sorted(season.values(), reverse=True)
    replacement = ordered[min(pool_size, len(ordered)) - 1] if ordered else 0.0
    return Valuation({pid: v - replacement for pid, v in season.items()}, fpts=fpts, pool_size=pool_size)


def _category_z(players: list[Player], league: League, pool: list[Player]) -> dict[int, dict[int, float]]:
    z: dict[int, dict[int, float]] = {p.id: {} for p in players}
    # Per-game stats for head-to-head; projected season totals for roto.
    games = {p.id: (p.gp or FULL_SEASON_GP) if league.season_totals else 1.0 for p in players}
    for cat in league.categories:
        sid = cat.stat_id
        if sid in PERCENT_STATS and all(PERCENT_STATS[sid][1] in p.avg for p in pool[:10]):
            made, att = PERCENT_STATS[sid]
            total_att = sum(p.avg.get(att, 0.0) * games[p.id] for p in pool) or 1.0
            league_pct = sum(p.avg.get(made, 0.0) * games[p.id] for p in pool) / total_att

            def metric(p: Player, made=made, att=att, league_pct=league_pct) -> float:
                return (p.avg.get(made, 0.0) - league_pct * p.avg.get(att, 0.0)) * games[p.id]
        else:
            def metric(p: Player, sid=sid) -> float:
                return p.avg.get(sid, 0.0) * games[p.id]

        pool_vals = [metric(p) for p in pool]
        mean = statistics.fmean(pool_vals) if pool_vals else 0.0
        std = statistics.pstdev(pool_vals) if len(pool_vals) > 1 else 0.0
        for p in players:
            score = (metric(p) - mean) / std if std else 0.0
            z[p.id][sid] = -score if cat.reverse else score
    return z


def value_categories(players: list[Player], league: League, pool_size: int,
                     punt: set[int] = frozenset()) -> Valuation:
    with_stats = [p for p in players if p.avg]
    # Seed the pool by ESPN's own rank, then re-pool on our values until it settles.
    pool = sorted(with_stats, key=lambda p: p.espn_rank or 10_000)[:pool_size]
    value: dict[int, float] = {}
    z: dict[int, dict[int, float]] = {}
    for _ in range(3):
        z = _category_z(players, league, pool)
        value = {}
        for p in players:
            total = sum(v for sid, v in z[p.id].items() if sid not in punt)
            value[p.id] = total * games_factor(p, league) if total > 0 else total
            if not p.avg:
                value[p.id] = -99.0
        pool = sorted(with_stats, key=lambda p: value[p.id], reverse=True)[:pool_size]
    return Valuation(value, cats=z, pool_size=pool_size)


def value_players(players: list[Player], league: League, punt: set[int] = frozenset()) -> Valuation:
    pool_size = max(league.num_teams * league.rounds, 20)
    if league.is_points:
        return value_points(players, league, pool_size)
    return value_categories(players, league, pool_size, punt)
