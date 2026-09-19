"""Reference importer contract tests using isolated temporary databases.

These tests exercise WRS CSV, PANS XML and NSC CSV ingestion without requiring
operational production reference databases.
"""

import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from Validation.Database.common.database_utils import (
    create_import_tracking_tables,
    open_database,
)
from Validation.Database.PANS.importer.pans_importer import (
    PANS_TABLES,
    process_xml_file,
)
from Validation.Database.NSC.importer.nsc_importer import process_file
from Validation.Database.WRS.importer.wrs_importer import process_csv_file


class TestReferenceImporters(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _db(self, name):
        path = self.root / name
        conn = open_database(path)
        create_import_tracking_tables(conn)
        cur = conn.execute(
            "INSERT INTO import_batch (source_system, started_at, status) "
            "VALUES (?, datetime('now'), 'RUNNING')",
            (name.upper(),),
        )
        conn.commit()
        return conn, cur.lastrowid

    def test_wrs_csv_loader_preserves_headers_and_rows(self):
        csv_path = self.root / "VESSELS.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["VESSEL_ID", "MMSI", "IMO", "VESSEL_NAME"])
            writer.writerow(["V001", "419697000", "8407979", "SAGA"])

        conn, batch_id = self._db("wrs")
        try:
            ok, rows = process_csv_file(conn, csv_path, batch_id, is_decode=False)
            self.assertTrue(ok)
            self.assertEqual(rows, 1)
            row = conn.execute(
                "SELECT MMSI, IMO, VESSEL_NAME FROM wrs_datasets_vessels"
            ).fetchone()
            self.assertEqual(tuple(row), ("419697000", "8407979", "SAGA"))
            self.assertEqual(
                conn.execute(
                    "SELECT status FROM import_file WHERE file_id=1"
                ).fetchone()[0],
                "COMPLETED",
            )
        finally:
            conn.close()

    def test_pans_xml_root_maps_to_expected_table(self):
        xml_path = self.root / "vespro.xml"
        xml_path.write_text(
            "<VesselProfile><IMONumber>8407979</IMONumber>"
            "<MMSINumber>419697000</MMSINumber>"
            "<VesselName>SAGA</VesselName><CallSign>SAGA</CallSign></VesselProfile>",
            encoding="utf-8",
        )

        conn, batch_id = self._db("pans")
        try:
            ok = process_xml_file(conn, xml_path, batch_id)
            self.assertTrue(ok)
            self.assertIn("VesselProfile", PANS_TABLES)
            row = conn.execute(
                "SELECT IMONumber, MMSINumber, VesselName FROM pans_vespro"
            ).fetchone()
            self.assertEqual(tuple(row), ("8407979", "419697000", "SAGA"))
        finally:
            conn.close()

    def test_nsc_csv_unifies_region_and_columns(self):
        csv_path = self.root / "NSC_EAST.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["ID_MMSI", "ID_IMO", "ID_CALLSIGN", "VESSEL_NAME", "TYPE"])
            writer.writerow(["419697000", "8407979", "SAGA", "SAGA", "VESSEL"])

        conn, batch_id = self._db("nsc")
        try:
            ok, rows = process_file(conn, csv_path, batch_id, "EAST")
            self.assertTrue(ok)
            self.assertEqual(rows, 1)
            row = conn.execute(
                "SELECT SOURCE_REGION, ID_MMSI, ID_IMO, ID_CALLSIGN, VESSEL_NAME "
                "FROM nsc_vessels"
            ).fetchone()
            self.assertEqual(
                tuple(row),
                ("EAST", "419697000", "8407979", "SAGA", "SAGA"),
            )
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
