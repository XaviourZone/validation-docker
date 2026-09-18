from Validation.Data_Parser.app.models.common import ParserEnvelope
from Validation.Data_Parser.app.parsers.msis import MSISParser


def test_msis_accepts_legacy_navigation_status_typo():
    payload = "mmsi,navigatetion_status,latitude,longitude\n419000122,15,13.1,80.3\n"
    envelope = ParserEnvelope(
        message_id="test-msis",
        source="MSIS",
        input_type="FILE",
        received_at="2026-06-25T10:00:00+00:00",
        payload=payload,
    )
    result = MSISParser().parse(envelope)
    assert result.success
    assert result.records_parsed == 1
    assert result.records[0].nav_status == 15
