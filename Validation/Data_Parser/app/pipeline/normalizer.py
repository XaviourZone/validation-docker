"""
Normalizer bridging raw decoded input (XML, CSV, NMEA CommonVesselRecord)
into the standardized 41 logical fields.

Preserves:
- Exact 41 logical field names
- Source provenance
- Safe conversions (degrees -> radians, knots -> m/s, timestamps -> epoch ms)
- Guard against double-conversions (checks units)
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

from ..models.common import CommonVesselRecord
from .source_registry import (
    deg_to_rad,
    get_source_id,
    get_source_label,
    is_valid_imo,
    is_valid_mmsi,
    iso_to_epoch_ms,
    knots_to_ms,
    sanitize_string,
)
from .xml_decoder import DecodedTrack

log = logging.getLogger("parser.normalizer")

# Downstream iTrackLib expects descriptive AIS navigation/type strings, not raw numeric codes.
NAV_STATUS_TEXT = {
    0: "UNDER WAY USING ENGINE", 1: "ANCHORED", 2: "NOT UNDER COMMAND",
    3: "RESTRICTED MANOEUVRABILITY", 4: "CONSTRAINED BY HER DRAUGHT",
    5: "MOORED", 6: "AGROUND", 7: "ENGAGED IN FISHING", 8: "UNDER WAY SAILING",
    9: "RESERVED FOR FUTURE AMENDMENT OF NAVIGATIONAL STATUS FOR SHIPS CARRYING DG, HS, OR MP, OR IMO HAZARD OR POLLUTANT CATEGORY C (HSC)",
    10: "RESERVED FOR FUTURE AMENDMENT OF NAVIGATIONAL STATUS FOR SHIPS CARRYING DG, HS OR MP, OR IMO HAZARD OR POLLUTANT CATEGORY A (WIG)",
    11: "RESERVED FOR FUTURE USE", 12: "RESERVED FOR FUTURE USE", 13: "RESERVED FOR FUTURE USE",
    14: "RESERVED FOR FUTURE USE", 15: "NOT DEFINED",
}

# AIS type 5/19 numeric vessel type -> the labels used by the authoritative
# iTrackLib typeAndCargo decoder. Category-specific AIS codes are preserved.
AIS_TYPE_TEXT = {
    0: "UNDEFINED",
    1: "GPS", 2: "GLONASS", 3: "COMBINED GPS AND GLONASS", 4: "LORAN C",
    5: "CHAYKA", 6: "INTEGRATED NAVIGATION SYSTEM", 7: "SURVEYED",
    8: "NOT USED 8", 9: "NOT USED 9", 10: "RESERVED FOR FUTURE USE 10",
    11: "RESERVED FOR FUTURE USE 11", 12: "RESERVED FOR FUTURE USE 12",
    13: "RESERVED FOR FUTURE USE 13", 14: "RESERVED FOR FUTURE USE 14",
    15: "RESERVED FOR FUTURE USE 15", 16: "RESERVED FOR FUTURE USE 16",
    17: "RESERVED FOR FUTURE USE 17", 18: "RESERVED FOR FUTURE USE 18",
    19: "RESERVED FOR FUTURE USE 19",
    20: "WIG", 21: "WIG CATEGORY A", 22: "WIG CATEGORY B", 23: "WIG CATEGORY C", 24: "WIG CATEGORY D",
    25: "WIG 25", 26: "WIG 26", 27: "WIG 27", 28: "WIG 28", 29: "WIG 29",
    30: "FISHING VESSEL", 31: "TOWING VESSEL",
    32: "TOWING VESSEL WITH LENGTH OF TOW EXCEEDING 200 M OR BREADTH EXCEEDING 25 M",
    33: "VESSEL ENGAGED IN DREDGING OR UNDERWATER OPERATIONS",
    34: "VESSEL ENGAGED IN DIVING OPERATIONS",
    35: "VESSEL ENGAGED IN MILITARY OPERATIONS",
    36: "SAILING VESSEL", 37: "PLEASURE CRAFT",
    38: "RESERVED FOR FUTURE USE 38", 39: "RESERVED FOR FUTURE USE 39",
    40: "HSC", 41: "HSC CATEGORY A", 42: "HSC CATEGORY B", 43: "HSC CATEGORY C", 44: "HSC CATEGORY D",
    45: "HSC 45", 46: "HSC 46", 47: "HSC 47", 48: "HSC 48", 49: "HSC 49",
    50: "PILOT VESSEL", 51: "SEARCH AND RESCUE VESSEL", 52: "TUG", 53: "PORT TENDER",
    54: "VESSEL WITH ANTI-POLLUTION FACILITIES OR EQUIPMENT", 55: "LAW ENFORCEMENT VESSEL",
    56: "LOCAL VESSEL TYPE 56", 57: "LOCAL VESSEL TYPE 57", 58: "MEDICAL TRANSPORT",
    59: "SHIP ACCORDING TO RR RESOLUTION NO. 18",
    60: "PASSENGER SHIP", 61: "PASSENGER SHIP CATEGORY A", 62: "PASSENGER SHIP CATEGORY B",
    63: "PASSENGER SHIP CATEGORY C", 64: "PASSENGER SHIP CATEGORY D",
    65: "PASSENGER SHIP 65", 66: "PASSENGER SHIP 66", 67: "PASSENGER SHIP 67",
    68: "PASSENGER SHIP 68", 69: "PASSENGER SHIP 69",
    70: "CARGO SHIP", 71: "CARGO SHIP CATEGORY A", 72: "CARGO SHIP CATEGORY B",
    73: "CARGO SHIP CATEGORY C", 74: "CARGO SHIP CATEGORY D",
    75: "CARGO SHIP 75", 76: "CARGO SHIP 76", 77: "CARGO SHIP 77", 78: "CARGO SHIP 78", 79: "CARGO SHIP 79",
    80: "TANKER", 81: "TANKER CATEGORY A", 82: "TANKER CATEGORY B", 83: "TANKER CATEGORY C",
    84: "TANKER CATEGORY D", 85: "TANKER 85", 86: "TANKER 86", 87: "TANKER 87", 88: "TANKER 88", 89: "TANKER 89",
    90: "OTHER VESSEL", 91: "OTHER VESSEL CATEGORY A", 92: "OTHER VESSEL CATEGORY B",
    93: "OTHER VESSEL CATEGORY C", 94: "OTHER VESSEL CATEGORY D",
    95: "OTHER VESSEL 95", 96: "OTHER VESSEL 96", 97: "OTHER VESSEL 97", 98: "OTHER VESSEL 98", 99: "OTHER VESSEL 99",
}

def normalize_nav_status(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return NAV_STATUS_TEXT.get(int(float(stripped)), "NOT DEFINED")
        except ValueError:
            return stripped
    try:
        return NAV_STATUS_TEXT.get(int(value), "NOT DEFINED")
    except (TypeError, ValueError):
        return None


def normalize_type_and_cargo(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            code = int(float(stripped))
        except ValueError:
            return stripped
    else:
        try:
            code = int(value)
        except (TypeError, ValueError):
            return str(value)
    return AIS_TYPE_TEXT.get(code, "OTHER VESSEL")


# The 41 canonical logical field identifiers
LOGICAL_FIELDS_41 = [
    "ais.lenToBow",
    "ais.lenToStern",
    "ais.navStatus",
    "ais.typeAndCargo",
    "ais.widthToPort",
    "ais.widthToStarboard",
    "app.message.id",
    "cat.annotation",
    "cat.category",
    "cat.identity",
    "foreign.track.number",
    "id.callsign",
    "id.imo",
    "id.mmsi",
    "id.mmsi.destination",
    "kinematic.course.true",
    "kinematic.flag.3d",
    "kinematic.heading.true",
    "kinematic.pos.lla.alt",
    "kinematic.pos.lla.lat",
    "kinematic.pos.lla.lon",
    "kinematic.speed",
    "sys.source.id",
    "sys.track.number",
    "timestamp.receipt",
    "timestamp.source",
    "track.flag.active",
    "track.quality",
    "vessel.beam",
    "vessel.description",
    "vessel.draft",
    "vessel.grosstonnage",
    "vessel.length",
    "vessel.name",
    "vessel.remarks",
    "voyage.arrival",
    "voyage.departure",
    "voyage.destination",
    "voyage.eta",
    "voyage.etd",
    "voyage.origin",
]


@dataclass
class NormalizedRecord:
    """Standardized representation of all 41 logical fields for one vessel transmission."""
    source_name: str
    message_id: str

    # 41 logical fields
    ais_lenToBow:           Optional[int]   = None
    ais_lenToStern:         Optional[int]   = None
    ais_navStatus:          Optional[Any]   = None
    ais_typeAndCargo:       Optional[Any]   = None
    ais_widthToPort:        Optional[float] = None
    ais_widthToStarboard:   Optional[float] = None
    app_message_id:         Optional[int]   = None
    cat_annotation:         Optional[str]   = None
    cat_category:           Optional[Any]   = "Surface"
    cat_identity:           Optional[Any]   = "Unknown"
    foreign_track_number:   Optional[int]   = None
    id_callsign:            Optional[str]   = None
    id_imo:                 Optional[int]   = None
    id_mmsi:                Optional[int]   = None
    id_mmsi_destination:     Optional[int]   = None
    kinematic_course_true:  Optional[float] = None  # in radians
    kinematic_flag_3d:      bool            = False
    kinematic_heading_true: Optional[float] = None  # in radians
    kinematic_pos_lla_alt:  Optional[float] = None  # in meters
    kinematic_pos_lla_lat:  Optional[float] = None  # in radians
    kinematic_pos_lla_lon:  Optional[float] = None  # in radians
    kinematic_speed:        Optional[float] = None  # in m/s
    sys_source_id:          int             = 0
    sys_track_number:       Optional[int]   = None
    timestamp_receipt:      Optional[int]   = None  # epoch ms
    timestamp_source:       Optional[int]   = None  # epoch ms
    track_flag_active:      bool            = True
    track_quality:          int             = 15
    vessel_beam:            Optional[float] = None  # in meters
    vessel_description:     Optional[str]   = None
    vessel_draft:           Optional[float] = None  # in meters
    vessel_grosstonnage:    Optional[float] = None
    vessel_length:          Optional[float] = None  # in meters
    vessel_name:            Optional[str]   = None
    vessel_remarks:         Optional[str]   = None
    voyage_arrival:         Optional[str]   = None
    voyage_departure:       Optional[str]   = None
    voyage_destination:     Optional[str]   = None
    voyage_eta:             Optional[Any]   = None
    voyage_etd:             Optional[Any]   = None
    voyage_origin:          Optional[str]   = None

    # Extra supported fields (not replacing the 41)
    kinematic_rot:          Optional[float] = None

    # Traceability container: stores original raw values
    raw_attributes: Dict[str, Any] = field(default_factory=dict)

    def to_logical_dict(self) -> Dict[str, Any]:
        """Map back to the 41 canonical dotted keys."""
        return {
            "ais.lenToBow":            self.ais_lenToBow,
            "ais.lenToStern":          self.ais_lenToStern,
            "ais.navStatus":           self.ais_navStatus,
            "ais.typeAndCargo":        self.ais_typeAndCargo,
            "ais.widthToPort":         self.ais_widthToPort,
            "ais.widthToStarboard":    self.ais_widthToStarboard,
            "app.message.id":          self.app_message_id,
            "cat.annotation":          self.cat_annotation,
            "cat.category":            self.cat_category,
            "cat.identity":            self.cat_identity,
            "foreign.track.number":    self.foreign_track_number,
            "id.callsign":             self.id_callsign,
            "id.imo":                  self.id_imo,
            "id.mmsi":                 self.id_mmsi,
            "id.mmsi.destination":     self.id_mmsi_destination,
            "kinematic.course.true":    self.kinematic_course_true,
            "kinematic.flag.3d":        self.kinematic_flag_3d,
            "kinematic.heading.true":   self.kinematic_heading_true,
            "kinematic.pos.lla.alt":    self.kinematic_pos_lla_alt,
            "kinematic.pos.lla.lat":    self.kinematic_pos_lla_lat,
            "kinematic.pos.lla.lon":    self.kinematic_pos_lla_lon,
            "kinematic.speed":          self.kinematic_speed,
            "sys.source.id":           self.sys_source_id,
            "sys.track.number":        self.sys_track_number,
            "timestamp.receipt":       self.timestamp_receipt,
            "timestamp.source":        self.timestamp_source,
            "track.flag.active":       self.track_flag_active,
            "track.quality":           self.track_quality,
            "vessel.beam":             self.vessel_beam,
            "vessel.description":      self.vessel_description,
            "vessel.draft":            self.vessel_draft,
            "vessel.grosstonnage":     self.vessel_grosstonnage,
            "vessel.length":           self.vessel_length,
            "vessel.name":             self.vessel_name,
            "vessel.remarks":          self.vessel_remarks,
            "voyage.arrival":          self.voyage_arrival,
            "voyage.departure":        self.voyage_departure,
            "voyage.destination":      self.voyage_destination,
            "voyage.eta":              self.voyage_eta,
            "voyage.etd":              self.voyage_etd,
            "voyage.origin":           self.voyage_origin,
        }


def normalize_from_common_record(
    rec: CommonVesselRecord,
    receipt_time_ms: Optional[int] = None,
) -> NormalizedRecord:
    """Convert source-native CommonVesselRecord into the canonical 41-field model."""
    source_id = get_source_id(rec.source)
    rec_ms = receipt_time_ms or int(datetime.now(timezone.utc).timestamp() * 1000)
    tx_ms = iso_to_epoch_ms(rec.timestamp) or rec_ms

    lat_rad = deg_to_rad(rec.latitude) if rec.latitude is not None else None
    lon_rad = deg_to_rad(rec.longitude) if rec.longitude is not None else None
    cog_rad = deg_to_rad(rec.cog) if rec.cog is not None else None
    hdg_rad = deg_to_rad(rec.true_heading) if rec.true_heading is not None else None
    speed_ms = knots_to_ms(rec.sog) if rec.sog is not None else None

    valid_mmsi = rec.mmsi if is_valid_mmsi(rec.mmsi) else None

    return NormalizedRecord(
        source_name=rec.source,
        message_id=rec.message_id,
        sys_source_id=source_id,
        sys_track_number=rec.mmsi,
        foreign_track_number=valid_mmsi,
        id_mmsi=rec.mmsi,
        id_imo=rec.imo,
        id_callsign=sanitize_string(rec.callsign),
        vessel_name=sanitize_string(rec.vessel_name),
        kinematic_pos_lla_lat=lat_rad,
        kinematic_pos_lla_lon=lon_rad,
        kinematic_course_true=cog_rad,
        kinematic_heading_true=hdg_rad,
        kinematic_speed=speed_ms,
        kinematic_pos_lla_alt=rec.altitude,
        kinematic_flag_3d=rec.altitude is not None,
        ais_lenToBow=int(rec.len_to_bow) if rec.len_to_bow is not None else None,
        ais_lenToStern=int(rec.len_to_stern) if rec.len_to_stern is not None else None,
        ais_widthToPort=float(rec.width_to_port) if rec.width_to_port is not None else None,
        ais_widthToStarboard=float(rec.width_to_starboard) if rec.width_to_starboard is not None else None,
        ais_navStatus=normalize_nav_status(rec.nav_status),
        ais_typeAndCargo=normalize_type_and_cargo(rec.vessel_type),
        app_message_id=rec.app_message_id,
        vessel_description=normalize_type_and_cargo(rec.vessel_type),
        vessel_length=rec.length,
        vessel_beam=rec.width,
        vessel_draft=rec.draught,
        vessel_grosstonnage=rec.gross_tonnage,
        vessel_remarks=None,
        voyage_destination=sanitize_string(rec.destination),
        voyage_origin=sanitize_string(rec.origin),
        voyage_arrival=sanitize_string(rec.arrival),
        voyage_departure=sanitize_string(rec.departure),
        voyage_eta=rec.eta,
        timestamp_source=tx_ms,
        timestamp_receipt=rec_ms,
        track_quality=15,
        cat_category="Surface",
        cat_identity="Unknown",
        raw_attributes={
            "raw_payload": rec.raw_payload,
            **(rec.raw_attributes or {}),
        },
    )

def normalize_from_decoded_track(
    track: DecodedTrack,
    source_name: str,
    message_id: str,
    receipt_time_ms: Optional[int] = None,
) -> NormalizedRecord:
    """Convert DecodedTrack (from XML decoder) to NormalizedRecord."""
    rec_ms = receipt_time_ms or int(datetime.now(timezone.utc).timestamp() * 1000)

    # Resolve source ID: check sys.source.id first, else envelope source
    src_id_val = track.get("sys.source.id")
    if src_id_val is not None:
        try:
            sys_src_id = int(src_id_val)
        except Exception:
            sys_src_id = get_source_id(source_name)
    else:
        sys_src_id = get_source_id(source_name)

    # MMSI resolution: check id.mmsi or vessel.mmsi
    mmsi_val = track.get("id.mmsi") or track.get("vessel.mmsi") or track.get("sys.track.number")
    mmsi: Optional[int] = None
    if mmsi_val is not None:
        try:
            mmsi = int(float(str(mmsi_val)))
        except Exception:
            pass

    # IMO resolution: check id.imo or vessel.imo
    imo_val = track.get("id.imo") or track.get("vessel.imo")
    imo: Optional[int] = None
    if imo_val is not None:
        try:
            imo = int(float(str(imo_val)))
        except Exception:
            pass

    # Callsign: id.callsign or vessel.callsign
    callsign = track.get("id.callsign") or track.get("vessel.callsign")

    # Name: vessel.name
    vessel_name = track.get("vessel.name")

    # Coordinates
    lat = None
    lon = None

    # Check kinematic.pos object first
    pos_obj = track.get("kinematic.pos") or track.get("kinematic.pos.ext")
    if isinstance(pos_obj, dict) and pos_obj.get("lat") is not None:
        u = pos_obj.get("u", "deg")
        raw_lat = pos_obj.get("lat")
        raw_lon = pos_obj.get("lon")
        lat = raw_lat if u == "rad" else (deg_to_rad(raw_lat) if raw_lat is not None else None)
        lon = raw_lon if u == "rad" else (deg_to_rad(raw_lon) if raw_lon is not None else None)
    else:
        # Check kinematic.pos.lla.lat / lon
        raw_lat = track.get("kinematic.pos.lla.lat")
        raw_lon = track.get("kinematic.pos.lla.lon")
        lat_u = track.get_unit("kinematic.pos.lla.lat") or "rad"
        lon_u = track.get_unit("kinematic.pos.lla.lon") or "rad"

        if raw_lat is not None:
            lat = raw_lat if lat_u == "rad" else deg_to_rad(float(raw_lat))
        if raw_lon is not None:
            lon = raw_lon if lon_u == "rad" else deg_to_rad(float(raw_lon))

    # Course: kinematic.course.true or kinematic.course
    cog = None
    cog_val = track.get("kinematic.course.true") or track.get("kinematic.course")
    cog_u = track.get_unit("kinematic.course.true") or track.get_unit("kinematic.course") or "rad"
    if cog_val is not None:
        try:
            fcog = float(cog_val)
            cog = fcog if cog_u == "rad" else deg_to_rad(fcog)
        except Exception:
            pass

    # Heading: kinematic.heading.true or kinematic.heading
    hdg = None
    hdg_val = track.get("kinematic.heading.true") or track.get("kinematic.heading")
    hdg_u = track.get_unit("kinematic.heading.true") or track.get_unit("kinematic.heading") or "rad"
    if hdg_val is not None:
        try:
            fhdg = float(hdg_val)
            hdg = fhdg if hdg_u == "rad" else deg_to_rad(fhdg)
        except Exception:
            pass

    # Speed: kinematic.speed
    spd = None
    spd_val = track.get("kinematic.speed")
    spd_u = track.get_unit("kinematic.speed") or "m/s"
    if spd_val is not None:
        try:
            fspd = float(spd_val)
            spd = fspd if spd_u == "m/s" else knots_to_ms(fspd)
        except Exception:
            pass

    # Altitude / 3D
    alt_val = track.get("kinematic.pos.lla.alt")
    alt: Optional[float] = None
    if alt_val is not None:
        try:
            alt = float(alt_val)
        except Exception:
            pass
    flag_3d = (alt is not None and alt != 0.0) or (track.get("kinematic.flag.3d") is True)

    # Timestamps
    tx_time = iso_to_epoch_ms(track.get("timestamp.source")) or rec_ms
    rx_time = iso_to_epoch_ms(track.get("timestamp.receipt")) or rec_ms

    # Track numbers
    foreign_trk = track.get("foreign.track.number")
    foreign_num: Optional[int] = None
    if foreign_trk is not None:
        try:
            foreign_num = int(float(str(foreign_trk)))
        except Exception:
            pass
    if foreign_num is None and is_valid_mmsi(mmsi):
        foreign_num = mmsi

    # Dimensions
    len_bow = track.get("ais.lenToBow") or track.get("vessel.dim.bow")
    len_stern = track.get("ais.lenToStern") or track.get("vessel.dim.stern")
    w_port = track.get("ais.widthToPort") or track.get("vessel.dim.port")
    w_starboard = track.get("ais.widthToStarboard") or track.get("vessel.dim.starboard")
    v_len = track.get("vessel.length")
    v_beam = track.get("vessel.beam")
    v_draft = track.get("vessel.draft")
    v_gt = track.get("vessel.grosstonnage") or track.get("vessel.gt")

    # AIS types
    nav_status = track.get("ais.navStatus") or track.get("vessel.navstatus")
    type_cargo = track.get("ais.typeAndCargo") or track.get("vessel.type") or track.get("vessel.cargo")
    app_msg_id = track.get("app.message.id")

    # Categories
    cat_annotation = track.get("cat.annotation") or get_source_label(source_name)
    cat_category = track.get("cat.category") or "Surface"
    cat_identity = track.get("cat.identity") or "Unknown"

    # Destination / voyage
    voy_dest = track.get("voyage.destination") or track.get("vessel.destination")
    voy_orig = track.get("voyage.origin")
    voy_arr = track.get("voyage.arrival")
    voy_dep = track.get("voyage.departure")
    voy_eta = track.get("voyage.eta") or track.get("vessel.eta")
    voy_etd = track.get("voyage.etd")

    norm = NormalizedRecord(
        source_name=source_name,
        message_id=message_id,
        sys_source_id=sys_src_id,
        sys_track_number=mmsi,
        foreign_track_number=foreign_num,
        id_mmsi=mmsi,
        id_imo=imo,
        id_callsign=sanitize_string(callsign),
        vessel_name=sanitize_string(vessel_name),
        kinematic_pos_lla_lat=lat,
        kinematic_pos_lla_lon=lon,
        kinematic_course_true=cog,
        kinematic_heading_true=hdg,
        kinematic_speed=spd,
        kinematic_pos_lla_alt=alt,
        kinematic_flag_3d=flag_3d,
        ais_lenToBow=int(float(len_bow)) if len_bow is not None else None,
        ais_lenToStern=int(float(len_stern)) if len_stern is not None else None,
        ais_widthToPort=float(w_port) if w_port is not None else None,
        ais_widthToStarboard=float(w_starboard) if w_starboard is not None else None,
        ais_navStatus=normalize_nav_status(nav_status),
        ais_typeAndCargo=normalize_type_and_cargo(type_cargo),
        app_message_id=int(float(str(app_msg_id))) if app_msg_id is not None else None,
        cat_annotation=cat_annotation,
        cat_category=cat_category,
        cat_identity=cat_identity,
        id_mmsi_destination=int(float(str(track.get("id.mmsi.destination")))) if track.get("id.mmsi.destination") is not None else None,
        vessel_length=float(v_len) if v_len is not None else None,
        vessel_beam=float(v_beam) if v_beam is not None else None,
        vessel_draft=float(v_draft) if v_draft is not None else None,
        vessel_grosstonnage=float(v_gt) if v_gt is not None else None,
        vessel_description=track.get("vessel.description"),
        vessel_remarks=track.get("vessel.remarks"),
        voyage_destination=sanitize_string(voy_dest),
        voyage_origin=sanitize_string(voy_orig),
        voyage_arrival=sanitize_string(voy_arr),
        voyage_departure=sanitize_string(voy_dep),
        voyage_eta=voy_eta,
        voyage_etd=voy_etd,
        timestamp_source=tx_time,
        timestamp_receipt=rx_time,
        track_quality=15,
        raw_attributes=track.to_dict(),
    )
    return norm
