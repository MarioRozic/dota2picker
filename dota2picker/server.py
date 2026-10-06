"""Local web app: manual draft input, suggestions, and the GSI endpoint."""

from __future__ import annotations

import hmac
from importlib import resources

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
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


def create_app(stats: Stats, gsi_token: str | None = None, watcher=None) -> FastAPI:
    """watcher: an optional capture.ScreenWatcher whose latest reads are exposed in /api/game."""
    app = FastAPI(title="Dota2Picker")
    app.state.game = gsi.GameState()
    app.state.gsi_seen = False

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
        out = {"game_state": g.game_state, "in_draft": g.in_draft, "team": g.team, "hero_id": g.hero_id}
        if watcher is not None:
            reads = [
                {"hero_id": d.hero_id, "score": round(d.score, 3)} if d.hero_id else None
                for d in watcher.latest
            ]
            out["screen"] = {"radiant": reads[:5], "dire": reads[5:], "error": watcher.error}
        return out

    @app.get("/api/screen.png")
    def screen_debug() -> Response:
        """The top of the last captured screen with slot boxes and reads drawn on."""
        if watcher is None or watcher.last_frame is None:
            raise HTTPException(404, "no screen captured yet")
        import cv2

        from .vision import annotate

        ok, png = cv2.imencode(".png", annotate(watcher.last_frame, watcher.last_reads))
        return Response(png.tobytes(), media_type="image/png", headers={"Cache-Control": "no-store"})

    def screen_should_run() -> bool:
        # With GSI we only read the screen during the draft; without it, always.
        return app.state.game.in_draft or not app.state.gsi_seen

    app.state.screen_should_run = screen_should_run

    @app.post("/gsi")
    async def gsi_update(request: Request) -> dict:
        payload = await request.json()
        if gsi_token is not None:
            token = (payload.get("auth") or {}).get("token", "")
            if not hmac.compare_digest(token, gsi_token):
                raise HTTPException(403, "bad GSI token")
        app.state.game = gsi.parse(payload)
        app.state.gsi_seen = True
        return {}

    return app
