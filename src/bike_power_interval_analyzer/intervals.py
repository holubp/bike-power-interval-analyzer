"""Interval search and statistics engine."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable

from .models import ActivityData, DataPoint, IntervalStats, IntervalWindow

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
) -> list[IntervalStats]:
    """Identify highest-average intervals for one metric.

    Args:
        activity: Parsed activity stream.
        duration_s: Fixed interval duration in seconds.
        max_overlap_ratio: Maximum overlap allowed between selected intervals.
        count: Maximum number of intervals to return.
        analyzed_metric: Either ``"power"`` or ``"heart_rate"``.
        inner_interval_lengths_s: Inner floating windows to compute.

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

    inner_lengths = sorted(float(x) for x in inner_interval_lengths_s)
    for item in inner_lengths:
        if item <= 0:
            raise ValueError(f"Inner interval lengths must be > 0, got {item}.")

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

    selected: list[IntervalWindow] = []
    max_overlap_s = max_overlap_ratio * duration_s
    for candidate in candidates:
        if all(
            _overlap_seconds(candidate, existing) <= max_overlap_s + EPSILON
            for existing in selected
        ):
            selected.append(candidate)
        if len(selected) >= count:
            break

    if not selected:
        raise RuntimeError("No intervals met the overlap constraint.")

    results: list[IntervalStats] = []
    for rank, window in enumerate(selected, start=1):
        results.append(
            _compute_interval_stats(
                prepared=prepared,
                rank=rank,
                analyzed_metric=window.score_metric,
                start_s=window.start_s,
                end_s=window.end_s,
                inner_interval_lengths_s=inner_lengths,
            )
        )
    return results


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
    times = prepared.times
    candidates: list[IntervalWindow] = []

    for start_s in times[:-1]:
        end_s = start_s + duration_s
        if end_s > prepared.duration_s + EPSILON:
            break
        average = _metric_average(prepared, analyzed_metric, start_s, end_s, require_full=True)
        if average is None:
            continue
        candidates.append(
            IntervalWindow(
                start_s=start_s,
                end_s=end_s,
                score_metric=analyzed_metric,
                score_average=average,
            )
        )

    candidates.sort(key=lambda c: (-c.score_average, c.start_s))
    return candidates


def _compute_interval_stats(
    prepared: _PreparedActivity,
    rank: int,
    analyzed_metric: str,
    start_s: float,
    end_s: float,
    inner_interval_lengths_s: list[float],
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
        length_m=length_m,
        average_power_w=average_power,
        maximum_power_w=max_power,
        average_heart_rate_bpm=average_hr,
        maximum_heart_rate_bpm=max_hr,
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
    n = len(points)
    right = bisect_left(times, t)

    if right < n and abs(times[right] - t) <= EPSILON:
        if points[right].distance_m is not None:
            return points[right].distance_m

    left = right - 1
    while left >= 0 and points[left].distance_m is None:
        left -= 1

    r = right
    while r < n and points[r].distance_m is None:
        r += 1

    if left < 0 or r >= n:
        return None

    x0 = times[left]
    x1 = times[r]
    y0 = points[left].distance_m
    y1 = points[r].distance_m
    if y0 is None or y1 is None:
        return None

    if abs(x1 - x0) <= EPSILON:
        return y0

    ratio = (t - x0) / (x1 - x0)
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


def _overlap_seconds(a: IntervalWindow, b: IntervalWindow) -> float:
    start = max(a.start_s, b.start_s)
    end = min(a.end_s, b.end_s)
    if end <= start:
        return 0.0
    return end - start
