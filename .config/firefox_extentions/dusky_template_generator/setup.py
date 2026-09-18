#!/usr/bin/env python3
"""Register the Dusky native messaging host with Firefox on Arch Linux.

Writes ~/.mozilla/native-messaging-hosts/dusky_template_generator.json pointing
at host/dusky_template_host.py, and marks the host executable.

    python3 setup.py            install
    python3 setup.py --remove   uninstall
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

HOST_NAME = "dusky_template_generator"
EXT_ID = "dusky_template_generator@dusk.com"
HERE = Path(__file__).resolve().parent
HOST_PY = HERE / "host" / "dusky_template_host.py"
MANIFEST_DIR = Path.home() / ".mozilla" / "native-messaging-hosts"
MANIFEST = MANIFEST_DIR / f"{HOST_NAME}.json"


def install() -> int:
    if not HOST_PY.is_file():
        print(f"error: {HOST_PY} not found", file=sys.stderr)
        return 1
    HOST_PY.chmod(HOST_PY.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps({
            "name": HOST_NAME,
            "description": "Dusky Template Generator native host",
            "path": str(HOST_PY),
            "type": "stdio",
            "allowed_extensions": [EXT_ID],
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    templates = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "dusky_sites"
    templates.mkdir(parents=True, exist_ok=True)

    print(f"installed  {MANIFEST}")
    print(f"host       {HOST_PY}")
    print(f"templates  {templates}")
    print("\nNow load the extension:  about:debugging#/runtime/this-firefox -> Load Temporary Add-on -> manifest.json")
    return 0


def remove() -> int:
    MANIFEST.unlink(missing_ok=True)
    print(f"removed  {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(remove() if "--remove" in sys.argv[1:] else install())
