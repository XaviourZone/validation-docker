"""Validation Data Parser Pipeline Processor.

Raw Envelope -> Decoding -> AIS state merge -> Normalization -> Enrichment
-> positional validation -> XML Generation -> Forwarder spool.
"""
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
from .reference_db import ReferenceDB
from .spoofing import PositionalSpoofingDetector
from .track_state import TrackStateDB
from .xml_decoder import decode_xml_payload
from .xml_generator import XTrackXMLGenerator

log = logging.getLogger("parser.processor")

class PipelineProcessor:
    """Master processor running the end-to-end Data Parser pipeline."""
    def __init__(self, reference_db: Optional[ReferenceDB] = None, track_state_db: Optional[TrackStateDB] = None,
                 ais_state_db: Optional[AISStateDB] = None, xml_output_dir: Optional[Path] = None):
        self.ref_db = reference_db or ReferenceDB()
        self.state_db = track_state_db or TrackStateDB()
        self.ais_state_db = ais_state_db or AISStateDB()
        self.enricher = VesselEnricher(reference_db=self.ref_db, track_state_db=self.state_db)
        self.spoofing = PositionalSpoofingDetector()
        self.xml_generator = XTrackXMLGenerator()
        self.downstream_parser = DownstreamXMLParser()
        if xml_output_dir:
            configured = xml_output_dir
        elif os.environ.get("VALIDATION_FORWARDER_INPUT_DIR"):
            configured = Path(os.environ["VALIDATION_FORWARDER_INPUT_DIR"])
        else:
            validation_home = os.environ.get("VALIDATION_HOME")
            root = Path(validation_home).resolve() if validation_home else Path(__file__).resolve().parents[4]
            configured = root / "Validation" / "Data_Forwarder" / "spool" / "pending"
        self.xml_output_dir = Path(configured)
        self.xml_output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _spoofing_remark(anomaly: dict) -> str:
        detail = (f"POSITIONAL SPOOFING FOUND | calculated speed: {anomaly['calculated_speed_knots']:.2f} kt"
                  f" | distance: {anomaly['distance_nm']:.2f} NM"
                  f" | delta-t: {anomaly['elapsed_seconds']:.1f} s"
                  f" | threshold: {anomaly['threshold_knots']:.2f} kt")
        if anomaly.get("reported_sog_knots") is not None:
            detail += f" | reported SOG: {anomaly['reported_sog_knots']:.2f} kt"
        return detail

    def process_envelope(self, envelope: ParserEnvelope, fallback_source_parser: Optional[Any] = None) -> Tuple[ParseResult, str]:
        source, message_id, payload = envelope.source, envelope.message_id, envelope.payload or ""
        errors: List[str] = []
        normalized_records: List[NormalizedRecord] = []
        trimmed = payload.strip()
        is_xml = trimmed.startswith("<?xml") or trimmed.startswith("<ns2:XTracks") or trimmed.startswith("<XTracks") or "<XTrack" in trimmed
        if is_xml:
            try:
                for trk in decode_xml_payload(payload):
                    normalized_records.append(normalize_from_decoded_track(track=trk, source_name=source, message_id=message_id))
            except Exception as e:
                errors.append(f"XML decoding error: {e}")
        else:
            parser = fallback_source_parser or self._get_default_parser(source)
            if parser is not None:
                try:
                    res: ParseResult = parser.parse(envelope)
                    for rec in res.records:
                        try:
                            anomaly = None
                            if rec.mmsi and rec.app_message_id is not None:
                                previous_state = self.ais_state_db.get(rec.mmsi)
                                incoming_lat, incoming_lon = rec.latitude, rec.longitude
                                self.ais_state_db.merge_record(rec)
                                state = self.ais_state_db.get(rec.mmsi)
                                if state:
                                    rec.raw_attributes = dict(rec.raw_attributes or {})
                                    rec.raw_attributes["ais_state"] = state
                                if incoming_lat is not None and incoming_lon is not None:
                                    anomaly = self.spoofing.check(previous_state, rec)
                            norm = normalize_from_common_record(rec)
                            if anomaly and anomaly.get("flagged"):
                                norm.vessel_remarks = self._spoofing_remark(anomaly)
                            normalized_records.append(norm)
                        except Exception as state_exc:
                            errors.append(f"AIS state/position validation error for MMSI={rec.mmsi}: {state_exc}")
                    errors.extend(res.errors)
                except Exception as e:
                    errors.append(f"Source parser error: {e}")
            else:
                errors.append(f"Non-XML payload received with no source parser available for {source}")

        enriched_records: List[NormalizedRecord] = []
        common_records: List[CommonVesselRecord] = []
        for norm in normalized_records:
            try:
                enr = self.enricher.enrich(norm)
                enriched_records.append(enr)
                common_records.append(CommonVesselRecord(
                    source=source, message_id=message_id, record_id=f"{source}:{message_id}:{enr.id_mmsi or 'unknown'}",
                    timestamp=str(enr.timestamp_source or ""), mmsi=enr.id_mmsi, imo=enr.id_imo,
                    vessel_name=enr.vessel_name, callsign=enr.id_callsign, latitude=enr.kinematic_pos_lla_lat,
                    longitude=enr.kinematic_pos_lla_lon, sog=enr.kinematic_speed, cog=enr.kinematic_course_true,
                    true_heading=enr.kinematic_heading_true, nav_status=enr.ais_navStatus if isinstance(enr.ais_navStatus, int) else None,
                    draught=enr.vessel_draft, vessel_type=str(enr.ais_typeAndCargo or ""), destination=enr.voyage_destination,
                    eta=str(enr.voyage_eta or ""), length=enr.vessel_length, width=enr.vessel_beam,
                ))
            except Exception as e:
                errors.append(f"Enrichment error for record MMSI={norm.id_mmsi}: {e}")
        generated_xml = ""
        if enriched_records:
            try:
                generated_xml = self.xml_generator.generate_batch_xml(enriched_records)
                self._spool_xml(source, message_id, generated_xml)
            except Exception as e:
                errors.append(f"XML generation/spooling error: {e}")
        success = len(enriched_records) > 0 and not errors
        return ParseResult(message_id=message_id, source=source, success=success, records_parsed=len(enriched_records), records_rejected=len(errors), records=common_records, errors=errors), generated_xml

    def _spool_xml(self, source: str, message_id: str, xml: str) -> Path:
        safe_source = re.sub(r"[^A-Za-z0-9_.-]+", "_", source or "UNKNOWN")[:80]
        safe_message = re.sub(r"[^A-Za-z0-9_.-]+", "_", message_id or "UNKNOWN")[:100]
        digest = hashlib.sha256(xml.encode("utf-8")).hexdigest()[:16]
        target = self.xml_output_dir / f"{safe_source}_{safe_message}_{digest}.xml"
        temp = target.with_name(target.name + ".part")
        temp.write_text(xml, encoding="utf-8")
        temp.replace(target)
        log.info("Final XML spooled for Forwarder: %s", target)
        return target

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
        except Exception as e:
            log.warning("Could not load default parser for %s: %s", source, e)
        return None
