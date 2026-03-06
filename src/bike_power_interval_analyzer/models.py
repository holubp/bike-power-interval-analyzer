"""Core data models for interval analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping


@dataclass(frozen=True)
class DataPoint:
    """Single activity point sampled from TCX or FIT input."""

    timestamp: datetime
    elapsed_s: float
    distance_m: float | None
    power_w: float | None
    heart_rate_bpm: float | None
    latitude_deg: float | None = None
    longitude_deg: float | None = None
    elevation_m: float | None = None


@dataclass(frozen=True)
class ActivityData:
    """Activity stream with monotonically increasing elapsed seconds."""

    source_path: str
    start_time: datetime
    points: tuple[DataPoint, ...]
    heart_rate_zone_tabs_bpm: tuple[float, ...] | None = None
    power_zone_tabs_w: tuple[float, ...] | None = None


@dataclass(frozen=True)
class IntervalWindow:
    """Candidate or selected interval window."""

    start_s: float
    end_s: float
    score_metric: str
    score_average: float


@dataclass(frozen=True)
class IntervalStats:
    """Computed statistics for a selected interval."""

    rank: int
    analyzed_metric: str
    start_s: float
    end_s: float
    start_time: datetime
    end_time: datetime
    duration_s: float
    relative_start_hms: str
    relative_end_hms: str
    length_m: float | None
    ascent_m: float | None
    descent_m: float | None
    slope_window_m: float
    minimum_slope_pct: float | None
    median_slope_pct: float | None
    average_slope_pct: float | None
    maximum_slope_pct: float | None
    minimum_speed_kmh: float | None
    median_speed_kmh: float | None
    average_speed_kmh: float | None
    maximum_speed_kmh: float | None
    non_moving_time_s: float | None
    non_moving_speed_threshold_kmh: float
    non_moving_perimeter_m: float
    minimum_power_w: float | None
    median_power_w: float | None
    average_power_w: float | None
    maximum_power_w: float | None
    minimum_heart_rate_bpm: float | None
    median_heart_rate_bpm: float | None
    average_heart_rate_bpm: float | None
    maximum_heart_rate_bpm: float | None
    heart_rate_hist_profile_zones: Mapping[str, float] = field(default_factory=dict)
    heart_rate_hist_cmd_zones: Mapping[str, float] = field(default_factory=dict)
    heart_rate_hist_bins: Mapping[str, float] = field(default_factory=dict)
    power_hist_profile_zones: Mapping[str, float] = field(default_factory=dict)
    power_hist_cmd_zones: Mapping[str, float] = field(default_factory=dict)
    power_hist_bins: Mapping[str, float] = field(default_factory=dict)
    inner_power_max_avg_w: Mapping[float, float | None] = field(default_factory=dict)
    inner_heart_rate_max_avg_bpm: Mapping[float, float | None] = field(default_factory=dict)
