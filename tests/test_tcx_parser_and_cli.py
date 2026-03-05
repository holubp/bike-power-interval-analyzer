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
    assert set(payload["results"].keys()) == {"power", "heart_rate"}
    assert len(payload["results"]["power"]) == 2

    csv_text = csv_out.read_text(encoding="utf-8")
    assert "analysis_metric" in csv_text
    assert "inner_power_max_avg_5s" in csv_text
