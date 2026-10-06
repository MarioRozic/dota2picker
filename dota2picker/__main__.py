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


def main() -> None:
    parser = argparse.ArgumentParser(prog="dota2picker", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to open the UI from a phone on your LAN")
    parser.add_argument("--port", type=int, default=53000)
    parser.add_argument("--refresh", action="store_true", help="re-download stats from OpenDota now")
    parser.add_argument("--demo", action="store_true", help="use made-up stats (no network)")
    parser.add_argument("--install-gsi", action="store_true", help="write the GSI config into the Dota 2 folder and exit")
    parser.add_argument("--dota-dir", type=Path, default=None, help="Dota 2 install folder ('dota 2 beta')")
    parser.add_argument("--no-browser", action="store_true")
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

    if args.demo:
        data = demo_stats()
    else:
        print("Loading hero stats (first run downloads from OpenDota, about 3 minutes)...", flush=True)
        data = stats.load(refresh=args.refresh)

    url = f"http://127.0.0.1:{args.port}/"
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    print(f"Dota2Picker running at {url}", flush=True)
    uvicorn.run(create_app(data, gsi_token=token), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
