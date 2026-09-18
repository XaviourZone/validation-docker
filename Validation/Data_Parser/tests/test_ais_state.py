from pathlib import Path

from Validation.Data_Parser.app.models.common import CommonVesselRecord
from Validation.Data_Parser.app.pipeline.ais_state import AISStateDB


def _record(msg_type, name=None, latitude=None, longitude=None):
    return CommonVesselRecord(
        source="SAIS_IOR",
        message_id=f"m{msg_type}",
        record_id=f"r{msg_type}",
        timestamp="2026-06-25T10:00:00+00:00",
        mmsi=419000122,
        vessel_name=name,
        latitude=latitude,
        longitude=longitude,
        app_message_id=msg_type,
    )


def test_type5_state_is_reused_by_later_position_message(tmp_path: Path):
    db = AISStateDB(tmp_path / "ais.db")
    static = _record(5, name="TEST VESSEL")
    db.merge_record(static)

    position = _record(1, latitude=13.1, longitude=80.3)
    db.merge_record(position)

    assert position.vessel_name == "TEST VESSEL"
    assert position.latitude == 13.1
    assert position.longitude == 80.3
    assert db.recent_messages(419000122, 10)[0]["message_type"] == 1
    assert any(x["message_type"] == 5 for x in db.recent_messages(419000122, 10))
    db.close()
