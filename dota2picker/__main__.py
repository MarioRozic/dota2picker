"""Run the app: `python -m dota2picker`."""

from __future__ import annotations

import argparse
import json
import logging
import threading
import webbrowser
from pathlib import Path

import uvicorn

from . import gsi, stats
from .demo import demo_stats
from .server import create_app

CONFIG = Path.home() / ".dota2picker" / "config.json"


def gsi_token() -> str:
    config = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    if "gsi_token" not in config:
        config["gsi_token"] = gsi.new_token()
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        CONFIG.write_text(json.dumps(config, indent=2))
    return config["gsi_token"]


def read_image(path: Path) -> None:
    import cv2

    from . import heroes, vision

    image = cv2.imread(str(path))
    if image is None:
        raise SystemExit(f"can't read image {path}")
    matcher = vision.PortraitMatcher(vision.load_portraits(vision.default_portrait_dir()))
    reads = matcher.read(image)
    for i, d in enumerate(reads):
        side = "Radiant" if i < 5 else "Dire"
        name = heroes.by_id()[d.hero_id].localized_name if d.hero_id else "-"
        print(f"{side} {i % 5 + 1}: {name:<20} {d.score:.2f}")
    out = path.with_name(path.stem + ".slots.png")
    cv2.imwrite(str(out), vision.annotate(image, reads))
    print(f"Wrote {out} showing where each slot was read")


def main() -> None:
    parser = argparse.ArgumentParser(prog="dota2picker", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to open the UI from a phone on your LAN")
    parser.add_argument("--port", type=int, default=53000)
    parser.add_argument("--refresh", action="store_true", help="re-download stats from OpenDota now")
    parser.add_argument("--demo", action="store_true", help="use made-up stats (no network)")
    parser.add_argument("--install-gsi", action="store_true", help="write the GSI config into the Dota 2 folder and exit")
    parser.add_argument("--dota-dir", type=Path, default=None, help="Dota 2 install folder ('dota 2 beta')")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-screen", action="store_true", help="don't read picks from the screen")
    parser.add_argument("--monitor", type=int, default=1, help="which monitor Dota is on (1 = primary)")
    parser.add_argument("--read-image", type=Path, metavar="FILE", help="read the heroes from a screenshot file, print them and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    token = gsi_token()
    if args.install_gsi:
        dota_dir = args.dota_dir or gsi.default_dota_dir()
        if not dota_dir.exists():
            parser.error(f"Dota 2 not found at {dota_dir}; pass --dota-dir")
        path = gsi.install_cfg(dota_dir, f"http://127.0.0.1:{args.port}/gsi", token)
        print(f"Wrote {path}")
        print("Add -gamestateintegration to Dota 2's launch options in Steam, then restart Dota.")
        return

    if args.read_image:
        read_image(args.read_image)
        return

    if args.demo:
        data = demo_stats()
    else:
        print("Loading hero stats (first run downloads from OpenDota, about 3 minutes)...", flush=True)
        data = stats.load(refresh=args.refresh)

    url = f"http://127.0.0.1:{args.port}/"
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    print(f"Dota2Picker running at {url}", flush=True)
    watcher = None
    if not args.no_screen:
        from . import capture, vision

        print("Loading hero portraits (first run downloads them from Valve's CDN)...", flush=True)
        matcher = vision.PortraitMatcher(vision.load_portraits(vision.default_portrait_dir()))
        watcher = capture.ScreenWatcher(matcher, should_run=lambda: True, monitor=args.monitor)

    app = create_app(data, gsi_token=token, watcher=watcher)
    if watcher is not None:
        watcher.should_run = app.state.screen_should_run
        watcher.start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
