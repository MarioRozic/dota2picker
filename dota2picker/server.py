"""Local web app: manual draft input, suggestions, and the GSI endpoint."""

from __future__ import annotations

import hmac
from importlib import resources

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import gsi, heroes
from .scoring import Draft, Scorer
from .stats import BRACKETS, Stats


class DraftIn(BaseModel):
    allies: list[int] = []
    enemies: list[int] = []
    bans: list[int] = []
    role: str | None = None
    bracket: str | None = None


def create_app(stats: Stats, gsi_token: str | None = None) -> FastAPI:
    app = FastAPI(title="Dota2Picker")
    app.state.game = gsi.GameState()

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return resources.files("dota2picker.static").joinpath("index.html").read_text()

    @app.get("/api/heroes")
    def list_heroes() -> list[dict]:
        return [h.to_dict() for h in heroes.all_heroes()]

    @app.get("/api/meta")
    def meta() -> dict:
        return {"brackets": list(BRACKETS), "fetched_at": stats.fetched_at}

    @app.post("/api/suggest")
    def suggest(body: DraftIn) -> dict:
        known = heroes.by_id()
        for hid in body.allies + body.enemies + body.bans:
            if hid not in known:
                raise HTTPException(400, f"unknown hero id {hid}")
        bracket = BRACKETS.get(body.bracket) if body.bracket else None
        result = Scorer(stats, bracket).suggest(
            Draft(body.allies, body.enemies, body.bans), role=body.role
        )
        return {k: [s.to_dict() for s in v] for k, v in result.items()}

    @app.get("/api/game")
    def game() -> dict:
        g = app.state.game
        return {"game_state": g.game_state, "in_draft": g.in_draft, "team": g.team, "hero_id": g.hero_id}

    @app.post("/gsi")
    async def gsi_update(request: Request) -> dict:
        payload = await request.json()
        if gsi_token is not None:
            token = (payload.get("auth") or {}).get("token", "")
            if not hmac.compare_digest(token, gsi_token):
                raise HTTPException(403, "bad GSI token")
        app.state.game = gsi.parse(payload)
        return {}

    return app
