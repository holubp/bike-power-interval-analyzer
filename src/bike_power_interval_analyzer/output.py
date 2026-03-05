"""Output renderers for text, CSV, JSON, and GPX."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Mapping
from xml.etree import ElementTree as ET

from .models import ActivityData, IntervalStats


def render_text_report(
    results_by_metric: Mapping[str, list[IntervalStats]],
    color: bool,
) -> str:
    """Render a human-readable report for stdout."""
    lines: list[str] = []

    for metric in ("power", "heart_rate"):
        intervals = results_by_metric.get(metric)
        if not intervals:
            continue

        title = (
            "Power-based intervals"
            if metric == "power"
            else "Heart-rate-based intervals"
        )
        lines.append(_style(title, "1;36", color))

        for stat in intervals:
            lines.append(
                (
                    f"#{stat.rank} {fmt_hms_ms(stat.start_time)} - {fmt_hms_ms(stat.end_time)} "
                    f"| dur={stat.duration_s:.3f}s | len={fmt_optional(stat.length_m, 'm')}"
                )
            )
            lines.append(
                (
                    f"  avg_power={fmt_optional(stat.average_power_w, 'W')} "
                    f"max_power={fmt_optional(stat.maximum_power_w, 'W')} "
                    f"avg_hr={fmt_optional(stat.average_heart_rate_bpm, 'bpm')} "
                    f"max_hr={fmt_optional(stat.maximum_heart_rate_bpm, 'bpm')}"
                )
            )
            if stat.inner_power_max_avg_w or stat.inner_heart_rate_max_avg_bpm:
                lines.append("  inner windows:")
                keys = sorted(
                    set(stat.inner_power_max_avg_w.keys())
                    | set(stat.inner_heart_rate_max_avg_bpm.keys())
                )
                for inner in keys:
                    lines.append(
                        (
                            f"    {inner:.3f}s -> "
                            f"power={fmt_optional(stat.inner_power_max_avg_w.get(inner), 'W')} "
                            f"hr={fmt_optional(stat.inner_heart_rate_max_avg_bpm.get(inner), 'bpm')}"
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
            row = dict(row)
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
        "start_elapsed_s": stat.start_s,
        "end_elapsed_s": stat.end_s,
        "duration_s": stat.duration_s,
        "length_m": stat.length_m,
        "average_power_w": stat.average_power_w,
        "maximum_power_w": stat.maximum_power_w,
        "average_heart_rate_bpm": stat.average_heart_rate_bpm,
        "maximum_heart_rate_bpm": stat.maximum_heart_rate_bpm,
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


def fmt_hms_ms(value) -> str:
    """Format datetime as HH:MM:SS.sss."""
    return value.strftime("%H:%M:%S.%f")[:-3]


def fmt_optional(value: float | None, unit: str) -> str:
    """Format optional numeric values for text report."""
    if value is None:
        return "n/a"
    return f"{value:.2f}{unit}"


def _style(text: str, ansi_code: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"\x1b[{ansi_code}m{text}\x1b[0m"
