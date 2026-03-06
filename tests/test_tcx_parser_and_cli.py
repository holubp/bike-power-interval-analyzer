from __future__ import annotations

import json
from pathlib import Path

import pytest

from bike_power_interval_analyzer.cli import main
from bike_power_interval_analyzer.parsers import parse_tcx


def _write_tcx(path: Path) -> None:
    points = []
    for i in range(0, 41):
        power = 320 if 10 <= i < 25 else 180
        hr = 170 if 15 <= i < 30 else 140
        points.append(
            f"""
            <Trackpoint>
              <Time>2025-01-01T12:00:{i:02d}Z</Time>
              <Position>
                <LatitudeDegrees>{50.100000 + i * 0.0001:.6f}</LatitudeDegrees>
                <LongitudeDegrees>{14.100000 + i * 0.0001:.6f}</LongitudeDegrees>
              </Position>
              <AltitudeMeters>{220 + i * 0.1:.1f}</AltitudeMeters>
              <DistanceMeters>{i * 9.5:.2f}</DistanceMeters>
              <HeartRateBpm><Value>{hr}</Value></HeartRateBpm>
              <Extensions>
                <TPX xmlns=\"http://www.garmin.com/xmlschemas/ActivityExtension/v2\">
                  <Watts>{power}</Watts>
                </TPX>
              </Extensions>
            </Trackpoint>
            """
        )

    tcx = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<TrainingCenterDatabase xmlns=\"http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2\">
  <Activities>
    <Activity Sport=\"Biking\">
      <Id>2025-01-01T12:00:00Z</Id>
      <Lap StartTime=\"2025-01-01T12:00:00Z\">
        <Track>
          {''.join(points)}
        </Track>
      </Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>
"""
    path.write_text(tcx, encoding="utf-8")


def _write_tcx_two_laps(path: Path) -> None:
    lap1_points = []
    lap2_points = []
    for i in range(0, 21):
        lap1_points.append(
            f"""
            <Trackpoint>
              <Time>2025-01-01T12:00:{i:02d}Z</Time>
              <Position>
                <LatitudeDegrees>{50.200000 + i * 0.0001:.6f}</LatitudeDegrees>
                <LongitudeDegrees>{14.200000 + i * 0.0001:.6f}</LongitudeDegrees>
              </Position>
              <AltitudeMeters>{200 + i * 0.1:.1f}</AltitudeMeters>
              <DistanceMeters>{i * 8.0:.2f}</DistanceMeters>
              <HeartRateBpm><Value>{140 + i % 5}</Value></HeartRateBpm>
              <Extensions><TPX xmlns=\"http://www.garmin.com/xmlschemas/ActivityExtension/v2\"><Watts>{180 + i}</Watts></TPX></Extensions>
            </Trackpoint>
            """
        )
    for i in range(20, 41):
        lap2_points.append(
            f"""
            <Trackpoint>
              <Time>2025-01-01T12:00:{i:02d}Z</Time>
              <Position>
                <LatitudeDegrees>{50.210000 + i * 0.0001:.6f}</LatitudeDegrees>
                <LongitudeDegrees>{14.210000 + i * 0.0001:.6f}</LongitudeDegrees>
              </Position>
              <AltitudeMeters>{202 + i * 0.1:.1f}</AltitudeMeters>
              <DistanceMeters>{160 + (i - 20) * 9.0:.2f}</DistanceMeters>
              <HeartRateBpm><Value>{150 + i % 5}</Value></HeartRateBpm>
              <Extensions><TPX xmlns=\"http://www.garmin.com/xmlschemas/ActivityExtension/v2\"><Watts>{220 + i}</Watts></TPX></Extensions>
            </Trackpoint>
            """
        )

    tcx = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<TrainingCenterDatabase xmlns=\"http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2\">
  <Activities>
    <Activity Sport=\"Biking\">
      <Id>2025-01-01T12:00:00Z</Id>
      <Lap StartTime=\"2025-01-01T12:00:00Z\"><TotalTimeSeconds>20</TotalTimeSeconds><Track>{''.join(lap1_points)}</Track></Lap>
      <Lap StartTime=\"2025-01-01T12:00:20Z\"><TotalTimeSeconds>20</TotalTimeSeconds><Track>{''.join(lap2_points)}</Track></Lap>
    </Activity>
  </Activities>
</TrainingCenterDatabase>
"""
    path.write_text(tcx, encoding="utf-8")


def test_parse_tcx(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.tcx"
    _write_tcx(file_path)

    activity = parse_tcx(file_path)
    assert len(activity.points) == 41
    assert activity.points[0].elapsed_s == 0
    assert activity.points[10].power_w == 320
    assert activity.points[20].heart_rate_bpm == 170
    assert len(activity.stored_intervals) == 1


def test_cli_writes_json_csv_and_gpx(tmp_path: Path) -> None:
    input_file = tmp_path / "sample.tcx"
    _write_tcx(input_file)

    csv_out = tmp_path / "intervals.csv"
    json_out = tmp_path / "intervals.json"
    gpx_out = tmp_path / "intervals.gpx"

    exit_code = main(
        [
            str(input_file),
            "--duration",
            "00:15",
            "--count",
            "2",
            "--target",
            "power,heart-rate",
            "--inner-intlen",
            "5,10",
            "--slope-window-m",
            "25",
            "--hr-zone-tabs",
            "145,160",
            "--power-zone-tabs",
            "190,250",
            "--hr-hist-bins",
            "4",
            "--power-hist-bins",
            "5",
            "--no-stdout",
            "--csv-out",
            str(csv_out),
            "--json-out",
            str(json_out),
            "--gpx-out",
            str(gpx_out),
        ]
    )

    assert exit_code == 0
    assert csv_out.exists()
    assert json_out.exists()
    assert gpx_out.exists()

    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["duration_s"] == 15
    assert payload["slope_window_m"] == 25
    assert set(payload["results"].keys()) == {"power", "heart_rate"}
    assert len(payload["results"]["power"]) == 2
    first = payload["results"]["power"][0]
    assert "start_relative_hms" in first
    assert "ascent_m" in first
    assert "heart_rate_hist_cmd_zones" in first
    assert "minimum_speed_kmh" in first
    assert "non_moving_time_s" in first

    csv_text = csv_out.read_text(encoding="utf-8")
    assert "analysis_metric" in csv_text
    assert "inner_power_max_avg_5s" in csv_text
    assert "median_slope_pct" in csv_text
    assert "average_speed_kmh" in csv_text


def test_cli_preset_defaults_and_override(tmp_path: Path) -> None:
    input_file = tmp_path / "sample.tcx"
    _write_tcx(input_file)

    preset_path = tmp_path / "preset.json"
    output_json = tmp_path / "from_preset.json"
    preset_path.write_text(
        json.dumps(
            {
                "input_file": str(input_file),
                "duration": "00:12",
                "count": 1,
                "target": "power",
                "inner_intlen": [6],
                "slope_window_m": 20,
                "no_stdout": True,
                "json_out": str(output_json),
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--preset",
            str(preset_path),
            "--count",
            "2",
            "--target",
            "power,heart-rate",
        ]
    )
    assert exit_code == 0
    assert output_json.exists()

    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["duration_s"] == 12
    assert payload["count"] == 2
    assert payload["target"] == "power,heart-rate"
    assert set(payload["results"].keys()) == {"power", "heart_rate"}


def test_cli_rejects_unknown_preset_keys(tmp_path: Path) -> None:
    preset_path = tmp_path / "bad_preset.json"
    preset_path.write_text(json.dumps({"unknown_option": 123}), encoding="utf-8")
    exit_code = main(["--preset", str(preset_path)])
    assert exit_code == 2


def test_cli_write_preset_exports_effective_config(tmp_path: Path) -> None:
    input_file = tmp_path / "sample.tcx"
    _write_tcx(input_file)

    exported_preset = tmp_path / "effective_preset.json"
    result_json = tmp_path / "result.json"

    exit_code = main(
        [
            str(input_file),
            "--duration",
            "15",
            "--count",
            "2",
            "--target",
            "power,heart-rate",
            "--inner-intlen",
            "5,10",
            "--slope-window-m",
            "25",
            "--hr-zone-tabs",
            "145,160",
            "--power-zone-tabs",
            "190,250",
            "--hr-hist-bins",
            "4",
            "--power-hist-bins",
            "5",
            "--absolute-timezone",
            "utc",
            "--non-moving-speed-threshold-kmh",
            "2.5",
            "--non-moving-perimeter-m",
            "15",
            "--no-stdout",
            "--json-out",
            str(result_json),
            "--write-preset",
            str(exported_preset),
        ]
    )
    assert exit_code == 0
    assert exported_preset.exists()

    preset_payload = json.loads(exported_preset.read_text(encoding="utf-8"))
    assert preset_payload["input_file"] == str(input_file)
    assert preset_payload["duration"] == "15"
    assert preset_payload["count"] == 2
    assert preset_payload["target"] == "power,heart-rate"
    assert preset_payload["inner_intlen"] == [5.0, 10.0]
    assert preset_payload["slope_window_m"] == 25.0
    assert preset_payload["hr_zone_tabs"] == [145.0, 160.0]
    assert preset_payload["power_zone_tabs"] == [190.0, 250.0]
    assert preset_payload["hr_hist_bins"] == 4
    assert preset_payload["power_hist_bins"] == 5
    assert preset_payload["absolute_timezone"] == "utc"
    assert preset_payload["non_moving_speed_threshold_kmh"] == 2.5
    assert preset_payload["non_moving_perimeter_m"] == 15.0
    assert preset_payload["no_stdout"] is True

    replay_json = tmp_path / "replay.json"
    replay_exit = main(
        [
            "--preset",
            str(exported_preset),
            "--json-out",
            str(replay_json),
            "--no-stdout",
        ]
    )
    assert replay_exit == 0
    assert replay_json.exists()


def test_multiple_presets_are_applied_in_order(tmp_path: Path) -> None:
    input_file = tmp_path / "sample.tcx"
    _write_tcx(input_file)

    base_preset = tmp_path / "base.json"
    user_preset = tmp_path / "user.json"
    output_json = tmp_path / "multi.json"

    base_preset.write_text(
        json.dumps(
            {
                "input_file": str(input_file),
                "duration": "00:10",
                "count": 1,
                "target": "power",
                "no_stdout": True,
                "json_out": str(output_json),
                "non_moving_speed_threshold_kmh": 3.0,
            }
        ),
        encoding="utf-8",
    )
    user_preset.write_text(
        json.dumps(
            {
                "count": 2,
                "target": "power,heart-rate",
                "non_moving_speed_threshold_kmh": 2.0,
                "non_moving_perimeter_m": 18.0,
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--preset",
            str(base_preset),
            "--preset",
            str(user_preset),
        ]
    )
    assert exit_code == 0
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["count"] == 2
    assert payload["target"] == "power,heart-rate"
    assert payload["non_moving_speed_threshold_kmh"] == 2.0
    assert payload["non_moving_perimeter_m"] == 18.0


def test_cli_interval_target_uses_file_intervals_without_duration(tmp_path: Path) -> None:
    input_file = tmp_path / "sample_two_laps.tcx"
    _write_tcx_two_laps(input_file)
    output_json = tmp_path / "interval_target.json"

    exit_code = main(
        [
            str(input_file),
            "--target",
            "interval",
            "--count",
            "1",
            "--no-stdout",
            "--json-out",
            str(output_json),
        ]
    )
    assert exit_code == 0
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["target"] == "interval"
    assert payload["duration_s"] is None
    assert set(payload["results"].keys()) == {"interval"}
    assert len(payload["results"]["interval"]) == 2


def test_cli_interval_select_filters_specific_intervals(tmp_path: Path) -> None:
    input_file = tmp_path / "sample_two_laps.tcx"
    _write_tcx_two_laps(input_file)
    output_json = tmp_path / "interval_select.json"

    exit_code = main(
        [
            str(input_file),
            "--target",
            "interval",
            "--interval-select",
            "2",
            "--no-stdout",
            "--json-out",
            str(output_json),
        ]
    )
    assert exit_code == 0
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    intervals = payload["results"]["interval"]
    assert len(intervals) == 1
    assert intervals[0]["start_elapsed_s"] == pytest.approx(20.0)


def test_cli_rejects_legacy_both_target(tmp_path: Path) -> None:
    input_file = tmp_path / "sample.tcx"
    _write_tcx(input_file)
    with pytest.raises(SystemExit) as exc_info:
        main([str(input_file), "--target", "both", "--duration", "00:10"])
    assert exc_info.value.code == 2


def test_cli_rejects_legacy_space_separated_list_syntax(tmp_path: Path) -> None:
    input_file = tmp_path / "sample.tcx"
    _write_tcx(input_file)
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                str(input_file),
                "--duration",
                "00:10",
                "--target",
                "power",
                "--inner-intlen",
                "5",
                "10",
            ]
        )
    assert exc_info.value.code == 2


def test_cli_accepts_comma_list_values_from_preset_strings(tmp_path: Path) -> None:
    input_file = tmp_path / "sample.tcx"
    _write_tcx(input_file)
    preset_path = tmp_path / "preset_strings.json"
    output_json = tmp_path / "preset_strings_out.json"
    preset_path.write_text(
        json.dumps(
            {
                "input_file": str(input_file),
                "duration": "00:12",
                "target": "power,heart-rate",
                "inner_intlen": "6,12",
                "hr_zone_tabs": "140,160",
                "power_zone_tabs": "190,250",
                "no_stdout": True,
                "json_out": str(output_json),
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(["--preset", str(preset_path)])
    assert exit_code == 0
    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["inner_interval_lengths_s"] == [6.0, 12.0]
    assert payload["hr_zone_tabs"] == [140.0, 160.0]
    assert payload["power_zone_tabs"] == [190.0, 250.0]


def test_cli_stdout_stat_order_is_min_med_avg_max(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    input_file = tmp_path / "sample.tcx"
    _write_tcx(input_file)

    exit_code = main(
        [
            str(input_file),
            "--duration",
            "00:10",
            "--count",
            "1",
            "--target",
            "power",
            "--bw",
        ]
    )
    assert exit_code == 0
    output_text = capsys.readouterr().out

    for prefix in ("  speed=", "  power=", "  hr="):
        line = next(line for line in output_text.splitlines() if line.startswith(prefix))
        assert "min:" in line
        assert " med:" in line
        assert " avg:" in line
        assert " max:" in line
        assert line.index("min:") < line.index(" med:")
        assert line.index(" med:") < line.index(" avg:")
        assert line.index(" avg:") < line.index(" max:")
