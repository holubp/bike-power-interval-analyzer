from __future__ import annotations

import math

import pytest

from bike_power_interval_analyzer.duration import (
    parse_duration_to_seconds,
    parse_inner_interval_lengths,
)


def test_parse_duration_supported_formats() -> None:
    assert parse_duration_to_seconds("30") == 30
    assert parse_duration_to_seconds("12.5") == 12.5
    assert parse_duration_to_seconds("02:30") == 150
    assert parse_duration_to_seconds("01:02:03") == 3723


def test_parse_duration_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        parse_duration_to_seconds("")
    with pytest.raises(ValueError):
        parse_duration_to_seconds("0")
    with pytest.raises(ValueError):
        parse_duration_to_seconds("1:99")
    with pytest.raises(ValueError):
        parse_duration_to_seconds("aa:bb")


def test_parse_inner_lengths_defaults_and_empty() -> None:
    assert parse_inner_interval_lengths(None) == [10.0]
    assert parse_inner_interval_lengths([]) == []
    assert parse_inner_interval_lengths(["5", "00:20"]) == [5.0, 20.0]


def test_parse_inner_lengths_reject_empty_string() -> None:
    with pytest.raises(ValueError):
        parse_inner_interval_lengths([""])


def test_hypothesis_round_trip_seconds() -> None:
    hypothesis = pytest.importorskip("hypothesis")
    st = hypothesis.strategies
    given = hypothesis.given

    @given(st.floats(min_value=0.001, max_value=100000, allow_nan=False, allow_infinity=False))
    def run_case(seconds: float) -> None:
        raw = f"{seconds:.6f}"
        parsed = parse_duration_to_seconds(raw)
        assert math.isclose(parsed, float(raw), rel_tol=0, abs_tol=1e-9)

    run_case()
