"""Output renderers for text, CSV, JSON, and GPX."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Mapping
from xml.etree import ElementTree as ET

from .models import ActivityData, IntervalStats


def render_text_report(
    results_by_metric: Mapping[str, list[IntervalStats]],
    color: bool,
    absolute_timezone: str = "local",
) -> str:
    """Render a human-readable report for stdout."""
    lines: list[str] = []

    preferred_order = (
        "power",
        "power-max",
        "hr",
        "hr-max",
        "interval",
        "heart_rate",
        "heart_rate_max",
    )
    metric_order = [metric for metric in preferred_order if metric in results_by_metric]
    metric_order.extend(
        metric for metric in results_by_metric.keys() if metric not in metric_order
    )

    for metric in metric_order:
        intervals = results_by_metric.get(metric)
        if not intervals:
            continue

        if metric == "power":
            title = "Power-based intervals"
        elif metric == "power-max":
            title = "Power max-average intervals"
        elif metric in {"hr", "heart_rate"}:
            title = "Heart-rate-based intervals"
        elif metric in {"hr-max", "heart_rate_max"}:
            title = "Heart-rate max-average intervals"
        else:
            title = "File-stored intervals"
        lines.append(_section_title(title, color))

        for stat in intervals:
            header = (
                f"#{stat.rank} abs={fmt_hms_ms(stat.start_time, absolute_timezone)}-"
                f"{fmt_hms_ms(stat.end_time, absolute_timezone)} "
                f"rel={stat.relative_start_hms}-{stat.relative_end_hms} "
                f"| dur={stat.duration_s:.3f}s ({_format_duration_hms(stat.duration_s)}) "
                f"| len={fmt_optional(stat.length_m, 'm', color)}"
            )
            slope_summary = _format_summary_fields(
                stat.minimum_slope_pct,
                stat.median_slope_pct,
                stat.average_slope_pct,
                stat.maximum_slope_pct,
                "%",
                color,
            )
            speed_summary = _format_summary_fields(
                stat.minimum_speed_kmh,
                stat.median_speed_kmh,
                stat.average_speed_kmh,
                stat.maximum_speed_kmh,
                "km/h",
                color,
            )
            power_summary = _format_summary_fields(
                stat.minimum_power_w,
                stat.median_power_w,
                stat.average_power_w,
                stat.maximum_power_w,
                "W",
                color,
            )
            hr_summary = _format_summary_fields(
                stat.minimum_heart_rate_bpm,
                stat.median_heart_rate_bpm,
                stat.average_heart_rate_bpm,
                stat.maximum_heart_rate_bpm,
                "bpm",
                color,
            )
            lines.append(_interval_header(header, color))
            lines.append(
                (
                    f"  {_label('ascent', color)}={fmt_optional(stat.ascent_m, 'm', color)} "
                    f"{_label('descent', color)}={fmt_optional(stat.descent_m, 'm', color)} "
                    f"{_label(f'slope[{stat.slope_window_m:g}m]', color)}={slope_summary}"
                )
            )
            lines.append(
                (
                    f"  {_label('speed', color)}={speed_summary}"
                )
            )
            lines.append(
                (
                    f"  {_label('non_moving', color)}={fmt_optional(stat.non_moving_time_s, 's', color)} "
                    f"{_label(f'(speed<={stat.non_moving_speed_threshold_kmh:g}km/h, perimeter<={stat.non_moving_perimeter_m:g}m)', color)}"
                )
            )
            lines.append(
                (
                    f"  {_label('power', color)}={power_summary}"
                )
            )
            lines.append(
                (
                    f"  {_label('hr', color)}={hr_summary}"
                )
            )

            _append_histogram_block(
                lines, "heart-rate profile zones", stat.heart_rate_hist_profile_zones, color
            )
            _append_histogram_block(
                lines, "heart-rate custom zones", stat.heart_rate_hist_cmd_zones, color
            )
            _append_histogram_block(lines, "heart-rate bins", stat.heart_rate_hist_bins, color)
            _append_histogram_block(
                lines, "power profile zones", stat.power_hist_profile_zones, color
            )
            _append_histogram_block(
                lines, "power custom zones", stat.power_hist_cmd_zones, color
            )
            _append_histogram_block(lines, "power bins", stat.power_hist_bins, color)

            if stat.inner_power_max_avg_w or stat.inner_heart_rate_max_avg_bpm:
                lines.append(f"  {_label('inner windows', color)}:")
                keys = sorted(
                    set(stat.inner_power_max_avg_w.keys())
                    | set(stat.inner_heart_rate_max_avg_bpm.keys())
                )
                for inner in keys:
                    lines.append(
                        (
                            f"    {_style(f'{inner:.3f}s', '37', color)} -> "
                            f"power={fmt_optional(stat.inner_power_max_avg_w.get(inner), 'W', color)} "
                            f"hr={fmt_optional(stat.inner_heart_rate_max_avg_bpm.get(inner), 'bpm', color)}"
                        )
                    )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_csv(path: str, rows: list[dict[str, object]]) -> None:
    """Write interval rows to CSV."""
    if not rows:
        raise ValueError("Cannot write CSV with zero rows.")

    fieldnames: list[str] = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: str, payload: object) -> None:
    """Write JSON output."""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")


def serialize_results(
    results_by_metric: Mapping[str, list[IntervalStats]],
) -> dict[str, list[dict[str, object]]]:
    """Convert dataclass stats to JSON-serializable dictionaries."""
    payload: dict[str, list[dict[str, object]]] = {}
    for metric, stats in results_by_metric.items():
        payload[metric] = [interval_to_dict(stat) for stat in stats]
    return payload


def flatten_results_for_csv(
    results_by_metric: Mapping[str, list[IntervalStats]],
) -> list[dict[str, object]]:
    """Flatten interval stats into row dictionaries for CSV output."""
    rows: list[dict[str, object]] = []
    for metric, stats in results_by_metric.items():
        for stat in stats:
            row = interval_to_dict(stat)
            row = {key: _scalarize_csv_value(value) for key, value in row.items()}
            row["analysis_metric"] = metric
            rows.append(row)
    return rows


def interval_to_dict(stat: IntervalStats) -> dict[str, object]:
    """Convert one interval stats object to a dictionary."""
    payload: dict[str, object] = {
        "rank": stat.rank,
        "analyzed_metric": stat.analyzed_metric,
        "start_time": stat.start_time.isoformat(),
        "end_time": stat.end_time.isoformat(),
        "start_relative_hms": stat.relative_start_hms,
        "end_relative_hms": stat.relative_end_hms,
        "start_elapsed_s": stat.start_s,
        "end_elapsed_s": stat.end_s,
        "duration_s": stat.duration_s,
        "length_m": stat.length_m,
        "ascent_m": stat.ascent_m,
        "descent_m": stat.descent_m,
        "slope_window_m": stat.slope_window_m,
        "minimum_slope_pct": stat.minimum_slope_pct,
        "median_slope_pct": stat.median_slope_pct,
        "average_slope_pct": stat.average_slope_pct,
        "maximum_slope_pct": stat.maximum_slope_pct,
        "minimum_speed_kmh": stat.minimum_speed_kmh,
        "median_speed_kmh": stat.median_speed_kmh,
        "average_speed_kmh": stat.average_speed_kmh,
        "maximum_speed_kmh": stat.maximum_speed_kmh,
        "non_moving_time_s": stat.non_moving_time_s,
        "non_moving_speed_threshold_kmh": stat.non_moving_speed_threshold_kmh,
        "non_moving_perimeter_m": stat.non_moving_perimeter_m,
        "minimum_power_w": stat.minimum_power_w,
        "median_power_w": stat.median_power_w,
        "average_power_w": stat.average_power_w,
        "maximum_power_w": stat.maximum_power_w,
        "minimum_heart_rate_bpm": stat.minimum_heart_rate_bpm,
        "median_heart_rate_bpm": stat.median_heart_rate_bpm,
        "average_heart_rate_bpm": stat.average_heart_rate_bpm,
        "maximum_heart_rate_bpm": stat.maximum_heart_rate_bpm,
        "heart_rate_hist_profile_zones": dict(stat.heart_rate_hist_profile_zones),
        "heart_rate_hist_cmd_zones": dict(stat.heart_rate_hist_cmd_zones),
        "heart_rate_hist_bins": dict(stat.heart_rate_hist_bins),
        "power_hist_profile_zones": dict(stat.power_hist_profile_zones),
        "power_hist_cmd_zones": dict(stat.power_hist_cmd_zones),
        "power_hist_bins": dict(stat.power_hist_bins),
    }

    for inner, value in sorted(stat.inner_power_max_avg_w.items()):
        payload[f"inner_power_max_avg_{inner:g}s"] = value
    for inner, value in sorted(stat.inner_heart_rate_max_avg_bpm.items()):
        payload[f"inner_heart_rate_max_avg_{inner:g}s"] = value

    return payload


def write_gpx(
    path: str,
    activity: ActivityData,
    results_by_metric: Mapping[str, list[IntervalStats]],
) -> None:
    """Write identified intervals as GPX tracks."""
    root = ET.Element(
        "gpx",
        attrib={
            "version": "1.1",
            "creator": "bike-power-interval-analyzer",
            "xmlns": "http://www.topografix.com/GPX/1/1",
        },
    )

    interval_count = 0
    for metric, stats in results_by_metric.items():
        for stat in stats:
            trackpoints = [
                p
                for p in activity.points
                if stat.start_s - 1e-9 <= p.elapsed_s <= stat.end_s + 1e-9
                and p.latitude_deg is not None
                and p.longitude_deg is not None
            ]
            if not trackpoints:
                continue

            trk = ET.SubElement(root, "trk")
            name = ET.SubElement(trk, "name")
            name.text = f"{metric}-interval-{stat.rank}"
            trkseg = ET.SubElement(trk, "trkseg")

            for point in trackpoints:
                trkpt = ET.SubElement(
                    trkseg,
                    "trkpt",
                    attrib={
                        "lat": f"{point.latitude_deg:.8f}",
                        "lon": f"{point.longitude_deg:.8f}",
                    },
                )
                if point.elevation_m is not None:
                    ele = ET.SubElement(trkpt, "ele")
                    ele.text = f"{point.elevation_m:.2f}"
                time = ET.SubElement(trkpt, "time")
                time.text = point.timestamp.isoformat()

            interval_count += 1

    if interval_count == 0:
        raise RuntimeError(
            "No intervals contained GPS coordinates; GPX output would be empty."
        )

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    tree.write(out_path, encoding="utf-8", xml_declaration=True)


def fmt_hms_ms(value: datetime, absolute_timezone: str = "local") -> str:
    """Format datetime as HH:MM:SS.sss."""
    if absolute_timezone == "utc":
        dt = value.astimezone(timezone.utc) if value.tzinfo else value
    elif absolute_timezone == "file":
        dt = value
    elif absolute_timezone == "local":
        dt = value.astimezone() if value.tzinfo else value
    else:
        raise RuntimeError(
            "absolute_timezone must be one of: local, utc, file; "
            f"got '{absolute_timezone}'."
        )
    return dt.strftime("%H:%M:%S.%f")[:-3]


def _format_duration_hms(duration_s: float) -> str:
    """Format duration as HH:MM:SS using truncated whole seconds."""
    whole_seconds = int(duration_s)
    hours, remainder = divmod(whole_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def fmt_optional(value: float | None, unit: str, color: bool = False) -> str:
    """Format optional numeric values for text report."""
    if value is None:
        return _style("n/a", "37", color)
    return f"{value:.2f}{_unit(unit, color)}"


def _format_summary_fields(
    minimum: float | None,
    median: float | None,
    average: float | None,
    maximum: float | None,
    unit: str,
    color: bool,
) -> str:
    """Format min/avg/med/max fields with middle values ordered by value."""
    middle_items = [("med", median), ("avg", average)]
    middle_items.sort(
        key=lambda item: (float("inf") if item[1] is None else item[1], item[0])
    )

    ordered_items = [("min", minimum), *middle_items, ("max", maximum)]
    return " ".join(
        f"{_stat_key(f'{label}:', color)}{fmt_optional(value, unit, color)}"
        for label, value in ordered_items
    )


def _append_histogram_block(
    lines: list[str],
    title: str,
    histogram: Mapping[str, float],
    color: bool,
) -> None:
    if not histogram:
        return
    lines.append(f"  {_label(title, color)}:")
    for key, value in histogram.items():
        lines.append(f"    {_style(key, '37', color)} -> {value:.2f}{_unit('s', color)}")


def _scalarize_csv_value(value: object) -> object:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True)
    return value


def _style(text: str, ansi_code: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"\x1b[{ansi_code}m{text}\x1b[0m"


def _section_title(text: str, color: bool) -> str:
    return _style(text, "1;97", color)


def _interval_header(text: str, color: bool) -> str:
    return _style(text, "36", color)


def _label(text: str, color: bool) -> str:
    return _style(text, "38;5;250", color)


def _stat_key(text: str, color: bool) -> str:
    return _style(text, "38;5;250", color)


def _unit(text: str, color: bool) -> str:
    return _style(text, "38;5;250", color)
