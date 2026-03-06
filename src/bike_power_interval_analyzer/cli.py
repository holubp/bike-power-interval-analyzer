"""Command-line interface for bike interval analysis."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .duration import parse_duration_to_seconds, parse_inner_interval_lengths
from .intervals import analyze_stored_intervals, identify_top_intervals
from .output import (
    flatten_results_for_csv,
    render_text_report,
    serialize_results,
    write_csv,
    write_gpx,
    write_json,
)
from .parsers import parse_activity_file


TARGET_TO_RESULT_KEY = {
    "power": "power",
    "heart-rate": "heart_rate",
    "interval": "interval",
}

PRESET_ALLOWED_KEYS = {
    "input_file",
    "duration",
    "max_overlap",
    "count",
    "target",
    "metrics",
    "interval_select",
    "inner_intlen",
    "slope_window_m",
    "hr_zone_tabs",
    "power_zone_tabs",
    "hr_hist_bins",
    "power_hist_bins",
    "absolute_timezone",
    "non_moving_speed_threshold_kmh",
    "non_moving_perimeter_m",
    "bw",
    "no_stdout",
    "csv_out",
    "json_out",
    "gpx_out",
}


def build_argument_parser(defaults: dict[str, Any] | None = None) -> argparse.ArgumentParser:
    """Build argparse parser for the CLI."""
    default_values = defaults or {}
    parser = argparse.ArgumentParser(
        prog="bike-intervals",
        description=(
            "Identify maximum-average power and/or heart-rate intervals "
            "from TCX, FIT, and Garmin Connect ZIP files."
        ),
    )
    parser.add_argument(
        "--preset",
        action="append",
        metavar="PATH",
        help="JSON preset path; can be provided multiple times, later presets override earlier ones",
    )
    parser.add_argument(
        "--write-preset",
        metavar="PATH",
        help="Write effective merged configuration (preset + CLI overrides) to JSON",
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        default=default_values.get("input_file"),
        help="Path to .tcx, .fit, or Garmin Connect .zip export",
    )
    parser.add_argument(
        "-d",
        "--duration",
        default=default_values.get("duration"),
        help="Interval duration as seconds, MM:SS, or HH:MM:SS",
    )
    parser.add_argument(
        "--max-overlap",
        type=float,
        default=default_values.get("max_overlap", 0.0),
        help="Maximum overlap proportion in [0, 1) between selected intervals",
    )
    parser.add_argument(
        "-n",
        "--count",
        type=int,
        default=default_values.get("count", 3),
        help="Maximum number of intervals to identify per metric",
    )
    parser.add_argument(
        "--target",
        default=default_values.get(
            "target", default_values.get("metrics", "power,heart-rate")
        ),
        help=(
            "Analysis target(s) as comma-separated values from "
            "power,heart-rate,interval"
        ),
    )
    parser.add_argument(
        "--metrics",
        dest="target",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--inner-intlen",
        nargs="?",
        const="",
        default=default_values.get("inner_intlen"),
        metavar="SECONDS_CSV",
        help=(
            "Inner floating windows in seconds/MM:SS/HH:MM:SS as comma-separated values "
            "(e.g. 3,10,60). Default: 10. Pass '--inner-intlen' with no value for an empty list."
        ),
    )
    parser.add_argument(
        "--interval-select",
        default=default_values.get("interval_select", "all"),
        help=(
            "Selectors for file-stored intervals: 'all' or comma-separated "
            "labels/1-based indices (e.g. 1,3,lap-5)"
        ),
    )
    parser.add_argument(
        "--slope-window-m",
        type=float,
        default=default_values.get("slope_window_m", 30.0),
        help="Distance window in meters used for floating slope statistics (default: 30)",
    )
    parser.add_argument(
        "--hr-zone-tabs",
        default=default_values.get("hr_zone_tabs"),
        metavar="BPM_CSV",
        help="Custom HR zone tabs as comma-separated values (e.g. 120,140,160)",
    )
    parser.add_argument(
        "--power-zone-tabs",
        default=default_values.get("power_zone_tabs"),
        metavar="WATTS_CSV",
        help="Custom power zone tabs as comma-separated values (e.g. 150,220,300)",
    )
    parser.add_argument(
        "--hr-hist-bins",
        type=int,
        default=default_values.get("hr_hist_bins"),
        help="Heart-rate histogram bin count",
    )
    parser.add_argument(
        "--power-hist-bins",
        type=int,
        default=default_values.get("power_hist_bins"),
        help="Power histogram bin count",
    )
    parser.add_argument(
        "--absolute-timezone",
        choices=["local", "utc", "file"],
        default=default_values.get("absolute_timezone", "local"),
        help="Timezone used for displayed absolute HH:MM:SS.sss values",
    )
    parser.add_argument(
        "--non-moving-speed-threshold-kmh",
        type=float,
        default=default_values.get("non_moving_speed_threshold_kmh", 3.0),
        help="Speed threshold for non-moving detection (default: 3 km/h)",
    )
    parser.add_argument(
        "--non-moving-perimeter-m",
        type=float,
        default=default_values.get("non_moving_perimeter_m", 20.0),
        help="Perimeter threshold for non-moving detection (default: 20 m)",
    )
    parser.add_argument(
        "--bw",
        dest="bw",
        action="store_true",
        default=bool(default_values.get("bw", False)),
        help="Disable ANSI colors in text output",
    )
    parser.add_argument(
        "--color",
        dest="bw",
        action="store_false",
        help="Enable ANSI colors in text output",
    )
    parser.add_argument(
        "--no-stdout",
        dest="no_stdout",
        action="store_true",
        default=bool(default_values.get("no_stdout", False)),
        help="Suppress text report to STDOUT",
    )
    parser.add_argument(
        "--stdout",
        dest="no_stdout",
        action="store_false",
        help="Force text report to STDOUT",
    )
    parser.add_argument(
        "--csv-out",
        default=default_values.get("csv_out"),
        metavar="PATH",
        help="Write interval results to CSV file",
    )
    parser.add_argument(
        "--json-out",
        default=default_values.get("json_out"),
        metavar="PATH",
        help="Write interval results to JSON file",
    )
    parser.add_argument(
        "--gpx-out",
        default=default_values.get("gpx_out"),
        metavar="PATH",
        help="Write identified intervals as GPX tracks",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run CLI and return shell exit code."""
    actual_argv = argv if argv is not None else sys.argv[1:]

    try:
        preset_paths = _extract_preset_paths(actual_argv)
        preset_defaults = _load_preset_defaults(preset_paths)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    parser = build_argument_parser(defaults=preset_defaults)
    args = parser.parse_args(actual_argv)

    if args.input_file is None:
        parser.error("input_file is required (either on CLI or in preset).")
    try:
        target_list = _parse_target_spec(args.target, "--target")
    except ValueError as exc:
        parser.error(str(exc))
    if any(target in {"power", "heart-rate"} for target in target_list) and args.duration is None:
        parser.error("--duration is required when target includes power or heart-rate.")

    try:
        duration_s = (
            parse_duration_to_seconds(str(args.duration))
            if args.duration is not None
            else None
        )
        inner_lengths_s = parse_inner_interval_lengths(
            _expand_csv_list(args.inner_intlen, "--inner-intlen")
        )
    except ValueError as exc:
        parser.error(str(exc))

    if not (0 <= args.max_overlap < 1):
        parser.error("--max-overlap must be in [0, 1).")
    if args.count <= 0:
        parser.error("--count must be > 0.")
    if args.slope_window_m <= 0:
        parser.error("--slope-window-m must be > 0.")
    if args.hr_hist_bins is not None and args.hr_hist_bins <= 0:
        parser.error("--hr-hist-bins must be > 0.")
    if args.power_hist_bins is not None and args.power_hist_bins <= 0:
        parser.error("--power-hist-bins must be > 0.")
    if args.non_moving_speed_threshold_kmh < 0:
        parser.error("--non-moving-speed-threshold-kmh must be >= 0.")
    if args.non_moving_perimeter_m <= 0:
        parser.error("--non-moving-perimeter-m must be > 0.")

    if args.no_stdout and not any([args.csv_out, args.json_out, args.gpx_out]):
        parser.error(
            "--no-stdout requires at least one of --csv-out, --json-out, or --gpx-out."
        )

    try:
        hr_zone_tabs = _parse_zone_tabs(
            _expand_csv_list(args.hr_zone_tabs, "--hr-zone-tabs"),
            "--hr-zone-tabs",
        )
        power_zone_tabs = _parse_zone_tabs(
            _expand_csv_list(args.power_zone_tabs, "--power-zone-tabs"),
            "--power-zone-tabs",
        )
        interval_selectors = _parse_interval_select(args.interval_select)
    except ValueError as exc:
        parser.error(str(exc))

    try:
        activity = parse_activity_file(args.input_file)

        results_by_metric: dict[str, list] = {}
        if "interval" in target_list:
            results_by_metric["interval"] = analyze_stored_intervals(
                activity=activity,
                interval_selectors=interval_selectors,
                inner_interval_lengths_s=inner_lengths_s,
                slope_window_m=args.slope_window_m,
                hr_zone_tabs_bpm=hr_zone_tabs,
                power_zone_tabs_w=power_zone_tabs,
                hr_hist_bins=args.hr_hist_bins,
                power_hist_bins=args.power_hist_bins,
                non_moving_speed_threshold_kmh=args.non_moving_speed_threshold_kmh,
                non_moving_perimeter_m=args.non_moving_perimeter_m,
            )
        if any(target in {"power", "heart-rate"} for target in target_list):
            if duration_s is None:
                raise RuntimeError("Internal error: duration_s missing for windowed target.")
            for target in target_list:
                if target == "interval":
                    continue
                metric = TARGET_TO_RESULT_KEY[target]
                results_by_metric[metric] = identify_top_intervals(
                    activity=activity,
                    duration_s=duration_s,
                    max_overlap_ratio=args.max_overlap,
                    count=args.count,
                    analyzed_metric=metric,
                    inner_interval_lengths_s=inner_lengths_s,
                    slope_window_m=args.slope_window_m,
                    hr_zone_tabs_bpm=hr_zone_tabs,
                    power_zone_tabs_w=power_zone_tabs,
                    hr_hist_bins=args.hr_hist_bins,
                    power_hist_bins=args.power_hist_bins,
                    non_moving_speed_threshold_kmh=args.non_moving_speed_threshold_kmh,
                    non_moving_perimeter_m=args.non_moving_perimeter_m,
                )

        if not args.no_stdout:
            sys.stdout.write(
                render_text_report(
                    results_by_metric,
                    color=not args.bw,
                    absolute_timezone=args.absolute_timezone,
                )
            )

        if args.csv_out:
            rows = flatten_results_for_csv(results_by_metric)
            if not rows:
                raise RuntimeError("No interval rows available for CSV output.")
            write_csv(args.csv_out, rows)

        payload = {
            "input_file": args.input_file,
            "duration_s": duration_s,
            "max_overlap": args.max_overlap,
            "count": args.count,
            "target": _format_target_spec(target_list),
            "target_list": target_list,
            "interval_select": "all" if interval_selectors is None else interval_selectors,
            "inner_interval_lengths_s": inner_lengths_s,
            "slope_window_m": args.slope_window_m,
            "hr_zone_tabs": hr_zone_tabs,
            "power_zone_tabs": power_zone_tabs,
            "hr_hist_bins": args.hr_hist_bins,
            "power_hist_bins": args.power_hist_bins,
            "absolute_timezone": args.absolute_timezone,
            "non_moving_speed_threshold_kmh": args.non_moving_speed_threshold_kmh,
            "non_moving_perimeter_m": args.non_moving_perimeter_m,
            "preset": args.preset or [],
            "results": serialize_results(results_by_metric),
        }
        if args.json_out:
            write_json(args.json_out, payload)

        if args.write_preset:
            write_json(
                args.write_preset,
                _build_effective_preset(
                    input_file=args.input_file,
                    duration=args.duration,
                    max_overlap=args.max_overlap,
                    count=args.count,
                    target=_format_target_spec(target_list),
                    interval_select="all"
                    if interval_selectors is None
                    else ",".join(interval_selectors),
                    inner_intlen=inner_lengths_s,
                    slope_window_m=args.slope_window_m,
                    hr_zone_tabs=hr_zone_tabs,
                    power_zone_tabs=power_zone_tabs,
                    hr_hist_bins=args.hr_hist_bins,
                    power_hist_bins=args.power_hist_bins,
                    absolute_timezone=args.absolute_timezone,
                    non_moving_speed_threshold_kmh=args.non_moving_speed_threshold_kmh,
                    non_moving_perimeter_m=args.non_moving_perimeter_m,
                    bw=args.bw,
                    no_stdout=args.no_stdout,
                    csv_out=args.csv_out,
                    json_out=args.json_out,
                    gpx_out=args.gpx_out,
                ),
            )

        if args.gpx_out:
            write_gpx(args.gpx_out, activity, results_by_metric)

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    return 0


def _extract_preset_paths(argv: list[str]) -> list[str]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--preset", action="append", metavar="PATH")
    ns, _ = parser.parse_known_args(argv)
    return ns.preset or []


def _load_preset_defaults(paths: list[str]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for path in paths:
        file_path = Path(path)
        if not file_path.exists():
            raise ValueError(f"Preset file does not exist: {path}")
        if not file_path.is_file():
            raise ValueError(f"Preset path is not a file: {path}")

        try:
            payload = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Preset file is not valid JSON: {path}: {exc}") from exc

        if not isinstance(payload, dict):
            raise ValueError(f"Preset JSON root must be an object: {path}")

        normalized: dict[str, Any] = {}
        for key, value in payload.items():
            normalized_key = key.replace("-", "_")
            if normalized_key not in PRESET_ALLOWED_KEYS:
                raise ValueError(
                    f"Unsupported preset key '{key}' in {path}. "
                    f"Allowed keys: {sorted(PRESET_ALLOWED_KEYS)}"
                )
            normalized[normalized_key] = value
        if "metrics" in normalized and "target" not in normalized:
            normalized["target"] = normalized["metrics"]
            del normalized["metrics"]

        _validate_preset_types(normalized, path)
        merged.update(normalized)
    return merged


def _validate_preset_types(preset: dict[str, Any], source: str) -> None:
    for key in ("bw", "no_stdout"):
        if key in preset and not isinstance(preset[key], bool):
            raise ValueError(f"Preset key '{key}' must be boolean in {source}.")

    for key in ("inner_intlen", "hr_zone_tabs", "power_zone_tabs"):
        if key in preset and not isinstance(preset[key], (list, str)):
            raise ValueError(
                f"Preset key '{key}' must be an array or comma-separated string in {source}."
            )

    for key in ("input_file", "target", "interval_select", "csv_out", "json_out", "gpx_out"):
        if key in preset and not isinstance(preset[key], str):
            raise ValueError(f"Preset key '{key}' must be a string in {source}.")
    if "target" in preset:
        _parse_target_spec(preset["target"], f"preset:{source}:target")
    if "interval_select" in preset:
        _parse_interval_select(preset["interval_select"])

    if "duration" in preset and not isinstance(preset["duration"], (str, int, float)):
        raise ValueError(f"Preset key 'duration' must be string or number in {source}.")
    for key in (
        "max_overlap",
        "count",
        "slope_window_m",
        "hr_hist_bins",
        "power_hist_bins",
        "non_moving_speed_threshold_kmh",
        "non_moving_perimeter_m",
    ):
        if key in preset and not isinstance(preset[key], (int, float)):
            raise ValueError(f"Preset key '{key}' must be numeric in {source}.")
    if "absolute_timezone" in preset and preset["absolute_timezone"] not in {
        "local",
        "utc",
        "file",
    }:
        raise ValueError(
            f"Preset key 'absolute_timezone' must be one of local|utc|file in {source}."
        )


def _parse_zone_tabs(raw_values: list[Any] | None, arg_name: str) -> list[float] | None:
    if raw_values is None:
        return None
    tabs: list[float] = []
    for raw in raw_values:
        text = str(raw).strip()
        if not text:
            raise ValueError(f"{arg_name} must not contain empty values.")
        try:
            value = float(text)
        except ValueError as exc:
            raise ValueError(
                f"{arg_name} values must be numeric thresholds, got '{raw}'."
            ) from exc
        if value <= 0:
            raise ValueError(f"{arg_name} values must be > 0, got {value}.")
        tabs.append(value)

    sorted_tabs = sorted(tabs)
    for i in range(len(sorted_tabs) - 1):
        if abs(sorted_tabs[i + 1] - sorted_tabs[i]) <= 1e-9:
            raise ValueError(f"{arg_name} values must be unique.")
    return sorted_tabs


def _expand_csv_list(raw_values: Any, arg_name: str) -> list[str] | None:
    """Expand comma-separated values from CLI/preset into a flat string list."""
    if raw_values is None:
        return None
    if isinstance(raw_values, str):
        candidates = [raw_values]
    elif isinstance(raw_values, list):
        candidates = [str(item) for item in raw_values]
    else:
        candidates = [str(raw_values)]

    expanded: list[str] = []
    for raw in candidates:
        text = raw.strip()
        if not text:
            continue
        if "," in text:
            parts = [part.strip() for part in text.split(",")]
        else:
            if any(ch.isspace() for ch in text):
                raise ValueError(
                    f"{arg_name} must use comma-separated values "
                    "(e.g. 10,30,60), not space-separated values."
                )
            parts = [text]
        for part in parts:
            if not part:
                raise ValueError(f"{arg_name} contains an empty comma-separated value.")
            expanded.append(part)
    return expanded


def _parse_interval_select(raw: Any) -> list[str] | None:
    text = str(raw).strip()
    if not text:
        raise ValueError("--interval-select must not be empty.")
    parts = [part.strip() for part in text.split(",")]
    selectors = [part for part in parts if part]
    if not selectors:
        raise ValueError("--interval-select resolved to an empty selector list.")

    lowered = [item.lower() for item in selectors]
    if "all" in lowered:
        if len(selectors) > 1:
            raise ValueError("--interval-select value 'all' must not be combined with other selectors.")
        return None
    return selectors


def _parse_target_spec(raw: Any, arg_name: str) -> list[str]:
    if isinstance(raw, list):
        tokens = [str(item).strip() for item in raw]
    else:
        text = str(raw).strip()
        if not text:
            raise ValueError(f"{arg_name} must not be empty.")
        tokens = [item.strip() for item in text.split(",")]

    selected: list[str] = []
    for token in tokens:
        if not token:
            raise ValueError(
                f"{arg_name} contains an empty target. Use comma-separated values like "
                "power,heart-rate,interval."
            )
        if token == "both":
            raise ValueError(
                f"{arg_name} no longer supports 'both'. Use 'power,heart-rate'."
            )
        if token not in TARGET_TO_RESULT_KEY:
            raise ValueError(
                f"{arg_name} contains unsupported target '{token}'. "
                "Allowed: power,heart-rate,interval."
            )
        if token not in selected:
            selected.append(token)

    if not selected:
        raise ValueError(f"{arg_name} resolved to an empty target set.")
    return selected


def _format_target_spec(target_list: list[str]) -> str:
    return ",".join(target_list)


def _build_effective_preset(
    *,
    input_file: str,
    duration: Any,
    max_overlap: float,
    count: int,
    target: str,
    interval_select: str,
    inner_intlen: list[float],
    slope_window_m: float,
    hr_zone_tabs: list[float] | None,
    power_zone_tabs: list[float] | None,
    hr_hist_bins: int | None,
    power_hist_bins: int | None,
    absolute_timezone: str,
    non_moving_speed_threshold_kmh: float,
    non_moving_perimeter_m: float,
    bw: bool,
    no_stdout: bool,
    csv_out: str | None,
    json_out: str | None,
    gpx_out: str | None,
) -> dict[str, Any]:
    preset: dict[str, Any] = {
        "input_file": input_file,
        "max_overlap": max_overlap,
        "count": count,
        "target": target,
        "interval_select": interval_select,
        "inner_intlen": inner_intlen,
        "slope_window_m": slope_window_m,
        "absolute_timezone": absolute_timezone,
        "non_moving_speed_threshold_kmh": non_moving_speed_threshold_kmh,
        "non_moving_perimeter_m": non_moving_perimeter_m,
        "bw": bw,
        "no_stdout": no_stdout,
    }
    if duration is not None:
        preset["duration"] = duration
    if hr_zone_tabs is not None:
        preset["hr_zone_tabs"] = hr_zone_tabs
    if power_zone_tabs is not None:
        preset["power_zone_tabs"] = power_zone_tabs
    if hr_hist_bins is not None:
        preset["hr_hist_bins"] = hr_hist_bins
    if power_hist_bins is not None:
        preset["power_hist_bins"] = power_hist_bins
    if csv_out is not None:
        preset["csv_out"] = csv_out
    if json_out is not None:
        preset["json_out"] = json_out
    if gpx_out is not None:
        preset["gpx_out"] = gpx_out
    return preset


if __name__ == "__main__":
    raise SystemExit(main())
