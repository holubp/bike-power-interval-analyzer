#!/usr/bin/env python3
"""Repository-local launcher for running the CLI without installation."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parent
    src_dir = repo_root / "src"
    if not src_dir.is_dir():
        raise RuntimeError(f"Expected src directory at {src_dir}, but it was not found.")

    sys.path.insert(0, src_dir.as_posix())
    from bike_power_interval_analyzer.cli import main as cli_main

    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
