from pathlib import Path

from Validation.Data_Parser.app.models.common import CommonVesselRecord
from Validation.Data_Parser.app.pipeline.ais_state import AISStateDB
from Validation.Data_Parser.app.pipeline.spoofing import PositionalSpoofingDetector


def _record(ts, lat, lon, sog=10.0, vessel_type="Commercial Cargo"):
    return CommonVesselRecord(
        source="SAIS_IOR", message_id=ts, record_id=ts, timestamp=ts,
        mmsi=419000122, latitude=lat, longitude=lon, sog=sog,
        vessel_type=vessel_type, app_message_id=1,
    )


def test_haversine_spoofing_flags_teleportation():
    detector = PositionalSpoofingDetector(Path("Validation/Data_Parser/config/spoofing.yaml"))
    previous = {
        "last_position_latitude": 10.0,
        "last_position_longitude": 70.0,
        "last_position_timestamp": "2026-06-25T10:00:00+00:00",
    }
    current = _record("2026-06-25T10:01:00+00:00", 15.0, 75.0)
    result = detector.check(previous, current)
    assert result is not None
    assert result["flagged"] is True
    assert result["calculated_speed_knots"] > 40


def test_ais_state_keeps_last_position_time_separate_from_static_message(tmp_path: Path):
    db = AISStateDB(tmp_path / "ais.db")
    position = _record("2026-06-25T10:00:00+00:00", 10.0, 70.0)
    db.merge_record(position)
    static = _record("2026-06-25T10:00:30+00:00", None, None)
    static.app_message_id = 5
    db.merge_record(static)
    state = db.get(419000122)
    assert state["last_position_latitude"] == 10.0
    assert state["last_position_longitude"] == 70.0
    assert state["last_position_timestamp"] == "2026-06-25T10:00:00+00:00"
    assert state["last_timestamp"] == "2026-06-25T10:00:30+00:00"
    db.close()
