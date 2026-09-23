#!/usr/bin/env python3
"""Validation PostgreSQL DB Manager.

Responsibilities:
- create/check the local Validation PostgreSQL database;
- continuously ingest PANS XML files;
- manually import WRS and NSC reference folders;
- preserve current + history on every update (never delete reference rows);
- expose a small local web console for status/search/table/mapping operations.

The feed scripts remain independent. This process is only the shared database and
reference-data controller.
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
import os
import re
import subprocess
import threading
import time
import traceback
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row

from config import (
    PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD,
    WEB_HOST, WEB_PORT, PANS_INPUT_DIR, WRS_INPUT_DIR, NSC_INPUT_DIR,
    PANS_POLL_SECONDS, PANS_STABILITY_SECONDS, PG_CTL_PATH, PG_DATA_DIR,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=os.getenv("VALIDATION_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "db_manager.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("validation.db_manager")

SOURCE_DEFAULTS = [
    (0, "NONE", "IMAC NONE", "FILE", None),
    (37, "NAIS", "IMAC NAIS", "FILE/TCP", 10005),
    (38, "SAIS_IOR", "IMAC SAIS", "FILE/TCP", 10001),
    (38, "SAIS_GLOBAL", "IMAC SAIS", "FILE/TCP", 10001),
    (40, "LRIT", "IMAC LRIT", "FILE/TCP", 10003),
    (41, "SAC", "IMAC SAC", "TCP", None),
    (223, "VATMS_WEST", "IMAC VATMSW", "FILE/TCP", 10004),
    (245, "VATMS_EAST", "IMAC VATMSE", "FILE/TCP", 10004),
    (250, "MSIS", "IMAC MSIS", "FILE/TCP", 10002),
]

DEFAULT_MAPPINGS = [
    ("SAIS_IOR","MMSI","id.mmsi","integer",True,1),
    ("SAIS_IOR","IMO","id.imo","integer",False,1),
    ("SAIS_IOR","CALLSIGN","id.callsign","string",False,1),
    ("SAIS_IOR","VESSEL_NAME","vessel.name","sanitize_string",False,1),
    ("SAIS_GLOBAL","MMSI","id.mmsi","integer",True,1),
    ("SAIS_GLOBAL","IMO","id.imo","integer",False,1),
    ("SAIS_GLOBAL","CALLSIGN","id.callsign","string",False,1),
    ("MSIS","mmsi","id.mmsi","integer",True,1),
    ("MSIS","imo","id.imo","integer",False,1),
    ("MSIS","callsign","id.callsign","string",False,1),
    ("MSIS","ship_name","vessel.name","sanitize_string",False,1),
    ("LRIT","column[0]","id.mmsi","integer",True,1),
    ("LRIT","column[12]","id.imo","integer",False,1),
    ("LRIT","column[11]","vessel.name","sanitize_string",False,1),
    ("VATMS_EAST","AIS_MMSI","id.mmsi","integer",False,1),
    ("VATMS_WEST","MMSI","id.mmsi","integer",False,1),
    ("NAIS","AIS_MMSI","id.mmsi","integer",False,1),
]

PARSER_MAPPING_DEFAULTS = [
    ("SAIS_IOR","id.mmsi",["incoming:mmsi"],None,None),("SAIS_IOR","id.imo",["incoming:imo","ais_state:imo"],None,None),
    ("SAIS_IOR","id.callsign",["incoming:callsign","ais_state:callsign"],None,None),("SAIS_IOR","vessel.name",["incoming:vessel_name","ais_state:vessel_name"],"UNKNOWN",None),
    ("SAIS_IOR","ais.typeAndCargo",["incoming:vessel_type","ais_state:vessel_type"],None,None),("SAIS_IOR","vessel.length",["incoming:length","ais_state:length"],None,None),
    ("SAIS_IOR","vessel.beam",["incoming:width","ais_state:width"],None,None),("SAIS_IOR","vessel.draft",["incoming:draught","ais_state:draught"],None,None),
    ("SAIS_IOR","kinematic.pos.lla.lat",["incoming:latitude"],None,"degrees_to_radians"),("SAIS_IOR","kinematic.pos.lla.lon",["incoming:longitude"],None,"degrees_to_radians"),
    ("SAIS_IOR","kinematic.speed",["incoming:sog"],None,"knots_to_ms"),("SAIS_IOR","kinematic.course.true",["incoming:cog"],None,"degrees_to_radians"),
    ("SAIS_IOR","kinematic.heading.true",["incoming:true_heading"],None,"degrees_to_radians"),("SAIS_IOR","ais.navStatus",["incoming:nav_status","ais_state:nav_status"],None,None),
    ("SAIS_IOR","voyage.destination",["incoming:destination","ais_state:destination"],None,None),("SAIS_IOR","voyage.eta",["incoming:eta","ais_state:eta"],None,None),
    ("MSIS","id.mmsi",["incoming:mmsi"],None,None),("MSIS","id.imo",["incoming:imo","ais_state:imo"],None,None),
    ("MSIS","id.callsign",["incoming:callsign","ais_state:callsign"],None,None),("MSIS","vessel.name",["incoming:ship_name","ais_state:vessel_name"],"UNKNOWN",None),
    ("MSIS","ais.typeAndCargo",["incoming:type_and_cargo","ais_state:vessel_type"],None,None),("MSIS","vessel.length",["incoming:length","ais_state:length"],None,None),
    ("MSIS","vessel.beam",["incoming:width","ais_state:width"],None,None),("MSIS","vessel.draft",["incoming:draught","ais_state:draught"],None,None),
    ("MSIS","kinematic.pos.lla.lat",["incoming:latitude"],None,"degrees_to_radians"),("MSIS","kinematic.pos.lla.lon",["incoming:longitude"],None,"degrees_to_radians"),
    ("MSIS","kinematic.speed",["incoming:sog"],None,"knots_to_ms"),("MSIS","kinematic.course.true",["incoming:cog"],None,"degrees_to_radians"),
    ("MSIS","kinematic.heading.true",["incoming:true_heading"],None,"degrees_to_radians"),("MSIS","ais.navStatus",["incoming:navigation_status","incoming:navigatetion_status","ais_state:nav_status"],None,None),
    ("MSIS","voyage.destination",["incoming:destination","ais_state:destination"],None,None),("MSIS","voyage.eta",["incoming:eta","ais_state:eta"],None,None),
    ("LRIT","id.mmsi",["incoming:mmsi"],None,None),("LRIT","id.imo",["incoming:imo","ais_state:imo"],None,None),
    ("LRIT","id.callsign",["incoming:callsign","ais_state:callsign"],None,None),("LRIT","vessel.name",["incoming:vessel_name","ais_state:vessel_name"],"UNKNOWN",None),
    ("LRIT","kinematic.pos.lla.lat",["incoming:latitude"],None,"degrees_to_radians"),("LRIT","kinematic.pos.lla.lon",["incoming:longitude"],None,"degrees_to_radians"),
    ("LRIT","kinematic.speed",["incoming:sog"],None,"knots_to_ms"),("LRIT","kinematic.course.true",["incoming:cog"],None,"degrees_to_radians"),
    ("LRIT","kinematic.heading.true",["incoming:heading"],None,"degrees_to_radians"),("LRIT","ais.navStatus",["incoming:nav_status","ais_state:nav_status"],None,None),
    ("LRIT","vessel.length",["incoming:length","ais_state:length"],None,None),("LRIT","vessel.beam",["incoming:width","ais_state:width"],None,None),
    ("LRIT","vessel.draft",["incoming:draught","ais_state:draught"],None,None),("LRIT","ais.typeAndCargo",["incoming:vessel_type","ais_state:vessel_type"],None,None),
    ("LRIT","voyage.destination",["incoming:destination","ais_state:destination"],None,None),("LRIT","voyage.eta",["incoming:eta","ais_state:eta"],None,None),
]

def setting(key, default=None):
    with db() as conn:
        row=conn.execute("SELECT value FROM system_config WHERE key=%s",(key,)).fetchone()
    return row["value"] if row else default

def set_setting(key, value):
    with db() as conn:
        conn.execute("""INSERT INTO system_config(key,value) VALUES(%s,%s)
                        ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now()""",(key,str(value)))

def configured_dir(key, fallback):
    return Path(setting(key, str(fallback)))

def browse_folder_native():
    try:
        import tkinter as tk
        from tkinter import filedialog
        root=tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
        path=filedialog.askdirectory(title="Select Validation source folder")
        root.destroy()
        return path or None
    except Exception as exc:
        log.warning("Native folder dialog unavailable: %s", exc)
        return None

def validate_wrs_root(path: Path):
    if not path.exists() or not path.is_dir():
        return False, "WRS root does not exist"
    dirs={p.name.lower():p for p in path.iterdir() if p.is_dir()}
    if "datasets" not in dirs:
        return False, "WRS root must contain Datasets"
    if "decode files" not in dirs and "decode" not in dirs:
        return False, "WRS root must contain Decode files or Decode"
    if not list(dirs["datasets"].rglob("*.csv")):
        return False, "WRS Datasets contains no CSV files"
    return True, "WRS root valid"

def validate_nsc_root(path: Path):
    if not path.exists() or not path.is_dir():
        return False, "NSC root does not exist"
    files=list(path.rglob("*.csv"))+list(path.rglob("*.xlsx"))+list(path.rglob("*.xlsm"))
    names=[p.name.upper() for p in files]
    east=any("NSC_EAST" in n or "EAST" in p.parent.name.upper() for n,p in zip(names,files))
    west=any("NSC_WEST" in n or "WEST" in p.parent.name.upper() for n,p in zip(names,files))
    return (True,"NSC EAST/WEST sources found") if east and west else (False,"NSC root must provide both EAST and WEST sources")

def validate_pans_root(path: Path):
    if not path.exists() or not path.is_dir():
        return False, "PANS folder does not exist"
    count=len(list(path.rglob("*.xml")))
    return (True,f"PANS folder valid: {count} XML files") if count else (False,"PANS folder contains no XML files")

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def clean_col(v: Any) -> str:
    s = str(v).strip()
    s = re.sub(r"[^A-Za-z0-9_]+", "_", s).strip("_").upper()
    return s or "UNKNOWN_COLUMN"

def text(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s and s.upper() not in {"NONE","NULL","N/A","NA","-"} else None

def number(v: Any, integer=False):
    s = text(v)
    if s is None:
        return None
    try:
        x = float(s)
        return int(x) if integer else x
    except (ValueError, TypeError):
        return None

def pg_dsn(database=PG_DATABASE):
    return {
        "host": PG_HOST,
        "port": PG_PORT,
        "dbname": database,
        "user": PG_USER,
        "password": PG_PASSWORD,
        "connect_timeout": 3,
    }

def try_connect(database=PG_DATABASE):
    return psycopg.connect(**pg_dsn(database), row_factory=dict_row)

def start_local_postgres_if_configured():
    if not PG_CTL_PATH or not PG_DATA_DIR:
        return
    try:
        subprocess.run(
            [PG_CTL_PATH, "-D", PG_DATA_DIR, "status"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return
    except Exception:
        pass
    log.warning("PostgreSQL is not reachable; attempting pg_ctl start using configured local data directory.")
    subprocess.run(
        [PG_CTL_PATH, "-D", PG_DATA_DIR, "-l", str(LOG_DIR / "postgresql.log"), "start"],
        check=False,
    )

def ensure_database():
    start_local_postgres_if_configured()
    try:
        conn = try_connect(PG_DATABASE)
        conn.close()
        return
    except Exception:
        pass
    with try_connect("postgres") as conn:
        conn.autocommit = True
        row = conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (PG_DATABASE,)).fetchone()
        if not row:
            safe_db = PG_DATABASE.replace('"','""')
            conn.execute(f'CREATE DATABASE "{safe_db}"')
            log.info("Created PostgreSQL database %s", PG_DATABASE)

def db():
    return try_connect(PG_DATABASE)

def ensure_schema():
    ensure_database()
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    with db() as conn:
        conn.execute(sql)
        for source_id, source_name, label, input_type, port in SOURCE_DEFAULTS:
            conn.execute(
                """INSERT INTO source(source_id,source_name,source_label,input_type,receive_port)
                   VALUES(%s,%s,%s,%s,%s)
                   ON CONFLICT(source_name) DO UPDATE SET source_id=EXCLUDED.source_id,
                     source_label=EXCLUDED.source_label, input_type=EXCLUDED.input_type,
                     receive_port=EXCLUDED.receive_port""",
                (source_id, source_name, label, input_type, port),
            )
        for row in DEFAULT_MAPPINGS:
            conn.execute(
                """INSERT INTO field_mapping(source_name,input_field,target_field,transformation,required,fallback_order)
                   VALUES(%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(source_name,input_field,target_field) DO NOTHING""", row)        for source_name,logical_field,candidates,default_value,transformation in PARSER_MAPPING_DEFAULTS:
            conn.execute(
                """INSERT INTO parser_mapping(source_name,logical_field,candidates,default_value,transformation)
                   VALUES(%s,%s,%s::jsonb,%s,%s)
                   ON CONFLICT(source_name,logical_field) DO NOTHING""",
                (source_name,logical_field,json.dumps(candidates),default_value,transformation)
            )
        for alias in ("SAIS_GLOBAL","VATMS_EAST","VATMS_WEST","NAIS"):
            conn.execute(
                """INSERT INTO parser_mapping(source_name,logical_field,candidates,default_value,transformation)
                   SELECT %s,logical_field,candidates,default_value,transformation
                   FROM parser_mapping WHERE source_name='SAIS_IOR'
                   ON CONFLICT(source_name,logical_field) DO NOTHING""",(alias,)
            )

        unlocode_file=ROOT/"Data_Parser"/"config"/"unlocode.json"
        if unlocode_file.exists():
            existing=conn.execute("SELECT count(*) AS n FROM unlocode").fetchone()["n"]
            if existing == 0:
                try:
                    locs=json.loads(unlocode_file.read_text(encoding="utf-8"))
                    for code,name in locs.items():
                        code_clean="".join(str(code).upper().split())
                        if len(code_clean)==5:
                            conn.execute(
                                """INSERT INTO unlocode(locode,country_code,location_code,location_name,raw_data)
                                   VALUES(%s,%s,%s,%s,%s::jsonb)
                                   ON CONFLICT(locode) DO NOTHING""",
                                (code_clean,code_clean[:2],code_clean[2:],str(name).strip(),json.dumps({"import_source":str(unlocode_file)}))
                            )
                    log.info("Loaded %s UN/LOCODE entries into PostgreSQL",len(locs))
                except Exception:
                    log.exception("UN/LOCODE bootstrap failed")
    log.info("PostgreSQL schema/default configuration ready.")

def normalized_xml_record(root: ET.Element) -> dict[str, str]:
    out = {}
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if el is root:
            continue
        if el.text and el.text.strip():
            out[tag] = el.text.strip()
    return out

PANS_TABLES = {
    "VesselProfile": "VESPRO",
    "VoyageRegistration": "CALINF",
    "VesselCallNumber": "CALINV",
    "BerthManagement": "BERMAN",
}

def flatten_xml(element: ET.Element, result=None):
    if result is None:
        result = {}
    tag = element.tag.split("}")[-1]
    if element.text and element.text.strip():
        key = next((k for k in result if k.lower() == tag.lower()), tag)
        value = element.text.strip()
        if key in result:
            result[key] = f"{result[key]}; {value}"
        else:
            result[key] = value
    for child in element:
        flatten_xml(child, result)
    return result

def record_identity(data: dict, prefix: str = "") -> tuple[str|None,int|None,int|None,str|None,str|None]:
    def get(*names):
        lower = {str(k).lower(): v for k,v in data.items()}
        for n in names:
            if n.lower() in lower and text(lower[n.lower()]) is not None:
                return text(lower[n.lower()])
        return None
    mmsi = number(get("MMSI","MMSINumber","ID_MMSI"), True)
    imo = number(get("IMO","IMONumber","ID_IMO"), True)
    callsign = get("CALL_SIGN","CallSign","ID_CALLSIGN")
    name = get("VESSEL_NAME","VesselName")
    vessel_id = get("VESSEL_ID")
    return vessel_id, mmsi, imo, callsign, name

def upsert_reference(table: str, history_table: str, identity_cols: dict, data: dict, source_file: str, source_hash: str):
    """UPSERT current state and append the replaced version to history.

    Missing records in a later WRS/NSC refresh are deliberately not deleted.
    """
    cols = list(identity_cols)
    vals = [identity_cols[c] for c in cols]
    data_json = json.dumps(data, ensure_ascii=False)
    where_cols = " AND ".join(f"{c} IS NOT DISTINCT FROM %s" for c in cols)
    if table == "reference_wrs_current":
        history_cols = ["dataset_name", "natural_key"]
    elif table == "reference_pans_current":
        history_cols = ["document_type", "natural_key"]
    else:
        history_cols = ["natural_key", "source_region"]
    history_vals = [identity_cols.get(c) for c in history_cols]
    with db() as conn:
        old = conn.execute(
            f"SELECT * FROM {table} WHERE {where_cols} LIMIT 1", tuple(vals)
        ).fetchone()
        if old:
            old_data = old["data"] if isinstance(old["data"], dict) else json.loads(old["data"])
            if old_data != data:
                conn.execute(
                    f"""INSERT INTO {history_table}
                        ({", ".join(history_cols)},source_file,source_hash,data)
                        VALUES ({",".join(["%s"]*len(history_cols))},%s,%s,%s::jsonb)""",
                    (*history_vals, old.get("source_file"), old.get("source_hash"),
                     json.dumps(old_data, ensure_ascii=False)),
                )
            # Current identity columns are retained as part of the latest version.
            sets = ", ".join([f"{c}=%s" for c in cols] + ["source_file=%s","source_hash=%s","data=%s::jsonb","updated_at=now()"])
            conn.execute(
                f"UPDATE {table} SET {sets} WHERE {where_cols}",
                (*vals, source_file, source_hash, data_json, *vals),
            )
        else:
            all_cols = cols + ["source_file","source_hash","data"]
            conn.execute(
                f"""INSERT INTO {table} ({",".join(all_cols)})
                    VALUES ({",".join(["%s"]*len(all_cols[:-1]))},%s,%s,%s::jsonb)""",
                (*vals, source_file, source_hash, data_json),
            )

def import_wrs_once(input_dir: Path | None = None) -> dict:\n    input_dir = input_dir or configured_dir('WRS_INPUT_DIR', WRS_INPUT_DIR)\n    ok, msg = validate_wrs_root(input_dir)\n    if not ok: return {'status':'INVALID_SOURCE','error':msg,'path':str(input_dir)}
    files = sorted(input_dir.rglob("*.csv")) if input_dir.exists() else []
    if not files:
        return {"status":"NO_DATA","files":0,"rows":0}
    batch_id = None
    with db() as conn:
        row = conn.execute(
            "INSERT INTO import_batch(source_system,status,files_discovered) VALUES('WRS','RUNNING',%s) RETURNING batch_id",
            (len(files),)
        ).fetchone()
        batch_id = row["batch_id"]
    loaded = 0
    errors = 0
    for path in files:
        try:
            h = sha256_file(path)
            with db() as conn:
                done = conn.execute(
                    "SELECT 1 FROM import_file WHERE source_system='WRS' AND file_hash_sha256=%s AND status='COMPLETED' LIMIT 1",
                    (h,)
                ).fetchone()
                if done:
                    continue
            dataset = path.stem
            low = dataset.lower()
            if low.startswith("wrs.datasets."):
                dataset = dataset[len("wrs.datasets."):]
            elif low.startswith("wrs.decode."):
                dataset = dataset[len("wrs.decode."):]
            elif low.startswith("decode_"):
                dataset = dataset[len("decode_"):]
            dataset = dataset.upper()
            is_decode = "DECODE" in path.parent.name.upper() or low.startswith("wrs.decode.") or low.startswith("decode_")
            if is_decode:
                dataset = "DECODE_" + dataset
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row_no, raw in enumerate(reader, 1):
                    data = {clean_col(k): (v.strip() if isinstance(v,str) else v) for k,v in raw.items() if k is not None}
                    vessel_id, mmsi, imo, callsign, name = record_identity(data)
                    if vessel_id:
                        natural = vessel_id
                    elif mmsi or imo or callsign or name:
                        natural = "|".join(str(x or "") for x in (mmsi,imo,callsign,(name or "").upper()))
                    else:
                        natural = f"{h}:{row_no}"
                    identity = {
                        "dataset_name": dataset,
                        "natural_key": natural,
                        "vessel_id": vessel_id,
                        "mmsi": mmsi,
                        "imo": imo,
                        "callsign": callsign,
                        "vessel_name": name,
                    }
                    upsert_reference("reference_wrs_current","reference_wrs_history",identity,data,path.name,h)
                    loaded += 1
            with db() as conn:
                conn.execute(
                    """INSERT INTO import_file(batch_id,source_system,file_name,file_path,file_hash_sha256,file_size_bytes,target_table,status,rows_loaded,loaded_at)
                       VALUES(%s,'WRS',%s,%s,%s,%s,%s,'COMPLETED',%s,now())""",
                    (batch_id,path.name,str(path),h,path.stat().st_size,dataset,loaded)
                )
        except Exception as exc:
            errors += 1
            log.exception("WRS import failed for %s", path)
            with db() as conn:
                conn.execute(
                    """INSERT INTO import_file(batch_id,source_system,file_name,file_path,file_hash_sha256,file_size_bytes,status,error_message)
                       VALUES(%s,'WRS',%s,%s,%s,%s,'FAILED',%s)""",
                    (batch_id,path.name,str(path),h if 'h' in locals() else '',path.stat().st_size,str(exc))
                )
    with db() as conn:
        conn.execute("UPDATE import_batch SET completed_at=now(),status=%s,files_loaded=%s,rows_loaded=%s,error_count=%s WHERE batch_id=%s",
                     ("COMPLETED" if errors==0 else "FAILED", files.__len__()-errors, loaded, errors, batch_id))
    return {"status":"COMPLETED" if errors==0 else "FAILED","files":len(files),"rows":loaded,"errors":errors}

def import_nsc_once(input_dir: Path | None = None) -> dict:\n    input_dir = input_dir or configured_dir('NSC_INPUT_DIR', NSC_INPUT_DIR)\n    ok, msg = validate_nsc_root(input_dir)\n    if not ok: return {'status':'INVALID_SOURCE','error':msg,'path':str(input_dir)}
    try:
        import openpyxl
    except ImportError:
        return {"status":"ERROR","error":"openpyxl is required for NSC XLSX input"}
    files = [p for p in input_dir.rglob("*") if p.suffix.lower() in {".xlsx",".csv"}] if input_dir.exists() else []
    if not files:
        return {"status":"NO_DATA","files":0,"rows":0}
    with db() as conn:
        batch_id = conn.execute(
            "INSERT INTO import_batch(source_system,status,files_discovered) VALUES('NSC','RUNNING',%s) RETURNING batch_id",
            (len(files),)
        ).fetchone()["batch_id"]
    loaded = errors = 0
    for path in files:
        try:
            h = sha256_file(path)
            with db() as conn:
                if conn.execute("SELECT 1 FROM import_file WHERE source_system='NSC' AND file_hash_sha256=%s AND status='COMPLETED'",(h,)).fetchone():
                    continue
            region = "EAST" if "EAST" in path.name.upper() or "EAST" in str(path.parent).upper() else "WEST" if "WEST" in path.name.upper() or "WEST" in str(path.parent).upper() else "UNKNOWN"
            if path.suffix.lower()==".xlsx":
                wb = openpyxl.load_workbook(path,read_only=True,data_only=True)
                ws = wb.active
                rows = ws.iter_rows(values_only=True)
                headers = [clean_col(x) if x is not None else None for x in next(rows)]
                iterator = rows
            else:
                f = path.open("r",encoding="utf-8-sig",newline="")
                reader = csv.reader(f)
                headers = [clean_col(x) if x is not None else None for x in next(reader)]
                iterator = reader
            for row_no, row in enumerate(iterator,1):
                data={}
                for i,hdr in enumerate(headers):
                    if hdr and i < len(row):
                        data[hdr]= "" if row[i] is None else str(row[i]).strip()
                data["SOURCE_REGION"]=region
                vessel_id,mmsi,imo,callsign,name=record_identity(data)
                natural="|".join([region,str(mmsi or ""),str(imo or ""),str(callsign or ""),(name or "").upper()])
                identity={"natural_key":natural,"source_region":region,"mmsi":mmsi,"imo":imo,"callsign":callsign,"vessel_name":name}
                upsert_reference("reference_nsc_current","reference_nsc_history",identity,data,path.name,h)
                loaded+=1
            if path.suffix.lower()==".xlsx":
                wb.close()
            else:
                f.close()
            with db() as conn:
                conn.execute(
                    """INSERT INTO import_file(batch_id,source_system,source_region,file_name,file_path,file_hash_sha256,file_size_bytes,target_table,status,rows_loaded,loaded_at)
                       VALUES(%s,'NSC',%s,%s,%s,%s,%s,'reference_nsc_current','COMPLETED',%s,now())""",
                    (batch_id,region,path.name,str(path),h,path.stat().st_size,loaded)
                )
        except Exception as exc:
            errors+=1
            log.exception("NSC import failed for %s",path)
    with db() as conn:
        conn.execute("UPDATE import_batch SET completed_at=now(),status=%s,files_loaded=%s,rows_loaded=%s,error_count=%s WHERE batch_id=%s",
                     ("COMPLETED" if errors==0 else "FAILED",len(files)-errors,loaded,errors,batch_id))
    return {"status":"COMPLETED" if errors==0 else "FAILED","files":len(files),"rows":loaded,"errors":errors}

def pans_process_file(path: Path) -> bool:
    h = sha256_file(path)
    with db() as conn:
        if conn.execute("SELECT 1 FROM import_file WHERE source_system='PANS' AND file_hash_sha256=%s AND status='COMPLETED'",(h,)).fetchone():
            return True
    try:
        root = ET.parse(path).getroot()
        doc_type = PANS_TABLES.get(root.tag.split("}")[-1])
        if not doc_type:
            raise ValueError(f"Unknown PANS XML root: {root.tag}")
        data = flatten_xml(root)
        vessel_id,mmsi,imo,callsign,name=record_identity(data)
        natural = f"IMO:{imo}" if imo else f"MMSI:{mmsi}" if mmsi else f"CALLSIGN:{callsign}" if callsign else f"NAME:{(name or '').upper()}"
        identity={"document_type":doc_type,"natural_key":natural,"mmsi":mmsi,"imo":imo,"callsign":callsign,"vessel_name":name}
        upsert_reference("reference_pans_current","reference_pans_history",identity,data,path.name,h)
        with db() as conn:
            batch = conn.execute("SELECT batch_id FROM import_batch WHERE source_system='PANS' AND status='RUNNING' ORDER BY batch_id DESC LIMIT 1").fetchone()
            if not batch:
                batch=conn.execute("INSERT INTO import_batch(source_system,status,files_discovered) VALUES('PANS','RUNNING',1) RETURNING batch_id").fetchone()
            conn.execute(
                """INSERT INTO import_file(batch_id,source_system,document_type,file_name,file_path,file_hash_sha256,file_size_bytes,target_table,status,rows_loaded,loaded_at)
                   VALUES(%s,'PANS',%s,%s,%s,%s,%s,'reference_pans_current','COMPLETED',1,now())""",
                (batch["batch_id"],doc_type,path.name,str(path),h,path.stat().st_size)
            )
            conn.execute("UPDATE import_batch SET completed_at=now(),status='COMPLETED',files_loaded=1,rows_loaded=1 WHERE batch_id=%s",(batch["batch_id"],))
        return True
    except Exception as exc:
        log.error("PANS file failed %s: %s",path,exc)
        with db() as conn:
            batch=conn.execute("SELECT batch_id FROM import_batch WHERE source_system='PANS' AND status='RUNNING' ORDER BY batch_id DESC LIMIT 1").fetchone()
            if batch:
                conn.execute("UPDATE import_batch SET completed_at=now(),status='FAILED',error_count=1,error_message=%s WHERE batch_id=%s",(str(exc),batch["batch_id"]))
            conn.execute(
                """INSERT INTO pans_pending(file_hash_sha256,file_name,file_path,last_error,attempts)
                   VALUES(%s,%s,%s,%s,1)
                   ON CONFLICT(file_hash_sha256) DO UPDATE SET last_error=EXCLUDED.last_error,attempts=pans_pending.attempts+1""",
                (h,path.name,str(path),str(exc))
            )
        return False

class Manager:
    def __init__(self):
        self.stop_event=threading.Event()
        self.thread=None
        self.ready=False
    def start(self):
        ensure_schema()
        self.ready=True
        self.thread=threading.Thread(target=self.pans_loop,daemon=True,name="PANS-Monitor")
        self.thread.start()
    def pans_loop(self):
        while not self.stop_event.is_set():
            try:
                pans_dir=configured_dir('PANS_INPUT_DIR',PANS_INPUT_DIR)
                pans_dir.mkdir(parents=True,exist_ok=True)
                for path in sorted(pans_dir.rglob("*.xml")):
                    try:
                        age=time.time()-path.stat().st_mtime
                        if age < PANS_STABILITY_SECONDS:
                            continue
                        pans_process_file(path)
                    except FileNotFoundError:
                        continue
            except Exception:
                log.exception("PANS monitor cycle failed")
            self.stop_event.wait(PANS_POLL_SECONDS)
    def stop(self):
        self.stop_event.set()

MANAGER=Manager()

HTML="""<!doctype html>
<html><head><meta charset="utf-8"><title>Validation DB Manager</title>
<style>
body{font-family:Arial,sans-serif;background:#111827;color:#e5e7eb;margin:0;padding:24px}
h1{margin-top:0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}
.card{background:#1f2937;border:1px solid #374151;border-radius:10px;padding:16px}
button{background:#2563eb;color:white;border:0;padding:9px 12px;border-radius:6px;cursor:pointer;margin:4px}
input{background:#111827;color:#fff;border:1px solid #4b5563;padding:8px;border-radius:5px;width:80%}
pre{white-space:pre-wrap;max-height:400px;overflow:auto}.muted{color:#9ca3af}
</style></head>
<body>
<h1>Validation — PostgreSQL Reference DB Manager</h1>
<p class="muted">PANS is monitored continuously. WRS/NSC are manual updates. Reference history is retained; current rows are UPSERTed.</p>
<div class="grid">
<div class="card"><h2>Status</h2><pre id="status">Loading...</pre><button onclick="load()">Refresh</button></div>
<div class="card"><h2>Reference Folders</h2>
<div>WRS: <button onclick="browse('wrs')">Browse</button></div><pre id="wrsdir"></pre>
<div>NSC: <button onclick="browse('nsc')">Browse</button></div><pre id="nscdir"></pre>
<div>PANS: <button onclick="browse('pans')">Browse</button></div><pre id="pansdir"></pre>
<button onclick="post('/api/import/wrs')">Update WRS</button>
<button onclick="post('/api/import/nsc')">Update NSC</button>
<button onclick="post('/api/import/pans/once')">Process PANS now</button><pre id="action"></pre></div>
<div class="card"><h2>Vessel Search</h2><input id="q" placeholder="MMSI / IMO / callsign / name"><button onclick="search()">Search</button><pre id="results"></pre></div>
<div class="card"><h2>Reference Viewer</h2><button onclick="viewRef('wrs')">WRS current</button><button onclick="viewRef('pans')">PANS current</button><button onclick="viewRef('nsc')">NSC current</button><pre id="refview"></pre></div>
<div class="card"><h2>Source IDs</h2><button onclick="sources()">View source IDs</button><pre id="sources"></pre>
<form onsubmit="saveSource(event)"><input id="ssid" placeholder="source_id"><input id="ssname" placeholder="source_name"><input id="sslabel" placeholder="label"><button>Save source</button></form></div>
<div class="card"><h2>Mappings / Config</h2>
<button onclick="mappings()">View mappings</button><button onclick="parserMappings()">View parser JSON mappings</button>
<form onsubmit="saveMapping(event)">
<input id="ms" placeholder="source_name"><input id="mi" placeholder="input_field"><input id="mt" placeholder="target_field">
<input id="mx" placeholder="transformation"><button>Save mapping</button></form><pre id="maps"></pre><pre id="pmaps"></pre>
<form onsubmit="saveParserMapping(event)"><input id="ps" placeholder="source_name"><input id="pl" placeholder="logical field"><input id="pc" placeholder='candidates JSON, e.g. ["incoming:mmsi"]'><input id="pd" placeholder="default"><input id="pt" placeholder="transformation"><button>Save parser mapping</button></form>
</div>
<div class="card"><h2>UN/LOCODE / Destination</h2>
<form onsubmit="saveLoc(event)"><input id="lk" placeholder="LOCODE"><input id="ln" placeholder="Location name"><input id="lc" placeholder="Country"><button>Save UN/LOCODE</button></form>
<form onsubmit="saveDest(event)"><input id="dk" placeholder="Destination key"><input id="dn" placeholder="Destination name"><input id="dl" placeholder="LOCODE"><button>Save destination</button></form>
<pre id="cfg"></pre></div>
</div>
<script>
async function get(u){let r=await fetch(u);return await r.json()}
async function post(u){let r=await fetch(u,{method:'POST'});document.getElementById('action').textContent=JSON.stringify(await r.json(),null,2);load()}
async function load(){document.getElementById('status').textContent=JSON.stringify(await get('/api/status'),null,2);let c=await get('/api/config');wrsdir.textContent=c.WRS_INPUT_DIR;nscdir.textContent=c.NSC_INPUT_DIR;pansdir.textContent=c.PANS_INPUT_DIR}
async function browse(kind){let r=await fetch('/api/browse/'+kind,{method:'POST'});let x=await r.json();document.getElementById(kind+'dir').textContent=(x.path||'')+'\n'+(x.message||x.status);load()}
async function search(){document.getElementById('results').textContent=JSON.stringify(await get('/api/search?q='+encodeURIComponent(document.getElementById('q').value)),null,2)}
async function viewRef(t){document.getElementById('refview').textContent=JSON.stringify(await get('/api/reference?table='+t),null,2)}
async function sources(){document.getElementById('sources').textContent=JSON.stringify(await get('/api/sources'),null,2)}
async function saveSource(e){e.preventDefault();let r=await fetch('/api/source',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source_id:Number(ssid.value),source_name:ssname.value,source_label:sslabel.value})});document.getElementById('sources').textContent=JSON.stringify(await r.json(),null,2);sources()}
async function mappings(){document.getElementById('maps').textContent=JSON.stringify(await get('/api/mappings'),null,2)}
async function parserMappings(){document.getElementById('pmaps').textContent=JSON.stringify(await get('/api/parser-mappings'),null,2)}
async function saveParserMapping(e){e.preventDefault();let candidates=JSON.parse(pc.value);let r=await fetch('/api/parser-mapping',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source_name:ps.value,logical_field:pl.value,candidates:candidates,default_value:pd.value,transformation:pt.value})});document.getElementById('pmaps').textContent=JSON.stringify(await r.json(),null,2);parserMappings()}
async function saveMapping(e){e.preventDefault();let r=await fetch('/api/mapping',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source_name:ms.value,input_field:mi.value,target_field:mt.value,transformation:mx.value})});document.getElementById('maps').textContent=JSON.stringify(await r.json(),null,2);mappings()}
async function saveLoc(e){e.preventDefault();let r=await fetch('/api/unlocode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({locode:lk.value,location_name:ln.value,country_code:lc.value})});document.getElementById('cfg').textContent=JSON.stringify(await r.json(),null,2)}
async function saveDest(e){e.preventDefault();let r=await fetch('/api/destination',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({destination_key:dk.value,destination_name:dn.value,locode:dl.value})});document.getElementById('cfg').textContent=JSON.stringify(await r.json(),null,2)}
load()
</script></body></html>"""

class Handler(BaseHTTPRequestHandler):
    def _body_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))
    def _send(self, status, obj, content_type="application/json"):
        body = obj.encode() if isinstance(obj,str) else json.dumps(obj,default=str,ensure_ascii=False).encode()
        self.send_response(status); self.send_header("Content-Type",content_type); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        try:
            if self.path=="/":
                return self._send(200,HTML,"text/html; charset=utf-8")
            if self.path.startswith("/api/config"):
                return self._send(200,{
                    "PANS_INPUT_DIR":setting("PANS_INPUT_DIR",str(PANS_INPUT_DIR)),
                    "WRS_INPUT_DIR":setting("WRS_INPUT_DIR",str(WRS_INPUT_DIR)),
                    "NSC_INPUT_DIR":setting("NSC_INPUT_DIR",str(NSC_INPUT_DIR))
                })
            if self.path.startswith("/api/status"):
                with db() as conn:
                    counts={}
                    for t in ("reference_wrs_current","reference_pans_current","reference_nsc_current","field_mapping","unlocode","destination_mapping"):
                        counts[t]=conn.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"]
                    pending=conn.execute("SELECT count(*) AS n FROM pans_pending WHERE processed_at IS NULL").fetchone()["n"]
                return self._send(200,{"database":"READY","host":PG_HOST,"port":PG_PORT,"database_name":PG_DATABASE,"counts":counts,"pans_pending":pending})
            if self.path.startswith("/api/search"):
                from urllib.parse import urlparse,parse_qs
                q=parse_qs(urlparse(self.path).query).get("q",[""])[0].strip()
                with db() as conn:
                    rows=conn.execute(
                        """SELECT 'WRS' source,dataset_name dataset,vessel_id,mmsi,imo,callsign,vessel_name,data
                           FROM reference_wrs_current WHERE mmsi::text=%s OR imo::text=%s OR upper(callsign)=upper(%s) OR upper(vessel_name) LIKE upper(%s)
                           LIMIT 50""",(q,q,q,f"%{q}%")
                    ).fetchall()
                    rows += conn.execute(
                        """SELECT 'PANS' source,document_type dataset,NULL vessel_id,mmsi,imo,callsign,vessel_name,data
                           FROM reference_pans_current WHERE mmsi::text=%s OR imo::text=%s OR upper(callsign)=upper(%s) OR upper(vessel_name) LIKE upper(%s)
                           LIMIT 50""",(q,q,q,f"%{q}%")
                    ).fetchall()
                    rows += conn.execute(
                        """SELECT 'NSC' source,'NSC' dataset,NULL vessel_id,mmsi,imo,callsign,vessel_name,data
                           FROM reference_nsc_current WHERE mmsi::text=%s OR imo::text=%s OR upper(callsign)=upper(%s) OR upper(vessel_name) LIKE upper(%s)
                           LIMIT 50""",(q,q,q,f"%{q}%")
                    ).fetchall()
                return self._send(200,rows)
            if self.path.startswith("/api/sources"):
                with db() as conn:
                    rows=conn.execute("SELECT * FROM source ORDER BY source_id,source_name").fetchall()
                return self._send(200,rows)
            if self.path.startswith("/api/mappings"):
                with db() as conn:
                    rows=conn.execute("SELECT * FROM field_mapping ORDER BY source_name,mapping_id").fetchall()
                return self._send(200,rows)
            if self.path.startswith("/api/parser-mappings"):
                with db() as conn:
                    rows=conn.execute("SELECT * FROM parser_mapping ORDER BY source_name,logical_field").fetchall()
                return self._send(200,rows)
            if self.path.startswith("/api/reference"):
                from urllib.parse import urlparse,parse_qs
                table=parse_qs(urlparse(self.path).query).get("table",[""])[0]
                allowed={"wrs":"reference_wrs_current","pans":"reference_pans_current","nsc":"reference_nsc_current"}
                if table not in allowed:
                    return self._send(400,{"error":"table must be wrs, pans or nsc"})
                with db() as conn:
                    rows=conn.execute(f"SELECT * FROM {allowed[table]} ORDER BY updated_at DESC LIMIT 100").fetchall()
                return self._send(200,rows)
            return self._send(404,{"error":"not found"})
        except Exception as exc:
            log.exception("GET API failed")
            return self._send(500,{"error":str(exc)})
    def do_POST(self):
        try:
            if self.path.startswith("/api/browse/"):
                kind=self.path.rsplit("/",1)[-1]
                if kind not in {"wrs","nsc","pans"}:
                    return self._send(400,{"error":"unsupported browse target"})
                chosen=browse_folder_native()
                if not chosen:return self._send(200,{"status":"CANCELLED"})
                key={"wrs":"WRS_INPUT_DIR","nsc":"NSC_INPUT_DIR","pans":"PANS_INPUT_DIR"}[kind]
                set_setting(key,chosen)
                validator={"wrs":validate_wrs_root,"nsc":validate_nsc_root,"pans":validate_pans_root}[kind]
                ok,msg=validator(Path(chosen))
                return self._send(200,{"status":"VALID" if ok else "INVALID","path":chosen,"message":msg})
            if self.path=="/api/config/folder":
                body=self._body_json()
                key=body.get("key");value=body.get("path")
                allowed={"WRS_INPUT_DIR","NSC_INPUT_DIR","PANS_INPUT_DIR"}
                if key not in allowed or not value:return self._send(400,{"error":"invalid folder config"})
                set_setting(key,value)
                return self._send(200,{"status":"UPDATED","key":key,"path":value})
            if self.path=="/api/parser-mapping":
                body=self._body_json()
                if not {"source_name","logical_field","candidates"}.issubset(body):
                    return self._send(400,{"error":"source_name, logical_field and candidates required"})
                with db() as conn:
                    conn.execute(
                        """INSERT INTO parser_mapping(source_name,logical_field,candidates,default_value,transformation,enabled)
                           VALUES(%s,%s,%s::jsonb,%s,%s,%s)
                           ON CONFLICT(source_name,logical_field) DO UPDATE SET candidates=EXCLUDED.candidates,
                             default_value=EXCLUDED.default_value,transformation=EXCLUDED.transformation,
                             enabled=EXCLUDED.enabled,updated_at=now()""",
                        (body["source_name"],body["logical_field"],json.dumps(body["candidates"]),body.get("default_value"),
                         body.get("transformation"),bool(body.get("enabled",True)))
                    )
                return self._send(200,{"status":"UPDATED"})
            if self.path=="/api/mapping":
                body=self._body_json()
                required={"source_name","input_field","target_field"}
                if not required.issubset(body):
                    return self._send(400,{"error":"source_name,input_field,target_field required"})
                with db() as conn:
                    conn.execute(
                        """INSERT INTO field_mapping(source_name,input_field,target_field,transformation,required,fallback_order,enabled)
                           VALUES(%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT(source_name,input_field,target_field) DO UPDATE SET transformation=EXCLUDED.transformation,
                             required=EXCLUDED.required,fallback_order=EXCLUDED.fallback_order,enabled=EXCLUDED.enabled""",
                        (body["source_name"],body["input_field"],body["target_field"],body.get("transformation"),
                         bool(body.get("required",False)),int(body.get("fallback_order",1)),bool(body.get("enabled",True)))
                    )
                return self._send(200,{"status":"UPDATED"})
            if self.path=="/api/source":
                body=self._body_json()
                required={"source_id","source_name"}
                if not required.issubset(body):
                    return self._send(400,{"error":"source_id and source_name required"})
                with db() as conn:
                    conn.execute(
                        """INSERT INTO source(source_id,source_name,source_label,input_type,receive_port,enabled,notes)
                           VALUES(%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT(source_name) DO UPDATE SET source_id=EXCLUDED.source_id,source_label=EXCLUDED.source_label,
                             input_type=EXCLUDED.input_type,receive_port=EXCLUDED.receive_port,enabled=EXCLUDED.enabled,notes=EXCLUDED.notes""",
                        (int(body["source_id"]),body["source_name"],body.get("source_label"),body.get("input_type"),
                         body.get("receive_port"),bool(body.get("enabled",True)),body.get("notes"))
                    )
                return self._send(200,{"status":"UPDATED"})
            if self.path=="/api/destination":
                body=self._body_json()
                if not {"destination_key","destination_name"}.issubset(body):
                    return self._send(400,{"error":"destination_key and destination_name required"})
                with db() as conn:
                    conn.execute(
                        """INSERT INTO destination_mapping(destination_key,destination_name,locode,enabled)
                           VALUES(%s,%s,%s,%s)
                           ON CONFLICT(destination_key) DO UPDATE SET destination_name=EXCLUDED.destination_name,
                             locode=EXCLUDED.locode,enabled=EXCLUDED.enabled,updated_at=now()""",
                        (body["destination_key"],body["destination_name"],body.get("locode"),bool(body.get("enabled",True)))
                    )
                return self._send(200,{"status":"UPDATED"})
            if self.path=="/api/unlocode":
                body=self._body_json()
                if not {"locode","location_name"}.issubset(body):
                    return self._send(400,{"error":"locode and location_name required"})
                with db() as conn:
                    conn.execute(
                        """INSERT INTO unlocode(locode,country_code,location_code,location_name,subdivision,function_code,status,raw_data)
                           VALUES(%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                           ON CONFLICT(locode) DO UPDATE SET country_code=EXCLUDED.country_code,location_code=EXCLUDED.location_code,
                             location_name=EXCLUDED.location_name,subdivision=EXCLUDED.subdivision,function_code=EXCLUDED.function_code,
                             status=EXCLUDED.status,raw_data=EXCLUDED.raw_data,updated_at=now()""",
                        (body["locode"],body.get("country_code"),body.get("location_code"),body["location_name"],body.get("subdivision"),
                         body.get("function_code"),body.get("status"),json.dumps(body.get("raw_data",{}),ensure_ascii=False))
                    )
                return self._send(200,{"status":"UPDATED"})
            if self.path=="/api/import/wrs":
                return self._send(200,import_wrs_once(configured_dir("WRS_INPUT_DIR",WRS_INPUT_DIR)))
            if self.path=="/api/import/nsc":
                return self._send(200,import_nsc_once(configured_dir("NSC_INPUT_DIR",NSC_INPUT_DIR)))
            if self.path=="/api/import/pans/once":
                pans_dir=configured_dir("PANS_INPUT_DIR",PANS_INPUT_DIR)
                files=list(pans_dir.rglob("*.xml")) if pans_dir.exists() else []
                ok=sum(1 for p in files if pans_process_file(p))
                return self._send(200,{"status":"COMPLETED","files":len(files),"processed":ok})
            return self._send(404,{"error":"not found"})
        except Exception as exc:
            log.exception("POST API failed")
            return self._send(500,{"error":str(exc)})
    def log_message(self, fmt,*args):
        log.info("WEB "+fmt,args)

def main():
    MANAGER.start()
    server=ThreadingHTTPServer((WEB_HOST,WEB_PORT),Handler)
    log.info("Validation DB Manager ready: http://%s:%s",WEB_HOST,WEB_PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        MANAGER.stop()
        server.server_close()

if __name__=="__main__":
    main()
