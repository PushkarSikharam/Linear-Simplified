"""Operator commands, run on the server itself — never reachable through the public API.

Resetting everyone's demo data used to be one click on the public page, available to every
visitor because every visitor was signed in as the administrator. It now belongs to whoever can
open a shell on the server. From the repository root (or `/app` in the container):

    PYTHONPATH=apps/api python -m app.ops check-readiness
    PYTHONPATH=apps/api python -m app.ops reset-demo-data

`check-readiness` exits non-zero when any active product cannot start a conversation, and prints
which ones and why — the detail the public health endpoint deliberately withholds.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from app.db import migrate
from app.definitions.integrity import session_start_problems
from app.services.product_data_store import ProductDataStore


def check_readiness() -> int:
    problems = session_start_problems()
    print(json.dumps({"ready": not problems, "problems": [asdict(problem) for problem in problems]},
                     indent=2))
    return 1 if problems else 0


def reset_demo_data() -> int:
    data = ProductDataStore().reset()
    print(json.dumps({"reset": True, **{name: len(rows) for name, rows in data.items()}}, indent=2))
    return 0


COMMANDS = {"check-readiness": check_readiness, "reset-demo-data": reset_demo_data}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ops", description="Pixel operator commands.")
    parser.add_argument("command", choices=sorted(COMMANDS))
    arguments = parser.parse_args(argv)
    migrate()
    return COMMANDS[arguments.command]()


if __name__ == "__main__":
    sys.exit(main())
