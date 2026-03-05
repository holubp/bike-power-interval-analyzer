from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from bike_power_interval_analyzer.intervals import identify_top_intervals
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
                elevation_m=200.0,
            )
        )
        distance += 10.0

    return ActivityData(
        source_path="synthetic",
        start_time=start,
        points=tuple(points),
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
