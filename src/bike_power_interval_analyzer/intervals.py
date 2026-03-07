"""Interval search and statistics engine."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import deque
from dataclasses import dataclass
from datetime import timedelta
import math
from typing import Iterable

from .models import ActivityData, DataPoint, IntervalStats, IntervalWindow, StoredInterval

EPSILON = 1e-9


@dataclass(frozen=True)
class _MetricSeries:
    values: tuple[float | None, ...]
    integral_prefix: tuple[float, ...]
    valid_duration_prefix: tuple[float, ...]


@dataclass(frozen=True)
class _PreparedActivity:
    activity: ActivityData
    times: tuple[float, ...]
    duration_s: float
    power: _MetricSeries
    heart_rate: _MetricSeries


def identify_top_intervals(
    activity: ActivityData,
    duration_s: float,
    max_overlap_ratio: float,
    count: int,
    analyzed_metric: str,
    inner_interval_lengths_s: Iterable[float],
    output_metric: str | None = None,
    slope_window_m: float = 30.0,
    hr_zone_tabs_bpm: Iterable[float] | None = None,
    power_zone_tabs_w: Iterable[float] | None = None,
    hr_hist_bins: int | None = None,
    power_hist_bins: int | None = None,
    non_moving_speed_threshold_kmh: float = 3.0,
    non_moving_perimeter_m: float = 20.0,
) -> list[IntervalStats]:
    """Identify highest-average intervals for one metric.

    Args:
        activity: Parsed activity stream.
        duration_s: Fixed interval duration in seconds.
        max_overlap_ratio: Maximum overlap allowed between selected intervals.
        count: Maximum number of intervals to return.
        analyzed_metric: Either ``"power"`` or ``"heart_rate"``.
        inner_interval_lengths_s: Inner floating windows to compute.
        output_metric: Label stored in the returned stats payload.
        slope_window_m: Floating distance window in meters for slope stats.
        hr_zone_tabs_bpm: Optional command-line HR zone tabs.
        power_zone_tabs_w: Optional command-line power zone tabs.
        hr_hist_bins: Optional command-line HR histogram bin count.
        power_hist_bins: Optional command-line power histogram bin count.
        non_moving_speed_threshold_kmh: Maximum speed considered stationary.
        non_moving_perimeter_m: Maximum location drift for stationary detection.

    Returns:
        Ranked interval statistics.

    Raises:
        ValueError: If arguments are invalid.
        RuntimeError: If no eligible intervals are found.
    """
    if duration_s <= 0:
        raise ValueError(f"duration_s must be > 0, got {duration_s}.")
    if not (0 <= max_overlap_ratio < 1):
        raise ValueError(
            f"max_overlap_ratio must be in [0, 1), got {max_overlap_ratio}."
        )
    if count <= 0:
        raise ValueError(f"count must be > 0, got {count}.")
    if analyzed_metric not in {"power", "heart_rate"}:
        raise ValueError(
            f"analyzed_metric must be 'power' or 'heart_rate', got '{analyzed_metric}'."
        )
    if slope_window_m <= 0:
        raise ValueError(f"slope_window_m must be > 0, got {slope_window_m}.")
    if non_moving_speed_threshold_kmh < 0:
        raise ValueError(
            "non_moving_speed_threshold_kmh must be >= 0, got "
            f"{non_moving_speed_threshold_kmh}."
        )
    if non_moving_perimeter_m <= 0:
        raise ValueError(
            f"non_moving_perimeter_m must be > 0, got {non_moving_perimeter_m}."
        )

    inner_lengths = sorted(float(x) for x in inner_interval_lengths_s)
    for item in inner_lengths:
        if item <= 0:
            raise ValueError(f"Inner interval lengths must be > 0, got {item}.")

    hr_tabs = _normalize_tabs(hr_zone_tabs_bpm, "hr_zone_tabs_bpm")
    power_tabs = _normalize_tabs(power_zone_tabs_w, "power_zone_tabs_w")

    if hr_hist_bins is not None and hr_hist_bins <= 0:
        raise ValueError(f"hr_hist_bins must be > 0 when provided, got {hr_hist_bins}.")
    if power_hist_bins is not None and power_hist_bins <= 0:
        raise ValueError(
            f"power_hist_bins must be > 0 when provided, got {power_hist_bins}."
        )

    prepared = _prepare_activity(activity)
    if duration_s > prepared.duration_s + EPSILON:
        raise RuntimeError(
            f"Requested duration {duration_s:.3f}s exceeds activity duration {prepared.duration_s:.3f}s."
        )

    candidates = _build_candidates(prepared, duration_s, analyzed_metric)
    if not candidates:
        raise RuntimeError(
            f"No valid intervals with full {analyzed_metric} coverage for duration {duration_s:.3f}s."
        )

    selected = _select_interval_windows(
        candidates=candidates,
        max_overlap_ratio=max_overlap_ratio,
        count=count,
        fixed_reference_duration_s=duration_s,
    )

    if not selected:
        raise RuntimeError("No intervals met the overlap constraint.")

    results: list[IntervalStats] = []
    for rank, window in enumerate(selected, start=1):
        results.append(
            _compute_interval_stats(
                prepared=prepared,
                rank=rank,
                analyzed_metric=output_metric or window.score_metric,
                start_s=window.start_s,
                end_s=window.end_s,
                inner_interval_lengths_s=inner_lengths,
                slope_window_m=slope_window_m,
                hr_zone_tabs_cmd=hr_tabs,
                power_zone_tabs_cmd=power_tabs,
                hr_hist_bins=hr_hist_bins,
                power_hist_bins=power_hist_bins,
                non_moving_speed_threshold_kmh=non_moving_speed_threshold_kmh,
                non_moving_perimeter_m=non_moving_perimeter_m,
            )
        )
    return results


def identify_top_intervals_at_least_duration(
    activity: ActivityData,
    minimum_duration_s: float,
    max_overlap_ratio: float,
    count: int,
    analyzed_metric: str,
    inner_interval_lengths_s: Iterable[float],
    output_metric: str | None = None,
    slope_window_m: float = 30.0,
    hr_zone_tabs_bpm: Iterable[float] | None = None,
    power_zone_tabs_w: Iterable[float] | None = None,
    hr_hist_bins: int | None = None,
    power_hist_bins: int | None = None,
    non_moving_speed_threshold_kmh: float = 3.0,
    non_moving_perimeter_m: float = 20.0,
) -> list[IntervalStats]:
    """Identify highest-average intervals with duration at least ``minimum_duration_s``."""
    if minimum_duration_s <= 0:
        raise ValueError(f"minimum_duration_s must be > 0, got {minimum_duration_s}.")
    if not (0 <= max_overlap_ratio < 1):
        raise ValueError(
            f"max_overlap_ratio must be in [0, 1), got {max_overlap_ratio}."
        )
    if count <= 0:
        raise ValueError(f"count must be > 0, got {count}.")
    if analyzed_metric not in {"power", "heart_rate"}:
        raise ValueError(
            f"analyzed_metric must be 'power' or 'heart_rate', got '{analyzed_metric}'."
        )
    if slope_window_m <= 0:
        raise ValueError(f"slope_window_m must be > 0, got {slope_window_m}.")
    if non_moving_speed_threshold_kmh < 0:
        raise ValueError(
            "non_moving_speed_threshold_kmh must be >= 0, got "
            f"{non_moving_speed_threshold_kmh}."
        )
    if non_moving_perimeter_m <= 0:
        raise ValueError(
            f"non_moving_perimeter_m must be > 0, got {non_moving_perimeter_m}."
        )

    inner_lengths = sorted(float(x) for x in inner_interval_lengths_s)
    for item in inner_lengths:
        if item <= 0:
            raise ValueError(f"Inner interval lengths must be > 0, got {item}.")

    hr_tabs = _normalize_tabs(hr_zone_tabs_bpm, "hr_zone_tabs_bpm")
    power_tabs = _normalize_tabs(power_zone_tabs_w, "power_zone_tabs_w")

    if hr_hist_bins is not None and hr_hist_bins <= 0:
        raise ValueError(f"hr_hist_bins must be > 0 when provided, got {hr_hist_bins}.")
    if power_hist_bins is not None and power_hist_bins <= 0:
        raise ValueError(
            f"power_hist_bins must be > 0 when provided, got {power_hist_bins}."
        )

    prepared = _prepare_activity(activity)
    if minimum_duration_s > prepared.duration_s + EPSILON:
        raise RuntimeError(
            "Requested minimum duration "
            f"{minimum_duration_s:.3f}s exceeds activity duration {prepared.duration_s:.3f}s."
        )

    candidates = _build_min_duration_candidates(
        prepared=prepared,
        minimum_duration_s=minimum_duration_s,
        analyzed_metric=analyzed_metric,
    )
    if not candidates:
        raise RuntimeError(
            "No valid intervals with full "
            f"{analyzed_metric} coverage for minimum duration {minimum_duration_s:.3f}s."
        )

    selected = _select_interval_windows(
        candidates=candidates,
        max_overlap_ratio=max_overlap_ratio,
        count=count,
        fixed_reference_duration_s=None,
    )
    if not selected:
        raise RuntimeError("No intervals met the overlap constraint.")

    results: list[IntervalStats] = []
    for rank, window in enumerate(selected, start=1):
        results.append(
            _compute_interval_stats(
                prepared=prepared,
                rank=rank,
                analyzed_metric=output_metric or window.score_metric,
                start_s=window.start_s,
                end_s=window.end_s,
                inner_interval_lengths_s=inner_lengths,
                slope_window_m=slope_window_m,
                hr_zone_tabs_cmd=hr_tabs,
                power_zone_tabs_cmd=power_tabs,
                hr_hist_bins=hr_hist_bins,
                power_hist_bins=power_hist_bins,
                non_moving_speed_threshold_kmh=non_moving_speed_threshold_kmh,
                non_moving_perimeter_m=non_moving_perimeter_m,
            )
        )
    return results


def analyze_stored_intervals(
    activity: ActivityData,
    interval_selectors: list[str] | None,
    inner_interval_lengths_s: Iterable[float],
    slope_window_m: float = 30.0,
    hr_zone_tabs_bpm: Iterable[float] | None = None,
    power_zone_tabs_w: Iterable[float] | None = None,
    hr_hist_bins: int | None = None,
    power_hist_bins: int | None = None,
    non_moving_speed_threshold_kmh: float = 3.0,
    non_moving_perimeter_m: float = 20.0,
) -> list[IntervalStats]:
    """Analyze intervals already stored in source file metadata.

    Args:
        activity: Parsed activity stream.
        interval_selectors: Optional list of selectors (label or 1-based index).
            ``None`` means all stored intervals.
        inner_interval_lengths_s: Inner floating windows to compute.
        slope_window_m: Floating distance window in meters for slope stats.
        hr_zone_tabs_bpm: Optional command-line HR zone tabs.
        power_zone_tabs_w: Optional command-line power zone tabs.
        hr_hist_bins: Optional command-line HR histogram bin count.
        power_hist_bins: Optional command-line power histogram bin count.
        non_moving_speed_threshold_kmh: Maximum speed considered stationary.
        non_moving_perimeter_m: Maximum location drift for stationary detection.
    """
    if slope_window_m <= 0:
        raise ValueError(f"slope_window_m must be > 0, got {slope_window_m}.")
    if non_moving_speed_threshold_kmh < 0:
        raise ValueError(
            "non_moving_speed_threshold_kmh must be >= 0, got "
            f"{non_moving_speed_threshold_kmh}."
        )
    if non_moving_perimeter_m <= 0:
        raise ValueError(
            f"non_moving_perimeter_m must be > 0, got {non_moving_perimeter_m}."
        )

    inner_lengths = sorted(float(x) for x in inner_interval_lengths_s)
    for item in inner_lengths:
        if item <= 0:
            raise ValueError(f"Inner interval lengths must be > 0, got {item}.")

    hr_tabs = _normalize_tabs(hr_zone_tabs_bpm, "hr_zone_tabs_bpm")
    power_tabs = _normalize_tabs(power_zone_tabs_w, "power_zone_tabs_w")

    if hr_hist_bins is not None and hr_hist_bins <= 0:
        raise ValueError(f"hr_hist_bins must be > 0 when provided, got {hr_hist_bins}.")
    if power_hist_bins is not None and power_hist_bins <= 0:
        raise ValueError(
            f"power_hist_bins must be > 0 when provided, got {power_hist_bins}."
        )

    prepared = _prepare_activity(activity)
    if not activity.stored_intervals:
        raise RuntimeError("No intervals/laps were found in the input file.")

    intervals: list[StoredInterval] = _select_stored_intervals(
        stored_intervals=list(activity.stored_intervals),
        selectors=interval_selectors,
    )
    results: list[IntervalStats] = []
    for rank, interval in enumerate(intervals, start=1):
        results.append(
            _compute_interval_stats(
                prepared=prepared,
                rank=rank,
                analyzed_metric="interval",
                start_s=interval.start_s,
                end_s=interval.end_s,
                inner_interval_lengths_s=inner_lengths,
                slope_window_m=slope_window_m,
                hr_zone_tabs_cmd=hr_tabs,
                power_zone_tabs_cmd=power_tabs,
                hr_hist_bins=hr_hist_bins,
                power_hist_bins=power_hist_bins,
                non_moving_speed_threshold_kmh=non_moving_speed_threshold_kmh,
                non_moving_perimeter_m=non_moving_perimeter_m,
            )
        )
    return results


def _select_stored_intervals(
    stored_intervals: list[StoredInterval],
    selectors: list[str] | None,
) -> list[StoredInterval]:
    if selectors is None:
        return list(stored_intervals)

    selected: list[StoredInterval] = []
    seen_ids: set[tuple[float, float, str]] = set()
    for selector in selectors:
        if selector.isdigit():
            index = int(selector)
            if index <= 0:
                raise ValueError(
                    f"Interval selector index must be >= 1, got {selector}."
                )
            if index > len(stored_intervals):
                raise ValueError(
                    f"Interval selector index {selector} exceeds available intervals "
                    f"({len(stored_intervals)})."
                )
            interval = stored_intervals[index - 1]
            key = (interval.start_s, interval.end_s, interval.label)
            if key not in seen_ids:
                selected.append(interval)
                seen_ids.add(key)
            continue

        matches = [interval for interval in stored_intervals if interval.label == selector]
        if not matches:
            raise ValueError(
                f"Interval selector '{selector}' does not match any interval label."
            )
        for interval in matches:
            key = (interval.start_s, interval.end_s, interval.label)
            if key not in seen_ids:
                selected.append(interval)
                seen_ids.add(key)

    return selected


def _prepare_activity(activity: ActivityData) -> _PreparedActivity:
    points = activity.points
    if len(points) < 2:
        raise RuntimeError("Activity must contain at least two points.")

    times = tuple(p.elapsed_s for p in points)
    if times[0] != 0:
        raise RuntimeError(
            f"Expected first elapsed value to be 0, got {times[0]:.6f}."
        )

    for i in range(len(times) - 1):
        if not times[i + 1] > times[i]:
            raise RuntimeError(
                "Elapsed times must be strictly increasing for interval analysis."
            )

    return _PreparedActivity(
        activity=activity,
        times=times,
        duration_s=times[-1],
        power=_build_metric_series(points, "power"),
        heart_rate=_build_metric_series(points, "heart_rate"),
    )


def _build_metric_series(points: tuple[DataPoint, ...], metric: str) -> _MetricSeries:
    if metric == "power":
        raw = [p.power_w for p in points]
    elif metric == "heart_rate":
        raw = [p.heart_rate_bpm for p in points]
    else:  # pragma: no cover - protected by callers
        raise RuntimeError(f"Unsupported metric: {metric}")

    values = tuple(raw[:-1])
    integral_prefix = [0.0]
    valid_duration_prefix = [0.0]

    for i, value in enumerate(values):
        dt = points[i + 1].elapsed_s - points[i].elapsed_s
        if dt <= 0:
            raise RuntimeError(
                f"Non-positive dt found at segment {i}: {dt}. Input timestamps invalid."
            )
        if value is None:
            integral_prefix.append(integral_prefix[-1])
            valid_duration_prefix.append(valid_duration_prefix[-1])
        else:
            integral_prefix.append(integral_prefix[-1] + value * dt)
            valid_duration_prefix.append(valid_duration_prefix[-1] + dt)

    return _MetricSeries(
        values=values,
        integral_prefix=tuple(integral_prefix),
        valid_duration_prefix=tuple(valid_duration_prefix),
    )


def _build_candidates(
    prepared: _PreparedActivity,
    duration_s: float,
    analyzed_metric: str,
) -> list[IntervalWindow]:
    if analyzed_metric == "power":
        series = prepared.power
    elif analyzed_metric == "heart_rate":
        series = prepared.heart_rate
    else:  # pragma: no cover - protected by caller
        raise RuntimeError(f"Unsupported metric: {analyzed_metric}")

    unique: dict[tuple[float, float], IntervalWindow] = {}
    for value_start, value_end_exclusive in _valid_metric_segments(series.values):
        boundary_start = value_start
        boundary_end = value_end_exclusive
        segment_boundary_times = list(prepared.times[boundary_start : boundary_end + 1])
        segment_start_s = segment_boundary_times[0]
        segment_end_s = segment_boundary_times[-1]
        latest_start_s = segment_end_s - duration_s
        if latest_start_s < segment_start_s - EPSILON:
            continue

        for start_s in _fixed_duration_candidate_starts(
            segment_boundary_times=segment_boundary_times,
            duration_s=duration_s,
        ):
            end_s = start_s + duration_s
            average = _metric_average(
                prepared, analyzed_metric, start_s, end_s, require_full=True
            )
            if average is None:
                continue
            unique[(start_s, end_s)] = IntervalWindow(
                start_s=start_s,
                end_s=end_s,
                score_metric=analyzed_metric,
                score_average=average,
            )

    candidates = list(unique.values())
    candidates.sort(key=lambda c: (-c.score_average, c.start_s))
    return candidates


def _fixed_duration_candidate_starts(
    segment_boundary_times: list[float],
    duration_s: float,
) -> list[float]:
    """Return all boundary breakpoints where the exact fixed-window optimum can occur."""
    if len(segment_boundary_times) < 2:
        return []

    segment_start_s = segment_boundary_times[0]
    latest_start_s = segment_boundary_times[-1] - duration_s
    if latest_start_s < segment_start_s - EPSILON:
        return []

    candidate_starts = [segment_start_s, latest_start_s]
    for boundary_time in segment_boundary_times:
        candidate_starts.append(boundary_time)
        candidate_starts.append(boundary_time - duration_s)

    candidate_starts.sort()

    unique: list[float] = []
    for start_s in candidate_starts:
        if start_s < segment_start_s - EPSILON or start_s > latest_start_s + EPSILON:
            continue
        clamped = min(max(start_s, segment_start_s), latest_start_s)
        if unique and abs(unique[-1] - clamped) <= EPSILON:
            continue
        unique.append(clamped)

    return unique


def _build_min_duration_candidates(
    prepared: _PreparedActivity,
    minimum_duration_s: float,
    analyzed_metric: str,
) -> list[IntervalWindow]:
    if analyzed_metric == "power":
        series = prepared.power
    elif analyzed_metric == "heart_rate":
        series = prepared.heart_rate
    else:  # pragma: no cover - protected by caller
        raise RuntimeError(f"Unsupported metric: {analyzed_metric}")

    unique: dict[tuple[float, float], IntervalWindow] = {}
    for value_start, value_end_exclusive in _valid_metric_segments(series.values):
        boundary_start = value_start
        boundary_end = value_end_exclusive
        segment_start_s = prepared.times[boundary_start]
        segment_end_s = prepared.times[boundary_end]
        if segment_end_s - segment_start_s < minimum_duration_s - EPSILON:
            continue

        time_slice = [
            prepared.times[i] for i in range(boundary_start, boundary_end + 1)
        ]
        prefix_slice = [
            series.integral_prefix[i] - series.integral_prefix[boundary_start]
            for i in range(boundary_start, boundary_end + 1)
        ]

        for candidate in _best_candidates_for_boundaries(
            time_slice,
            prefix_slice,
            minimum_duration_s,
            analyzed_metric,
        ):
            unique[(candidate.start_s, candidate.end_s)] = candidate

        reversed_origin_s = time_slice[-1]
        reversed_times = [reversed_origin_s - t for t in reversed(time_slice)]
        reversed_prefix = [prefix_slice[-1] - p for p in reversed(prefix_slice)]
        for candidate in _best_candidates_for_boundaries(
            reversed_times,
            reversed_prefix,
            minimum_duration_s,
            analyzed_metric,
        ):
            mapped = IntervalWindow(
                start_s=reversed_origin_s - candidate.end_s,
                end_s=reversed_origin_s - candidate.start_s,
                score_metric=candidate.score_metric,
                score_average=candidate.score_average,
            )
            unique[(mapped.start_s, mapped.end_s)] = mapped

    candidates = list(unique.values())
    candidates.sort(key=lambda c: (-c.score_average, c.end_s - c.start_s, c.start_s))
    return candidates


def _best_candidates_for_boundaries(
    boundary_times: list[float],
    boundary_prefix: list[float],
    minimum_duration_s: float,
    analyzed_metric: str,
) -> list[IntervalWindow]:
    """Return one best candidate per end boundary using a lower-hull scan."""
    if len(boundary_times) != len(boundary_prefix):
        raise RuntimeError("Boundary time/prefix arrays must have equal length.")
    if len(boundary_times) < 2:
        return []

    hull: deque[int] = deque()
    eligible_start = 0
    candidates: list[IntervalWindow] = []

    for end_idx in range(1, len(boundary_times)):
        threshold = boundary_times[end_idx] - minimum_duration_s
        while eligible_start < end_idx and boundary_times[eligible_start] <= threshold + EPSILON:
            _append_hull_index(hull, boundary_times, boundary_prefix, eligible_start)
            eligible_start += 1

        if not hull:
            continue

        while len(hull) >= 2 and _window_average_from_prefix(
            boundary_times, boundary_prefix, hull[0], end_idx
        ) <= _window_average_from_prefix(
            boundary_times, boundary_prefix, hull[1], end_idx
        ) + EPSILON:
            hull.popleft()

        start_idx = hull[0]
        if boundary_times[end_idx] - boundary_times[start_idx] < minimum_duration_s - EPSILON:
            continue
        average = _window_average_from_prefix(
            boundary_times, boundary_prefix, start_idx, end_idx
        )
        candidates.append(
            IntervalWindow(
                start_s=boundary_times[start_idx],
                end_s=boundary_times[end_idx],
                score_metric=analyzed_metric,
                score_average=average,
            )
        )

    return candidates


def _append_hull_index(
    hull: deque[int],
    boundary_times: list[float],
    boundary_prefix: list[float],
    new_idx: int,
) -> None:
    while len(hull) >= 2 and _slope_between_prefix_points(
        boundary_times, boundary_prefix, hull[-2], hull[-1]
    ) >= _slope_between_prefix_points(
        boundary_times, boundary_prefix, hull[-1], new_idx
    ) - EPSILON:
        hull.pop()
    hull.append(new_idx)


def _slope_between_prefix_points(
    boundary_times: list[float],
    boundary_prefix: list[float],
    left_idx: int,
    right_idx: int,
) -> float:
    duration = boundary_times[right_idx] - boundary_times[left_idx]
    if duration <= EPSILON:
        raise RuntimeError("Boundary duration must be positive for slope calculation.")
    return (boundary_prefix[right_idx] - boundary_prefix[left_idx]) / duration


def _window_average_from_prefix(
    boundary_times: list[float],
    boundary_prefix: list[float],
    start_idx: int,
    end_idx: int,
) -> float:
    return _slope_between_prefix_points(
        boundary_times, boundary_prefix, start_idx, end_idx
    )


def _valid_metric_segments(
    values: tuple[float | None, ...],
) -> list[tuple[int, int]]:
    """Return contiguous valid-value segments as boundary-index pairs."""
    segments: list[tuple[int, int]] = []
    start_idx: int | None = None
    for idx, value in enumerate(values):
        if value is not None:
            if start_idx is None:
                start_idx = idx
            continue
        if start_idx is not None:
            segments.append((start_idx, idx))
            start_idx = None
    if start_idx is not None:
        segments.append((start_idx, len(values)))
    return segments


def _select_interval_windows(
    candidates: list[IntervalWindow],
    max_overlap_ratio: float,
    count: int,
    fixed_reference_duration_s: float | None,
) -> list[IntervalWindow]:
    selected: list[IntervalWindow] = []
    for candidate in candidates:
        if all(
            _overlap_seconds(candidate, existing)
            <= _allowed_overlap_seconds(
                candidate, existing, max_overlap_ratio, fixed_reference_duration_s
            )
            + EPSILON
            for existing in selected
        ):
            selected.append(candidate)
        if len(selected) >= count:
            break
    return selected


def _allowed_overlap_seconds(
    candidate: IntervalWindow,
    existing: IntervalWindow,
    max_overlap_ratio: float,
    fixed_reference_duration_s: float | None,
) -> float:
    if fixed_reference_duration_s is not None:
        return max_overlap_ratio * fixed_reference_duration_s

    candidate_duration = candidate.end_s - candidate.start_s
    existing_duration = existing.end_s - existing.start_s
    return max_overlap_ratio * min(candidate_duration, existing_duration)


def _compute_interval_stats(
    prepared: _PreparedActivity,
    rank: int,
    analyzed_metric: str,
    start_s: float,
    end_s: float,
    inner_interval_lengths_s: list[float],
    slope_window_m: float,
    hr_zone_tabs_cmd: tuple[float, ...] | None,
    power_zone_tabs_cmd: tuple[float, ...] | None,
    hr_hist_bins: int | None,
    power_hist_bins: int | None,
    non_moving_speed_threshold_kmh: float,
    non_moving_perimeter_m: float,
) -> IntervalStats:
    activity = prepared.activity
    duration = end_s - start_s
    if duration <= 0:
        raise RuntimeError(
            f"Computed non-positive interval duration ({duration}) for rank {rank}."
        )

    average_power = _metric_average(prepared, "power", start_s, end_s, require_full=True)
    average_hr = _metric_average(prepared, "heart_rate", start_s, end_s, require_full=True)

    max_power = _metric_max(prepared, "power", start_s, end_s)
    max_hr = _metric_max(prepared, "heart_rate", start_s, end_s)

    length_m = _distance_length(prepared, start_s, end_s)

    power_samples = _metric_samples(prepared, "power", start_s, end_s)
    hr_samples = _metric_samples(prepared, "heart_rate", start_s, end_s)
    speed_samples = _speed_samples(prepared, start_s, end_s)

    min_power, med_power, _, _ = _weighted_summary(power_samples)
    min_hr, med_hr, _, _ = _weighted_summary(hr_samples)
    min_speed, med_speed, avg_speed, max_speed = _weighted_summary(speed_samples)

    interval_profile = _interval_distance_elevation_profile(prepared, start_s, end_s)
    ascent_m, descent_m = _ascent_descent(interval_profile)
    min_slope, med_slope, avg_slope, max_slope = _slope_summary(
        interval_profile,
        slope_window_m,
    )
    non_moving_time_s = _non_moving_elapsed_time(
        prepared=prepared,
        start_s=start_s,
        end_s=end_s,
        speed_threshold_kmh=non_moving_speed_threshold_kmh,
        perimeter_m=non_moving_perimeter_m,
    )

    inner_power: dict[float, float | None] = {}
    inner_hr: dict[float, float | None] = {}
    for inner in inner_interval_lengths_s:
        if inner > duration + EPSILON:
            inner_power[inner] = None
            inner_hr[inner] = None
            continue
        inner_power[inner] = _max_floating_average(
            prepared, "power", start_s, end_s, inner
        )
        inner_hr[inner] = _max_floating_average(
            prepared, "heart_rate", start_s, end_s, inner
        )

    hr_hist_profile = _histogram_by_tabs(hr_samples, activity.heart_rate_zone_tabs_bpm)
    hr_hist_cmd = _histogram_by_tabs(hr_samples, hr_zone_tabs_cmd)
    hr_hist_by_bins = _histogram_by_bin_count(hr_samples, hr_hist_bins)

    power_hist_profile = _histogram_by_tabs(power_samples, activity.power_zone_tabs_w)
    power_hist_cmd = _histogram_by_tabs(power_samples, power_zone_tabs_cmd)
    power_hist_by_bins = _histogram_by_bin_count(power_samples, power_hist_bins)

    start_time = activity.start_time + timedelta(seconds=start_s)
    end_time = activity.start_time + timedelta(seconds=end_s)

    return IntervalStats(
        rank=rank,
        analyzed_metric=analyzed_metric,
        start_s=start_s,
        end_s=end_s,
        start_time=start_time,
        end_time=end_time,
        duration_s=duration,
        relative_start_hms=_format_elapsed_hms(start_s),
        relative_end_hms=_format_elapsed_hms(end_s),
        length_m=length_m,
        ascent_m=ascent_m,
        descent_m=descent_m,
        slope_window_m=slope_window_m,
        minimum_slope_pct=min_slope,
        median_slope_pct=med_slope,
        average_slope_pct=avg_slope,
        maximum_slope_pct=max_slope,
        minimum_speed_kmh=min_speed,
        median_speed_kmh=med_speed,
        average_speed_kmh=avg_speed,
        maximum_speed_kmh=max_speed,
        non_moving_time_s=non_moving_time_s,
        non_moving_speed_threshold_kmh=non_moving_speed_threshold_kmh,
        non_moving_perimeter_m=non_moving_perimeter_m,
        minimum_power_w=min_power,
        median_power_w=med_power,
        average_power_w=average_power,
        maximum_power_w=max_power,
        minimum_heart_rate_bpm=min_hr,
        median_heart_rate_bpm=med_hr,
        average_heart_rate_bpm=average_hr,
        maximum_heart_rate_bpm=max_hr,
        heart_rate_hist_profile_zones=hr_hist_profile,
        heart_rate_hist_cmd_zones=hr_hist_cmd,
        heart_rate_hist_bins=hr_hist_by_bins,
        power_hist_profile_zones=power_hist_profile,
        power_hist_cmd_zones=power_hist_cmd,
        power_hist_bins=power_hist_by_bins,
        inner_power_max_avg_w=inner_power,
        inner_heart_rate_max_avg_bpm=inner_hr,
    )


def _metric_average(
    prepared: _PreparedActivity,
    metric: str,
    start_s: float,
    end_s: float,
    require_full: bool,
) -> float | None:
    if end_s <= start_s:
        return None

    integral, valid_duration = _metric_integral_and_valid_duration(
        prepared, metric, start_s, end_s
    )
    duration = end_s - start_s

    if require_full and valid_duration + EPSILON < duration:
        return None
    if valid_duration <= EPSILON:
        return None

    denominator = duration if require_full else valid_duration
    return integral / denominator


def _metric_integral_and_valid_duration(
    prepared: _PreparedActivity,
    metric: str,
    start_s: float,
    end_s: float,
) -> tuple[float, float]:
    if not (0 <= start_s <= end_s <= prepared.duration_s + EPSILON):
        raise RuntimeError(
            f"Window [{start_s}, {end_s}] is outside activity bounds [0, {prepared.duration_s}]."
        )

    if metric == "power":
        series = prepared.power
    elif metric == "heart_rate":
        series = prepared.heart_rate
    else:  # pragma: no cover
        raise RuntimeError(f"Unsupported metric: {metric}")

    return _integrate_piecewise(
        times=prepared.times,
        values=series.values,
        integral_prefix=series.integral_prefix,
        valid_prefix=series.valid_duration_prefix,
        start_s=start_s,
        end_s=end_s,
    )


def _integrate_piecewise(
    times: tuple[float, ...],
    values: tuple[float | None, ...],
    integral_prefix: tuple[float, ...],
    valid_prefix: tuple[float, ...],
    start_s: float,
    end_s: float,
) -> tuple[float, float]:
    if end_s <= start_s:
        return 0.0, 0.0

    n = len(times)
    if n < 2:
        raise RuntimeError("At least two timestamps are required for integration.")

    i_start = _segment_index_for_time(times, start_s)
    i_end = _segment_index_for_time(times, end_s)

    if i_start == i_end:
        return _partial_contribution(values, i_start, end_s - start_s)

    first_duration = times[i_start + 1] - start_s
    first_integral, first_valid = _partial_contribution(values, i_start, first_duration)

    middle_integral = 0.0
    middle_valid = 0.0
    if i_start + 1 <= i_end - 1:
        middle_integral = integral_prefix[i_end] - integral_prefix[i_start + 1]
        middle_valid = valid_prefix[i_end] - valid_prefix[i_start + 1]

    last_duration = end_s - times[i_end]
    last_integral, last_valid = _partial_contribution(values, i_end, last_duration)

    return (
        first_integral + middle_integral + last_integral,
        first_valid + middle_valid + last_valid,
    )


def _segment_index_for_time(times: tuple[float, ...], t: float) -> int:
    if t <= times[0]:
        return 0
    if t >= times[-1]:
        return len(times) - 2
    idx = bisect_right(times, t) - 1
    if idx < 0:
        return 0
    if idx >= len(times) - 1:
        return len(times) - 2
    return idx


def _partial_contribution(
    values: tuple[float | None, ...],
    idx: int,
    duration: float,
) -> tuple[float, float]:
    if duration <= 0:
        return 0.0, 0.0
    value = values[idx]
    if value is None:
        return 0.0, 0.0
    return value * duration, duration


def _metric_max(
    prepared: _PreparedActivity,
    metric: str,
    start_s: float,
    end_s: float,
) -> float | None:
    if metric == "power":
        values = prepared.power.values
    elif metric == "heart_rate":
        values = prepared.heart_rate.values
    else:  # pragma: no cover
        raise RuntimeError(f"Unsupported metric: {metric}")

    times = prepared.times
    n_seg = len(times) - 1
    i = _segment_index_for_time(times, start_s)
    max_value: float | None = None

    while i < n_seg and times[i] < end_s - EPSILON:
        overlap_start = max(start_s, times[i])
        overlap_end = min(end_s, times[i + 1])
        if overlap_end > overlap_start + EPSILON:
            value = values[i]
            if value is not None:
                if max_value is None or value > max_value:
                    max_value = value
        i += 1
    return max_value


def _metric_samples(
    prepared: _PreparedActivity,
    metric: str,
    start_s: float,
    end_s: float,
) -> list[tuple[float, float]]:
    if metric == "power":
        values = prepared.power.values
    elif metric == "heart_rate":
        values = prepared.heart_rate.values
    else:  # pragma: no cover
        raise RuntimeError(f"Unsupported metric: {metric}")

    times = prepared.times
    n_seg = len(times) - 1
    i = _segment_index_for_time(times, start_s)
    samples: list[tuple[float, float]] = []

    while i < n_seg and times[i] < end_s - EPSILON:
        overlap_start = max(start_s, times[i])
        overlap_end = min(end_s, times[i + 1])
        duration = overlap_end - overlap_start
        if duration > EPSILON and values[i] is not None:
            samples.append((values[i], duration))
        i += 1

    return samples


def _speed_samples(
    prepared: _PreparedActivity,
    start_s: float,
    end_s: float,
) -> list[tuple[float, float]]:
    """Compute speed samples (km/h, duration) from distance derivatives."""
    times = prepared.times
    points = prepared.activity.points
    n_seg = len(times) - 1
    i = _segment_index_for_time(times, start_s)
    samples: list[tuple[float, float]] = []

    while i < n_seg and times[i] < end_s - EPSILON:
        overlap_start = max(start_s, times[i])
        overlap_end = min(end_s, times[i + 1])
        duration = overlap_end - overlap_start
        if duration <= EPSILON:
            i += 1
            continue

        d0 = _distance_at(points, times, overlap_start)
        d1 = _distance_at(points, times, overlap_end)
        if d0 is None or d1 is None:
            i += 1
            continue

        delta_m = d1 - d0
        if delta_m < -EPSILON:
            i += 1
            continue

        speed_kmh = (delta_m / duration) * 3.6
        samples.append((speed_kmh, duration))
        i += 1

    return samples


def _non_moving_elapsed_time(
    prepared: _PreparedActivity,
    start_s: float,
    end_s: float,
    speed_threshold_kmh: float,
    perimeter_m: float,
) -> float | None:
    """Estimate non-moving time using low speed and bounded-position drift."""
    times = prepared.times
    points = prepared.activity.points
    n_seg = len(times) - 1
    i = _segment_index_for_time(times, start_s)
    anchor_position: tuple[float, float] | None = None
    stationary_time_s = 0.0
    had_position_data = False

    while i < n_seg and times[i] < end_s - EPSILON:
        overlap_start = max(start_s, times[i])
        overlap_end = min(end_s, times[i + 1])
        duration = overlap_end - overlap_start
        if duration <= EPSILON:
            i += 1
            continue

        d0 = _distance_at(points, times, overlap_start)
        d1 = _distance_at(points, times, overlap_end)
        if d0 is None or d1 is None:
            anchor_position = None
            i += 1
            continue

        delta_m = d1 - d0
        if delta_m < -EPSILON:
            anchor_position = None
            i += 1
            continue

        speed_kmh = (delta_m / duration) * 3.6
        p0 = _position_at(points, times, overlap_start)
        p1 = _position_at(points, times, overlap_end)
        if p0 is None or p1 is None:
            anchor_position = None
            i += 1
            continue
        had_position_data = True

        if speed_kmh > speed_threshold_kmh + EPSILON:
            anchor_position = None
            i += 1
            continue

        if anchor_position is None:
            anchor_position = p0

        if (
            _haversine_m(anchor_position, p0) <= perimeter_m + EPSILON
            and _haversine_m(anchor_position, p1) <= perimeter_m + EPSILON
        ):
            stationary_time_s += duration
        else:
            anchor_position = p0
            if _haversine_m(anchor_position, p1) <= perimeter_m + EPSILON:
                stationary_time_s += duration

        i += 1

    if not had_position_data:
        return None
    return stationary_time_s


def _weighted_summary(
    samples: list[tuple[float, float]],
) -> tuple[float | None, float | None, float | None, float | None]:
    if not samples:
        return None, None, None, None

    values = [value for value, _ in samples]
    minimum = min(values)
    maximum = max(values)

    total_weight = sum(weight for _, weight in samples)
    if total_weight <= EPSILON:
        return None, None, None, None

    average = sum(value * weight for value, weight in samples) / total_weight

    sorted_samples = sorted(samples, key=lambda item: item[0])
    half = total_weight / 2.0
    cumulative = 0.0
    median = sorted_samples[-1][0]
    for value, weight in sorted_samples:
        cumulative += weight
        if cumulative + EPSILON >= half:
            median = value
            break

    return minimum, median, average, maximum


def _distance_length(prepared: _PreparedActivity, start_s: float, end_s: float) -> float | None:
    start_distance = _distance_at(prepared.activity.points, prepared.times, start_s)
    end_distance = _distance_at(prepared.activity.points, prepared.times, end_s)
    if start_distance is None or end_distance is None:
        return None
    delta = end_distance - start_distance
    if delta < -EPSILON:
        return None
    return max(0.0, delta)


def _distance_at(
    points: tuple[DataPoint, ...],
    times: tuple[float, ...],
    t: float,
) -> float | None:
    return _value_at_time(points, times, t, attr_name="distance_m")


def _elevation_at(
    points: tuple[DataPoint, ...],
    times: tuple[float, ...],
    t: float,
) -> float | None:
    return _value_at_time(points, times, t, attr_name="elevation_m")


def _position_at(
    points: tuple[DataPoint, ...],
    times: tuple[float, ...],
    t: float,
) -> tuple[float, float] | None:
    lat = _value_at_time(points, times, t, attr_name="latitude_deg")
    lon = _value_at_time(points, times, t, attr_name="longitude_deg")
    if lat is None or lon is None:
        return None
    return lat, lon


def _value_at_time(
    points: tuple[DataPoint, ...],
    times: tuple[float, ...],
    t: float,
    attr_name: str,
) -> float | None:
    n = len(points)
    right = bisect_left(times, t)

    if right < n and abs(times[right] - t) <= EPSILON:
        value = getattr(points[right], attr_name)
        if value is not None:
            return value

    left = right - 1
    while left >= 0 and getattr(points[left], attr_name) is None:
        left -= 1

    r = right
    while r < n and getattr(points[r], attr_name) is None:
        r += 1

    if left < 0 or r >= n:
        return None

    x0 = times[left]
    x1 = times[r]
    y0 = getattr(points[left], attr_name)
    y1 = getattr(points[r], attr_name)
    if y0 is None or y1 is None:
        return None

    if abs(x1 - x0) <= EPSILON:
        return y0

    ratio = (t - x0) / (x1 - x0)
    return y0 + ratio * (y1 - y0)


def _interval_distance_elevation_profile(
    prepared: _PreparedActivity,
    start_s: float,
    end_s: float,
) -> list[tuple[float, float]]:
    points = prepared.activity.points
    rows: list[tuple[float, float, float]] = []

    start_dist = _distance_at(points, prepared.times, start_s)
    start_ele = _elevation_at(points, prepared.times, start_s)
    if start_dist is not None and start_ele is not None:
        rows.append((start_s, start_dist, start_ele))

    for point in points:
        if start_s + EPSILON < point.elapsed_s < end_s - EPSILON:
            if point.distance_m is not None and point.elevation_m is not None:
                rows.append((point.elapsed_s, point.distance_m, point.elevation_m))

    end_dist = _distance_at(points, prepared.times, end_s)
    end_ele = _elevation_at(points, prepared.times, end_s)
    if end_dist is not None and end_ele is not None:
        rows.append((end_s, end_dist, end_ele))

    if len(rows) < 2:
        return []

    rows.sort(key=lambda item: item[0])
    profile: list[tuple[float, float]] = []
    for _, distance, elevation in rows:
        if profile and distance <= profile[-1][0] + EPSILON:
            continue
        profile.append((distance, elevation))
    return profile


def _ascent_descent(profile: list[tuple[float, float]]) -> tuple[float | None, float | None]:
    if len(profile) < 2:
        return None, None

    ascent = 0.0
    descent = 0.0
    for i in range(len(profile) - 1):
        delta = profile[i + 1][1] - profile[i][1]
        if delta > 0:
            ascent += delta
        elif delta < 0:
            descent += -delta
    return ascent, descent


def _slope_summary(
    profile: list[tuple[float, float]],
    slope_window_m: float,
) -> tuple[float | None, float | None, float | None, float | None]:
    if len(profile) < 2:
        return None, None, None, None

    start_dist = profile[0][0]
    end_dist = profile[-1][0]
    if end_dist - start_dist < slope_window_m - EPSILON:
        return None, None, None, None

    last_start = end_dist - slope_window_m
    starts = {start_dist, last_start}
    for distance, _ in profile:
        if start_dist + EPSILON < distance < last_start - EPSILON:
            starts.add(distance)

    slopes: list[float] = []
    for d0 in sorted(starts):
        d1 = d0 + slope_window_m
        if d1 > end_dist + EPSILON:
            continue
        e0 = _elevation_at_distance(profile, d0)
        e1 = _elevation_at_distance(profile, d1)
        if e0 is None or e1 is None:
            continue
        slopes.append(((e1 - e0) / slope_window_m) * 100.0)

    if not slopes:
        return None, None, None, None

    sorted_slopes = sorted(slopes)
    minimum = sorted_slopes[0]
    maximum = sorted_slopes[-1]
    average = sum(slopes) / len(slopes)
    median = sorted_slopes[len(sorted_slopes) // 2]
    if len(sorted_slopes) % 2 == 0:
        mid = len(sorted_slopes) // 2
        median = (sorted_slopes[mid - 1] + sorted_slopes[mid]) / 2.0

    return minimum, median, average, maximum


def _elevation_at_distance(
    profile: list[tuple[float, float]],
    distance: float,
) -> float | None:
    distances = [item[0] for item in profile]
    idx = bisect_left(distances, distance)
    if idx < len(profile) and abs(profile[idx][0] - distance) <= EPSILON:
        return profile[idx][1]

    left = idx - 1
    right = idx
    if left < 0 or right >= len(profile):
        return None

    x0, y0 = profile[left]
    x1, y1 = profile[right]
    if x1 - x0 <= EPSILON:
        return None

    ratio = (distance - x0) / (x1 - x0)
    return y0 + ratio * (y1 - y0)


def _max_floating_average(
    prepared: _PreparedActivity,
    metric: str,
    interval_start_s: float,
    interval_end_s: float,
    floating_window_s: float,
) -> float | None:
    if floating_window_s <= 0:
        raise RuntimeError(f"floating_window_s must be > 0, got {floating_window_s}.")

    latest_start = interval_end_s - floating_window_s
    if latest_start < interval_start_s - EPSILON:
        return None

    starts = {interval_start_s, latest_start}
    for t in prepared.times:
        if interval_start_s + EPSILON < t < latest_start - EPSILON:
            starts.add(t)

    best: float | None = None
    for start in sorted(starts):
        end = start + floating_window_s
        avg = _metric_average(prepared, metric, start, end, require_full=True)
        if avg is None:
            continue
        if best is None or avg > best:
            best = avg
    return best


def _histogram_by_tabs(
    samples: list[tuple[float, float]],
    tabs: tuple[float, ...] | None,
) -> dict[str, float]:
    if not samples or not tabs:
        return {}

    labels = _labels_for_tabs(tabs)
    counts = {label: 0.0 for label in labels}
    for value, weight in samples:
        idx = bisect_right(tabs, value)
        label = labels[idx]
        counts[label] += weight
    return counts


def _labels_for_tabs(tabs: tuple[float, ...]) -> list[str]:
    labels: list[str] = []
    labels.append(f"<{tabs[0]:g}")
    for i in range(len(tabs) - 1):
        labels.append(f"[{tabs[i]:g},{tabs[i + 1]:g})")
    labels.append(f">={tabs[-1]:g}")
    return labels


def _histogram_by_bin_count(
    samples: list[tuple[float, float]],
    bin_count: int | None,
) -> dict[str, float]:
    if not samples or bin_count is None:
        return {}
    if bin_count <= 0:
        raise RuntimeError(f"bin_count must be > 0, got {bin_count}.")

    values = [v for v, _ in samples]
    minimum = min(values)
    maximum = max(values)
    total_duration = sum(weight for _, weight in samples)

    if abs(maximum - minimum) <= EPSILON:
        return {f"[{minimum:g},{maximum:g}]": total_duration}

    width = (maximum - minimum) / bin_count
    if width <= EPSILON:
        return {f"[{minimum:g},{maximum:g}]": total_duration}

    counts = [0.0 for _ in range(bin_count)]
    for value, weight in samples:
        idx = int((value - minimum) / width)
        if idx >= bin_count:
            idx = bin_count - 1
        counts[idx] += weight

    payload: dict[str, float] = {}
    for i in range(bin_count):
        low = minimum + i * width
        high = minimum + (i + 1) * width
        if i == bin_count - 1:
            label = f"[{low:g},{high:g}]"
        else:
            label = f"[{low:g},{high:g})"
        payload[label] = counts[i]
    return payload


def _normalize_tabs(
    raw_tabs: Iterable[float] | None,
    name: str,
) -> tuple[float, ...] | None:
    if raw_tabs is None:
        return None

    tabs = sorted(float(x) for x in raw_tabs)
    if not tabs:
        return None

    for tab in tabs:
        if tab <= 0:
            raise ValueError(f"{name} must contain positive thresholds, got {tab}.")

    unique_tabs: list[float] = []
    for tab in tabs:
        if unique_tabs and abs(tab - unique_tabs[-1]) <= EPSILON:
            continue
        if unique_tabs and tab < unique_tabs[-1]:
            raise ValueError(f"{name} must be sorted increasingly.")
        unique_tabs.append(tab)

    if len(unique_tabs) != len(tabs):
        raise ValueError(f"{name} contains duplicate thresholds.")
    return tuple(unique_tabs)


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in meters for two latitude/longitude points."""
    lat1_rad = math.radians(a[0])
    lon1_rad = math.radians(a[1])
    lat2_rad = math.radians(b[0])
    lon2_rad = math.radians(b[1])

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    sin_dlat = math.sin(dlat / 2.0)
    sin_dlon = math.sin(dlon / 2.0)
    h = sin_dlat * sin_dlat + math.cos(lat1_rad) * math.cos(lat2_rad) * sin_dlon * sin_dlon
    c = 2.0 * math.asin(min(1.0, math.sqrt(h)))
    return 6_371_000.0 * c


def _format_elapsed_hms(seconds: float) -> str:
    total_ms = int(round(seconds * 1000.0))
    hours = total_ms // 3_600_000
    rem = total_ms % 3_600_000
    minutes = rem // 60_000
    rem = rem % 60_000
    sec = rem / 1000.0
    return f"{hours:02d}:{minutes:02d}:{sec:06.3f}"


def _overlap_seconds(a: IntervalWindow, b: IntervalWindow) -> float:
    start = max(a.start_s, b.start_s)
    end = min(a.end_s, b.end_s)
    if end <= start:
        return 0.0
    return end - start
