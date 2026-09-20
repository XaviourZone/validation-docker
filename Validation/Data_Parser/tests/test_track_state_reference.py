import tempfile
import unittest
from pathlib import Path

from Validation.Data_Parser.app.pipeline.track_state import TrackStateDB


class TestMMSIReferenceStore(unittest.TestCase):
    def test_reference_persists_and_blank_does_not_erase(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "track_state.db"
            db = TrackStateDB(db_path)

            db.upsert(
                mmsi=419000001,
                imo=1234567,
                vessel_name="FIRST VESSEL",
                latitude=10.0,
                longitude=20.0,
                tx_timestamp_iso="2026-09-20T10:00:00Z",
                source="SAIS_IOR",
                reference_values={
                    "id.imo": 1234567,
                    "id.callsign": "ABC1",
                    "vessel.name": "FIRST VESSEL",
                    "vessel.length": 100.0,
                    "voyage.destination": "INMAA",
                },
            )

            self.assertEqual(db.reference_count(), 1)
            self.assertEqual(db.get_reference(419000001)["id.callsign"], "ABC1")

            db.upsert(
                mmsi=419000001,
                imo=None,
                vessel_name=None,
                latitude=11.0,
                longitude=21.0,
                tx_timestamp_iso="2026-09-20T10:05:00Z",
                source="MSIS",
                reference_values={
                    "id.imo": None,
                    "id.callsign": "",
                    "vessel.name": None,
                    "vessel.length": 105.0,
                    "voyage.destination": "INBOM",
                },
            )

            reference = db.get_reference(419000001)
            self.assertEqual(reference["id.imo"], 1234567)
            self.assertEqual(reference["id.callsign"], "ABC1")
            self.assertEqual(reference["vessel.name"], "FIRST VESSEL")
            self.assertEqual(reference["vessel.length"], 105.0)
            self.assertEqual(reference["voyage.destination"], "INBOM")

            db.close()

            reopened = TrackStateDB(db_path)
            self.assertEqual(reopened.reference_count(), 1)
            self.assertEqual(reopened.get_reference(419000001)["id.callsign"], "ABC1")
            reopened.close()

    def test_dynamic_fields_are_not_stored(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = TrackStateDB(Path(tmp) / "track_state.db")
            db.upsert(
                mmsi=419000002,
                imo=None,
                vessel_name=None,
                latitude=1.0,
                longitude=2.0,
                tx_timestamp_iso="2026-09-20T10:00:00Z",
                source="SAIS_GLOBAL",
                reference_values={
                    "kinematic.pos.lla.lat": 1.0,
                    "kinematic.pos.lla.lon": 2.0,
                    "kinematic.speed": 12.0,
                    "vessel.name": "STATIC NAME",
                },
            )
            reference = db.get_reference(419000002)
            self.assertNotIn("kinematic.pos.lla.lat", reference)
            self.assertNotIn("kinematic.speed", reference)
            self.assertEqual(reference["vessel.name"], "STATIC NAME")
            db.close()


if __name__ == "__main__":
    unittest.main()
