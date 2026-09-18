"""NAIS Parser for National AIS feed (!ABVDM / !ABVDO sentences)."""

from typing import List

from ..models.common import CommonVesselRecord, ParseResult, ParserEnvelope
from .base import BaseParser
from .sais import SAISParser


class NAISParser(BaseParser):
    """Parses NAIS feed consisting of !ABVDM, !ABVDO, and $ABVSI sentences."""

    def __init__(self):
        self._sais_parser = SAISParser()

    @property
    def parser_name(self) -> str:
        return "NAIS"

    def parse(self, envelope: ParserEnvelope) -> ParseResult:
        source = envelope.source
        message_id = envelope.message_id
        raw_text = envelope.payload or ""

        records: List[CommonVesselRecord] = []
        errors: List[str] = []
        parsed_count = 0
        rejected_count = 0

        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]

        for line_idx, line in enumerate(lines, 1):
            try:
                # $ABVSI is a site status/signal strength record
                if line.startswith("$ABVSI"):
                    continue

                if line.startswith("!"):
                    record = self._sais_parser._parse_line(source, message_id, line_idx, line)
                    if record:
                        records.append(record)
                        parsed_count += 1
            except Exception as e:
                rejected_count += 1
                errors.append(f"Line {line_idx} parse failed: {str(e)} | Line: {line[:60]}")

        success = parsed_count > 0 or len(errors) == 0

        return ParseResult(
            message_id=message_id,
            source=source,
            success=success,
            records_parsed=parsed_count,
            records_rejected=rejected_count,
            records=records,
            errors=errors,
        )
