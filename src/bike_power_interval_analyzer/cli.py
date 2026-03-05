"""Command-line interface for bike interval analysis."""

from __future__ import annotations

import argparse
import sys

from .duration import parse_duration_to_seconds, parse_inner_interval_lengths
from .intervals import identify_top_intervals
from .output import (
    flatten_results_for_csv,
    render_text_report,
    serialize_results,
    write_csv,
    write_gpx,
    write_json,
)
from .parsers import parse_activity_file


METRIC_MAP = {
    "power": ["power"],
    "heart-rate": ["heart_rate"],
    "both": ["power", "heart_rate"],
}


def build_argument_parser() -> argparse.ArgumentParser:
    """Build argparse parser for the CLI."""
    parser = argparse.ArgumentParser(
        prog="bike-intervals",
        description=(
            "Identify maximum-average power and/or heart-rate intervals "
            "from TCX and FIT files."
        ),
    )
    parser.add_argument("input_file", help="Path to .tcx or .fit file")
    parser.add_argument(
        "-d",
        "--duration",
        required=True,
        help="Interval duration as seconds, MM:SS, or HH:MM:SS",
    )
    parser.add_argument(
        "--max-overlap",
        type=float,
        default=0.0,
        help="Maximum overlap proportion in [0, 1) between selected intervals",
    )
    parser.add_argument(
        "-n",
        "--count",
        type=int,
        default=3,
        help="Maximum number of intervals to identify per metric",
    )
    parser.add_argument(
        "--metrics",
        choices=["power", "heart-rate", "both"],
        default="both",
        help="Which metric(s) to optimize",
    )
    parser.add_argument(
        "--inner-intlen",
        nargs="*",
        default=None,
        metavar="SECONDS",
        help=(
            "Inner floating windows in seconds/MM:SS/HH:MM:SS. "
            "Default: 10. Pass '--inner-intlen' with no values for an empty list."
        ),
    )
    parser.add_argument(
        "--bw",
        action="store_true",
        help="Disable ANSI colors in text output",
    )
    parser.add_argument(
        "--no-stdout",
        action="store_true",
        help="Suppress text report to STDOUT",
    )
    parser.add_argument(
        "--csv-out",
        metavar="PATH",
        help="Write interval results to CSV file",
    )
    parser.add_argument(
        "--json-out",
        metavar="PATH",
        help="Write interval results to JSON file",
    )
    parser.add_argument(
        "--gpx-out",
        metavar="PATH",
        help="Write identified intervals as GPX tracks",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run CLI and return shell exit code."""
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    try:
        duration_s = parse_duration_to_seconds(args.duration)
        inner_lengths_s = parse_inner_interval_lengths(args.inner_intlen)
    except ValueError as exc:
        parser.error(str(exc))

    if not (0 <= args.max_overlap < 1):
        parser.error("--max-overlap must be in [0, 1).")
    if args.count <= 0:
        parser.error("--count must be > 0.")

    if args.no_stdout and not any([args.csv_out, args.json_out, args.gpx_out]):
        parser.error(
            "--no-stdout requires at least one of --csv-out, --json-out, or --gpx-out."
        )

    try:
        activity = parse_activity_file(args.input_file)

        results_by_metric: dict[str, list] = {}
        for metric in METRIC_MAP[args.metrics]:
            results_by_metric[metric] = identify_top_intervals(
                activity=activity,
                duration_s=duration_s,
                max_overlap_ratio=args.max_overlap,
                count=args.count,
                analyzed_metric=metric,
                inner_interval_lengths_s=inner_lengths_s,
            )

        if not args.no_stdout:
            sys.stdout.write(render_text_report(results_by_metric, color=not args.bw))

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
            "metrics": args.metrics,
            "inner_interval_lengths_s": inner_lengths_s,
            "results": serialize_results(results_by_metric),
        }
        if args.json_out:
            write_json(args.json_out, payload)

        if args.gpx_out:
            write_gpx(args.gpx_out, activity, results_by_metric)

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
