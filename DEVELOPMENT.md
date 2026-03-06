# Development Guide

## Repository Layout

- `run.py`: repo-local launcher (no installation required)
- `bike-intervals`: shell wrapper launcher
- `src/bike_power_interval_analyzer/`: application package
- `tests/`: pytest test suite

## Local Execution

Run directly from the repository root without installing:

```bash
python3 run.py --help
python3 run.py INPUT_FILE --duration 05:00 --metrics both
python3 run.py --preset presets/base.json --preset presets/user.json --metrics power
```

Optional shell wrapper:

```bash
sh bike-intervals INPUT_FILE --duration 05:00
```

## Quality Gates

Run before commit:

```bash
python3 -m py_compile run.py src/bike_power_interval_analyzer/*.py tests/*.py
pytest -q -k "duration or intervals or tcx or wrapper"
pytest -q
```

## Testing Notes

- The test suite includes parser, interval-engine, CLI, and launcher coverage.
- One test is skip-safe when `hypothesis` is not installed.
- Use temporary files for synthetic TCX fixtures in tests; avoid relying on local activity exports.
- `--absolute-timezone` defaults to `local` for text rendering; JSON keeps source timestamps.
- FIT profile zones can be extracted from `time_in_zone` boundaries.
