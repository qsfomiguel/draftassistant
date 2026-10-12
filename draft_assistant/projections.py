"""Projections from outside ESPN, averaged with ESPN's own.

Sources (both free, public pages):
- FantasyPros consensus: season totals for ~260 players, itself an average of several experts.
  Percentages only, no attempts, so its FG%/FT% are applied to the other sources' attempt volume.
- Hashtag Basketball: per-game projections with makes and attempts, but only the top 30 are free.

For each stat, a player's number is the plain average of every source that projects it. ESPN counts
as a source only when it has a real projection; when ESPN only has last season's stats, the outside
projections replace them. A source that fails to download is skipped and reported, never fatal.
"""
from __future__ import annotations

import html
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from .constants import GP, STAT_IDS
from .draft import normalize
from .models import Player

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/128 Safari/537.36"}

PTS, BLK, STL, AST, REB, TO = (STAT_IDS[k] for k in ("PTS", "BLK", "STL", "AST", "REB", "TO"))
FGM, FGA, FTM, FTA, TPM = (STAT_IDS[k] for k in ("FGM", "FGA", "FTM", "FTA", "3PM"))
FGP, FTP, MPG = STAT_IDS["FG%"], STAT_IDS["FT%"], STAT_IDS["MPG"]
COUNTING = (PTS, BLK, STL, AST, REB, TO, TPM, MPG)
# Percentage stat -> (makes, attempts).
PERCENTS = {FGP: (FGM, FGA), FTP: (FTM, FTA)}

SOURCES = {
    "fantasypros": "https://www.fantasypros.com/nba/projections/overall.php",
    "hashtag": "https://hashtagbasketball.com/fantasy-basketball-projections",
}
LABELS = {"espn": "ESPN", "fantasypros": "FantasyPros", "hashtag": "Hashtag Basketball"}


@dataclass
class Projection:
    name: str
    team: str
    gp: float | None
    avg: dict[int, float]  # per game; percentages as 0-1, with makes/attempts when the source has them


@dataclass
class SourceResult:
    name: str
    projections: list[Projection] = field(default_factory=list)
    error: str | None = None
    fetched: float | None = None


# ---- parsing ----------------------------------------------------------------------
def _cells(row: str) -> list[str]:
    cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
    return [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip() for c in cells]


def _num(text: str) -> float | None:
    text = text.replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _table(page: str, marker: str) -> str:
    start = page.find(marker)
    if start < 0:
        raise ValueError("projection table not found (the page layout may have changed)")
    return page[start:page.find("</table>", start)]


def parse_fantasypros(page: str) -> list[Projection]:
    table = _table(page, 'id="data"')
    heads = [re.sub(r"<[^>]+>", "", h).strip() for h in re.findall(r"<th[^>]*>(.*?)</th>", table, re.S)]
    col = {h: i for i, h in enumerate(heads)}
    need = ("Player", "PTS", "REB", "AST", "BLK", "STL", "FG%", "FT%", "3PM", "GP")
    if any(h not in col for h in need):
        raise ValueError(f"unexpected FantasyPros columns: {heads}")
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S):
        c = _cells(row)
        if len(c) < len(heads):
            continue
        m = re.match(r"(.+?) \((\w+)", c[col["Player"]])
        gp = _num(c[col["GP"]])
        if not m or not gp:
            continue
        avg = {sid: (_num(c[col[h]]) or 0.0) / gp
               for h, sid in (("PTS", PTS), ("REB", REB), ("AST", AST), ("BLK", BLK), ("STL", STL), ("3PM", TPM))}
        if "TO" in col:
            avg[TO] = (_num(c[col["TO"]]) or 0.0) / gp
        if "MIN" in col and _num(c[col["MIN"]]):
            avg[MPG] = _num(c[col["MIN"]]) / gp
        for h, sid in (("FG%", FGP), ("FT%", FTP)):
            pct = _num(c[col[h]])
            if pct is not None:
                avg[sid] = pct
        out.append(Projection(m.group(1), m.group(2), gp, avg))
    return out


def parse_hashtag(page: str) -> list[Projection]:
    table = _table(page, 'id="ContentPlaceHolder1_GridView1"')
    heads = [re.sub(r"<[^>]+>", "", h).strip() for h in re.findall(r"<th[^>]*>(.*?)</th>", table, re.S)]
    col = {h: i for i, h in enumerate(heads)}
    if any(h not in col for h in ("PLAYER", "TEAM", "GP", "FG%", "FT%", "3PM", "PTS", "TREB", "AST", "STL", "BLK")):
        raise ValueError(f"unexpected Hashtag Basketball columns: {heads}")
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.S):
        c = _cells(row)
        if len(c) < len(heads) or not _num(c[col["GP"]]):
            continue
        name = c[col["PLAYER"]]
        # The cell holds the full name followed by a short form, e.g. "Nikola Jokic N.Jokic".
        name = re.sub(r"\s+[^\s.]+\.\S.*$", "", name).strip()
        avg = {sid: _num(c[col[h]]) or 0.0
               for h, sid in (("PTS", PTS), ("TREB", REB), ("AST", AST), ("STL", STL), ("BLK", BLK), ("3PM", TPM))}
        if "TO" in col:
            avg[TO] = _num(c[col["TO"]]) or 0.0
        if "MPG" in col and _num(c[col["MPG"]]):
            avg[MPG] = _num(c[col["MPG"]])
        # "0.573 (10.5/18.3)": percentage, then makes/attempts per game.
        for h, (pct_id, made_id, att_id) in (("FG%", (FGP, FGM, FGA)), ("FT%", (FTP, FTM, FTA))):
            m = re.match(r"([\d.]+)\s*\(([\d.]+)/([\d.]+)\)", c[col[h]])
            if m:
                avg[pct_id], avg[made_id], avg[att_id] = float(m.group(1)), float(m.group(2)), float(m.group(3))
        out.append(Projection(name, c[col["TEAM"]], _num(c[col["GP"]]), avg))
    return out


PARSERS = {"fantasypros": parse_fantasypros, "hashtag": parse_hashtag}


# ---- fetching with a cache ---------------------------------------------------------
def fetch_source(name: str, cache_dir: Path, max_age_hours: float = 12, refresh: bool = False) -> SourceResult:
    path = cache_dir / f"proj_{name}.json"
    cached = None
    if path.exists():
        try:
            cached = json.loads(path.read_text())
        except ValueError:
            cached = None
    if cached and not refresh and time.time() - cached["fetched"] < max_age_hours * 3600:
        return SourceResult(name, [Projection(**p) for p in _decode(cached["projections"])], fetched=cached["fetched"])
    try:
        resp = requests.get(SOURCES[name], headers=UA, timeout=30)
        resp.raise_for_status()
        projections = PARSERS[name](resp.text)
        if not projections:
            raise ValueError("no players found on the page")
    except (requests.RequestException, ValueError) as exc:
        # Fall back to an older download rather than losing the source.
        if cached:
            return SourceResult(name, [Projection(**p) for p in _decode(cached["projections"])],
                                error=f"using saved copy; download failed: {exc}", fetched=cached["fetched"])
        return SourceResult(name, error=str(exc))
    now = time.time()
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fetched": now, "projections": [
        {"name": p.name, "team": p.team, "gp": p.gp, "avg": {str(k): v for k, v in p.avg.items()}}
        for p in projections]}))
    return SourceResult(name, projections, fetched=now)


def _decode(rows: list[dict]) -> list[dict]:
    return [{**r, "avg": {int(k): v for k, v in r["avg"].items()}} for r in rows]


def fetch_all(cache_dir: Path, refresh: bool = False) -> list[SourceResult]:
    return [fetch_source(name, cache_dir, refresh=refresh) for name in SOURCES]


# ---- matching and blending ---------------------------------------------------------
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def name_key(name: str) -> str:
    words = normalize(name.replace("-", " ").replace(".", "")).split()
    return " ".join(w for w in words if w not in SUFFIXES)


def blend(players: list[Player], results: list[SourceResult]) -> dict:
    """Average outside projections into players' per-game stats, in place. Returns a summary."""
    by_key: dict[str, list[Player]] = {}
    for p in players:
        by_key.setdefault(name_key(p.name), []).append(p)

    matched: dict[int, list[tuple[str, Projection]]] = {}
    summary = {"sources": []}
    for res in results:
        hits = 0
        for proj in res.projections:
            candidates = by_key.get(name_key(proj.name), [])
            if len(candidates) > 1:  # same name twice: use the team to tell them apart
                candidates = [p for p in candidates if p.pro_team[:2] == proj.team[:2]] or candidates[:1]
            if candidates:
                matched.setdefault(candidates[0].id, []).append((res.name, proj))
                hits += 1
        summary["sources"].append({"name": res.name, "label": LABELS.get(res.name, res.name), "players": len(res.projections),
                                   "matched": hits, "error": res.error, "fetched": res.fetched})

    for p in players:
        outside = matched.get(p.id)
        p.sources = ["espn"] if p.stat_source == "proj" else []
        if not outside:
            continue
        _blend_player(p, outside)
    summary["blended"] = sum(1 for p in players if len(p.sources) > 1)
    summary["filled"] = sum(1 for p in players if p.sources and "espn" not in p.sources)
    return summary


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _blend_player(p: Player, outside: list[tuple[str, Projection]]) -> None:
    has_espn = p.stat_source == "proj"
    espn = p.avg if has_espn else {}
    views = ([dict(espn)] if has_espn else []) + [proj.avg for _, proj in outside]
    old = dict(p.avg)
    new = dict(old) if has_espn else {k: v for k, v in old.items() if k not in COUNTING}

    for sid in COUNTING:
        vals = [v[sid] for v in views if sid in v]
        if vals:
            new[sid] = _mean(vals)

    # Percentages: average the percentage, then pick an attempt volume from whoever has one
    # (a source's own attempts, or last season's from ESPN), so roto volume weighting still works.
    for pct_id, (made_id, att_id) in PERCENTS.items():
        pcts = [v[pct_id] if pct_id in v else v[made_id] / v[att_id]
                for v in views if pct_id in v or (v.get(att_id) and made_id in v)]
        atts = [v[att_id] for v in views if v.get(att_id)]
        att = _mean(atts) if atts else old.get(att_id)
        if not pcts or not att:
            continue
        pct = _mean(pcts)
        new[pct_id], new[att_id], new[made_id] = pct, att, pct * att

    gps = ([p.gp] if has_espn and p.gp else []) + [proj.gp for _, proj in outside if proj.gp]
    p.avg = new
    p.gp = _mean(gps) if gps else p.gp
    p.avg[GP] = p.gp or 0.0
    p.sources = (["espn"] if has_espn else []) + [name for name, _ in outside]
    if not has_espn:
        p.stat_source = "proj"
