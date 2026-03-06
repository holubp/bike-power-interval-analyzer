# Bike Intervals Tutorial (For Athletes and Coaches)

This guide explains how to run the tool without Python packaging setup and how to read the results.

## 1) What this tool does

It finds your strongest segments in a workout file:
- top average power windows
- top average heart-rate windows
- file-stored laps/intervals (if your device recorded them)

It can read:
- `.fit`
- `.tcx`
- Garmin Connect export `.zip` (containing FIT)

## 2) Run without installation

From the repository root:

```bash
python3 run.py --help
```

Main pattern:

```bash
python3 run.py YOUR_ACTIVITY.fit --duration 10:00 --target power
```

You can also use:

```bash
sh bike-intervals YOUR_ACTIVITY.fit --duration 10:00 --target power
```

## 3) First practical commands

Power-only ranking:

```bash
python3 run.py workout.fit --duration 10:00 --max-overlap 0.3 -n 5 --target power
```

Power + heart-rate ranking together:

```bash
python3 run.py workout.fit --duration 08:00 --target power,heart-rate
```

Use short inner windows (comma-separated list):

```bash
python3 run.py workout.fit --duration 10:00 --target power --inner-intlen 3,10,60
```

Important: list options are comma-separated only.
Examples: `power,heart-rate`, `3,10,60`, `130,150,170`.

## 4) Use intervals/laps from the file

Analyze intervals already stored by the device:

```bash
python3 run.py workout.fit --target interval
```

Select only some stored intervals:

```bash
python3 run.py workout.fit --target interval --interval-select 2,4
python3 run.py workout.fit --target interval --interval-select warmup,main-set-1
```

`--count` does not limit `--target interval`; selector controls this mode.

## 5) Export results

JSON + CSV + GPX:

```bash
python3 run.py workout.fit \
  --duration 10:00 \
  --target power,heart-rate \
  --csv-out out/intervals.csv \
  --json-out out/intervals.json \
  --gpx-out out/intervals.gpx
```

If you do not want text in terminal:

```bash
python3 run.py workout.fit --duration 10:00 --target power --no-stdout --json-out out/power.json
```

## 6) Presets (save your favorite setup)

Create `presets/base.json`:

```json
{
  "duration": "10:00",
  "max_overlap": 0.3,
  "count": 8,
  "target": "power,heart-rate",
  "inner_intlen": [3, 10, 60],
  "hr_zone_tabs": [130, 150, 170],
  "power_zone_tabs": [170, 230, 290]
}
```

Run with preset:

```bash
python3 run.py workout.fit --preset presets/base.json
```

Layer multiple presets (later one overrides earlier one):

```bash
python3 run.py workout.fit --preset presets/base.json --preset presets/user.json --preset presets/race.json
```

CLI flags still override preset values.

## 7) How to read one interval row

An anonymized example from a real sample activity:
- values are noise-modulated with small metric-specific offsets
- absolute time is shifted
- derived relationships are kept realistic (for example, duration/length/avg-speed consistency)

```text
#1 abs=08:41:12.000-08:51:12.000 rel=00:22:52.000-00:32:52.000 | dur=600.000s | len=2,620.00m
  ascent=97.60m descent=5.20m slope[30m]=min:-3.10% avg:3.75% med:3.92% max:8.21%
  speed=min:9.20km/h med:15.60km/h avg:15.72km/h max:27.10km/h
  non_moving=0.00s (speed<=3km/h, perimeter<=20m)
  power=min:36.00W avg:245.20W med:248.00W max:579.00W
  hr=min:132.00bpm avg:169.40bpm med:172.00bpm max:178.00bpm
```

Meaning:
- `abs`: clock time of the interval.
- `rel`: time from workout start.
- `dur`: duration in seconds.
- `len`: covered distance.
- `slope[...]`: gradient stats over moving window.
- `non_moving`: stoppage time under configured speed/perimeter thresholds.

## 8) Common beginner mistakes

- Missing `--duration` when using `power` or `heart-rate` target.
- Using spaces instead of commas for list options.
- Using `--no-stdout` without any output file (`--json-out`, `--csv-out`, or `--gpx-out`).

## 9) Good starter recipes

Cycling threshold check:

```bash
python3 run.py ride.fit --duration 20:00 --target power --inner-intlen 10,60 --max-overlap 0.2 -n 3
```

Running HR segment check:

```bash
python3 run.py run.fit --duration 05:00 --target heart-rate --max-overlap 0.2 -n 6
```

Garmin Connect ZIP directly:

```bash
python3 run.py activity_export.zip --duration 10:00 --target power
```
