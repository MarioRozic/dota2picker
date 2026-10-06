# Dota 2 Counter-Pick Helper: Options and Recommendation

_Written 2026-10-06. Items marked **(verify)** are from memory or secondary sources and should be confirmed during the prototype; I couldn't reach the APIs directly from my environment._

## TL;DR

- **Build a small desktop companion app**, not an injected in-game overlay. It shows suggestions in a compact always-on-top window (works over Dota in borderless/windowed mode) and can also serve the same view as a local web page for a second monitor or phone.
- **Read the draft with screen capture + hero-portrait matching**, with one-click manual correction. Use Valve's **Game State Integration (GSI)** only to detect "draft has started" and your own pick, because GSI does not give a player the enemy picks.
- **Data: OpenDota for v1** (free, no key, hero meta stats and hero-vs-hero matchups), with **STRATZ** as the upgrade path for rank-bracket-specific matchup data. Fetch once a day into a local cache; never call the APIs live during a draft.
- **Scoring:** for each candidate hero, sum its matchup advantage against the enemy picks, add synergy with allies and a meta (win rate) bonus, shrink low-sample numbers toward zero, and show the top 5 with the reason for each.

---

## 1. How the app learns the draft

| Approach | Gets enemy picks? | Effort | Risk | Verdict |
|---|---|---|---|---|
| **Game State Integration (GSI)**: Valve's official feature; Dota POSTs JSON to a local HTTP server you configure via a `.cfg` file | **No, for players.** Players get their own hero, items, abilities, and the game phase (e.g. `DOTA_GAMERULES_STATE_HERO_SELECTION`). Full draft data (picks/bans for both teams) is only sent to spectators/observers. | Low | None, it's the sanctioned API | Use it for **phase detection + own hero**, not for enemy picks |
| **Screen capture + image matching**: grab the top-bar region during draft, match each slot against the ~127 known hero portraits | Yes, as soon as they're visible on your screen | Medium | Low: reads pixels via the OS, never touches game memory or files | **Primary method** |
| **OCR of hero names** | Partly; names aren't reliably shown as text in the pick UI | Medium-high | Low | Worse than portrait matching; skip |
| **Manual input**: type-ahead search, click enemy heroes as they appear | Yes | Very low | None | **Always include** as fallback and correction |
| **Overwolf Game Events Provider** | Yes, via Overwolf's own privileged integration (this is how apps like Dota Coach do it) | Medium, but you're tied to the Overwolf platform, its review process and its monetization rules | Low | Viable alternative if you want a store-distributed app; not needed for v1 |
| **Reading game memory / console / replays** | Yes | High | **High**: this is what VAC and Valve's 2023 patch target | **Don't** |

Notes:
- Portrait matching is reliable because the draft UI uses fixed hero images at fixed positions per resolution. Calibrate once per resolution (or detect the top bar), then use OpenCV template matching or a small perceptual-hash lookup. Hero portrait images are available from the `dotaconstants` package / Valve CDN.
- In Ranked All Pick you see enemy picks in the top bar as they lock in, so capture can update live. Bans also appear and can be matched the same way to grey out banned heroes.

## 2. Overlay vs. other surfaces

**What Valve has done:** In Feb 2023 Valve patched Dota to stop apps from showing opponent profiles/stats during the draft (disabled `record` and many introspection console commands in matchmaking, and hid player profiles until the draft ends). The target was opponent-scouting overlays (e.g. smurf detection), not hero suggestions. Valve's longstanding line is that it doesn't "support or condone third-party modifications during matchmade games", and VAC targets software that modifies or reads the game process.

**What that means here:** A counter-pick suggester only uses public, aggregate hero statistics, the same kind of thing Valve's own Dota Plus "Plus Assistant" shows during the draft. As long as the app doesn't inject into Dota, read its memory, or use console tricks, the ban risk is very low. **(verify:** there is no written Valve whitelist; this is a risk assessment, not a guarantee.)

| Surface | Works over the game? | Risk | Notes |
|---|---|---|---|
| **Injected overlay** (DirectX hook, like Steam/Discord overlays) | Yes, incl. exclusive fullscreen | **Medium-high** for a homemade one: hooking the render process is exactly what anti-cheat looks at | Avoid |
| **Transparent always-on-top window** (separate process) | Yes, when Dota runs in borderless/windowed fullscreen (Dota's default "desktop-friendly" mode); not over exclusive fullscreen | Low | **Recommended** in-game surface |
| **Second-screen / phone web page** served by the app on the LAN | n/a, separate screen | None | Free to add: same UI as a local web page |
| **Overwolf app** | Yes | Low | Platform lock-in, see above |

## 3. Free data sources

| Source | What's useful | Access & limits | Fit |
|---|---|---|---|
| **OpenDota API** (`api.opendota.com`) | `/heroStats`: picks/wins per rank bracket (Herald→Immortal) and pro, for meta win rates. `/heroes/{id}/matchups`: games/wins vs each other hero. `/constants/heroes`: ids, names, images. | Free, no key needed. Free tier was 50k calls/month (2018 blog); currently documented around **60 calls/min and a daily cap (~2,000/day) (verify)**. Paid key is pay-per-call and cheap. Open-source, data is CC BY-SA-ish; credit OpenDota. | **v1 primary.** A full daily refresh is ~130 calls (1 heroStats + 1 per hero for matchups), well within free limits. Caveat: `/heroes/{id}/matchups` is based on OpenDota's parsed sample, which skews toward higher-level/pro games **(verify)**, so it's not bracket-specific. |
| **STRATZ GraphQL API** (`api.stratz.com/graphql`) | `heroStats { matchUp(heroId, bracketBasicIds) }` gives **vs** and **with** stats per hero pair, including a synergy/advantage value, filterable by rank bracket and recent patch. Also win rate by bracket and position. | Free token after Steam login on stratz.com. Rate-limited per token (roughly per-second/minute/hour/day caps) **(verify current numbers)**. Terms ask for attribution and restrict commercial use without agreement **(verify)**. | **v2 upgrade** for "counters at my rank" and per-position data. Good quality, but needs a token and per-user terms care if you ever distribute the app. |
| **Steam Dota 2 Web API** (`IDOTA2Match_570`, `IEconDOTA2_570`) | Match history/details, hero list | Steam API key, ~100k calls/day | Raw matches only, no aggregates. Not needed unless you want to compute stats yourself. |
| **dotaconstants** (npm / GitHub) | Hero ids, names, roles, image URLs, patch list | Static JSON | Use for hero metadata and portraits. |
| Dotabuff / Dota2ProTracker | Counter lists, meta | No public API; scraping is against their terms | Don't use |

**Recommendation:** OpenDota for v1, cached locally once a day as a single JSON file. Add STRATZ later behind the same internal data interface when you want per-bracket counters.

## 4. First-version architecture

```
 Dota 2 ──GSI POST──▶ ┌──────────────── Companion app (local) ────────────────┐
 (game phase,         │  GSI listener ──▶ Draft state ◀── Screen-capture matcher │
  own hero)           │                     ▲   │          (top bar, ~2 fps     │
 Screen ──capture───▶ │      Manual input ──┘   ▼           while drafting)     │
                      │                  Scoring engine ◀── Stats cache (JSON)  │
                      │                         │            refreshed daily    │
                      │                         ▼            from OpenDota      │
                      │      UI: always-on-top window  +  local web page (LAN)  │
                      └─────────────────────────────────────────────────────────┘
```

Components:
1. **GSI listener**: tiny local HTTP server on e.g. `127.0.0.1:3000`; app writes `gamestate_integration_dota2picker.cfg` into `dota 2 beta/game/dota/cfg/gamestate_integration/`. Triggers "draft started/ended" and fills in your own hero.
2. **Capture matcher**: only runs while GSI says hero selection is active. Captures the top-bar strip, splits into 10 slots, matches against portrait templates, emits picks with a confidence score. Low confidence → slot shown as "?" for manual fix.
3. **Draft state**: allies, enemies, bans, your role (set once in settings or chosen per game).
4. **Stats cache**: `heroes.json` (meta), `matchups.json` (hero×hero games/wins), fetched on startup if older than 24h.
5. **Scoring engine**: pure function `suggest(draft, stats, role) -> ranked list`, easy to unit-test.
6. **UI**: compact list of top 5 heroes with score and one-line reason ("+4.1% vs Phantom Assassin, +2.3% vs Lion").

Suggested build order: (1) data fetch + scoring + manual-input UI (useful on its own); (2) GSI phase detection; (3) screen-capture matching; (4) STRATZ / per-bracket data.

## 5. Counter-pick scoring

For a candidate hero `h` not already picked or banned:

```
score(h) = Σ_enemy  w_e · adv(h, e)          # counter value
         + α · Σ_ally  syn(h, a)              # team synergy (needs STRATZ "with" data; 0 in v1)
         + β · meta(h)                        # bracket win rate - 50%, shrunk
         + γ · role_fit(h, my_role)           # filter or penalty
```

- **Matchup advantage** `adv(h, e)`: don't use raw win rate vs `e`, because strong heroes win against everyone. Use the difference from expectation: `adv = wr(h vs e) − expected(h, e)`, where `expected` comes from both heroes' overall win rates (simplest: `wr(h) − wr(e) + 0.5`, or do it in log-odds). This is the same idea as Dotabuff's "disadvantage" column.
- **Shrinkage for small samples**: `adv_shrunk = adv · n / (n + k)` with `k ≈ 200–500` games, so a 70% win rate over 30 games doesn't dominate.
- **Weights**: start with `w_e = 1` for every enemy. Later, weight enemy cores more, and late picks more since they're final.
- **Meta**: use `/heroStats` for your rank bracket, `meta = (wins/picks − 0.5)`, shrunk the same way. Keep `β` small (≈0.3–0.5) so counters dominate.
- **Role fit**: v1 uses OpenDota's hero roles (Carry, Support, ...) as a filter; v2 uses STRATZ position data.
- **Output**: top 5 with the two biggest contributing matchups as the reason; also show "avoid" (worst 3 picks vs this enemy lineup).
- **Tuning later**: backtest on historical matches (pick the drafts, check whether higher-scored heroes actually won more) and fit the weights with logistic regression.

## 6. Decisions for Mara

1. **Tech stack.** Recommended: **Python** (FastAPI/aiohttp for GSI + local web UI, `mss` + OpenCV for capture, `pywebview` for the always-on-top window). Easiest for image matching and data work. Alternative: **TypeScript + Tauri/Electron** if you'd rather have a polished desktop app and distribute it later.
2. **GitHub repo for the prototype.** Recommended yes: create one (e.g. `dota2picker`) and attach it to this project so code lands as PRs.
3. **Platform.** Assumed **Windows only** for v1, where most Dota players are. Screen capture and window behavior differ on Linux/macOS.
4. **Data source.** OpenDota only for v1 (no signup). STRATZ later needs a free token from your Steam login.
5. **Overlay vs. companion.** Recommended: always-on-top companion window plus LAN web page; no injected overlay.

## Sources

- Valve Feb 2023 patch against draft-scouting apps: https://esports.gg/news/dota-2/dota-2-update-kills-third-party-applications-including-overwolf/ and https://game-tournaments.com/dota-2/news/44348
- GSI libraries and player vs spectator data: https://www.npmjs.com/package/dota2-gsi , https://www.nuget.org/packages/Dota2GSI , https://docs.rs/dota-gsi
- Dota Coach (Overwolf, uses GSI/Overwolf events): https://dotacoach.gg/en/app/faqs
- OpenDota API tiers (2018): https://blog.opendota.com/2018/04/17/changes-to-the-api/ ; docs: https://docs.opendota.com/
- STRATZ API: https://stratz.com/api , https://stratz.medium.com/stratz-api-major-update-5557335dbdfd
