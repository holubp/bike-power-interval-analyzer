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
    length_m: float | None
    average_power_w: float | None
    maximum_power_w: float | None
    average_heart_rate_bpm: float | None
    maximum_heart_rate_bpm: float | None
    inner_power_max_avg_w: Mapping[float, float | None] = field(default_factory=dict)
    inner_heart_rate_max_avg_bpm: Mapping[float, float | None] = field(default_factory=dict)
