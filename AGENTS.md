# AGENTS Guide

## Purpose

This repository provides a CLI tool that identifies top fixed-duration intervals by average power and/or average heart rate from TCX and FIT files.

## Architecture

Source code is in `src/bike_power_interval_analyzer/`:

- `cli.py`: argument parsing and end-to-end orchestration
- `parsers.py`: TCX/FIT ingestion and normalization into `ActivityData`
- `intervals.py`: interval candidate generation, overlap filtering, and stats
- `output.py`: text, CSV, JSON, GPX serialization
- `duration.py`: duration/inner-window parsing
- `models.py`: shared dataclasses

Tests are in `tests/`.

## Core Contracts

- Input points must normalize to strictly increasing timestamps.
- Interval duration must be `> 0` and not exceed activity duration.
- Overlap must be in `[0, 1)`.
- Interval averages are computed only for windows with full metric coverage.
- If `--no-stdout` is set, at least one file output must be requested.
- Segment output now includes relative times, ascent/descent, slope stats (`--slope-window-m`), HR/power min/median/avg/max, and HR/power histograms (profile zones, custom tabs, and fixed bins when configured).
- Segment output also includes speed min/median/avg/max and non-moving elapsed time based on speed/perimeter thresholds.
- CLI supports JSON presets via `--preset`; preset values act as defaults and explicit CLI args must take precedence.
- Multiple `--preset` values are supported; presets are applied in order and later presets override earlier ones.
- CLI can export effective merged settings via `--write-preset` for reproducible reruns.

## Development Workflow

1. Keep public functions documented with concise docstrings.
2. Use explicit input validation and actionable errors (assertive programming).
3. Add/adjust pytest tests for all changed behavior.
4. Update `README.md` when CLI semantics or outputs change.
5. Prefer running the repo-local launcher `python3 run.py` for manual checks to avoid requiring installation.

## Required Verification

Run from repo root:

```bash
python3 run.py --help
python3 -m py_compile src/bike_power_interval_analyzer/*.py
pytest -q
```

When touching parser or interval logic, prefer adding focused tests first:

```bash
pytest -q -k "duration or intervals or tcx"
```

## Extension Guidance

- New output format: add serializer in `output.py`, wire flag in `cli.py`, and test end-to-end.
- New metric: extend `DataPoint`, add parser extraction, add metric series in `intervals.py`, and update text/JSON/CSV fields.
- New input format: add parser module function returning `ActivityData`, then route from `parse_activity_file`.

## FIT/TCX Notes

- FIT parsing depends on `fitdecode`.
- TCX parser reads Garmin namespace variants by local XML tag names to remain robust across schema prefixes.
