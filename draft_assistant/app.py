"""Application state behind the browser UI: loads the league, follows the draft, answers actions."""
from __future__ import annotations

import threading
import time

from . import demo
from .config import CACHE_DIR, Config, normalize_espn_s2, normalize_swid, parse_punt, save_config
from .draft import DraftState, suggest
from .espn import EspnClient, EspnError, find_my_team, parse_league, parse_picks, parse_players
from .models import Player
from .valuation import Valuation, value_players

BOARD_SIZE = 300  # how many available players the board shows


class App:
    def __init__(self, cfg: Config, save=save_config):
        self.cfg = cfg
        self._save = save
        self.lock = threading.RLock()
        self.mode = "none"  # "espn", "demo" or "none"
        self.client: EspnClient | None = None
        self.state: DraftState | None = None
        self.valuation: Valuation | None = None
        self.error: str | None = None
        self.poll_error: str | None = None
        self.last_poll: float | None = None
        self.version = 0

    # ---- loading -------------------------------------------------------------
    def _changed(self) -> None:
        self.version += 1

    def _revalue(self) -> None:
        self.valuation = value_players(list(self.state.players.values()), self.state.league, self.cfg.punt_ids)

    def load_espn(self, refresh: bool = False) -> None:
        with self.lock:
            cfg = self.cfg
            if not cfg.league_id:
                raise ValueError("Enter your ESPN league ID first.")
            client = EspnClient(cfg.league_id, cfg.season, cfg.espn_s2, cfg.swid)
            raw = client.league_raw()
            league = parse_league(raw, cfg.league_id, cfg.season)
            players = parse_players(client.players_cached(CACHE_DIR, cfg.player_limit, refresh=refresh), cfg.season)
            my_team = cfg.team_id if cfg.team_id in league.teams else find_my_team(league, cfg.swid)
            state = DraftState(league, players, my_team)
            state.update_from_espn(*parse_picks(raw))
            self.client, self.state, self.mode = client, state, "espn"
            self.error = self.poll_error = None
            self.last_poll = time.time()
            self._revalue()
            self._changed()

    def load_demo(self, points: bool = False, slot: int = 4) -> None:
        with self.lock:
            self.client = None
            self.state = DraftState(demo.demo_league(points=points), demo.demo_players(), slot)
            self.mode = "demo"
            self.error = self.poll_error = None
            self._revalue()
            self._changed()

    def try_load(self) -> None:
        """Load on startup if the league is configured; keep the error for the page to show."""
        if not self.cfg.league_id:
            return
        try:
            self.load_espn()
        except (EspnError, ValueError) as exc:
            with self.lock:
                self.error = str(exc)
                self._changed()

    def update_config(self, data: dict) -> None:
        with self.lock:
            cfg = self.cfg
            if "league_id" in data:
                lid = str(data["league_id"] or "").strip()
                if lid and not lid.isdigit():
                    raise ValueError("The league ID should be a number.")
                cfg.league_id = int(lid) if lid else None
            if data.get("season"):
                cfg.season = int(data["season"])
            # Blank cookie fields keep what's saved; clear_cookies removes them.
            if data.get("clear_cookies"):
                cfg.espn_s2 = cfg.swid = None
            if data.get("espn_s2"):
                cfg.espn_s2 = normalize_espn_s2(str(data["espn_s2"]))
            if data.get("swid"):
                cfg.swid = normalize_swid(str(data["swid"]))
            self._save(cfg)
        self.load_espn(refresh=True)

    def update_settings(self, data: dict) -> None:
        with self.lock:
            cfg = self.cfg
            if "punt" in data:
                parse_punt(data["punt"])  # validate
                cfg.punt = list(data["punt"])
            if "balance" in data:
                cfg.balance = max(0.0, min(float(data["balance"]), 1.0))
            if "live" in data:
                cfg.live = bool(data["live"])
            if "team_id" in data and self.state:
                team_id = int(data["team_id"]) if data["team_id"] not in (None, "") else None
                self.state.my_team_id = team_id
                if self.mode == "espn":
                    cfg.team_id = team_id
            if self.mode == "espn":
                self._save(cfg)
            if self.state:
                self._revalue()
            self._changed()

    # ---- live polling -----------------------------------------------------------
    def poll(self) -> None:
        with self.lock:
            if self.mode != "espn" or not self.cfg.live or not self.client:
                return
            client = self.client
        try:
            picks = parse_picks(client.draft_raw())
        except EspnError as exc:
            with self.lock:
                if self.poll_error != str(exc):
                    self.poll_error = str(exc)
                    self._changed()
            return
        with self.lock:
            self.last_poll = time.time()
            changed = self.state.update_from_espn(*picks)
            if changed or self.poll_error:
                self.poll_error = None
                self._changed()

    def run_poller(self, stop: threading.Event) -> None:
        while not stop.wait(self.cfg.poll_seconds):
            try:
                self.poll()
            except Exception as exc:  # keep the poller alive whatever happens
                with self.lock:
                    self.poll_error = f"Polling failed: {exc}"
                    self._changed()

    # ---- draft actions --------------------------------------------------------
    def _require_state(self) -> DraftState:
        if not self.state:
            raise ValueError("No league loaded.")
        return self.state

    def record_pick(self, player_id: int, mine: bool) -> None:
        with self.lock:
            state = self._require_state()
            if player_id not in state.players:
                raise ValueError("Unknown player.")
            if player_id in state.drafted_ids:
                raise ValueError(f"{state.players[player_id].name} is already drafted.")
            if mine:
                team = state.my_team_id
            else:
                team = state.team_for_overall(state.current_overall() or 0)
                if team is None or team == state.my_team_id:
                    team = -1  # taken by someone else; keep him off my roster
            if state.record_manual(player_id, team) is None:
                raise ValueError("The draft is complete.")
            self._changed()

    def undo(self) -> None:
        with self.lock:
            if self._require_state().undo_manual() is None:
                raise ValueError("No picks entered here to undo.")
            self._changed()

    def autodraft(self) -> int:
        """Practice: other teams take the best player by ADP until it's my turn."""
        with self.lock:
            state = self._require_state()
            made = 0
            while True:
                current = state.current_overall()
                if current is None or state.team_for_overall(current) in (state.my_team_id, None):
                    break
                best = min(state.available(), key=lambda p: (p.adp or 999, p.espn_rank or 9999))
                state.record_manual(best.id)
                made += 1
            self._changed()
            return made

    def reset_manual(self) -> None:
        with self.lock:
            self._require_state().manual_picks.clear()
            self._changed()

    # ---- snapshot for the page ---------------------------------------------------
    def _player(self, p: Player) -> dict:
        v = self.valuation
        return {
            "id": p.id, "name": p.name, "pos": p.positions, "team": p.pro_team, "injury": p.injury,
            "gp": round(p.gp) if p.gp else None, "adp": round(p.adp, 1) if p.adp else None,
            "rank": p.espn_rank, "source": p.stat_source, "value": round(v.value.get(p.id, 0), 2),
            "cats": {str(k): round(z, 2) for k, z in v.cats.get(p.id, {}).items()},
            "fpg": round(v.fpts[p.id], 1) if p.id in v.fpts else None,
        }

    def _category_standings(self) -> dict:
        """Each category's total for my team and where it ranks among all teams."""
        state, v = self.state, self.valuation
        lg = state.league
        totals: dict[int, dict[str, float]] = {}
        for tid in lg.teams:
            roster = state.roster(tid)
            if lg.is_points:
                totals[tid] = {"fpg": sum(v.fpts.get(p.id, 0) for p in roster)}
            else:
                totals[tid] = {str(c.stat_id): sum(v.cats.get(p.id, {}).get(c.stat_id, 0) for p in roster)
                               for c in lg.categories}
        mine = totals.get(state.my_team_id)
        if not mine:
            return {}
        out = {}
        for key, val in mine.items():
            rank = 1 + sum(t[key] > val for tid, t in totals.items() if tid != state.my_team_id)
            out[key] = {"total": round(val, 2), "rank": rank}
        return out

    def snapshot(self) -> dict:
        with self.lock:
            base = {"version": self.version, "mode": self.mode, "config": self.cfg.public(), "error": self.error,
                    "poll_error": self.poll_error, "last_poll": self.last_poll}
            state = self.state
            if not state:
                return base
            lg = state.league
            current = state.current_overall()
            upcoming = state.my_upcoming()
            on_clock = state.team_for_overall(current) if current else None
            my_turn = current is not None and on_clock is not None and on_clock == state.my_team_id
            next_pick = upcoming[0] if upcoming else None
            if my_turn and len(upcoming) > 1:
                next_after = upcoming[1]
            else:
                next_after = next_pick
            suggestions = suggest(state, self.valuation, BOARD_SIZE, self.cfg.balance, self.cfg.punt_ids)
            teams = lg.teams
            picks = []
            for overall, pick in sorted(state.picks.items()):
                p = state.players.get(pick.player_id)
                team = teams.get(pick.team_id)
                picks.append({
                    "overall": overall, "round": (overall - 1) // max(lg.num_teams, 1) + 1,
                    "team": team.name if team else "?", "team_id": pick.team_id,
                    "player": p.name if p else str(pick.player_id), "pos": p.positions if p else [],
                    "mine": pick.team_id == state.my_team_id, "manual": pick.manual, "keeper": pick.keeper,
                })
            base.update({
                "league": {
                    "name": lg.name, "season": lg.season, "scoring": lg.scoring_type, "is_points": lg.is_points,
                    "num_teams": lg.num_teams, "rounds": lg.rounds, "draft_type": lg.draft_type,
                    "categories": [{"id": c.stat_id, "name": c.name, "reverse": c.reverse,
                                    "punted": c.stat_id in self.cfg.punt_ids} for c in lg.categories],
                    "teams": [{"id": t.id, "name": t.name, "abbrev": t.abbrev,
                               "slot": lg.pick_order.index(t.id) + 1 if t.id in lg.pick_order else None}
                              for t in teams.values()],
                    "has_order": bool(lg.pick_order),
                },
                "my_team_id": state.my_team_id,
                "clock": {
                    "current": current, "total": state.total_picks,
                    "round": (current - 1) // max(lg.num_teams, 1) + 1 if current else None,
                    "on_clock": teams[on_clock].name if on_clock in teams else None,
                    "my_turn": my_turn, "next_pick": next_pick,
                    "picks_away": next_pick - current if next_pick and current else None,
                    "next_after": next_after,
                    "espn": "done" if state.drafted else "live" if state.in_progress else "not started",
                },
                "suggestions": [dict(self._player(s.player), score=round(s.score, 2), fits=s.fits, lasts=s.lasts)
                                for s in suggestions],
                "roster": [self._player(p) for p in state.roster(state.my_team_id)],
                "standings": self._category_standings(),
                "picks": picks,
                "can_undo": bool(state.manual_picks),
                "with_stats": sum(1 for p in state.players.values() if p.avg),
            })
            return base

    def search(self, query: str) -> list[dict]:
        with self.lock:
            if not self.state or not query.strip():
                return []
            drafted = self.state.drafted_ids
            return [dict(self._player(p), drafted=p.id in drafted)
                    for p in self.state.find_player(query, only_available=False)[:10]]
