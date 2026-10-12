"""NBA team depth charts from ESPN's public site API. ESPN's athlete ids are the fantasy player ids."""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/depthcharts"
POSITIONS = ("pg", "sg", "sf", "pf", "c")


class DepthError(Exception):
    pass


def parse_depth(data: dict) -> list[dict]:
    charts = data.get("depthchart") or []
    if not charts:
        raise DepthError("ESPN has no depth chart for this team yet.")
    positions = charts[0].get("positions", {})
    out = []
    for pos in POSITIONS:
        athletes = (positions.get(pos) or {}).get("athletes", [])
        out.append({"pos": pos.upper(), "players": [
            {"id": int(a["id"]), "name": a.get("displayName", "?"),
             "injury": next((i.get("status") for i in a.get("injuries") or [] if i.get("status")), None)}
            for a in athletes if a.get("id")]})
    return out


def team_depth(team_id: int, cache_dir: Path, max_age_hours: float = 6) -> dict:
    """{"positions": [...], "fetched": ts}, from a cache refreshed every few hours."""
    path = cache_dir / f"depth_{team_id}.json"
    cached = None
    if path.exists():
        try:
            cached = json.loads(path.read_text())
        except ValueError:
            cached = None
    if cached and time.time() - cached["fetched"] < max_age_hours * 3600:
        return cached
    try:
        resp = requests.get(URL.format(team_id=team_id), timeout=15)
        resp.raise_for_status()
        result = {"positions": parse_depth(resp.json()), "fetched": time.time()}
    except (requests.RequestException, ValueError, DepthError) as exc:
        if cached:  # an older chart beats none
            return cached
        raise DepthError(f"Couldn't load the depth chart: {exc}") from exc
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result))
    return result
