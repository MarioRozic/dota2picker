"""Valve Game State Integration (GSI).

Dota 2 POSTs JSON game state to a local URL listed in a .cfg file in
`.../dota 2 beta/game/dota/cfg/gamestate_integration/`. Dota only reads these
files when launched with the `-gamestateintegration` launch option.

For a player (not a spectator) GSI reports the game phase and their own hero,
but not the enemy picks, so we use it to know when the draft is on and to fill
in our own pick.
"""

from __future__ import annotations

import platform
import secrets
from dataclasses import dataclass
from pathlib import Path

from . import heroes

CFG_NAME = "gamestate_integration_dota2picker.cfg"
DRAFT_STATES = {
    "DOTA_GAMERULES_STATE_HERO_SELECTION",
    "DOTA_GAMERULES_STATE_STRATEGY_TIME",
}

CFG_TEMPLATE = """"dota2picker"
{{
    "uri"           "{uri}"
    "timeout"       "5.0"
    "buffer"        "0.1"
    "throttle"      "0.1"
    "heartbeat"     "30.0"
    "data"
    {{
        "provider"  "1"
        "map"       "1"
        "player"    "1"
        "hero"      "1"
    }}
    "auth"
    {{
        "token"     "{token}"
    }}
}}
"""


def default_dota_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        steam = Path("C:/Program Files (x86)/Steam")
    elif system == "Darwin":
        steam = Path.home() / "Library/Application Support/Steam"
    else:
        steam = Path.home() / ".local/share/Steam"
    return steam / "steamapps/common/dota 2 beta"


def cfg_path(dota_dir: Path) -> Path:
    return dota_dir / "game/dota/cfg/gamestate_integration" / CFG_NAME


def render_cfg(uri: str, token: str) -> str:
    return CFG_TEMPLATE.format(uri=uri, token=token)


def new_token() -> str:
    return secrets.token_urlsafe(16)


def install_cfg(dota_dir: Path, uri: str, token: str) -> Path:
    path = cfg_path(dota_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_cfg(uri, token))
    return path


@dataclass
class GameState:
    game_state: str | None = None
    team: str | None = None  # "radiant" / "dire"
    hero_id: int | None = None

    @property
    def in_draft(self) -> bool:
        return self.game_state in DRAFT_STATES


def parse(payload: dict) -> GameState:
    """Extract what we care about from a GSI payload."""
    state = GameState()
    state.game_state = (payload.get("map") or {}).get("game_state")
    state.team = (payload.get("player") or {}).get("team_name")
    hero = payload.get("hero") or {}
    name = hero.get("name")
    if name in heroes.by_name():
        state.hero_id = heroes.by_name()[name].id
    elif hero.get("id") in heroes.by_id():
        state.hero_id = hero["id"]
    return state
