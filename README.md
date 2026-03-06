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
- Relative interval start/end time from activity start (`hh:mm:ss.sss`)
- Absolute interval time rendering in `local`, `utc`, or `file` timezone
- Total ascent/descent per interval
- Slope statistics using floating distance window (`--slope-window-m`, default `30m`)
- Speed minimum/median/average/maximum per interval
- Non-moving elapsed time per interval (speed + perimeter filter)
- HR/power min/median/avg/max statistics
- HR/power histograms by:
  - profile-defined zones (when present in file)
  - custom zone tabs
  - custom bin count

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

## JSON Presets

You can define defaults in JSON preset files and still override any of them on the command line.

```bash
python3 run.py --preset presets/threshold.json --count 5 --metrics both
python3 run.py --preset presets/base.json --preset presets/user.json --preset presets/workout.json
python3 run.py ride.fit --duration 05:00 --write-preset presets/new.json
```

Preset example:

```json
{
  "input_file": "ride.fit",
  "duration": "05:00",
  "count": 3,
  "metrics": "power",
  "inner_intlen": [10, 30],
  "slope_window_m": 30,
  "hr_zone_tabs": [130, 150, 170],
  "power_zone_tabs": [150, 220, 280],
  "hr_hist_bins": 6,
  "power_hist_bins": 8,
  "no_stdout": true,
  "json_out": "out/report.json"
}
```

Rules:
- preset keys can be partial (only what you want to predefine)
- multiple presets can be provided; they are applied in CLI order and later presets override earlier ones
- CLI options always override preset values
- `input_file` and `duration` can come from preset or CLI
- `--write-preset PATH` exports the effective merged configuration for reuse

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
- `--slope-window-m`:
  - Floating distance window length in meters for slope calculation
  - Default `30`
- `--hr-zone-tabs BPM ...`:
  - Custom HR zone tabs; histogram bins become `<tab1`, `[tab_i,tab_i+1)`, `>=last_tab`
- `--power-zone-tabs WATTS ...`:
  - Custom power zone tabs with the same tab semantics
- `--hr-hist-bins`:
  - Number of bins for heart-rate histogram
- `--power-hist-bins`:
  - Number of bins for power histogram
- `--absolute-timezone {local,utc,file}`:
  - Controls displayed absolute times in text output
- `--non-moving-speed-threshold-kmh`:
  - Speed threshold for non-moving detection (default `3`)
- `--non-moving-perimeter-m`:
  - Perimeter threshold for non-moving detection (default `20`)
- `--preset PATH`:
  - Load JSON defaults for any subset of CLI options
  - Can be provided multiple times; order matters
- `--write-preset PATH`:
  - Write effective merged settings (preset + CLI overrides) as reusable JSON
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
- start-end relative time from activity start (`HH:MM:SS.sss`)
- duration (`SS.sss`)
- interval length in meters (if distance data exists)
- total ascent/descent in meters (if elevation data exists)
- slope minimum/median/average/maximum in `%` (floating distance window)
- speed minimum/median/average/maximum in `km/h`
- non-moving elapsed time in seconds
- power minimum/median/average/maximum
- heart-rate minimum/median/average/maximum
- heart-rate histogram by profile zones (if available)
- heart-rate histogram by custom zone tabs (if provided)
- heart-rate histogram by fixed bin count (if provided)
- power histogram by profile zones (if available)
- power histogram by custom zone tabs (if provided)
- power histogram by fixed bin count (if provided)
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
