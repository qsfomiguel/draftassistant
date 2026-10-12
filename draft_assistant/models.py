from __future__ import annotations

from dataclasses import dataclass, field

from .constants import IR_SLOT, POINTS_SCORING


@dataclass
class Player:
    id: int
    name: str
    pro_team: str
    positions: list[str]
    eligible_slots: set[int]
    avg: dict[int, float]  # per-game stats keyed by ESPN stat id
    gp: float | None = None  # projected (or last season's) games played
    injury: str | None = None
    adp: float | None = None
    espn_rank: int | None = None
    stat_source: str = "none"  # "proj", "last", "current" or "none"


@dataclass
class Category:
    stat_id: int
    name: str
    reverse: bool = False  # lower is better, e.g. turnovers


@dataclass
class Team:
    id: int
    name: str
    abbrev: str
    owners: list[str] = field(default_factory=list)


@dataclass
class Pick:
    overall: int
    team_id: int
    player_id: int
    keeper: bool = False
    manual: bool = False


@dataclass
class League:
    id: int
    season: int
    name: str
    scoring_type: str
    categories: list[Category]
    points: dict[int, float]
    lineup_slots: dict[int, int]
    teams: dict[int, Team]
    pick_order: list[int]
    draft_type: str = "SNAKE"

    @property
    def is_points(self) -> bool:
        return self.scoring_type in POINTS_SCORING

    @property
    def season_totals(self) -> bool:
        """Roto ranks season totals, so games played matter as much as per-game production."""
        return self.scoring_type == "ROTO"

    @property
    def num_teams(self) -> int:
        return len(self.teams) or len(self.pick_order)

    @property
    def rounds(self) -> int:
        return sum(n for slot, n in self.lineup_slots.items() if slot != IR_SLOT)
