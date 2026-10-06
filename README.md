# Dota2Picker

Suggests counter picks during the Dota 2 draft. It runs as a small local web
app next to the game: you (or, later, screen reading) enter the enemy heroes,
and it ranks every available hero by how well it does against them, using
OpenDota matchup and meta data.

Design notes and the reasoning behind this approach: see `docs/design.md`.
Step-by-step guide for trying it in a real game on Windows: see
`docs/windows-testing.md`.

## Run it

Needs Python 3.10+. Works on Windows and macOS. macOS ships Python 3.9, so use a newer one (e.g. `brew install python`) to create the venv.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

dota2picker --demo               # made-up stats, no network: try the UI
dota2picker                      # real stats (first run downloads from OpenDota, about a minute)
```

The browser opens at http://127.0.0.1:53000/. Type a hero name and press
Enter to add it to enemies, Shift+Enter for allies, or use the buttons. Click a
hero chip to remove it. The page fills the browser window and shows the best
picks for every position side by side (1 Carry ... 5 Hard support), each
column only listing heroes commonly played there, so you don't have to pick a
position first. Choose Top 3, 5 or 10 per position and the rank bracket at
the top. Click a hero in a column once you pick it: that makes it your hero
and that column your position, for the item build.
**↺ Reset** (top right) clears all heroes, your hero and the item build for
the next game, and keeps your rank, side and Top N. With Game State
Integration this happens on its own when a new draft starts.

To use it from a phone or second PC on the same network, run with
`--host 0.0.0.0` and open `http://<this-pc-ip>:53000/`.

Stats are cached in `~/.dota2picker/stats.json` and refreshed once a day;
`--refresh` forces a download.

## Item build

Once the app knows your hero, it shows an item build split by game phase:
Start, Early game (0-10 min), Mid game (10-20 min), Late game (20+ min) and
If needed. Items that answer the enemy lineup are added to the phase where
they're normally bought, with a gold border and the enemies they help against.

The build starts from Valve's recommended build for the hero (the lists in
the in-game shop, saved in `dota2picker/data/builds.json`). OpenDota's item
timings from public games then decide the order and which phase each item
costing 1400 or more belongs in. They're downloaded the first time you pick
a hero and kept for a day. Run `python scripts/update_item_data.py` after a
patch to refresh the item list and Valve's builds. Your hero is set
automatically by Game State Integration; otherwise click ★ next to your hero
under Allies, or click a hero in Best picks when you pick it.

Cores (positions 1-3) and supports (4-5) get different items. The column
you clicked your hero in sets your position; if you set your hero another way,
its main position decides. Each enemy is tagged
with the threats it poses in `dota2picker/data/threats.json` (evasion,
illusions, invisibility, magic damage, stuns, silences, healing, ...) and
`dota2picker/data/counter_items.json` lists the items that answer each
threat. Both files are hand-written; edit them as the meta changes.

## Reading picks from the screen

By default the app reads the hero portraits in the top bar of your screen
and fills in allies and enemies on its own. It keeps reading during the
draft, so when a slot shows a different hero, or goes empty again, the lists
follow. A hero it isn't sure about gets a dashed border and a "?".

If a hero is wrong, click it: the app reads that slot again without that hero
and shows its next guess, if it has one. You can also type the right hero.
Heroes you type stay until you remove them or click **↺ Reset**, which also
starts the screen reading afresh. Each team shows at most five, so the screen
reads the app is least sure of make way for heroes you typed.

- The first run downloads the 127 hero portraits from Valve's CDN into
  `~/.dota2picker/portraits/`.
- Your team is taken from Game State Integration (below). Without it, set
  "Side" at the top to Radiant (left) or Dire (right).
- With Game State Integration on, the screen is only read during the draft,
  and a new draft clears the old picks automatically.
- Dota on a second monitor: `--monitor 2`. Turn screen reading off with
  `--no-screen`.
- macOS asks for Screen Recording permission the first time (System Settings
  → Privacy & Security → Screen Recording).
- The game has to fill the screen (full screen or borderless window, Dota's
  default). A smaller Dota window, or a screenshot open in a normal Preview
  window, won't read correctly. To test with a screenshot, open it in
  Preview and press Ctrl+Cmd+F for real full screen.
- Black bars around the game (e.g. a 16:9 game or screenshot on a 16:10
  screen) are trimmed automatically.
- A slot only changes after it reads the same on two captures in a row, and
  nothing changes while the screen doesn't look like a draft (for example
  while you're looking at the browser), so alt-tabbing doesn't lose picks.

If heroes come out wrong, click **What it sees** at the top of the page: it
shows the top of the last captured screen with each slot's box and what was
read there. To test on a screenshot file without any full-screen trickery:

```bash
dota2picker --read-image tests/fixtures/strategy_full.jpg
```

It prints the hero and score for each slot and writes a `.slots.png` next to
the image showing where it looked.

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
predict, with small samples shrunk toward zero), the same kind of edge with
every ally (how much more often the pair wins together), plus a small bonus
for its win rate in your bracket. These are the numbers Dota Plus shows in
"Friends and Foes". See `dota2picker/scoring.py`.

Matchups and synergy come from about the last day of public matches in
OpenDota's database (~1M games, all ranks). If that query fails, the app falls back to
OpenDota's per-hero matchup endpoint, which only counts pro games and is much
less reliable.

## Tests

```bash
pytest
```

## Data

Hero and matchup statistics from [OpenDota](https://www.opendota.com/).
Hero metadata from [dotaconstants](https://github.com/odota/dotaconstants).
