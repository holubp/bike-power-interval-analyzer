from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from bike_power_interval_analyzer.intervals import (
    identify_top_intervals,
    identify_top_intervals_at_least_duration,
)
from bike_power_interval_analyzer.models import ActivityData, DataPoint


def _build_activity() -> ActivityData:
    start = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    points: list[DataPoint] = []

    distance = 0.0
    for elapsed in range(0, 121):
        if 20 <= elapsed < 40:
            power = 320.0
        else:
            power = 150.0

        if 60 <= elapsed < 90:
            hr = 182.0
        else:
            hr = 145.0

        points.append(
            DataPoint(
                timestamp=start + timedelta(seconds=elapsed),
                elapsed_s=float(elapsed),
                distance_m=distance,
                power_w=power,
                heart_rate_bpm=hr,
                latitude_deg=50.0 + elapsed * 1e-5,
                longitude_deg=14.0 + elapsed * 1e-5,
                elevation_m=200.0 + elapsed * 0.1,
            )
        )
        distance += 10.0

    return ActivityData(
        source_path="synthetic",
        start_time=start,
        points=tuple(points),
    )


def _build_coarse_activity() -> ActivityData:
    start = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    points = (
        DataPoint(
            timestamp=start + timedelta(seconds=0),
            elapsed_s=0.0,
            distance_m=0.0,
            power_w=100.0,
            heart_rate_bpm=130.0,
        ),
        DataPoint(
            timestamp=start + timedelta(seconds=10),
            elapsed_s=10.0,
            distance_m=100.0,
            power_w=300.0,
            heart_rate_bpm=160.0,
        ),
        DataPoint(
            timestamp=start + timedelta(seconds=20),
            elapsed_s=20.0,
            distance_m=200.0,
            power_w=50.0,
            heart_rate_bpm=120.0,
        ),
        DataPoint(
            timestamp=start + timedelta(seconds=30),
            elapsed_s=30.0,
            distance_m=300.0,
            power_w=50.0,
            heart_rate_bpm=120.0,
        ),
    )
    return ActivityData(
        source_path="synthetic-coarse",
        start_time=start,
        points=points,
    )


def test_identify_power_interval_without_overlap() -> None:
    activity = _build_activity()
    intervals = identify_top_intervals(
        activity=activity,
        duration_s=20.0,
        max_overlap_ratio=0.0,
        count=2,
        analyzed_metric="power",
        inner_interval_lengths_s=[10.0],
    )

    assert len(intervals) == 2
    first = intervals[0]
    assert first.start_s == pytest.approx(20.0)
    assert first.average_power_w == pytest.approx(320.0)
    assert first.maximum_power_w == pytest.approx(320.0)
    assert first.duration_s == pytest.approx(20.0)
    assert first.length_m == pytest.approx(200.0)
    assert first.inner_power_max_avg_w[10.0] == pytest.approx(320.0)

    second = intervals[1]
    assert second.end_s <= first.start_s or second.start_s >= first.end_s


def test_identify_hr_interval() -> None:
    activity = _build_activity()
    intervals = identify_top_intervals(
        activity=activity,
        duration_s=30.0,
        max_overlap_ratio=0.0,
        count=1,
        analyzed_metric="heart_rate",
        inner_interval_lengths_s=[10.0, 20.0],
    )

    assert len(intervals) == 1
    first = intervals[0]
    assert first.start_s == pytest.approx(60.0)
    assert first.average_heart_rate_bpm == pytest.approx(182.0)
    assert first.inner_heart_rate_max_avg_bpm[10.0] == pytest.approx(182.0)
    assert first.inner_heart_rate_max_avg_bpm[20.0] == pytest.approx(182.0)


def test_identify_power_interval_with_minimum_duration() -> None:
    activity = _build_activity()
    intervals = identify_top_intervals_at_least_duration(
        activity=activity,
        minimum_duration_s=10.0,
        max_overlap_ratio=0.0,
        count=1,
        analyzed_metric="power",
        inner_interval_lengths_s=[5.0],
    )

    assert len(intervals) == 1
    first = intervals[0]
    assert first.start_s == pytest.approx(20.0)
    assert first.end_s == pytest.approx(30.0)
    assert first.duration_s == pytest.approx(10.0)
    assert first.average_power_w == pytest.approx(320.0)
    assert first.inner_power_max_avg_w[5.0] == pytest.approx(320.0)


def test_identify_fixed_duration_interval_uses_continuous_start_times() -> None:
    activity = _build_coarse_activity()
    intervals = identify_top_intervals(
        activity=activity,
        duration_s=15.0,
        max_overlap_ratio=0.0,
        count=1,
        analyzed_metric="power",
        inner_interval_lengths_s=[5.0],
    )

    assert len(intervals) == 1
    first = intervals[0]
    assert first.start_s == pytest.approx(5.0)
    assert first.end_s == pytest.approx(20.0)
    assert first.duration_s == pytest.approx(15.0)
    assert first.average_power_w == pytest.approx((5.0 * 100.0 + 10.0 * 300.0) / 15.0)


def test_invalid_overlap_rejected() -> None:
    activity = _build_activity()
    with pytest.raises(ValueError):
        identify_top_intervals(
            activity=activity,
            duration_s=30.0,
            max_overlap_ratio=1.0,
            count=1,
            analyzed_metric="power",
            inner_interval_lengths_s=[10.0],
        )


def test_missing_metric_coverage_fails() -> None:
    activity = _build_activity()
    modified = list(activity.points)
    modified[10] = DataPoint(
        timestamp=modified[10].timestamp,
        elapsed_s=modified[10].elapsed_s,
        distance_m=modified[10].distance_m,
        power_w=None,
        heart_rate_bpm=modified[10].heart_rate_bpm,
        latitude_deg=modified[10].latitude_deg,
        longitude_deg=modified[10].longitude_deg,
        elevation_m=modified[10].elevation_m,
    )
    broken = ActivityData(
        source_path=activity.source_path,
        start_time=activity.start_time,
        points=tuple(modified),
    )

    with pytest.raises(RuntimeError):
        identify_top_intervals(
            activity=broken,
            duration_s=110.0,
            max_overlap_ratio=0.0,
            count=1,
            analyzed_metric="power",
            inner_interval_lengths_s=[10.0],
        )


def test_extended_stats_and_histograms() -> None:
    start = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    points: list[DataPoint] = []
    distance = 0.0
    elevation = 100.0
    for elapsed in range(0, 81):
        if elapsed < 40:
            elevation += 0.5
        else:
            elevation -= 0.25
        points.append(
            DataPoint(
                timestamp=start + timedelta(seconds=elapsed),
                elapsed_s=float(elapsed),
                distance_m=distance,
                power_w=120.0 + elapsed,
                heart_rate_bpm=130.0 + (elapsed % 15),
                latitude_deg=50.0,
                longitude_deg=14.0,
                elevation_m=elevation,
            )
        )
        distance += 8.0

    activity = ActivityData(
        source_path="synthetic-with-zones",
        start_time=start,
        points=tuple(points),
        heart_rate_zone_tabs_bpm=(135.0, 142.0),
        power_zone_tabs_w=(150.0, 180.0),
    )

    intervals = identify_top_intervals(
        activity=activity,
        duration_s=20.0,
        max_overlap_ratio=0.0,
        count=1,
        analyzed_metric="power",
        inner_interval_lengths_s=[],
        slope_window_m=30.0,
        hr_zone_tabs_bpm=[134.0, 141.0],
        power_zone_tabs_w=[145.0, 175.0],
        hr_hist_bins=4,
        power_hist_bins=3,
    )

    assert len(intervals) == 1
    first = intervals[0]
    assert first.relative_start_hms.count(":") == 2
    assert first.relative_end_hms.count(":") == 2
    assert first.ascent_m is not None
    assert first.descent_m is not None
    assert first.minimum_slope_pct is not None
    assert first.median_slope_pct is not None
    assert first.average_slope_pct is not None
    assert first.maximum_slope_pct is not None
    assert first.minimum_speed_kmh is not None
    assert first.median_speed_kmh is not None
    assert first.average_speed_kmh is not None
    assert first.maximum_speed_kmh is not None
    assert first.non_moving_time_s is not None
    assert first.minimum_power_w is not None
    assert first.median_power_w is not None
    assert first.minimum_heart_rate_bpm is not None
    assert first.median_heart_rate_bpm is not None
    assert first.heart_rate_hist_profile_zones
    assert first.heart_rate_hist_cmd_zones
    assert first.heart_rate_hist_bins
    assert first.power_hist_profile_zones
    assert first.power_hist_cmd_zones
    assert first.power_hist_bins
    assert sum(first.heart_rate_hist_cmd_zones.values()) == pytest.approx(first.duration_s)
    assert sum(first.power_hist_cmd_zones.values()) == pytest.approx(first.duration_s)


def test_duplicate_tabs_rejected() -> None:
    activity = _build_activity()
    with pytest.raises(ValueError):
        identify_top_intervals(
            activity=activity,
            duration_s=20.0,
            max_overlap_ratio=0.0,
            count=1,
            analyzed_metric="power",
            inner_interval_lengths_s=[10.0],
            hr_zone_tabs_bpm=[140.0, 140.0],
        )
