from __future__ import annotations

import subprocess
from pathlib import Path


def test_repo_launcher_runs_without_installation() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    launcher = repo_root / "run.py"

    result = subprocess.run(
        ["python3", launcher.as_posix(), "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Identify maximum-average power and/or heart-rate intervals" in result.stdout
