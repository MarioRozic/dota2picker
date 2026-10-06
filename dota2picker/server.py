"""Local web app: manual draft input, suggestions, and the GSI endpoint."""

from __future__ import annotations

import hmac
from importlib import resources

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from . import builds, gsi, heroes, items
from .scoring import Draft, Scorer
from .stats import BRACKETS, Stats


class DraftIn(BaseModel):
    allies: list[int] = []
    enemies: list[int] = []
    bans: list[int] = []
    position: int | None = Field(None, ge=1, le=5)
    bracket: str | None = None


class ItemsIn(BaseModel):
    hero_id: int
    enemies: list[int] = []
    position: int | None = Field(None, ge=1, le=5)


class RejectIn(BaseModel):
    hero_id: int


PHASE_LABELS = {
    "start": "Start",
    "early": "Early game (0-10 min)",
    "mid": "Mid game (10-20 min)",
    "late": "Late game (20+ min)",
    "other": "If needed",
}


def create_app(stats: Stats, gsi_token: str | None = None, watcher=None, item_timings=None) -> FastAPI:
    """watcher: an optional capture.ScreenWatcher whose slots are exposed in /api/game.
    item_timings: an optional hero id -> OpenDota item timing rows lookup (builds.TimingsCache).
    """
    app = FastAPI(title="Dota2Picker")
    app.state.game = gsi.GameState()
    app.state.gsi_seen = False
    app.state.draft_id = 0  # counts drafts GSI reported, so the page can tell a new one started

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return resources.files("dota2picker.static").joinpath("index.html").read_text(encoding="utf-8")

    @app.get("/api/heroes")
    def list_heroes() -> list[dict]:
        return [h.to_dict() for h in heroes.all_heroes()]

    @app.get("/api/meta")
    def meta() -> dict:
        return {
            "brackets": list(BRACKETS),
            "positions": heroes.POSITIONS,
            "fetched_at": stats.fetched_at,
        }

    @app.post("/api/suggest")
    def suggest(body: DraftIn) -> dict:
        known = heroes.by_id()
        for hid in body.allies + body.enemies + body.bans:
            if hid not in known:
                raise HTTPException(400, f"unknown hero id {hid}")
        bracket = BRACKETS.get(body.bracket) if body.bracket else None
        result = Scorer(stats, bracket).suggest(
            Draft(body.allies, body.enemies, body.bans), position=body.position
        )
        return {k: [s.to_dict() for s in v] for k, v in result.items()}

    @app.post("/api/items")
    def suggest_items(body: ItemsIn) -> dict:
        known = heroes.by_id()
        for hid in [body.hero_id, *body.enemies]:
            if hid not in known:
                raise HTTPException(400, f"unknown hero id {hid}")
        return {
            "role": items.role_for(known[body.hero_id], body.position),
            "items": [s.to_dict() for s in items.suggest_items(body.hero_id, body.enemies, body.position)],
        }

    @app.post("/api/build")
    def item_build(body: ItemsIn) -> dict:
        known = heroes.by_id()
        for hid in [body.hero_id, *body.enemies]:
            if hid not in known:
                raise HTTPException(400, f"unknown hero id {hid}")
        timings = item_timings(body.hero_id) if item_timings else None
        rows = builds.build(body.hero_id, body.enemies, body.position, timings)
        return {
            "role": items.role_for(known[body.hero_id], body.position),
            "timings": bool(timings),
            "phases": [
                {"key": p, "label": PHASE_LABELS[p], "items": [e.to_dict() for e in rows[p]]}
                for p in builds.PHASES
                if rows[p]
            ],
        }

    @app.get("/api/game")
    def game() -> dict:
        g = app.state.game
        out = {
            "game_state": g.game_state,
            "in_draft": g.in_draft,
            "team": g.team,
            "hero_id": g.hero_id,
            "draft_id": app.state.draft_id,
        }
        if watcher is not None:
            reads = [
                {"hero_id": d.hero_id, "score": round(d.score, 3)} if d.hero_id else None
                for d in watcher.latest
            ]
            out["screen"] = {"radiant": reads[:5], "dire": reads[5:], "error": watcher.error}
        return out

    def need_watcher():
        if watcher is None:
            raise HTTPException(404, "screen reading is off")
        return watcher

    @app.post("/api/screen/reject")
    def screen_reject(body: RejectIn) -> dict:
        """You removed a hero read from the screen: read its slot again without it."""
        return {"rejected": need_watcher().reject(body.hero_id)}

    @app.post("/api/screen/reset")
    def screen_reset() -> dict:
        need_watcher().reset()
        return {}

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
        was_in_draft = app.state.game.in_draft
        app.state.game = gsi.parse(payload)
        app.state.gsi_seen = True
        if app.state.game.in_draft and not was_in_draft:
            # A new draft: forget the last game's picks.
            app.state.draft_id += 1
            if watcher is not None:
                watcher.reset()
        return {}

    return app
