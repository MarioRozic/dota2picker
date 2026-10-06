# Dota2Picker

Suggests counter picks during the Dota 2 draft. It runs as a small local web
app next to the game: you (or, later, screen reading) enter the enemy heroes,
and it ranks every available hero by how well it does against them, using
OpenDota matchup and meta data.

Design notes and the reasoning behind this approach: see `docs/design.md`.

## Run it

Needs Python 3.10+. Works on Windows and macOS. macOS ships Python 3.9, so use a newer one (e.g. `brew install python`) to create the venv.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

dota2picker --demo               # made-up stats, no network: try the UI
dota2picker                      # real stats (first run downloads ~130 OpenDota calls, about 3 min)
```

The browser opens at http://127.0.0.1:53000/. Type a hero name and press
Enter to add it to enemies, Shift+Enter for allies, or use the buttons. Click a
hero chip to remove it. Pick your role and rank bracket at the top.

To use it from a phone or second PC on the same network, run with
`--host 0.0.0.0` and open `http://<this-pc-ip>:53000/`.

Stats are cached in `~/.dota2picker/stats.json` and refreshed once a day;
`--refresh` forces a download.

## Game State Integration (optional)

Lets the app know when a draft starts and add your own pick automatically.

```bash
dota2picker --install-gsi        # add --dota-dir "<path to dota 2 beta>" if not found
```

Then in Steam: Dota 2 → Properties → Launch Options → add
`-gamestateintegration`, and restart Dota. The status in the top-right
corner changes to "Draft in progress" during hero selection.

## How the scoring works

For each candidate hero, the app sums its matchup advantage against every
enemy (how much better it does than the two heroes' overall win rates
predict, with small samples shrunk toward zero), plus a small bonus for its
win rate in your bracket. See `dota2picker/scoring.py`.

## Tests

```bash
pytest
```

## Data

Hero and matchup statistics from [OpenDota](https://www.opendota.com/).
Hero metadata from [dotaconstants](https://github.com/odota/dotaconstants).
