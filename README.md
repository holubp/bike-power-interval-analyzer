# Bike Power Interval Analyzer

CLI tool to identify maximum-average interval windows for **power**, **heart rate**, or both, from Garmin **TCX** and **FIT** activity files.

## Features

- Ingest `.tcx` and `.fit` files
- Fixed interval duration input as:
  - seconds (`300`, `12.5`)
  - `MM:SS` (`05:00`)
  - `HH:MM:SS` (`01:02:30`)
- Configurable maximum overlap between selected intervals (`0 <= overlap < 1`)
- Configurable number of intervals per analyzed metric
- Analyze power, heart rate, or both (separately)
- Text report to STDOUT (ANSI color by default, optional black/white)
- Optional suppression of STDOUT
- Optional CSV output
- Optional JSON output
- Optional GPX export of identified intervals (one GPX track per identified interval)
- Optional inner floating windows (`inner_intlen_array`) for nested max-average measurements

## Quick Start (No Installation)

From the repository root:

```bash
python3 run.py INPUT_FILE --duration DURATION [options]
```

`run.py` automatically points Python at `src/`, so `pip install -e .` is not required.

## Installation (Optional)

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

For development (tests + hypothesis):

```bash
pip install -e .[dev]
```

## Usage

```bash
bike-intervals INPUT_FILE --duration DURATION [options]
```

Without installation, use:

```bash
python3 run.py INPUT_FILE --duration DURATION [options]
```

Alternative launcher:

```bash
sh bike-intervals INPUT_FILE --duration DURATION [options]
```

Example:

```bash
bike-intervals ride.fit \
  --duration 05:00 \
  --max-overlap 0.2 \
  --count 5 \
  --metrics both \
  --inner-intlen 10 30 60 \
  --csv-out out/intervals.csv \
  --json-out out/intervals.json \
  --gpx-out out/intervals.gpx
```

## CLI Reference

- `input_file`:
  - Path to `.tcx` or `.fit`
- `-d, --duration` (required):
  - Interval duration (`seconds`, `MM:SS`, `HH:MM:SS`)
- `--max-overlap`:
  - Maximum overlap proportion in `[0, 1)`
  - `0` means no overlap
- `-n, --count`:
  - Number of intervals to identify per analyzed metric
- `--metrics`:
  - `power`, `heart-rate`, or `both`
- `--inner-intlen`:
  - Inner floating windows for nested max-average values
  - Default is `[10]`
  - Pass `--inner-intlen` with no values for an empty list
- `--bw`:
  - Disable colorized stdout output
- `--no-stdout`:
  - Suppress stdout report
  - Requires at least one of `--csv-out`, `--json-out`, `--gpx-out`
- `--csv-out PATH`:
  - Write flat interval rows to CSV
- `--json-out PATH`:
  - Write structured JSON
- `--gpx-out PATH`:
  - Export selected intervals as GPX tracks

## Reported Fields Per Interval

Each identified interval includes:

- start-end absolute time (`HH:MM:SS.sss` in text output)
- duration (`SS.sss`)
- interval length in meters (if distance data exists)
- average power, maximum power
- average heart rate, maximum heart rate
- for each inner interval length:
  - max floating average power
  - max floating average heart rate

## Assertive Programming Decisions

The code intentionally fails fast when assumptions are violated:

- unsupported file type
- unreadable/invalid FIT or TCX records
- invalid duration syntax
- invalid overlap range (`>= 1` rejected)
- non-positive interval count
- interval duration longer than activity
- missing output targets when stdout is suppressed

## Testing

Run:

```bash
python3 -m py_compile src/bike_power_interval_analyzer/*.py
pytest -q
```

Test suite covers:

- duration parsing (unit + hypothesis property test)
- overlap and ranking behavior
- inner interval calculations
- TCX parsing
- CLI end-to-end run with CSV/JSON/GPX outputs

## Notes

- FIT parsing uses `fitdecode`.
- Average metric calculations require full metric coverage for each interval.
- GPX export requires available GPS coordinates within identified intervals.
