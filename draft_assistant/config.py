from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from .constants import STAT_IDS

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
CACHE_DIR = ROOT / ".cache"


def default_season(today: date | None = None) -> int:
    """ESPN names an NBA season by the year it ends (2026-27 is 2027)."""
    today = today or date.today()
    return today.year + 1 if today.month >= 8 else today.year


@dataclass
class Config:
    league_id: int | None = None
    season: int = field(default_factory=default_season)
    team_id: int | None = None
    espn_s2: str | None = None
    swid: str | None = None
    punt: list[str] = field(default_factory=list)
    balance: float = 0.25
    poll_seconds: float = 4.0
    player_limit: int = 600
    live: bool = True

    @property
    def punt_ids(self) -> set[int]:
        return parse_punt(self.punt)

    def public(self) -> dict:
        """Settings safe to show in the browser (cookies are only reported as present or not)."""
        return {
            "league_id": self.league_id, "season": self.season, "team_id": self.team_id,
            "has_cookies": bool(self.espn_s2 and self.swid), "punt": self.punt,
            "balance": self.balance, "live": self.live,
        }


def parse_punt(names) -> set[int]:
    if isinstance(names, str):
        names = [n for n in names.split(",") if n.strip()]
    out = set()
    for n in names or []:
        key = n.strip().upper()
        if key not in STAT_IDS:
            raise ValueError(f"Unknown category '{n}'.")
        out.add(STAT_IDS[key])
    return out


def normalize_swid(swid: str | None) -> str | None:
    swid = (swid or "").strip().strip('"')
    found = re.search(r"\{?([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})\}?", swid)
    if found:  # also copes with a whole cookie row pasted from the developer tools
        return "{" + found.group(1) + "}"
    if not swid:
        return None
    return swid if swid.startswith("{") else "{" + swid + "}"


def normalize_espn_s2(value: str | None) -> str | None:
    """The cookie value is one long token. People often paste the whole developer-tools row
    (name, value, domain, path, expiry separated by tabs), so keep only the longest token."""
    value = (value or "").strip()
    if not value:
        return None
    tokens = [t.strip('"') for t in re.split(r"[\s;]+", value)]
    tokens = [t[len("espn_s2="):] if t.startswith("espn_s2=") else t for t in tokens]
    return max(tokens, key=len) or None


def load_config(path: Path = CONFIG_PATH) -> Config:
    raw = json.loads(path.read_text()) if path.exists() else {}
    known = {k: v for k, v in raw.items() if k in Config.__dataclass_fields__}
    cfg = Config(**known)
    env = os.environ
    if env.get("ESPN_LEAGUE_ID"):
        cfg.league_id = int(env["ESPN_LEAGUE_ID"])
    cfg.espn_s2 = normalize_espn_s2(env.get("ESPN_S2") or cfg.espn_s2)
    cfg.swid = normalize_swid(env.get("ESPN_SWID") or cfg.swid)
    return cfg


def save_config(cfg: Config, path: Path = CONFIG_PATH) -> None:
    path.write_text(json.dumps(asdict(cfg), indent=2))
    try:
        path.chmod(0o600)  # holds ESPN login cookies
    except OSError:
        pass
