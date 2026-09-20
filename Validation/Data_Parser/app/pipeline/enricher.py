"""Enricher & Correlator for maritime vessel records.

Performs reference lookup, AIS track-state handling, configurable parser mapping,
source fallback rules, vigilance/identity calculation and provenance remarks.
"""

import logging
from typing import Any, Dict, List, Optional

from .mapping_manager import ParserMappingManager
from .normalizer import NormalizedRecord, normalize_type_and_cargo
from .reference_db import ReferenceDB, VesselContext
from .source_registry import get_source_label, is_valid_imo, is_valid_mmsi, sanitize_string
from .track_state import MMSI_REFERENCE_FIELDS, TrackStateDB
from .unlocode import resolve_destination

log = logging.getLogger("parser.enricher")


LOGICAL_TO_ATTR = {
    "ais.lenToBow": "ais_lenToBow", "ais.lenToStern": "ais_lenToStern",
    "ais.navStatus": "ais_navStatus", "ais.typeAndCargo": "ais_typeAndCargo",
    "ais.widthToPort": "ais_widthToPort", "ais.widthToStarboard": "ais_widthToStarboard",
    "app.message.id": "app_message_id", "cat.annotation": "cat_annotation",
    "cat.category": "cat_category", "cat.identity": "cat_identity",
    "foreign.track.number": "foreign_track_number", "id.callsign": "id_callsign",
    "id.imo": "id_imo", "id.mmsi": "id_mmsi", "id.mmsi.destination": "id_mmsi_destination",
    "kinematic.course.true": "kinematic_course_true", "kinematic.flag.3d": "kinematic_flag_3d",
    "kinematic.heading.true": "kinematic_heading_true", "kinematic.pos.lla.alt": "kinematic_pos_lla_alt",
    "kinematic.pos.lla.lat": "kinematic_pos_lla_lat", "kinematic.pos.lla.lon": "kinematic_pos_lla_lon",
    "kinematic.speed": "kinematic_speed", "sys.source.id": "sys_source_id",
    "sys.track.number": "sys_track_number", "timestamp.receipt": "timestamp_receipt",
    "timestamp.source": "timestamp_source", "track.flag.active": "track_flag_active",
    "track.quality": "track_quality", "vessel.beam": "vessel_beam",
    "vessel.description": "vessel_description", "vessel.draft": "vessel_draft",
    "vessel.grosstonnage": "vessel_grosstonnage", "vessel.length": "vessel_length",
    "vessel.name": "vessel_name", "vessel.remarks": "vessel_remarks",
    "voyage.arrival": "voyage_arrival", "voyage.departure": "voyage_departure",
    "voyage.destination": "voyage_destination", "voyage.eta": "voyage_eta",
    "voyage.etd": "voyage_etd", "voyage.origin": "voyage_origin",
}

INCOMING_ALIASES = {
    "mmsi": "id_mmsi", "imo": "id_imo", "callsign": "id_callsign", "vessel_name": "vessel_name",
    "ship_name": "vessel_name", "vessel_type": "ais_typeAndCargo", "type_and_cargo": "ais_typeAndCargo",
    "length": "vessel_length", "width": "vessel_beam", "beam": "vessel_beam", "draught": "vessel_draft",
    "draft": "vessel_draft", "latitude": "kinematic_pos_lla_lat", "longitude": "kinematic_pos_lla_lon",
    "sog": "kinematic_speed", "cog": "kinematic_course_true", "true_heading": "kinematic_heading_true",
    "heading": "kinematic_heading_true", "nav_status": "ais_navStatus", "navigation_status": "ais_navStatus",
    "navigatetion_status": "ais_navStatus", "destination": "voyage_destination", "eta": "voyage_eta",
    "message_type": "app_message_id",
}

# Field-specific reference fallback priority.
#
# Incoming/transmitted data is always considered first. These priorities are
# only used when the incoming field is missing. They intentionally differ by
# business meaning instead of imposing one global WRS/PANS/NSC order.
#
# Current NSC schema (nsc_vessels) contains vessel identity/type fields but no
# voyage/calling columns. Therefore NSC is first for voyage fields as the
# agreed policy, but the lookup naturally falls through to PANS/WRS when NSC
# has no value for that field.
REFERENCE_FALLBACK_PRIORITY = {
    # Vessel identity / descriptive fields: NSC -> PANS -> WRS.
    "id.imo": ("NSC", "PANS", "WRS"),
    "id.callsign": ("NSC", "PANS", "WRS"),
    "vessel.name": ("NSC", "PANS", "WRS"),
    "vessel.description": ("NSC", "PANS", "WRS"),
    "ais.typeAndCargo": ("NSC", "PANS", "WRS"),

    # Physical/reference dimensions: WRS is the richer dimensions source;
    # PANS is the next vessel-profile fallback.
    "vessel.length": ("WRS", "PANS", "NSC"),
    "vessel.beam": ("WRS", "PANS", "NSC"),
    "vessel.draft": ("PANS", "WRS", "NSC"),
    "vessel.grosstonnage": ("WRS", "PANS", "NSC"),

    # Voyage/calling data: NSC -> PANS -> WRS. NSC currently has no such
    # columns, so PANS is normally the first populated source here.
    "voyage.arrival": ("NSC", "PANS", "WRS"),
    "voyage.departure": ("NSC", "PANS", "WRS"),
    "voyage.destination": ("NSC", "PANS", "WRS"),
    "voyage.eta": ("NSC", "PANS", "WRS"),
    "voyage.etd": ("NSC", "PANS", "WRS"),
    "voyage.origin": ("NSC", "PANS", "WRS"),

    # Operational/reference attributes that are authoritative in WRS.
    "cat.annotation": ("WRS", "PANS", "NSC"),
    "cat.identity": ("WRS", "PANS", "NSC"),
    "id.mmsi.destination": ("WRS", "PANS", "NSC"),
    "foreign.track.number": ("NSC", "PANS", "WRS"),
}

DEFAULT_REFERENCE_FALLBACK_PRIORITY = ("NSC", "PANS", "WRS")


def _reference_order(logical_field: str):
    return REFERENCE_FALLBACK_PRIORITY.get(
        logical_field,
        DEFAULT_REFERENCE_FALLBACK_PRIORITY,
    )



def _parser_name(source: str) -> str:
    upper = (source or "").upper()
    for name in ("SAIS", "MSIS", "LRIT", "VATMS", "NAIS"):
        if name in upper:
            return name
    return upper or "GENERIC"


class VesselEnricher:
    """Coordinates reference lookup, mapping, track state, fallbacks and remarks."""

    def __init__(self, reference_db: Optional[ReferenceDB] = None, track_state_db: Optional[TrackStateDB] = None, mapping_manager: Optional[ParserMappingManager] = None):
        self.ref_db = reference_db or ReferenceDB()
        self.state_db = track_state_db or TrackStateDB()
        self.mapping_manager = mapping_manager or ParserMappingManager()

    @staticmethod
    def _candidate_value(rec: NormalizedRecord, ctx: VesselContext, candidate: str):
        if ":" not in candidate:
            return None
        kind, key = candidate.split(":", 1)
        if kind == "default":
            return key
        if kind == "incoming":
            attr = INCOMING_ALIASES.get(key, key)
            return getattr(rec, attr, None)
        if kind == "ais_state":
            state = (rec.raw_attributes or {}).get("ais_state") or {}
            return state.get(key)
        if kind in {"wrs", "pans", "nsc"}:
            # ReferenceDB exposes provenance fields directly on VesselContext.
            return getattr(ctx, key, None)
        return None

    def _apply_configured_mapping(self, rec: NormalizedRecord, ctx: VesselContext) -> None:
        """Apply only configured candidates to fields still missing.

        Existing non-empty normalized values remain authoritative. This means the
        operator can add WRS/PANS/NSC fallbacks without accidentally overwriting a
        live incoming value.
        """
        try:
            mapping = self.mapping_manager.get(_parser_name(rec.source_name))
            fields = mapping.get("fields") or {}
            for logical, candidates in fields.items():
                attr = LOGICAL_TO_ATTR.get(logical)
                if not attr or getattr(rec, attr, None) not in (None, ""):
                    continue
                for candidate in candidates or []:
                    value = self._candidate_value(rec, ctx, str(candidate))
                    if value not in (None, ""):
                        setattr(rec, attr, value)
                        break
        except Exception as exc:
            log.warning("Parser mapping could not be applied for %s: %s", rec.source_name, exc)

    def enrich(self, rec: NormalizedRecord) -> NormalizedRecord:
        incoming_mmsi = rec.id_mmsi
        incoming_imo = rec.id_imo
        incoming_name = rec.vessel_name
        incoming_callsign = rec.id_callsign
        incoming_values = {attr: getattr(rec, attr, None) for attr in LOGICAL_TO_ATTR.values()}

        ctx: VesselContext = self.ref_db.resolve(mmsi=incoming_mmsi, imo=incoming_imo, callsign=incoming_callsign, vessel_name=incoming_name)
        self._apply_configured_mapping(rec, ctx)

        effective_mmsi = incoming_mmsi
        if not is_valid_mmsi(effective_mmsi):
            for candidate in (ctx.nsc_mmsi, ctx.pans_mmsi, ctx.wrs_mmsi):
                if candidate and is_valid_mmsi(candidate):
                    effective_mmsi = candidate
                    break

        # Persistent per-MMSI fallback is deliberately consulted after the
        # reference databases are resolved. It is the final source only.
        history = (
            self.state_db.get_reference(effective_mmsi)
            if effective_mmsi and is_valid_mmsi(effective_mmsi)
            else {}
        )

        ref_mmsi = ctx.nsc_mmsi or ctx.pans_mmsi or ctx.wrs_mmsi
        try:
            ref_mmsi = int(float(str(ref_mmsi))) if ref_mmsi is not None else None
        except Exception:
            ref_mmsi = None
        if is_valid_mmsi(incoming_mmsi):
            rec.foreign_track_number = incoming_mmsi
        elif ref_mmsi and is_valid_mmsi(ref_mmsi):
            rec.foreign_track_number = ref_mmsi
        elif not is_valid_mmsi(rec.foreign_track_number):
            rec.foreign_track_number = None
        rec.sys_track_number = incoming_mmsi

        # Reference enrichment is field-specific. A reference source only
        # participates when it actually matched the vessel. Missing values then
        # fall through according to REFERENCE_FALLBACK_PRIORITY.
        matched_sources = {
            "NSC": ctx.nsc_matched,
            "PANS": ctx.pans_matched,
            "WRS": ctx.wrs_matched,
        }

        def ref_order_for(logical_field):
            return tuple(
                source for source in _reference_order(logical_field)
                if matched_sources.get(source, False)
            )

        def ref_value(logical_field, *fields):
            for source in ref_order_for(logical_field):
                prefix = source.lower()
                for field in fields:
                    value = getattr(ctx, f"{prefix}_{field}", None)
                    if value not in (None, ""):
                        return value
            return None

        resolved_name = None
        if incoming_name and incoming_name.upper() not in ("UNKNOWN", "-", "N/A", "NONE"):
            resolved_name = incoming_name
        else:
            resolved_name = ref_value("vessel.name", "vessel_name")
        rec.vessel_name = sanitize_string(resolved_name)

        if not rec.id_callsign:
            rec.id_callsign = ref_value("id.callsign", "callsign")

        if not rec.id_imo or not is_valid_imo(rec.id_imo):
            for source in ref_order_for("id.imo"):
                value = getattr(ctx, f"{source.lower()}_imo", None)
                if value and is_valid_imo(value):
                    rec.id_imo = value
                    break

        if rec.ais_typeAndCargo is None:
            # PANS/NSC store descriptive vessel type text; WRS also has a
            # numeric AIS type decode. Prefer the first available source and
            # retain the existing WRS numeric decode as the WRS fallback.
            for source in ref_order_for("ais.typeAndCargo"):
                if source == "PANS" and ctx.pans_vessel_type:
                    rec.ais_typeAndCargo = ctx.pans_vessel_type
                elif source == "NSC" and ctx.nsc_type:
                    rec.ais_typeAndCargo = ctx.nsc_type
                elif source == "WRS":
                    if ctx.wrs_ais_type_code is not None:
                        rec.ais_typeAndCargo = normalize_type_and_cargo(ctx.wrs_ais_type_code)
                    elif ctx.wrs_vessel_type:
                        rec.ais_typeAndCargo = ctx.wrs_vessel_type
                if rec.ais_typeAndCargo is not None:
                    break

        if not rec.vessel_description:
            rec.vessel_description = ref_value("vessel.description", "vessel_type")

        if rec.vessel_length is None:
            rec.vessel_length = ref_value("vessel.length", "loa")
        if rec.vessel_beam is None:
            rec.vessel_beam = ref_value("vessel.beam", "breadth", "beam")
        if rec.vessel_draft is None:
            rec.vessel_draft = ref_value("vessel.draft", "draft", "max_draft")
        if rec.vessel_grosstonnage is None:
            rec.vessel_grosstonnage = ref_value("vessel.grosstonnage", "gross", "grt")

        effective_vigilance = ctx.wrs_vigilance_score if ctx.wrs_vigilance_score is not None else rec.id_mmsi_destination
        if effective_vigilance is not None:
            rec.id_mmsi_destination = int(effective_vigilance)
            score = float(effective_vigilance)
            # iTrackLib contract uses numeric identity categories: Friend=1, Neutral=3, Suspect=4.
            rec.cat_identity = 1 if score < 300 else (4 if score > 600 else 3)

        # Voyage fallback policy is NSC -> PANS -> WRS. The current NSC schema
        # has no voyage columns, so populated voyage values currently come from
        # PANS and then WRS calling data. Incoming values remain authoritative.
        voyage_fields = {
            "voyage_destination": {
                "PANS": ("pans_berman_dest", "pans_npc"),
                "WRS": ("wrs_calling_place",),
                "NSC": (),
            },
            "voyage_origin": {
                "PANS": ("pans_org_dep",),
                "WRS": ("wrs_calling_place",),
                "NSC": (),
            },
            "voyage_departure": {
                "PANS": ("pans_lpc", "pans_berman_lpc"),
                "WRS": ("wrs_calling_sailing",),
                "NSC": (),
            },
            "voyage_arrival": {
                "PANS": ("pans_berman_eta",),
                "WRS": ("wrs_calling_arrival",),
                "NSC": (),
            },
            "voyage_eta": {
                "PANS": ("pans_eta", "pans_berman_eta"),
                "WRS": (),
                "NSC": (),
            },
            "voyage_etd": {
                "PANS": ("pans_etd", "pans_berman_etd"),
                "WRS": (),
                "NSC": (),
            },
        }
        # Convert an incoming destination as well as a reference-supplied
        # destination. This keeps UN/LOCODE handling independent of source.
        if rec.voyage_destination:
            rec.voyage_destination = resolve_destination(rec.voyage_destination)

        for attr, source_fields in voyage_fields.items():
            if getattr(rec, attr, None):
                continue
            logical_field = attr.replace("_", ".", 1)
            # attr names map directly to the canonical voyage.* fields below.
            logical_field = {
                "voyage_destination": "voyage.destination",
                "voyage_origin": "voyage.origin",
                "voyage_departure": "voyage.departure",
                "voyage_arrival": "voyage.arrival",
                "voyage_eta": "voyage.eta",
                "voyage_etd": "voyage.etd",
            }.get(attr, logical_field)
            for source in ref_order_for(logical_field):
                for field in source_fields.get(source, ()):
                    value = getattr(ctx, field, None)
                    if value not in (None, ""):
                        if attr == "voyage_destination":
                            value = resolve_destination(value)
                        setattr(rec, attr, value)
                        break
                if getattr(rec, attr, None):
                    break

        if ctx.wrs_status_decode:
            rec.cat_annotation = ctx.wrs_status_decode

        # Final fallback: the cumulative last-known reference for this MMSI.
        # Only fields in MMSI_REFERENCE_FIELDS are eligible, so dynamic
        # position/kinematics/timestamps are never copied from an old message.
        history_recovered = []
        for logical in MMSI_REFERENCE_FIELDS:
            attr = LOGICAL_TO_ATTR.get(logical)
            if not attr or getattr(rec, attr, None) not in (None, ""):
                continue
            value = history.get(logical)
            if value not in (None, ""):
                if logical == "voyage.destination":
                    value = resolve_destination(value)
                setattr(rec, attr, value)
                history_recovered.append(logical)


        # Vessel remarks are a structured intelligence summary.
        # Keep the selected source-aligned intelligence fields visible in the
        # XML vessel.remarks field. Incoming/operator remarks are preserved
        # separately above; reference values never overwrite live fields.
        def remark_line(source: str, label: str, value: str) -> str:
            return f"{source:<8} | {label:<18} : {value}"

        def clean_remark_value(value, default="UNAVAILABLE"):
            if value in (None, "", "-", "None", "N/A"):
                return default
            return " ".join(str(value).strip().split())

        def format_remark_date(value):
            value = clean_remark_value(value, "")
            if not value:
                return ""
            # NSC dates are normally ISO/date strings. Keep unknown formats
            # unchanged rather than guessing.
            for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
                try:
                    from datetime import datetime
                    return datetime.strptime(value, fmt).strftime("%d-%m-%Y")
                except ValueError:
                    pass
            return value

        remarks_lines: List[str] = []

        if rec.vessel_remarks and rec.vessel_remarks not in ("-", "None"):
            for incoming_remark in str(rec.vessel_remarks).splitlines():
                incoming_remark = incoming_remark.strip()
                if incoming_remark:
                    remarks_lines.append(remark_line("INCOMING", "REMARKS", incoming_remark))

        # WRS intelligence: the four selected WRS remark categories.
        remarks_lines.append(remark_line(
            "WRS", "AIS SPOOFING RISK",
            clean_remark_value(ctx.wrs_ais_spoofing_detail, "NONE"),
        ))
        remarks_lines.append(remark_line(
            "WRS", "AIS GAP RISK",
            clean_remark_value(ctx.wrs_ais_gap_detail, "NONE"),
        ))
        remarks_lines.append(remark_line(
            "WRS", "VIGILANCE SCORE",
            clean_remark_value(ctx.wrs_vigilance_score, "NONE"),
        ))
        remarks_lines.append(remark_line(
            "WRS", "SANCTIONS",
            clean_remark_value(ctx.wrs_sanctions_detail, "NONE"),
        ))

        # PANS intelligence: current/latest voyage and cargo/hazardous cargo.
        voyage_parts = []
        destination = ctx.pans_berman_dest or ctx.pans_npc
        if destination:
            voyage_parts.append(f"NEXT PORT={clean_remark_value(destination)}")
        if ctx.pans_eta or ctx.pans_berman_eta:
            voyage_parts.append(f"ETA={clean_remark_value(ctx.pans_eta or ctx.pans_berman_eta)}")
        if ctx.pans_etd or ctx.pans_berman_etd:
            voyage_parts.append(f"ETD={clean_remark_value(ctx.pans_etd or ctx.pans_berman_etd)}")
        if ctx.pans_vcn:
            voyage_parts.append(f"VCN={clean_remark_value(ctx.pans_vcn)}")
        remarks_lines.append(remark_line(
            "PANS", "VOYAGE",
            " | ".join(voyage_parts) if voyage_parts else "UNAVAILABLE",
        ))

        cargo_parts = []
        if ctx.pans_cargo_description:
            cargo_parts.append(clean_remark_value(ctx.pans_cargo_description))
        if ctx.pans_cargo_tonnage is not None:
            cargo_parts.append(f"{ctx.pans_cargo_tonnage:g} MT")
        if ctx.pans_hazardous:
            cargo_parts.append(
                f"HAZARDOUS={'YES' if str(ctx.pans_hazardous).upper() in ('Y','YES','TRUE','1') else 'NO'}"
            )
        remarks_lines.append(remark_line(
            "PANS", "CARGO",
            " | ".join(cargo_parts) if cargo_parts else "UNAVAILABLE",
        ))

        # NSC intelligence: region and validity window.
        remarks_lines.append(remark_line(
            "NSC", "REGION",
            clean_remark_value(ctx.nsc_region, "UNAVAILABLE"),
        ))
        validity_start = format_remark_date(ctx.nsc_begin_date)
        validity_end = format_remark_date(ctx.nsc_end_date)
        validity = ""
        if validity_start or validity_end:
            validity = f"{validity_start or 'UNKNOWN'} TO {validity_end or 'UNKNOWN'}"
        remarks_lines.append(remark_line(
            "NSC", "VALIDITY",
            validity or "UNAVAILABLE",
        ))

        remarks_lines.append(remark_line("SOURCE", "FEED", get_source_label(rec.source_name)))
        rec.vessel_remarks = "\n".join(remarks_lines)

        # Preserve field-level provenance for acceptance/audit tooling. The
        # classification follows the actual enrichment order: incoming -> PANS
        # -> NSC -> WRS -> persistent MMSI history.
        reference_candidates = {
            "ais.typeAndCargo": {
                "PANS": ("pans_vessel_type",), "NSC": ("nsc_type",),
                "WRS": ("wrs_ais_type_code", "wrs_vessel_type"),
            },
            "cat.annotation": {"WRS": ("wrs_status_decode",)},
            "cat.identity": {"WRS": ("wrs_vigilance_score",)},
            "foreign.track.number": {"PANS": ("pans_mmsi",), "NSC": ("nsc_mmsi",), "WRS": ("wrs_mmsi",)},
            "id.callsign": {"PANS": ("pans_callsign",), "NSC": ("nsc_callsign",), "WRS": ("wrs_callsign",)},
            "id.imo": {"PANS": ("pans_imo",), "NSC": ("nsc_imo",), "WRS": ("wrs_imo",)},
            "id.mmsi.destination": {"WRS": ("wrs_vigilance_score",)},
            "vessel.beam": {"PANS": ("pans_beam",), "WRS": ("wrs_breadth",)},
            "vessel.description": {"PANS": ("pans_vessel_type",), "NSC": ("nsc_type",), "WRS": ("wrs_vessel_type",)},
            "vessel.draft": {"PANS": ("pans_max_draft",), "WRS": ("wrs_draft",)},
            "vessel.grosstonnage": {"PANS": ("pans_grt",), "WRS": ("wrs_gross",)},
            "vessel.length": {"PANS": ("pans_loa",), "WRS": ("wrs_loa",)},
            "vessel.name": {"PANS": ("pans_vessel_name",), "NSC": ("nsc_vessel_name",), "WRS": ("wrs_vessel_name",)},
            "voyage.arrival": {"PANS": ("pans_berman_eta",), "WRS": ("wrs_calling_arrival",)},
            "voyage.departure": {"PANS": ("pans_lpc", "pans_berman_lpc"), "WRS": ("wrs_calling_sailing",)},
            "voyage.destination": {"PANS": ("pans_berman_dest", "pans_npc"), "WRS": ("wrs_calling_place",)},
            "voyage.eta": {"PANS": ("pans_eta", "pans_berman_eta")},
            "voyage.etd": {"PANS": ("pans_etd", "pans_berman_etd")},
            "voyage.origin": {"PANS": ("pans_org_dep",), "WRS": ("wrs_calling_place",)},
        }
        provenance = {}
        for logical, attr in LOGICAL_TO_ATTR.items():
            value = getattr(rec, attr, None)
            if value in (None, ""):
                provenance[logical] = "NONE"
                continue
            if incoming_values.get(attr) not in (None, ""):
                provenance[logical] = "INCOMING"
                continue

            matched_source = None
            for source in ref_order_for(logical):
                for field in reference_candidates.get(logical, {}).get(source, ()):
                    ref_value = getattr(ctx, field, None)
                    if ref_value in (None, ""):
                        continue
                    if logical == "ais.typeAndCargo" and source == "WRS" and ctx.wrs_ais_type_code is not None:
                        try:
                            if str(value) == str(normalize_type_and_cargo(ctx.wrs_ais_type_code)):
                                matched_source = source
                                break
                        except Exception:
                            pass
                    elif str(value) == str(ref_value):
                        matched_source = source
                        break
                if matched_source:
                    break

            if matched_source:
                provenance[logical] = matched_source
            elif logical in history and history.get(logical) not in (None, "") and str(value) == str(history.get(logical)):
                provenance[logical] = "MMSI_HISTORY"
            else:
                provenance[logical] = "DERIVED"

        rec.raw_attributes["enrichment_provenance"] = provenance
        rec.raw_attributes["mmsi_history_recovered"] = history_recovered

        # Persist the cumulative reference after enrichment. Every transaction
        # updates the same unique MMSI record; blank current values never erase
        # an earlier known value. The operation is committed with track state.
        if effective_mmsi and is_valid_mmsi(effective_mmsi):
            reference_values = {
                logical: getattr(rec, attr, None)
                for logical, attr in LOGICAL_TO_ATTR.items()
                if logical in MMSI_REFERENCE_FIELDS
            }
            rec.track_flag_active = self.state_db.upsert(
                mmsi=effective_mmsi,
                imo=rec.id_imo if is_valid_imo(rec.id_imo) else None,
                vessel_name=rec.vessel_name,
                latitude=rec.kinematic_pos_lla_lat,
                longitude=rec.kinematic_pos_lla_lon,
                tx_timestamp_iso=str(rec.timestamp_source or ""),
                source=rec.source_name,
                reference_values=reference_values,
            )
        else:
            rec.track_flag_active = True
        return rec
