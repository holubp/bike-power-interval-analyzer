from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import zipfile

import pytest

from bike_power_interval_analyzer import parsers
from bike_power_interval_analyzer.models import ActivityData, DataPoint


def _dummy_activity(source_path: str) -> ActivityData:
    start = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    points = (
        DataPoint(
            timestamp=start,
            elapsed_s=0.0,
            distance_m=0.0,
            power_w=100.0,
            heart_rate_bpm=130.0,
            latitude_deg=50.0,
            longitude_deg=14.0,
            elevation_m=200.0,
        ),
        DataPoint(
            timestamp=start + timedelta(seconds=1),
            elapsed_s=1.0,
            distance_m=5.0,
            power_w=120.0,
            heart_rate_bpm=132.0,
            latitude_deg=50.00001,
            longitude_deg=14.00001,
            elevation_m=200.1,
        ),
    )
    return ActivityData(source_path=source_path, start_time=start, points=points)


def test_parse_activity_file_zip_routes_to_fit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    zip_path = tmp_path / "sample.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("folder/220_ACTIVITY.fit", b"fit-bytes")

    seen: dict[str, object] = {}

    def fake_parse_fit(path: Path) -> ActivityData:
        seen["name"] = path.name
        seen["bytes"] = path.read_bytes()
        return _dummy_activity(source_path="from-fit")

    monkeypatch.setattr(parsers, "parse_fit", fake_parse_fit)

    parsed = parsers.parse_activity_file(zip_path.as_posix())
    assert parsed.source_path.endswith("::folder/220_ACTIVITY.fit")
    assert seen["name"] == "220_ACTIVITY.fit"
    assert seen["bytes"] == b"fit-bytes"


def test_parse_activity_file_zip_prefers_activity_fit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    zip_path = tmp_path / "sample.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("a.fit", b"a")
        archive.writestr("b_ACTIVITY.fit", b"b")

    def fake_parse_fit(path: Path) -> ActivityData:
        return _dummy_activity(source_path=path.name)

    monkeypatch.setattr(parsers, "parse_fit", fake_parse_fit)

    parsed = parsers.parse_activity_file(zip_path.as_posix())
    assert parsed.source_path.endswith("::b_ACTIVITY.fit")


def test_parse_activity_file_zip_ambiguous_fit_entries_raise(tmp_path: Path) -> None:
    zip_path = tmp_path / "sample.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("a.fit", b"a")
        archive.writestr("b.fit", b"b")

    with pytest.raises(RuntimeError, match="multiple FIT entries"):
        parsers.parse_activity_file(zip_path.as_posix())


def test_parse_activity_file_zip_without_fit_raises(tmp_path: Path) -> None:
    zip_path = tmp_path / "sample.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("README.txt", b"none")

    with pytest.raises(RuntimeError, match="contains no .fit"):
        parsers.parse_activity_file(zip_path.as_posix())
