"""Master Data Parser processing pipeline with one-record/one-XML spooling."""

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Any, List, Optional, Tuple

from ..models.common import CommonVesselRecord, ParseResult, ParserEnvelope
from .ais_state import AISStateDB
from .downstream_parser import DownstreamXMLParser
from .enricher import VesselEnricher
from .normalizer import NormalizedRecord, normalize_from_common_record, normalize_from_decoded_track
from .source_registry import iso_to_epoch_ms
from .reference_db import ReferenceDB
from .spoofing import PositionalSpoofingDetector
from .track_state import TrackStateDB
from .xml_decoder import decode_xml_payload
from .xml_generator import XTrackXMLGenerator

log = logging.getLogger("parser.processor")


class PipelineProcessor:
    """Parser -> normalization -> validation/correlation -> enrichment -> XML spool."""

    def __init__(
        self,
        reference_db: Optional[ReferenceDB] = None,
        track_state_db: Optional[TrackStateDB] = None,
        ais_state_db: Optional[AISStateDB] = None,
        xml_output_dir: Optional[Path] = None,
    ):
        self.ref_db = reference_db or ReferenceDB()
        self.state_db = track_state_db or TrackStateDB()
        self.ais_state_db = ais_state_db or AISStateDB()
        self.enricher = VesselEnricher(reference_db=self.ref_db, track_state_db=self.state_db)
        self.spoofing = PositionalSpoofingDetector()
        self.xml_generator = XTrackXMLGenerator()
        self.downstream_parser = DownstreamXMLParser()

        if xml_output_dir:
            configured = Path(xml_output_dir)
        elif os.environ.get("VALIDATION_FORWARDER_INPUT_DIR"):
            configured = Path(os.environ["VALIDATION_FORWARDER_INPUT_DIR"])
        else:
            validation_home = os.environ.get("VALIDATION_HOME")
            root = Path(validation_home).resolve() if validation_home else Path(__file__).resolve().parents[4]
            configured = root / "Validation" / "Data_Forwarder" / "spool" / "pending"
        self.xml_output_dir = configured
        self.xml_output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _positional_remark(anomaly: dict) -> str:
        detail = (
            f"POSITIONAL SPOOFING FOUND | calculated speed: {anomaly['calculated_speed_knots']:.2f} kt"
            f" | distance: {anomaly['distance_nm']:.2f} NM"
            f" | delta-t: {anomaly['elapsed_seconds']:.1f} s"
            f" | threshold: {anomaly['threshold_knots']:.2f} kt"
        )
        if anomaly.get("reported_sog_knots") is not None:
            detail += f" | reported SOG: {anomaly['reported_sog_knots']:.2f} kt"
        return detail

    def _normalize_record(self, rec: CommonVesselRecord, receipt_time_ms: Optional[int] = None) -> NormalizedRecord:
        anomaly = None
        if rec.mmsi and rec.app_message_id is not None:
            previous_state = self.ais_state_db.get(rec.mmsi)
            if rec.latitude is not None and rec.longitude is not None:
                anomaly = self.spoofing.check(previous_state, rec)
            self.ais_state_db.merge_record(rec)
            state = self.ais_state_db.get(rec.mmsi)
            if state:
                rec.raw_attributes = dict(rec.raw_attributes or {})
                rec.raw_attributes["ais_state"] = state

        norm = normalize_from_common_record(rec, receipt_time_ms=receipt_time_ms)
        if anomaly and anomaly.get("flagged"):
            norm.vessel_remarks = self._positional_remark(anomaly)
        return norm

    def _enrich_one(self, norm: NormalizedRecord) -> NormalizedRecord:
        return self.enricher.enrich(norm)

    def _spool_xml(self, source: str, message_id: str, record_id: str, xml: str) -> Path:
        safe_source = re.sub(r"[^A-Za-z0-9_.-]+", "_", source or "UNKNOWN")[:80]
        safe_message = re.sub(r"[^A-Za-z0-9_.-]+", "_", message_id or "UNKNOWN")[:100]
        safe_record = re.sub(r"[^A-Za-z0-9_.-]+", "_", record_id or "record")[:120]
        digest = hashlib.sha256(xml.encode("utf-8")).hexdigest()[:16]
        target = self.xml_output_dir / f"{safe_source}_{safe_message}_{safe_record}_{digest}.xml"
        temp = target.with_name(target.name + ".part")
        temp.write_text(xml, encoding="utf-8")
        temp.replace(target)
        log.info("Final XML spooled: %s", target)
        return target

    def process_envelope(
        self,
        envelope: ParserEnvelope,
        fallback_source_parser: Optional[Any] = None,
    ) -> Tuple[ParseResult, str]:
        source, message_id, payload = envelope.source, envelope.message_id, envelope.payload or ""
        errors: List[str] = []
        normalized_records: List[NormalizedRecord] = []

        trimmed = payload.strip()
        is_xml = (
            trimmed.startswith("<?xml")
            or trimmed.startswith("<ns2:XTracks")
            or trimmed.startswith("<XTracks")
            or "<XTrack" in trimmed
        )

        if is_xml:
            try:
                for idx, trk in enumerate(decode_xml_payload(payload), 1):
                    normalized_records.append(
                        normalize_from_decoded_track(
                            track=trk,
                            source_name=source,
                            message_id=f"{message_id}:{idx}",
                            receipt_time_ms=iso_to_epoch_ms(envelope.received_at),
                        )
                    )
            except Exception as exc:
                errors.append(f"XML decoding error: {exc}")
        else:
            parser = fallback_source_parser or self._get_default_parser(source)
            if parser is None:
                errors.append(f"Non-XML payload received with no source parser for {source}")
            else:
                try:
                    parsed = parser.parse(envelope)
                    errors.extend(parsed.errors)
                    for rec in parsed.records:
                        try:
                            normalized_records.append(self._normalize_record(rec, receipt_time_ms=iso_to_epoch_ms(envelope.received_at)))
                        except Exception as exc:
                            errors.append(
                                f"Normalization/validation error for line-record {rec.record_id}: {exc}"
                            )
                except Exception as exc:
                    errors.append(f"Source parser error: {exc}")

        enriched: List[NormalizedRecord] = []
        common_records: List[CommonVesselRecord] = []
        for norm in normalized_records:
            try:
                enr = self._enrich_one(norm)
                enriched.append(enr)
                common_records.append(
                    CommonVesselRecord(
                        source=source,
                        message_id=message_id,
                        record_id=f"{source}:{message_id}:{enr.id_mmsi or 'unknown'}",
                        timestamp=str(enr.timestamp_source or ""),
                        mmsi=enr.id_mmsi,
                        imo=enr.id_imo,
                        vessel_name=enr.vessel_name,
                        callsign=enr.id_callsign,
                        latitude=enr.kinematic_pos_lla_lat,
                        longitude=enr.kinematic_pos_lla_lon,
                        sog=enr.kinematic_speed,
                        cog=enr.kinematic_course_true,
                        true_heading=enr.kinematic_heading_true,
                        nav_status=enr.ais_navStatus if isinstance(enr.ais_navStatus, int) else None,
                        draught=enr.vessel_draft,
                        vessel_type=str(enr.ais_typeAndCargo or ""),
                        destination=enr.voyage_destination,
                        eta=str(enr.voyage_eta or ""),
                        length=enr.vessel_length,
                        width=enr.vessel_beam,
                        raw_payload=enr.raw_attributes.get("raw_payload"),
                        raw_attributes=dict(enr.raw_attributes or {}),
                    )
                )
            except Exception as exc:
                errors.append(f"Enrichment error for MMSI={norm.id_mmsi}: {exc}")

        generated_docs: List[str] = []
        spool_failures = 0
        for index, enr in enumerate(enriched, 1):
            try:
                document = self.xml_generator.generate_document(enr)
                self.xml_generator.validate_document(document)
                # The compatibility parser is deliberately executed on every
                # generated document before it reaches the Forwarder spool.
                compat = self.downstream_parser.parse_xml(document)
                if len(compat) != 1:
                    raise ValueError(f"Downstream compatibility parser returned {len(compat)} records")
                record_id = f"{message_id}:{index}:{enr.id_mmsi or 'unknown'}"
                self._spool_xml(source, message_id, record_id, document)
                generated_docs.append(document)
            except Exception as exc:
                spool_failures += 1
                errors.append(f"XML generation/compatibility/spooling error for record {index}: {exc}")

        successful_records = len(generated_docs)
        # ACK means the envelope was accepted and every successfully parsed
        # record that could be materialized was emitted. Individual rejected
        # lines remain visible in records_rejected/errors.
        success = successful_records > 0 or (not normalized_records and not enriched and not errors)

        result = ParseResult(
            message_id=message_id,
            source=source,
            success=success,
            records_parsed=successful_records,
            records_rejected=max(len(errors), spool_failures),
            records=common_records,
            errors=errors,
        )
        # Backward-compatible return value: for a single-record envelope this
        # is the exact XML document. For multi-record file envelopes it is an
        # explicit concatenation of independent documents for diagnostics only;
        # the operational spool remains one file per record.
        return result, "\\n".join(generated_docs)

    def _get_default_parser(self, source: str) -> Optional[Any]:
        src = (source or "").upper()
        try:
            if "SAIS" in src:
                from ..parsers.sais import SAISParser
                return SAISParser()
            if "MSIS" in src:
                from ..parsers.msis import MSISParser
                return MSISParser()
            if "LRIT" in src:
                from ..parsers.lrit import LRITParser
                return LRITParser()
            if "VATMS" in src:
                from ..parsers.vatms import VATMSParser
                return VATMSParser()
            if "NAIS" in src:
                from ..parsers.nais import NAISParser
                return NAISParser()
        except Exception as exc:
            log.warning("Could not load default parser for %s: %s", source, exc)
        return None
