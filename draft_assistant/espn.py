"""Thin client for ESPN's fantasy basketball API plus parsers into our models."""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from .constants import GP, POSITION_SLOTS, PRO_TEAMS, SLOT_NAMES, STAT_NAMES
from .models import Category, League, Pick, Player, Team

BASE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{season}/segments/0/leagues/{league_id}"


class EspnError(RuntimeError):
    pass


class EspnClient:
    def __init__(self, league_id: int, season: int, espn_s2: str | None = None,
                 swid: str | None = None, timeout: float = 20):
        self.league_id = league_id
        self.season = season
        self.timeout = timeout
        self.url = BASE_URL.format(season=season, league_id=league_id)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "espn-draft-assistant"
        if espn_s2 and swid:
            self.session.cookies.set("espn_s2", espn_s2)
            self.session.cookies.set("SWID", swid)

    def _get(self, views: list[str], fantasy_filter: dict | None = None) -> dict:
        params = [("view", v) for v in views]
        headers = {"X-Fantasy-Filter": json.dumps(fantasy_filter)} if fantasy_filter else {}
        try:
            resp = self.session.get(self.url, params=params, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise EspnError(f"Could not reach ESPN: {exc}") from exc
        if resp.status_code in (401, 403):
            raise EspnError(
                "ESPN refused access to this league. If it's private, set espn_s2 and swid "
                "in config.toml (see README)."
            )
        if resp.status_code == 404:
            raise EspnError(f"League {self.league_id} not found for season {self.season}.")
        if not resp.ok:
            raise EspnError(f"ESPN returned HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except ValueError as exc:
            # ESPN serves an HTML login page instead of JSON when cookies are wrong.
            raise EspnError("ESPN did not return JSON; check espn_s2 / swid.") from exc
        return data

    def _get_league(self, views: list[str]) -> dict:
        data = self._get(views)
        if isinstance(data, list):  # some views wrap the league in a list
            data = data[0]
        return data

    def league_raw(self) -> dict:
        return self._get_league(["mSettings", "mTeam", "mDraftDetail"])

    def draft_raw(self) -> dict:
        return self._get_league(["mDraftDetail"])

    def players_raw(self, limit: int = 600) -> dict:
        s = self.season
        flt = {"players": {
            "limit": limit,
            "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
            "filterStatsForTopScoringPeriodIds": {
                "value": 82,
                "additionalValue": [f"00{s}", f"10{s}", f"00{s - 1}"],
            },
        }}
        return self._get(["kona_player_info"], flt)

    def players_cached(self, cache_dir: Path, limit: int = 600, max_age_hours: float = 12,
                       refresh: bool = False) -> dict:
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / f"players_{self.league_id}_{self.season}.json"
        if not refresh and path.exists() and time.time() - path.stat().st_mtime < max_age_hours * 3600:
            return json.loads(path.read_text())
        data = self.players_raw(limit)
        path.write_text(json.dumps(data))
        return data


def _team_name(t: dict) -> str:
    if t.get("name"):
        return t["name"]
    return f"{t.get('location', '')} {t.get('nickname', '')}".strip() or f"Team {t['id']}"


def parse_league(data: dict, league_id: int, season: int) -> League:
    settings = data.get("settings", {})
    scoring = settings.get("scoringSettings", {})
    items = scoring.get("scoringItems", [])
    scoring_type = scoring.get("scoringType", "H2H_CATEGORY")
    categories = [
        Category(i["statId"], STAT_NAMES.get(i["statId"], str(i["statId"])), bool(i.get("isReverseItem")))
        for i in items
    ]
    points = {i["statId"]: float(i.get("points", 0)) for i in items}
    lineup = {int(k): int(v) for k, v in settings.get("rosterSettings", {}).get("lineupSlotCounts", {}).items() if int(v) > 0}
    teams = {
        t["id"]: Team(t["id"], _team_name(t), t.get("abbrev", ""), [o.upper() for o in t.get("owners", [])])
        for t in data.get("teams", [])
    }
    draft_settings = settings.get("draftSettings", {})
    return League(
        id=league_id,
        season=season,
        name=settings.get("name", f"League {league_id}"),
        scoring_type=scoring_type,
        categories=categories,
        points=points,
        lineup_slots=lineup,
        teams=teams,
        pick_order=list(draft_settings.get("pickOrder", [])),
        draft_type=draft_settings.get("type", "SNAKE"),
    )


def parse_picks(data: dict) -> tuple[list[Pick], bool, bool]:
    """Returns (picks, in_progress, drafted)."""
    dd = data.get("draftDetail", {})
    picks = [
        Pick(p["overallPickNumber"], p["teamId"], p["playerId"], bool(p.get("keeper")))
        for p in dd.get("picks", [])
        if p.get("playerId", -1) > 0
    ]
    return picks, bool(dd.get("inProgress")), bool(dd.get("drafted"))


def _pick_stats(stats: list[dict], season: int) -> tuple[dict | None, str]:
    def find(season_id: int, source: int):
        for s in stats:
            if s.get("seasonId") == season_id and s.get("statSourceId") == source and s.get("statSplitTypeId") == 0:
                if s.get("averageStats") or s.get("stats"):
                    return s
        return None

    for season_id, source, label in ((season, 1, "proj"), (season - 1, 0, "last"), (season, 0, "current")):
        found = find(season_id, source)
        if found:
            return found, label
    return None, "none"


def parse_players(data: dict, season: int) -> list[Player]:
    players = []
    # The league endpoint wraps players in {"players": [...]}; ESPN's public endpoint returns a bare list.
    entries = data if isinstance(data, list) else data.get("players", [])
    for entry in entries:
        p = entry.get("player", entry)
        stats_entry, source = _pick_stats(p.get("stats", []) or [], season)
        avg: dict[int, float] = {}
        gp = None
        if stats_entry:
            totals = {int(k): float(v) for k, v in (stats_entry.get("stats") or {}).items()}
            averages = {int(k): float(v) for k, v in (stats_entry.get("averageStats") or {}).items()}
            gp = totals.get(GP) or None
            if averages:
                avg = averages
            elif gp:
                avg = {k: v / gp for k, v in totals.items()}
        slots = set(p.get("eligibleSlots", []))
        ranks = p.get("draftRanksByRankType", {}) or {}
        rank = (ranks.get("STANDARD") or ranks.get("ROTO") or {}).get("rank")
        adp = (p.get("ownership") or {}).get("averageDraftPosition")
        players.append(Player(
            id=p.get("id", entry.get("id")),
            name=p.get("fullName", "?"),
            pro_team=PRO_TEAMS.get(p.get("proTeamId", 0), "?"),
            positions=[SLOT_NAMES[s] for s in POSITION_SLOTS if s in slots],
            eligible_slots=slots,
            avg=avg,
            gp=gp,
            injury=None if p.get("injuryStatus") in (None, "ACTIVE", "NORMAL") else p.get("injuryStatus"),
            adp=adp if adp and adp > 0 else None,
            espn_rank=rank or None,
            stat_source=source,
        ))
    return players


def find_my_team(league: League, swid: str | None) -> int | None:
    if not swid:
        return None
    swid = swid.upper()
    for team in league.teams.values():
        if swid in team.owners:
            return team.id
    return None
