# Draft Assistant

A browser app that follows your ESPN fantasy basketball draft live and tells you who to pick.

It runs on your computer and opens in your browser. It reads your league's scoring (categories
or points), roster slots and draft order from ESPN, values every player for *your* league, and
checks ESPN for new picks every few seconds while the draft runs. The page shows:

- whose pick it is and how many picks until yours (it beeps when you're on the clock)
- the best available players for your team, with a colored score for each category
- whether each player will probably **last** to your next pick or be **gone soon** (by ESPN ADP)
- a **bench** flag when a player wouldn't fit your starting lineup
- your roster, and where your team ranks in every category against the other teams
- the full draft log

## Start it

Needs Python 3.9 or newer (the `python3` that comes with macOS works).

**On a Mac:** double-click `start.command` in Finder. The first run sets things up, then your
browser opens at <http://127.0.0.1:8765>. (If macOS blocks it, right-click → Open once.)

**From a terminal (any OS):**

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m draft_assistant
```

Options: `--port 9000`, `--no-browser`, `--demo` (start with the practice league).

## Connect your league

The first time, the page asks for:

- **League ID:** the number after `leagueId=` in your ESPN league's URL.
- **espn_s2 and SWID cookies** (private leagues only). Sign in at fantasy.espn.com, open the
  browser's developer tools, go to Application (Chrome) or Storage (Safari) → Cookies →
  `https://fantasy.espn.com`, and copy the values of `espn_s2` and `SWID`.

They're saved in `config.json` next to the app, on your computer only. Git ignores that file;
never commit it, because the cookies let anyone use your ESPN account. If ESPN can't tell which
team is yours, the page asks you to pick it.

## During the draft

Keep the page open next to the ESPN draft room. Picks appear on their own within a few seconds.

- **Mine / Taken** buttons record a pick by hand, if ESPN's feed lags or for practice.
  ESPN's own picks always replace hand-entered ones. **Undo** removes the last one you entered.
- Filter by position, search with `/`, hide injured players.
- **Settings:** your team, categories to punt, how much to lean toward your weakest
  categories, pausing live updates, re-downloading players.

## Practice

Settings → **Practice: 9-cat demo** (or points demo) loads a made-up 10-team league. Click
**Auto-pick to my turn** to let the other teams draft by ADP, then pick with **Mine**.
You can do the same with your real league before it drafts, then reload it to clear the picks.

## How players are valued

- **Category leagues:** per-game stats become z-scores against the players who will actually be
  drafted (teams × roster spots). FG%, FT% and 3P% are weighted by attempts. Turnovers (and
  anything ESPN marks "lower is better") count against a player. Players projected to miss a
  lot of games are scaled down.
- **Points leagues:** projected season fantasy points with your league's scoring, minus the
  replacement-level player.
- **For your team:** once you have two players, the score leans toward your weakest categories,
  and players who'd only sit on your bench drop a little.

Stats come from ESPN's season projections when they exist, otherwise last season's
(tagged "no proj").

## Tests

```bash
.venv/bin/pip install pytest && .venv/bin/python -m pytest
```
