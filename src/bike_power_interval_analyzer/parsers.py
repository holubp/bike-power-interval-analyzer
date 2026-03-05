"""Input parsers for TCX and FIT files."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .models import ActivityData, DataPoint


def parse_activity_file(path: str) -> ActivityData:
    """Parse TCX or FIT file into normalized activity data.

    Args:
        path: Path to `.tcx` or `.fit` file.

    Returns:
        Parsed activity data.

    Raises:
        ValueError: If the file extension is unsupported.
        FileNotFoundError: If the file does not exist.
        RuntimeError: If parser-specific errors occur.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Input file does not exist: {path}")
    if not file_path.is_file():
        raise ValueError(f"Input path is not a file: {path}")

    suffix = file_path.suffix.lower()
    if suffix == ".tcx":
        return parse_tcx(file_path)
    if suffix == ".fit":
        return parse_fit(file_path)
    raise ValueError(
        f"Unsupported input file extension '{suffix}'. Expected .tcx or .fit."
    )


def parse_tcx(path: Path) -> ActivityData:
    """Parse TCX trackpoints.

    Args:
        path: TCX file path.

    Returns:
        Activity data with normalized points.

    Raises:
        RuntimeError: If the XML is malformed or required fields are absent.
    """
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise RuntimeError(f"Failed to parse TCX XML from {path}: {exc}") from exc

    trackpoints = [e for e in root.iter() if _local_name(e.tag) == "Trackpoint"]
    if not trackpoints:
        raise RuntimeError(f"TCX file has no Trackpoint entries: {path}")

    raw_points: list[dict[str, Any]] = []
    for tp in trackpoints:
        timestamp_text = _find_descendant_text(tp, "Time")
        if not timestamp_text:
            continue
        timestamp = _parse_iso_datetime(timestamp_text)

        distance = _to_float(_find_descendant_text(tp, "DistanceMeters"))
        heart_rate = _to_float(_find_descendant_text(tp, "Value", parent_local_name="HeartRateBpm"))
        watts = _to_float(_find_descendant_text(tp, "Watts"))

        lat = _to_float(_find_descendant_text(tp, "LatitudeDegrees"))
        lon = _to_float(_find_descendant_text(tp, "LongitudeDegrees"))
        ele = _to_float(_find_descendant_text(tp, "AltitudeMeters"))

        raw_points.append(
            {
                "timestamp": timestamp,
                "distance_m": distance,
                "power_w": watts,
                "heart_rate_bpm": heart_rate,
                "latitude_deg": lat,
                "longitude_deg": lon,
                "elevation_m": ele,
            }
        )

    if len(raw_points) < 2:
        raise RuntimeError(
            f"TCX file requires at least 2 timed points, found {len(raw_points)} in {path}"
        )
    return _normalize_points(path.as_posix(), raw_points)


def parse_fit(path: Path) -> ActivityData:
    """Parse FIT record messages.

    Args:
        path: FIT file path.

    Returns:
        Activity data with normalized points.

    Raises:
        RuntimeError: If fitdecode is unavailable or data is invalid.
    """
    try:
        import fitdecode  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "FIT parsing requires the 'fitdecode' package. Install dependencies first."
        ) from exc

    raw_points: list[dict[str, Any]] = []
    try:
        with fitdecode.FitReader(path.as_posix()) as fit:
            for frame in fit:
                if not isinstance(frame, fitdecode.FitDataMessage):
                    continue
                if frame.name != "record":
                    continue
                fields = {f.name: f.value for f in frame.fields}
                timestamp = fields.get("timestamp")
                if timestamp is None:
                    continue
                if not isinstance(timestamp, datetime):
                    raise RuntimeError(
                        f"FIT record contains non-datetime timestamp in {path}: {timestamp!r}"
                    )

                lat = _semicircle_to_deg(fields.get("position_lat"))
                lon = _semicircle_to_deg(fields.get("position_long"))
                elevation = _to_float(fields.get("enhanced_altitude"))
                if elevation is None:
                    elevation = _to_float(fields.get("altitude"))

                raw_points.append(
                    {
                        "timestamp": timestamp,
                        "distance_m": _to_float(fields.get("distance")),
                        "power_w": _to_float(fields.get("power")),
                        "heart_rate_bpm": _to_float(fields.get("heart_rate")),
                        "latitude_deg": lat,
                        "longitude_deg": lon,
                        "elevation_m": elevation,
                    }
                )
    except Exception as exc:  # pragma: no cover - dependent on fitdecode behavior
        raise RuntimeError(f"Failed to parse FIT data from {path}: {exc}") from exc

    if len(raw_points) < 2:
        raise RuntimeError(
            f"FIT file requires at least 2 timed record points, found {len(raw_points)} in {path}"
        )
    return _normalize_points(path.as_posix(), raw_points)


def _normalize_points(source_path: str, raw_points: list[dict[str, Any]]) -> ActivityData:
    if len(raw_points) < 2:
        raise RuntimeError("At least two points are required for interval analysis.")
    raw_points.sort(key=lambda p: p["timestamp"])

    merged: list[dict[str, Any]] = []
    for row in raw_points:
        if merged and row["timestamp"] == merged[-1]["timestamp"]:
            merged[-1] = _merge_same_timestamp_points(merged[-1], row)
            continue
        if merged and row["timestamp"] < merged[-1]["timestamp"]:
            continue
        merged.append(row)

    if len(merged) < 2:
        raise RuntimeError(
            "Input data does not contain at least two unique timestamps after normalization."
        )

    start_time = merged[0]["timestamp"]
    points: list[DataPoint] = []
    prev_elapsed: float | None = None
    for row in merged:
        elapsed = (row["timestamp"] - start_time).total_seconds()
        if prev_elapsed is not None and elapsed <= prev_elapsed:
            raise RuntimeError(
                "Timestamps must be strictly increasing after normalization."
            )
        prev_elapsed = elapsed
        points.append(
            DataPoint(
                timestamp=row["timestamp"],
                elapsed_s=elapsed,
                distance_m=_to_float(row.get("distance_m")),
                power_w=_to_float(row.get("power_w")),
                heart_rate_bpm=_to_float(row.get("heart_rate_bpm")),
                latitude_deg=_to_float(row.get("latitude_deg")),
                longitude_deg=_to_float(row.get("longitude_deg")),
                elevation_m=_to_float(row.get("elevation_m")),
            )
        )

    # Ensure all points reference the canonical elapsed values from the sorted list.
    points = [replace(p, elapsed_s=(p.timestamp - start_time).total_seconds()) for p in points]

    return ActivityData(
        source_path=source_path,
        start_time=start_time,
        points=tuple(points),
    )


def _merge_same_timestamp_points(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        if key == "timestamp":
            continue
        if value is None:
            continue
        if key == "distance_m":
            current = merged.get(key)
            if current is None or value > current:
                merged[key] = value
            continue
        merged[key] = value
    return merged


def _parse_iso_datetime(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise RuntimeError(f"Invalid ISO timestamp '{value}'.") from exc


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _find_descendant_text(
    element: ET.Element,
    local_name: str,
    parent_local_name: str | None = None,
) -> str | None:
    if parent_local_name is None:
        for child in element.iter():
            if _local_name(child.tag) == local_name and child.text is not None:
                return child.text.strip()
        return None

    for parent in element.iter():
        if _local_name(parent.tag) != parent_local_name:
            continue
        for child in parent.iter():
            if _local_name(child.tag) == local_name and child.text is not None:
                return child.text.strip()
    return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise RuntimeError(f"Boolean value '{value}' is invalid for numeric field.")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid numeric value '{value}'.") from exc


def _semicircle_to_deg(value: Any) -> float | None:
    if value is None:
        return None
    return float(value) * (180.0 / 2147483648.0)
