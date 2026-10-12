"""Synthetic league and players for practicing with the UI without ESPN (and for tests)."""
from __future__ import annotations

import random

from .models import Category, League, Player, Team

NINE_CAT = [(19, "FG%", False), (20, "FT%", False), (17, "3PM", False), (6, "REB", False), (3, "AST", False),
            (2, "STL", False), (1, "BLK", False), (11, "TO", True), (0, "PTS", False)]
LINEUP = {0: 1, 1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 11: 3, 12: 3, 13: 1}  # PG SG SF PF C G F UTx3 BEx3 IR
POS_SLOTS = {"PG": {0, 5, 11, 12, 13}, "SG": {1, 5, 11, 12, 13}, "SF": {2, 6, 11, 12, 13},
             "PF": {3, 6, 11, 12, 13}, "C": {4, 11, 12, 13}}


def demo_league(num_teams: int = 10, points: bool = False) -> League:
    teams = {i: Team(i, f"Team {i}", f"T{i}") for i in range(1, num_teams + 1)}
    if points:
        pts = {0: 1, 6: 1, 3: 2, 2: 4, 1: 4, 11: -2, 13: 2, 14: -1, 15: 1, 16: -1, 17: 1}
        cats = []
    else:
        pts = {}
        cats = [Category(s, n, r) for s, n, r in NINE_CAT]
    return League(1, 2027, "Demo League", "H2H_POINTS" if points else "H2H_CATEGORY", cats, pts,
                  dict(LINEUP), teams, list(range(1, num_teams + 1)))


def demo_players(n: int = 250, seed: int = 7) -> list[Player]:
    rng = random.Random(seed)
    players = []
    for i in range(n):
        talent = max(0.15, 1.0 - i / n + rng.gauss(0, 0.12))
        pos = rng.choice(list(POS_SLOTS))
        big = pos in ("PF", "C")
        fga = 6 + 14 * talent
        fta = (2 + 6 * talent) * (1.2 if big else 1.0)
        tpa = (1 if big and pos == "C" else 3) + 5 * talent * rng.random()
        fgm = fga * (rng.uniform(0.50, 0.60) if big else rng.uniform(0.42, 0.49))
        ftm = fta * (rng.uniform(0.60, 0.78) if big else rng.uniform(0.75, 0.92))
        tpm = min(tpa * rng.uniform(0.30, 0.40), fgm)
        avg = {
            13: fgm, 14: fga, 15: ftm, 16: fta, 17: tpm, 18: tpa,
            19: fgm / fga, 20: ftm / fta,
            0: 2 * fgm + tpm + ftm,
            6: (3 + 9 * talent) * (1.5 if big else 0.8),
            3: (1 + 8 * talent) * (1.5 if pos == "PG" else 0.6),
            2: 0.4 + 1.2 * talent * rng.random(),
            1: (0.2 + 1.5 * talent * rng.random()) * (1.8 if big else 0.5),
            11: 0.8 + 2.5 * talent,
        }
        gp = rng.choice([82, 78, 74, 70, 65, 58, 45])
        players.append(Player(
            id=1000 + i, name=f"Demo Player {i + 1}", pro_team="DEM", positions=[pos],
            eligible_slots=POS_SLOTS[pos], avg=avg, gp=gp,
            injury="OUT" if rng.random() < 0.03 else None,
            adp=i + 1 + rng.gauss(0, 4), espn_rank=i + 1, stat_source="proj",
        ))
    return players
