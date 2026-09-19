"""Explicit acceptance tests for VATMS/NAIS control-message semantics."""

import unittest

from Validation.Data_Parser.app.models.common import ParserEnvelope
from Validation.Data_Parser.app.parsers.nais import NAISParser
from Validation.Data_Parser.app.parsers.vatms import VATMSParser


def nmea_checksum(body: str) -> str:
    value = 0
    for char in body:
        value ^= ord(char)
    return f"{value:02X}"


class TestControlMessageSemantics(unittest.TestCase):
    def test_nais_abvsi_status_is_not_emitted_as_vessel_track(self):
        envelope = ParserEnvelope(
            message_id="nais-status-1",
            source="NAIS",
            input_type="TCP",
            received_at="2026-09-19T00:00:00Z",
            payload="$ABVSI,North Point,2,102437.043072,1389,-79,36*54",
        )
        result = NAISParser().parse(envelope)

        self.assertEqual(result.records_parsed, 0)
        self.assertEqual(result.records_rejected, 0)
        self.assertEqual(result.records, [])

    def test_vatms_tmvtd_delete_control_is_not_emitted(self):
        body = "TMVTD,230726,103413.05,R,,,,,,,,,,,D"
        line = "$" + body + "*" + nmea_checksum(body)
        envelope = ParserEnvelope(
            message_id="vatms-delete-1",
            source="VATMS_WEST",
            input_type="TCP",
            received_at="2026-09-19T00:00:00Z",
            payload=line,
        )
        result = VATMSParser().parse(envelope)

        self.assertEqual(result.records_parsed, 0)
        self.assertEqual(result.records_rejected, 0)
        self.assertEqual(result.records, [])


if __name__ == "__main__":
    unittest.main()
