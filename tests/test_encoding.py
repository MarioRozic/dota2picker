"""Text files must be read and written as UTF-8 on every platform.

Windows defaults to the locale's code page (e.g. cp1250), which can't decode
the UTF-8 page and data files. Run the app's file I/O with Python's
EncodingWarning turned into an error, so a missing encoding= fails here
instead of only on Windows.
"""

import subprocess
import sys

SCRIPT = r"""
import json, sys, tempfile
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from dota2picker import __main__ as cli, gsi, heroes, items, stats
from dota2picker.demo import demo_stats
from dota2picker.server import create_app

heroes.all_heroes()
items.all_items(); items.threats(); items.counters()
assert "Dota2Picker" in TestClient(create_app(demo_stats(), gsi_token="t")).get("/").text

tmp = Path(tempfile.mkdtemp())
gsi.install_cfg(tmp, "http://127.0.0.1:53000/gsi", "t")
with mock.patch.object(cli, "CONFIG", tmp / "config.json"):
    cli.gsi_token(); cli.gsi_token()
cache = tmp / "stats.json"
with mock.patch.object(stats, "fetch", return_value=demo_stats()):
    stats.load(cache, refresh=True)
stats.load(cache)
"""


def test_file_io_does_not_depend_on_locale_encoding():
    result = subprocess.run(
        [sys.executable, "-X", "warn_default_encoding", "-W", "error::EncodingWarning", "-c", SCRIPT],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
