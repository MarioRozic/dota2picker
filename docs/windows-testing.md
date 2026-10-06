# Testing Dota2Picker on Windows in a real game

Use the **main** branch. Screen-detection fixes (#2), the position picker (#3),
the tighter position list (#4) and counter items (#5) are all merged.

## 1. One-time setup

1. **Install Python 3.10 or newer** from https://www.python.org/downloads/windows/.
   In the installer, tick **"Add python.exe to PATH"**. Check it in a new
   PowerShell window: `py --version` (or `python --version`).
   If typing `python` opens the Microsoft Store, use `py` instead everywhere below.
2. **Install Git** from https://git-scm.com/download/win (defaults are fine).
   No Git? On GitHub use Code → Download ZIP and unzip it instead.
3. **Get the code and install it** (PowerShell):

   ```powershell
   cd $HOME\Documents
   git clone https://github.com/MarioRozic/dota2picker.git
   cd dota2picker
   py -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -e ".[dev]"
   ```

   If PowerShell refuses to run `Activate.ps1` ("running scripts is disabled"),
   run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use
   Command Prompt and `.venv\Scripts\activate.bat`.
4. **Quick sanity check, no game needed:**

   ```powershell
   pytest
   dota2picker --demo
   dota2picker --read-image tests\fixtures\strategy_full.jpg
   ```

   `--demo` opens the UI with fake stats. `--read-image` should print the heroes
   in each slot. Close the demo with Ctrl+C.

## 2. Game State Integration (tells the app when a draft starts and your team)

1. With the venv active, run:

   ```powershell
   dota2picker --install-gsi
   ```

   It writes `gamestate_integration_dota2picker.cfg` into
   `C:\Program Files (x86)\Steam\steamapps\common\dota 2 beta\game\dota\cfg\gamestate_integration\`.
   If Dota is in another Steam library (e.g. `D:\SteamLibrary`), you'll get
   "Dota 2 not found"; pass the folder:

   ```powershell
   dota2picker --install-gsi --dota-dir "D:\SteamLibrary\steamapps\common\dota 2 beta"
   ```

   (Steam → Dota 2 → Manage → Browse local files shows where it lives.)
2. In Steam: Dota 2 → Properties → General → Launch Options, add
   `-gamestateintegration`.
3. Restart Dota if it was running. Dota only reads the file at startup.

## 3. Display settings in Dota

- **Display mode: Borderless window** (Dota's default). Exclusive full screen
  may capture as black, and a smaller windowed Dota won't read correctly.
- **16:9 resolution** is what the reader was measured on (1920×1080,
  2560×1440, 3840×2160). 16:10 works because black bars are trimmed.
  Ultrawide (21:9) hasn't been tested.
- If Dota is on a second monitor, start the app with `--monitor 2`.

## 4. Each time you play

1. Open PowerShell in the repo folder and activate the venv:
   `.venv\Scripts\Activate.ps1`
2. Start the app **before** or alongside Dota:

   ```powershell
   dota2picker
   ```

   The first run downloads OpenDota stats (about 3 minutes, ~130 calls) and the
   127 hero portraits. Both are cached in `%USERPROFILE%\.dota2picker\` and
   stats refresh once a day.
3. Your browser opens http://127.0.0.1:53000/. Pick your **position** and
   **rank bracket** at the top.
4. Launch Dota and queue. Top right of the page should change from
   "Game not detected" to **"Draft in progress"** during hero selection.
5. During the draft, stay in Dota. The app only reads the screen while it
   looks like a draft, so alt-tabbing to the browser pauses reading.
   Allies and enemies fill in on their own and follow the top bar as it
   changes; a slot changes after it reads the same on two captures in a row.
6. Check suggestions on a phone or second monitor. For a phone:
   `dota2picker --host 0.0.0.0`, then open `http://<your-PC-IP>:53000/`
   (find the IP with `ipconfig`; allow the Windows Firewall prompt).
7. Fixing mistakes: a dashed hero with "?" is a guess. Click a wrong hero: the
   app reads that slot again without it and shows its next guess, if it has
   one. Or type the right one (Enter = enemy, Shift+Enter = ally); heroes you
   type stay put.

## 5. When something goes wrong, send me this

- **Wrong or missing heroes:** during the draft, click **What it sees** at the
  top of the page and save that image. Also take an F12 Steam screenshot of the
  draft (saved under Steam's screenshot folder). Send both here.
- **Status stays "Game not detected":** tell me where the `.cfg` was written
  (the `--install-gsi` output) and confirm `-gamestateintegration` is in the
  launch options.
- **Crash or error:** copy the text from the PowerShell window.
- Mention your resolution, display mode and which monitor Dota is on.

To get the latest version later: `git pull` then `pip install -e ".[dev]"`
in the repo folder with the venv active.
