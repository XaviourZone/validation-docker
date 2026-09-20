"""
Reference database access layer.

Provides a single ReferenceDB object that:
- holds read-only connections to WRS, PANS, NSC SQLite databases
- exposes a resolve(mmsi, imo, callsign) method returning one VesselContext
- performs one compound lookup per record (not per field)
- uses in-process SQLite (thread-safe in WAL mode)
"""

import copy
import logging
import sqlite3
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("parser.reference")


# ──────────────────────────────────────────────────────────────────────────────
# Result container: all reference data for one vessel, fetched once
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Provenance:
    """Internal provenance tracking for resolved fields."""
    value: Any
    source: str         # 'WRS', 'PANS', 'NSC', 'INCOMING'
    match_method: str   # 'MMSI', 'IMO', 'CALLSIGN', 'VESSEL_NAME', 'PRIMARY'


@dataclass
class VesselContext:
    """All reference data resolved for one incoming record."""
    # Match flags & methods
    wrs_matched:       bool            = False
    wrs_match_method:  Optional[str]   = None
    pans_matched:      bool            = False
    pans_match_method: Optional[str]   = None
    nsc_matched:       bool            = False
    nsc_match_method:  Optional[str]   = None

    # Provenance tracking dictionary: field_name -> Provenance
    provenance: Dict[str, Provenance] = field(default_factory=dict)

    # WRS VESSELS
    wrs_vessel_id:     Optional[str]   = None
    wrs_imo:           Optional[int]   = None
    wrs_mmsi:          Optional[int]   = None  # WRS-stored MMSI (for correction)
    wrs_vessel_name:   Optional[str]   = None
    wrs_callsign:      Optional[str]   = None
    wrs_vessel_type:   Optional[str]   = None
    wrs_status:        Optional[str]   = None  # raw status code
    wrs_status_decode: Optional[str]   = None  # decoded status string
    wrs_gross:         Optional[float] = None  # VESSELS.GROSS (candidate for GRT)

    # WRS VESSEL_DIMENSIONS
    wrs_loa:           Optional[float] = None
    wrs_breadth:       Optional[float] = None
    wrs_draft:         Optional[float] = None

    # WRS VIGILANCE
    wrs_vigilance_score: Optional[float] = None

    # WRS analysis / risk signals used in vessel remarks
    wrs_ais_spoofing_detail: Optional[str] = None
    wrs_ais_gap_detail: Optional[str] = None
    wrs_ais_identity_detail: Optional[str] = None
    wrs_sanctions_detail: Optional[str] = None

    # WRS CALLINGS (most recent)
    wrs_calling_place:      Optional[str] = None
    wrs_calling_arrival:    Optional[str] = None
    wrs_calling_sailing:    Optional[str] = None

    # AIS type/cargo decode from WRS
    wrs_ais_type_code:  Optional[int]   = None  # numeric AIS code for vessel type

    # PANS VESPRO
    pans_vessel_name: Optional[str]   = None
    pans_callsign:    Optional[str]   = None
    pans_beam:        Optional[float] = None
    pans_loa:         Optional[float] = None
    pans_max_draft:   Optional[float] = None
    pans_grt:         Optional[float] = None
    pans_vessel_type: Optional[str]   = None
    pans_mmsi:        Optional[str]   = None
    pans_imo:         Optional[int]   = None

    # PANS CALINF
    pans_org_dep:     Optional[str]   = None
    pans_lpc:         Optional[str]   = None
    pans_npc:         Optional[str]   = None
    pans_eta:         Optional[str]   = None
    pans_etd:         Optional[str]   = None

    # PANS BERMAN
    pans_berman_dest: Optional[str]   = None
    pans_berman_lpc:  Optional[str]   = None
    pans_berman_eta:  Optional[str]   = None
    pans_berman_etd:  Optional[str]   = None
    pans_draft_fwd:   Optional[float] = None
    pans_draft_aft:   Optional[float] = None
    pans_vcn:         Optional[str]   = None
    pans_cargo_description: Optional[str] = None
    pans_cargo_tonnage: Optional[float] = None
    pans_hazardous:   Optional[str]   = None

    # NSC
    nsc_vessel_name:  Optional[str]   = None
    nsc_imo:          Optional[int]   = None
    nsc_mmsi:         Optional[int]   = None
    nsc_callsign:     Optional[str]   = None
    nsc_type:         Optional[str]   = None
    nsc_region:       Optional[str]   = None
    nsc_begin_date:   Optional[str]   = None
    nsc_end_date:     Optional[str]   = None

    # Reference DB that directly matched the transmitted MMSI.
    primary_mmsi_source: Optional[str] = None

    def record_provenance(self, field_name: str, value: Any, source: str, match_method: str):
        if value is not None:
            self.provenance[field_name] = Provenance(value=value, source=source, match_method=match_method)

    def is_pans_cleared(self) -> bool:
        return self.pans_matched

    def is_nsc_cleared(self) -> bool:
        return self.nsc_matched


def _find_default_db(subdir: str, filename: str) -> Path:
    """Find reference DB in standard locations."""
    # Try relative to current script
    cur = Path(__file__).resolve()
    for parent in [cur, *cur.parents]:
        cand = parent / "Validation" / "Database" / subdir / filename
        if cand.exists():
            return cand
        cand2 = parent / "Database" / subdir / filename
        if cand2.exists():
            return cand2
    return Path(f"Validation/Database/{subdir}/{filename}").resolve()


class ReferenceDB:
    """Thread-safe reference database access for WRS, PANS and NSC."""

    def __init__(
        self,
        wrs_path: Optional[Path] = None,
        pans_path: Optional[Path] = None,
        nsc_path: Optional[Path] = None,
    ):
        self._wrs_path  = wrs_path or _find_default_db("WRS", "wrs.db")
        self._pans_path = pans_path or _find_default_db("PANS", "pans.db")
        self._nsc_path  = nsc_path or _find_default_db("NSC", "nsc.db")
        self._lock = threading.Lock()
        # Reference DBs are read-only during parsing. A bounded cache avoids
        # repeating the same multi-query WRS/PANS/NSC resolution for every AIS
        # transmission of the same identity tuple.
        self._resolve_cache: OrderedDict[tuple, VesselContext] = OrderedDict()
        self._resolve_cache_max = 8192

        self._wrs_conn  = self._open(self._wrs_path,  "WRS")
        self._pans_conn = self._open(self._pans_path, "PANS")
        self._nsc_conn  = self._open(self._nsc_path,  "NSC")

    def _open(self, path: Path, label: str) -> Optional[sqlite3.Connection]:
        if not path.exists():
            log.warning(f"{label} database not found at {path}")
            return None
        try:
            conn = sqlite3.connect(str(path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as e:
            log.error(f"Cannot open {label} database: {e}")
            return None

    def resolve(
        self,
        mmsi: Optional[int],
        imo:  Optional[int],
        callsign: Optional[str] = None,
        vessel_name: Optional[str] = None,
    ) -> VesselContext:
        """
        Resolve all reference data for a vessel in one call.
        Uses MMSI as primary key; falls back to IMO, callsign, name.
        """
        key = self._resolve_cache_key(mmsi, imo, callsign, vessel_name)
        with self._lock:
            cached = self._resolve_cache.get(key)
            if cached is not None:
                self._resolve_cache.move_to_end(key)
                return copy.deepcopy(cached)

            ctx = VesselContext()
            self._resolve_wrs(ctx, mmsi, imo, callsign, vessel_name)
            self._resolve_pans(ctx, mmsi, imo, callsign, vessel_name)
            self._resolve_nsc(ctx, mmsi, imo, callsign, vessel_name)

            # Record the first direct MMSI match using the agreed source
            # check order. Field-level enrichment separately evaluates
            # PANS -> NSC -> WRS based on which data is actually available.
            if mmsi is not None:
                if ctx.pans_matched and ctx.pans_match_method == "MMSI":
                    ctx.primary_mmsi_source = "PANS"
                elif ctx.nsc_matched and ctx.nsc_match_method == "MMSI":
                    ctx.primary_mmsi_source = "NSC"
                elif ctx.wrs_matched and ctx.wrs_match_method == "MMSI":
                    ctx.primary_mmsi_source = "WRS"

            self._resolve_cache[key] = copy.deepcopy(ctx)
            self._resolve_cache.move_to_end(key)
            while len(self._resolve_cache) > self._resolve_cache_max:
                self._resolve_cache.popitem(last=False)
            return ctx

    @staticmethod
    def _resolve_cache_key(
        mmsi: Optional[int],
        imo: Optional[int],
        callsign: Optional[str],
        vessel_name: Optional[str],
    ) -> tuple:
        def norm_text(value):
            if value in (None, ""):
                return None
            return str(value).strip().upper()

        return (
            int(mmsi) if mmsi is not None else None,
            int(imo) if imo is not None else None,
            norm_text(callsign),
            norm_text(vessel_name),
        )

    # ── WRS ──────────────────────────────────────────────────────────────────

    # ── WRS ──────────────────────────────────────────────────────────────────

    def _resolve_wrs(
        self,
        ctx: VesselContext,
        mmsi: Optional[int],
        imo: Optional[int],
        callsign: Optional[str] = None,
        vessel_name: Optional[str] = None,
    ):
        if not self._wrs_conn:
            return
        c = self._wrs_conn.cursor()

        # 1. Find vessel record by MMSI -> IMO -> CALL_SIGN -> VESSEL_NAME
        row = None
        match_method = None
        if mmsi:
            rows = c.execute(
                "SELECT * FROM wrs_datasets_vessels WHERE MMSI=? LIMIT 2", (str(mmsi),)
            ).fetchall()
            if len(rows) == 1:
                row = rows[0]
                match_method = "MMSI"
            elif len(rows) > 1:
                log.warning(f"Ambiguous WRS match for MMSI={mmsi} ({len(rows)} records); match rejected")
        if row is None and imo:
            rows = c.execute(
                "SELECT * FROM wrs_datasets_vessels WHERE IMO=? LIMIT 2", (str(imo),)
            ).fetchall()
            if len(rows) == 1:
                row = rows[0]
                match_method = "IMO"
            elif len(rows) > 1:
                log.warning(f"Ambiguous WRS match for IMO={imo} ({len(rows)} records); match rejected")
        if row is None and callsign:
            rows = c.execute(
                "SELECT * FROM wrs_datasets_vessels WHERE CALL_SIGN=? LIMIT 2", (callsign,)
            ).fetchall()
            if len(rows) == 1:
                row = rows[0]
                match_method = "CALLSIGN"
            elif len(rows) > 1:
                log.warning(f"Ambiguous WRS match for CALLSIGN={callsign} ({len(rows)} records); match rejected")
        if row is None and vessel_name:
            rows = c.execute(
                "SELECT * FROM wrs_datasets_vessels WHERE UPPER(VESSEL_NAME)=? LIMIT 2",
                (vessel_name.strip().upper(),),
            ).fetchall()
            if len(rows) == 1:
                row = rows[0]
                match_method = "VESSEL_NAME"
            elif len(rows) > 1:
                log.warning(f"Ambiguous WRS match for VESSEL_NAME={vessel_name} ({len(rows)} records); match rejected")

        if row is None:
            return

        ctx.wrs_matched     = True
        ctx.wrs_match_method= match_method
        ctx.wrs_vessel_id   = row["VESSEL_ID"]
        ctx.wrs_imo         = _to_int(row["IMO"])
        ctx.wrs_mmsi        = _to_int(row["MMSI"])
        ctx.wrs_vessel_name = _str(row["VESSEL_NAME"])
        ctx.wrs_callsign    = _str(row["CALL_SIGN"])
        ctx.wrs_vessel_type = _str(row["VESSEL_TYPE"])
        ctx.wrs_status      = _str(row["STATUS"])
        ctx.wrs_gross       = _to_float(row["GROSS"])

        # Track provenance
        ctx.record_provenance("id.imo", ctx.wrs_imo, "WRS", match_method)
        ctx.record_provenance("id.mmsi", ctx.wrs_mmsi, "WRS", match_method)
        ctx.record_provenance("vessel.name", ctx.wrs_vessel_name, "WRS", match_method)
        ctx.record_provenance("id.callsign", ctx.wrs_callsign, "WRS", match_method)
        ctx.record_provenance("vessel.description", ctx.wrs_vessel_type, "WRS", match_method)
        ctx.record_provenance("vessel.grosstonnage", ctx.wrs_gross, "WRS", match_method)

        vid = ctx.wrs_vessel_id

        # 2. Decode status
        if ctx.wrs_status:
            sr = c.execute(
                "SELECT STATUS_DECODE FROM wrs_decode_vessel_status WHERE STATUS=? LIMIT 1",
                (ctx.wrs_status,)
            ).fetchone()
            if sr:
                ctx.wrs_status_decode = _str(sr["STATUS_DECODE"])
                ctx.record_provenance("cat.annotation", ctx.wrs_status_decode, "WRS", match_method)

        # 3. Dimensions
        dr = c.execute(
            "SELECT LOA, BREADTH_EXTREME, DRAFT FROM wrs_datasets_vessel_dimensions "
            "WHERE VESSEL_ID=? LIMIT 1", (vid,)
        ).fetchone()
        if dr:
            ctx.wrs_loa     = _to_float(dr["LOA"])
            ctx.wrs_breadth = _to_float(dr["BREADTH_EXTREME"])
            ctx.wrs_draft   = _to_float(dr["DRAFT"])
            ctx.record_provenance("vessel.length", ctx.wrs_loa, "WRS", match_method)
            ctx.record_provenance("vessel.beam", ctx.wrs_breadth, "WRS", match_method)
            ctx.record_provenance("vessel.draft", ctx.wrs_draft, "WRS", match_method)

        # 4. Vigilance
        vr = c.execute(
            "SELECT SCORE FROM wrs_datasets_vigilance WHERE VESSEL_ID=? LIMIT 1", (vid,)
        ).fetchone()
        if vr:
            ctx.wrs_vigilance_score = _to_float(vr["SCORE"])
            ctx.record_provenance("id.mmsi.destination", ctx.wrs_vigilance_score, "WRS", match_method)

        # 5. AIS type/cargo decode — map vessel type string to numeric AIS code
        if ctx.wrs_vessel_type:
            tr = c.execute(
                "SELECT ID FROM wrs_decode_ais_type_cargo "
                "WHERE LOWER(DESCRIPTION) LIKE ? LIMIT 1",
                (f"%{ctx.wrs_vessel_type.lower()[:20]}%",)
            ).fetchone()
            if tr:
                ctx.wrs_ais_type_code = _to_int(tr["ID"])
                ctx.record_provenance("ais.typeAndCargo", ctx.wrs_ais_type_code, "WRS", match_method)

        # 6. Most recent calling
        cr = c.execute(
            "SELECT PLACE, ARRIVAL_DATE, SAILING_DATE FROM wrs_datasets_callings "
            "WHERE VESSEL_ID=? ORDER BY LAST_UPDATED_DATE DESC LIMIT 1", (vid,)
        ).fetchone()
        if cr:
            ctx.wrs_calling_place   = _str(cr["PLACE"])
            ctx.wrs_calling_arrival = _str(cr["ARRIVAL_DATE"])
            ctx.wrs_calling_sailing = _str(cr["SAILING_DATE"])
            ctx.record_provenance("voyage.destination", ctx.wrs_calling_place, "WRS", match_method)
            ctx.record_provenance("voyage.arrival", ctx.wrs_calling_arrival, "WRS", match_method)
            ctx.record_provenance("voyage.departure", ctx.wrs_calling_sailing, "WRS", match_method)

        # 7. High-value WRS risk/analysis records for vessel remarks.
        # These are descriptive reference signals; they do not overwrite
        # incoming AIS values and are shown with their source-table details.
        try:
            rr = c.execute(
                "SELECT START_DATE, END_DATE, RISK_INDICATORS, START_LOCATION, END_LOCATION "
                "FROM wrs_datasets_aisspoofing_risk "
                "WHERE VESSEL_ID=? ORDER BY START_DATE DESC LIMIT 1", (vid,)
            ).fetchone()
            if rr:
                parts = []
                if _str(rr["RISK_INDICATORS"]): parts.append(f"INDICATOR={_str(rr['RISK_INDICATORS'])}")
                if _str(rr["START_DATE"]): parts.append(f"START={_str(rr['START_DATE'])}")
                if _str(rr["END_DATE"]): parts.append(f"END={_str(rr['END_DATE'])}")
                if _str(rr["START_LOCATION"]): parts.append(f"FROM={_str(rr['START_LOCATION'])}")
                if _str(rr["END_LOCATION"]): parts.append(f"TO={_str(rr['END_LOCATION'])}")
                ctx.wrs_ais_spoofing_detail = " | ".join(parts) or "PRESENT"
        except sqlite3.Error as exc:
            log.warning("WRS AIS spoofing risk lookup failed for VESSEL_ID=%s: %s", vid, exc)

        try:
            rr = c.execute(
                "SELECT START_DATE, END_DATE, RISK_INDICATORS, HIGH_RISK_AREA "
                "FROM wrs_datasets_ais_gap_risk "
                "WHERE VESSEL_ID=? ORDER BY START_DATE DESC LIMIT 1", (vid,)
            ).fetchone()
            if rr:
                parts = []
                if _str(rr["RISK_INDICATORS"]): parts.append(f"INDICATOR={_str(rr['RISK_INDICATORS'])}")
                if _str(rr["HIGH_RISK_AREA"]): parts.append(f"AREA={_str(rr['HIGH_RISK_AREA'])}")
                if _str(rr["START_DATE"]): parts.append(f"START={_str(rr['START_DATE'])}")
                if _str(rr["END_DATE"]): parts.append(f"END={_str(rr['END_DATE'])}")
                ctx.wrs_ais_gap_detail = " | ".join(parts) or "PRESENT"
        except sqlite3.Error as exc:
            log.warning("WRS AIS gap risk lookup failed for VESSEL_ID=%s: %s", vid, exc)

        try:
            rr = c.execute(
                "SELECT MMSI_NUMBER, RELATED_VESSEL_NAME, RISK_INDICATORS, START_DATE, END_DATE "
                "FROM wrs_datasets_ais_mnptn_risk "
                "WHERE VESSEL_ID=? ORDER BY START_DATE DESC LIMIT 1", (vid,)
            ).fetchone()
            if rr:
                parts = []
                if _str(rr["MMSI_NUMBER"]): parts.append(f"MMSI={_str(rr['MMSI_NUMBER'])}")
                if _str(rr["RELATED_VESSEL_NAME"]): parts.append(f"RELATED={_str(rr['RELATED_VESSEL_NAME'])}")
                if _str(rr["RISK_INDICATORS"]): parts.append(f"INDICATOR={_str(rr['RISK_INDICATORS'])}")
                if _str(rr["START_DATE"]): parts.append(f"START={_str(rr['START_DATE'])}")
                if _str(rr["END_DATE"]): parts.append(f"END={_str(rr['END_DATE'])}")
                ctx.wrs_ais_identity_detail = " | ".join(parts) or "PRESENT"
        except sqlite3.Error as exc:
            log.warning("WRS AIS identity risk lookup failed for VESSEL_ID=%s: %s", vid, exc)

        try:
            sr = c.execute(
                "SELECT SOURCE, PROGRAM, FIRST_PUBLISHED, LAST_PUBLISHED, START_DATE, END_DATE "
                "FROM wrs_datasets_vessel_sanctions "
                "WHERE VESSEL_ID=? ORDER BY START_DATE DESC LIMIT 1", (vid,)
            ).fetchone()
            if sr:
                parts = []
                if _str(sr["SOURCE"]): parts.append(f"SOURCE={_str(sr['SOURCE'])}")
                if _str(sr["PROGRAM"]): parts.append(f"PROGRAM={_str(sr['PROGRAM'])}")
                if _str(sr["FIRST_PUBLISHED"]): parts.append(f"FIRST={_str(sr['FIRST_PUBLISHED'])}")
                if _str(sr["LAST_PUBLISHED"]): parts.append(f"LAST={_str(sr['LAST_PUBLISHED'])}")
                if _str(sr["START_DATE"]): parts.append(f"START={_str(sr['START_DATE'])}")
                if _str(sr["END_DATE"]): parts.append(f"END={_str(sr['END_DATE'])}")
                ctx.wrs_sanctions_detail = " | ".join(parts) or "PRESENT"
        except sqlite3.Error as exc:
            log.warning("WRS sanctions lookup failed for VESSEL_ID=%s: %s", vid, exc)

    # ── PANS ─────────────────────────────────────────────────────────────────

    def _resolve_pans(
        self,
        ctx: VesselContext,
        mmsi: Optional[int],
        imo: Optional[int],
        callsign: Optional[str] = None,
        vessel_name: Optional[str] = None,
    ):
        if not self._pans_conn:
            return
        c = self._pans_conn.cursor()

        # VESPRO — match on IMONumber -> MMSINumber -> CallSign -> VesselName
        row = None
        match_method = None
        if imo:
            rows = c.execute(
                "SELECT * FROM pans_vespro WHERE IMONumber=? LIMIT 2", (str(imo),)
            ).fetchall()
            if len(rows) == 1:
                row = rows[0]
                match_method = "IMO"
            elif len(rows) > 1:
                log.warning(f"Ambiguous PANS match for IMO={imo} ({len(rows)} records); match rejected")
        if row is None and mmsi:
            rows = c.execute(
                "SELECT * FROM pans_vespro WHERE MMSINumber=? LIMIT 2", (str(mmsi),)
            ).fetchall()
            if len(rows) == 1:
                row = rows[0]
                match_method = "MMSI"
            elif len(rows) > 1:
                log.warning(f"Ambiguous PANS match for MMSI={mmsi} ({len(rows)} records); match rejected")
        if row is None and callsign:
            rows = c.execute(
                "SELECT * FROM pans_vespro WHERE CallSign=? LIMIT 2", (callsign,)
            ).fetchall()
            if len(rows) == 1:
                row = rows[0]
                match_method = "CALLSIGN"
            elif len(rows) > 1:
                log.warning(f"Ambiguous PANS match for CALLSIGN={callsign} ({len(rows)} records); match rejected")
        if row is None and vessel_name:
            rows = c.execute(
                "SELECT * FROM pans_vespro WHERE UPPER(VesselName)=? LIMIT 2",
                (vessel_name.strip().upper(),),
            ).fetchall()
            if len(rows) == 1:
                row = rows[0]
                match_method = "VESSEL_NAME"
            elif len(rows) > 1:
                log.warning(f"Ambiguous PANS match for VESSEL_NAME={vessel_name} ({len(rows)} records); match rejected")

        if row:
            ctx.pans_matched     = True
            ctx.pans_match_method= match_method
            ctx.pans_vessel_name = _str(row["VesselName"])
            ctx.pans_callsign    = _str(row["CallSign"])
            ctx.pans_beam        = _to_float(row["Beam"])
            ctx.pans_loa         = _to_float(row["LOA"])
            ctx.pans_max_draft   = _to_float(row["MaxDraft"])
            ctx.pans_grt         = _to_float(row["GRT"])
            ctx.pans_vessel_type = _str(row["VesselType"])
            ctx.pans_imo         = _to_int(row["IMONumber"])
            ctx.pans_mmsi        = _str(row["MMSINumber"])

            ctx.record_provenance("vessel.name", ctx.pans_vessel_name, "PANS", match_method)
            ctx.record_provenance("id.callsign", ctx.pans_callsign, "PANS", match_method)
            ctx.record_provenance("vessel.beam", ctx.pans_beam, "PANS", match_method)
            ctx.record_provenance("vessel.length", ctx.pans_loa, "PANS", match_method)
            ctx.record_provenance("vessel.draft", ctx.pans_max_draft, "PANS", match_method)
            ctx.record_provenance("vessel.grosstonnage", ctx.pans_grt, "PANS", match_method)
            ctx.record_provenance("vessel.description", ctx.pans_vessel_type, "PANS", match_method)

            cs  = _str(row["CallSign"]) or callsign

            # CALINV provides the VCN allocation. Keep it separate from
            # CALINF voyage identity, but expose the VCN for remarks.
            try:
                calinv = None
                if ctx.pans_imo:
                    calinv = c.execute(
                        "SELECT VCN FROM pans_calinv WHERE IMONumber=? ORDER BY _id DESC LIMIT 1",
                        (str(ctx.pans_imo),)
                    ).fetchone()
                if calinv and _str(calinv["VCN"]):
                    ctx.pans_vcn = _str(calinv["VCN"])
            except sqlite3.Error as exc:
                log.warning("PANS CALINV VCN lookup failed for IMO=%s: %s", ctx.pans_imo, exc)

            # CALINF
            calinf = None
            if ctx.pans_imo:
                calinf = c.execute(
                    "SELECT * FROM pans_calinf WHERE IMONumber=? ORDER BY _id DESC LIMIT 1",
                    (str(ctx.pans_imo),)
                ).fetchone()
            if calinf is None and cs:
                calinf = c.execute(
                    "SELECT * FROM pans_calinf WHERE CallSign=? ORDER BY _id DESC LIMIT 1",
                    (cs,)
                ).fetchone()
            if calinf:
                ctx.pans_org_dep = _str(calinf["OriginalPortOfDep"])
                ctx.pans_lpc     = _str(calinf["LastPortOfCall"])
                ctx.pans_npc     = _str(calinf["DockORTOCode"])  # NPC stored here
                ctx.pans_eta     = _str(calinf["EDTA"])
                ctx.pans_etd     = _str(calinf["EDTD"])
                ctx.record_provenance("voyage.origin", ctx.pans_org_dep, "PANS", match_method)
                ctx.record_provenance("voyage.departure", ctx.pans_lpc, "PANS", match_method)
                ctx.record_provenance("voyage.destination", ctx.pans_npc, "PANS", match_method)
                ctx.record_provenance("voyage.eta", ctx.pans_eta, "PANS", match_method)
                ctx.record_provenance("voyage.etd", ctx.pans_etd, "PANS", match_method)

            # BERMAN
            berman = None
            if ctx.pans_imo:
                berman = c.execute(
                    "SELECT * FROM pans_berman WHERE IMONumber=? ORDER BY _id DESC LIMIT 1",
                    (str(ctx.pans_imo),)
                ).fetchone()
            if berman is None and cs:
                berman = c.execute(
                    "SELECT * FROM pans_berman WHERE CallSign=? ORDER BY _id DESC LIMIT 1",
                    (cs,)
                ).fetchone()
            if berman:
                ctx.pans_berman_dest = _str(berman["DestinationPortl"])
                ctx.pans_berman_lpc  = _str(berman["Portcode"])
                ctx.pans_berman_eta  = _str(berman["EDTA"])
                ctx.pans_berman_etd  = _str(berman["EDTD"])
                ctx.pans_draft_fwd   = _to_float(berman["DraftFwd"])
                ctx.pans_draft_aft   = _to_float(berman["DraftAft"])

                ctx.pans_vcn         = _str(berman["VCN"])
                ctx.pans_cargo_description = _str(berman["CargoDescription"])
                ctx.pans_cargo_tonnage = _to_float(berman["TotalCargoTonnage"])
                ctx.pans_hazardous    = _str(berman["HazCargoOnBoard"])
                ctx.record_provenance("voyage.destination", ctx.pans_berman_dest, "PANS", match_method)
                ctx.record_provenance("voyage.arrival", ctx.pans_berman_eta, "PANS", match_method)
                ctx.record_provenance("voyage.etd", ctx.pans_berman_etd, "PANS", match_method)

    # ── NSC ──────────────────────────────────────────────────────────────────

    def _resolve_nsc(
        self,
        ctx: VesselContext,
        mmsi: Optional[int],
        imo: Optional[int],
        callsign: Optional[str] = None,
        vessel_name: Optional[str] = None,
    ):
        if not self._nsc_conn:
            return
        c = self._nsc_conn.cursor()

        row = None
        match_method = None
        if mmsi:
            rows = c.execute(
                "SELECT * FROM nsc_vessels WHERE ID_MMSI=? LIMIT 2", (str(mmsi),)
            ).fetchall()
            if len(rows) == 1:
                row = rows[0]
                match_method = "MMSI"
            elif len(rows) > 1:
                log.warning(f"Ambiguous NSC match for MMSI={mmsi} ({len(rows)} records); match rejected")
        if row is None and imo:
            rows = c.execute(
                "SELECT * FROM nsc_vessels WHERE ID_IMO=? LIMIT 2", (str(imo),)
            ).fetchall()
            if len(rows) == 1:
                row = rows[0]
                match_method = "IMO"
            elif len(rows) > 1:
                log.warning(f"Ambiguous NSC match for IMO={imo} ({len(rows)} records); match rejected")
        if row is None and callsign:
            rows = c.execute(
                "SELECT * FROM nsc_vessels WHERE ID_CALLSIGN=? LIMIT 2", (callsign,)
            ).fetchall()
            if len(rows) == 1:
                row = rows[0]
                match_method = "CALLSIGN"
            elif len(rows) > 1:
                log.warning(f"Ambiguous NSC match for CALLSIGN={callsign} ({len(rows)} records); match rejected")
        if row is None and vessel_name:
            rows = c.execute(
                "SELECT * FROM nsc_vessels WHERE UPPER(VESSEL_NAME)=? LIMIT 2",
                (vessel_name.strip().upper(),),
            ).fetchall()
            if len(rows) == 1:
                row = rows[0]
                match_method = "VESSEL_NAME"
            elif len(rows) > 1:
                log.warning(f"Ambiguous NSC match for VESSEL_NAME={vessel_name} ({len(rows)} records); match rejected")

        if row:
            ctx.nsc_matched     = True
            ctx.nsc_match_method= match_method
            ctx.nsc_vessel_name = _str(row["VESSEL_NAME"])
            ctx.nsc_imo         = _to_int(row["ID_IMO"])
            ctx.nsc_mmsi        = _to_int(row["ID_MMSI"])
            ctx.nsc_callsign    = _str(row["ID_CALLSIGN"])
            ctx.nsc_type        = _str(row["TYPE"])
            ctx.nsc_region      = _str(row["SOURCE_REGION"])
            ctx.nsc_begin_date  = _str(row["BEGIN_DATE"])
            ctx.nsc_end_date    = _str(row["END_DATE"])

            ctx.record_provenance("vessel.name", ctx.nsc_vessel_name, "NSC", match_method)
            ctx.record_provenance("id.imo", ctx.nsc_imo, "NSC", match_method)
            ctx.record_provenance("id.mmsi", ctx.nsc_mmsi, "NSC", match_method)
            ctx.record_provenance("id.callsign", ctx.nsc_callsign, "NSC", match_method)
            ctx.record_provenance("vessel.description", ctx.nsc_type, "NSC", match_method)

    def close(self):
        for conn in (self._wrs_conn, self._pans_conn, self._nsc_conn):
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _str(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s if s and s not in ("-", "N/A", "NONE", "None") else None


def _to_int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(float(str(v).strip()))
    except (ValueError, TypeError):
        return None


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(str(v).strip())
    except (ValueError, TypeError):
        return None
