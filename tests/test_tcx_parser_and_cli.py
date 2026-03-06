from __future__ import annotations

import json
from pathlib import Path

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


def test_parse_tcx(tmp_path: Path) -> None:
    file_path = tmp_path / "sample.tcx"
    _write_tcx(file_path)

    activity = parse_tcx(file_path)
    assert len(activity.points) == 41
    assert activity.points[0].elapsed_s == 0
    assert activity.points[10].power_w == 320
    assert activity.points[20].heart_rate_bpm == 170


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
            "--metrics",
            "both",
            "--inner-intlen",
            "5",
            "10",
            "--slope-window-m",
            "25",
            "--hr-zone-tabs",
            "145",
            "160",
            "--power-zone-tabs",
            "190",
            "250",
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
                "metrics": "power",
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
            "--metrics",
            "both",
        ]
    )
    assert exit_code == 0
    assert output_json.exists()

    payload = json.loads(output_json.read_text(encoding="utf-8"))
    assert payload["duration_s"] == 12
    assert payload["count"] == 2
    assert payload["metrics"] == "both"
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
            "--metrics",
            "both",
            "--inner-intlen",
            "5",
            "10",
            "--slope-window-m",
            "25",
            "--hr-zone-tabs",
            "145",
            "160",
            "--power-zone-tabs",
            "190",
            "250",
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
    assert preset_payload["metrics"] == "both"
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
                "metrics": "power",
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
                "metrics": "both",
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
    assert payload["metrics"] == "both"
    assert payload["non_moving_speed_threshold_kmh"] == 2.0
    assert payload["non_moving_perimeter_m"] == 18.0
