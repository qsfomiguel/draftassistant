"""Draft state (who picked whom, whose turn it is) and pick suggestions."""
from __future__ import annotations

import difflib
import unicodedata
from dataclasses import dataclass

from .models import League, Pick, Player
from .roster import fits_starting, starting_slots
from .valuation import Valuation, games_factor

BENCH_FACTOR = 0.85  # value kept by a player who would only sit on your bench


class DraftState:
    def __init__(self, league: League, players: list[Player], my_team_id: int | None):
        self.league = league
        self.players = {p.id: p for p in players}
        self.my_team_id = my_team_id
        self.espn_picks: dict[int, Pick] = {}
        self.manual_picks: dict[int, Pick] = {}
        self.in_progress = False
        self.drafted = False

    # ---- picks -------------------------------------------------------------
    @property
    def picks(self) -> dict[int, Pick]:
        merged = dict(self.manual_picks)
        espn_players = {p.player_id for p in self.espn_picks.values()}
        # A manual entry ESPN has since recorded elsewhere is dropped.
        merged = {n: p for n, p in merged.items() if p.player_id not in espn_players}
        merged.update(self.espn_picks)
        return merged

    def update_from_espn(self, picks: list[Pick], in_progress: bool, drafted: bool) -> bool:
        new = {p.overall: p for p in picks}
        changed = new != self.espn_picks or in_progress != self.in_progress
        self.espn_picks, self.in_progress, self.drafted = new, in_progress, drafted
        return changed

    @property
    def drafted_ids(self) -> set[int]:
        return {p.player_id for p in self.picks.values()}

    @property
    def total_picks(self) -> int:
        return self.league.num_teams * self.league.rounds

    def current_overall(self) -> int | None:
        taken = self.picks
        for n in range(1, self.total_picks + 1):
            if n not in taken:
                return n
        return None

    def team_for_overall(self, overall: int) -> int | None:
        order = self.league.pick_order
        if not order:
            return None
        rnd, idx = divmod(overall - 1, len(order))
        if self.league.draft_type != "LINEAR" and rnd % 2 == 1:
            idx = len(order) - 1 - idx
        return order[idx]

    def my_upcoming(self) -> list[int]:
        if self.my_team_id is None:
            return []
        taken = self.picks
        return [n for n in range(1, self.total_picks + 1)
                if n not in taken and self.team_for_overall(n) == self.my_team_id]

    def roster(self, team_id: int | None) -> list[Player]:
        return [self.players[p.player_id] for _, p in sorted(self.picks.items())
                if p.team_id == team_id and p.player_id in self.players]

    def record_manual(self, player_id: int, team_id: int | None = None) -> Pick | None:
        overall = self.current_overall()
        if overall is None:
            return None
        if team_id is None:
            team_id = self.team_for_overall(overall) or -1
        pick = Pick(overall, team_id, player_id, manual=True)
        self.manual_picks[overall] = pick
        return pick

    def undo_manual(self) -> Pick | None:
        if not self.manual_picks:
            return None
        return self.manual_picks.pop(max(self.manual_picks))

    def available(self) -> list[Player]:
        drafted = self.drafted_ids
        return [p for p in self.players.values() if p.id not in drafted]

    # ---- lookup ------------------------------------------------------------
    def find_player(self, query: str, only_available: bool = True) -> list[Player]:
        pool = self.available() if only_available else list(self.players.values())
        q = normalize(query)
        exact = [p for p in pool if normalize(p.name) == q]
        if exact:
            return exact
        partial = [p for p in pool if q in normalize(p.name)]
        if partial:
            return partial
        names = {normalize(p.name): p for p in pool}
        return [names[n] for n in difflib.get_close_matches(q, list(names), n=5, cutoff=0.6)]


def normalize(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return "".join(c for c in name.lower() if c.isalnum() or c == " ").strip()


@dataclass
class Suggestion:
    player: Player
    score: float
    value: float
    fits: bool
    lasts: bool | None  # likely still there at your next pick (by ADP)?


def category_weights(state: DraftState, valuation: Valuation, balance: float,
                     punt: set[int]) -> dict[int, float]:
    """Upweight categories where my roster is weakest, so picks round out the team."""
    cats = [c.stat_id for c in state.league.categories if c.stat_id not in punt]
    weights = {sid: 1.0 for sid in cats}
    mine = state.roster(state.my_team_id)
    if balance <= 0 or len(mine) < 2 or not cats:
        return weights
    totals = {sid: sum(valuation.cats.get(p.id, {}).get(sid, 0.0) for p in mine) for sid in cats}
    mean = sum(totals.values()) / len(totals)
    for sid in cats:
        weights[sid] = min(max(1.0 + balance * (mean - totals[sid]) / len(mine), 0.5), 1.5)
    return weights


def suggest(state: DraftState, valuation: Valuation, top: int = 15, balance: float = 0.25,
            punt: set[int] = frozenset()) -> list[Suggestion]:
    league = state.league
    slots = starting_slots(league.lineup_slots)
    mine = state.roster(state.my_team_id)
    weights = None if league.is_points else category_weights(state, valuation, balance, punt)
    upcoming = state.my_upcoming()
    current = state.current_overall()
    # Will the player still be there at my next pick? If I'm on the clock, that means the one after.
    if upcoming and upcoming[0] == current:
        upcoming = upcoming[1:]
    next_check = upcoming[0] if upcoming else None

    out = []
    for p in state.available():
        value = valuation.value.get(p.id, -99.0)
        if weights is not None and p.avg:
            score = sum(z * weights.get(sid, 0.0) for sid, z in valuation.cats.get(p.id, {}).items())
            if score > 0:
                score *= games_factor(p)
        else:
            score = value
        fits = fits_starting(mine, p, slots) if slots else True
        if not fits and score > 0:
            score *= BENCH_FACTOR
        lasts = None
        if p.adp and next_check:
            lasts = p.adp > next_check + 2
        out.append(Suggestion(p, score, value, fits, lasts))
    out.sort(key=lambda s: s.score, reverse=True)
    return out[:top]
