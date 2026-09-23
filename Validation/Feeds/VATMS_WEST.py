#!/usr/bin/env python3
"""Standalone VATMS_WEST processor: parse -> normalize -> correlate -> enrich -> XML -> forward."""
from __future__ import annotations
import csv, hashlib, json, logging, math, os, re, socket, time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape
import psycopg
from psycopg.rows import dict_row

# ================= USER-EDITABLE SETTINGS =================
SOURCE_NAME="VATMS_WEST"
INPUT_TYPE="FOLDER"                         # FOLDER / TCP
INPUT_FOLDER=r"DB_Data\VATMS_WEST"
TCP_HOST="127.0.0.1"; TCP_PORT=10001
OUTPUT_FOLDER=r"XML_Output\VATMS_WEST"
FORWARDING_ENABLED=False                    # True / False
FORWARDING_TYPE="NONE"                      # NONE / FOLDER / TCP
FORWARDING_FOLDER=r""
FORWARDING_HOST="127.0.0.1"; FORWARDING_PORT=0
POLL_SECONDS=1.0; FILE_STABILITY_SECONDS=0.25; RUN_ONCE=False
PG_HOST=os.getenv("VALIDATION_PG_HOST","127.0.0.1")
PG_PORT=int(os.getenv("VALIDATION_PG_PORT","5432"))
PG_DATABASE=os.getenv("VALIDATION_PG_DATABASE","validation")
PG_USER=os.getenv("VALIDATION_PG_USER","validation")
PG_PASSWORD=os.getenv("VALIDATION_PG_PASSWORD","")
ACTIVE_THRESHOLD_SECONDS=3*3600
MAX_SPEED_KNOTS={"default":50.0,"commercial":40.0,"cargo":40.0,"tanker":40.0,"passenger":45.0,"fishing":45.0,"high_speed":70.0}
# ==========================================================
ROOT=Path(__file__).resolve().parents[1]; STATE=ROOT/"state"; LOGS=ROOT/"logs"
OUT=ROOT/OUTPUT_FOLDER; STATE.mkdir(parents=True,exist_ok=True); LOGS.mkdir(parents=True,exist_ok=True); OUT.mkdir(parents=True,exist_ok=True)
logging.basicConfig(level=os.getenv("VALIDATION_LOG_LEVEL","INFO").upper(),format="%(asctime)s %(levelname)s VATMS_WEST %(message)s",
                    handlers=[logging.StreamHandler(),logging.FileHandler(LOGS/"VATMS_WEST.log",encoding="utf-8")])
log=logging.getLogger("VATMS_WEST")
DONE_FILE=STATE/"VATMS_WEST_processed.json"

FIELDS=["ais.lenToBow","ais.lenToStern","ais.navStatus","ais.typeAndCargo","ais.widthToPort","ais.widthToStarboard","app.message.id",
"cat.annotation","cat.category","cat.identity","foreign.track.number","id.callsign","id.imo","id.mmsi","id.mmsi.destination",
"kinematic.course.true","kinematic.flag.3d","kinematic.heading.true","kinematic.pos.lla.alt","kinematic.pos.lla.lat","kinematic.pos.lla.lon",
"kinematic.speed","sys.source.id","sys.track.number","timestamp.receipt","timestamp.source","track.flag.active","track.quality",
"vessel.beam","vessel.description","vessel.draft","vessel.grosstonnage","vessel.length","vessel.name","vessel.remarks",
"voyage.arrival","voyage.departure","voyage.destination","voyage.eta","voyage.etd","voyage.origin"]
SPECS={"ais.lenToBow":("qv","m"),"ais.lenToStern":("qv","m"),"ais.navStatus":("sv",None),"ais.typeAndCargo":("sv",None),
"ais.widthToPort":("qv","m"),"ais.widthToStarboard":("qv","m"),"app.message.id":("sv",None),"cat.annotation":("sv",None),
"cat.category":("sv",None),"cat.identity":("sv",None),"foreign.track.number":("sv",None),"id.callsign":("sv",None),
"id.imo":("iv",None),"id.mmsi":("iv",None),"id.mmsi.destination":("iv",None),"kinematic.course.true":("qv","rad"),
"kinematic.flag.3d":("bv",None),"kinematic.heading.true":("qv","rad"),"kinematic.pos.lla.alt":("qv","m"),
"kinematic.pos.lla.lat":("qv","rad"),"kinematic.pos.lla.lon":("qv","rad"),"kinematic.speed":("qv","m/s"),
"sys.source.id":("iv",None),"sys.track.number":("iv",None),"timestamp.receipt":("tv",None),"timestamp.source":("tv",None),
"track.flag.active":("bv",None),"track.quality":("iv",None),"vessel.beam":("qv","m"),"vessel.description":("sv",None),
"vessel.draft":("qv","m"),"vessel.grosstonnage":("qv","t"),"vessel.length":("qv","m"),"vessel.name":("sv",None),
"vessel.remarks":("sv",None),"voyage.arrival":("sv",None),"voyage.departure":("sv",None),"voyage.destination":("sv",None),
"voyage.eta":("tv",None),"voyage.etd":("tv",None),"voyage.origin":("sv",None)}
NSC="http://www.raytheon.com/athena/ctrack/common/1.1"; NSX="http://www.raytheon.com/athena/ctrack/xtrack/1.1"

def clean(v): return "" if v is None else "".join(c for c in str(v) if ord(c)>=32 or c in "\t\n\r").strip()
def num(v,integer=False):
    try:
        if v in (None,""): return None
        x=float(v); return int(x) if integer else x
    except (TypeError,ValueError): return None
def valid_mmsi(v):
    try:return 100000000<=int(v)<=999999999
    except:return False
def valid_imo(v):
    try:return 1000000<=int(v)<=9999999
    except:return False
def iso_ms(v):
    if v is None:return None
    try:
        if isinstance(v,(int,float)): n=int(v); return n if n>=100000000000 else n*1000
        s=str(v).strip()
        if not s:return None
        try:n=int(float(s));return n if n>=100000000000 else n*1000
        except ValueError:pass
        dt=datetime.fromisoformat(s.replace("Z","+00:00"))
        if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp()*1000)
    except Exception:return None
def type_text(v):
    n=num(v,True)
    if n is None:return clean(v)
    m={0:"UNDEFINED",20:"WIG",30:"FISHING VESSEL",31:"TOWING VESSEL",32:"TOWING VESSEL WITH LENGTH OF TOW EXCEEDING 200 M OR BREADTH EXCEEDING 25 M",
       33:"VESSEL ENGAGED IN DREDGING OR UNDERWATER OPERATIONS",34:"VESSEL ENGAGED IN DIVING OPERATIONS",35:"VESSEL ENGAGED IN MILITARY OPERATIONS",
       36:"SAILING VESSEL",37:"PLEASURE CRAFT",50:"PILOT VESSEL",51:"SEARCH AND RESCUE VESSEL",52:"TUG",53:"PORT TENDER",
       54:"VESSEL WITH ANTI-POLLUTION FACILITIES OR EQUIPMENT",55:"LAW ENFORCEMENT VESSEL",58:"MEDICAL TRANSPORT",59:"SHIP ACCORDING TO RR RESOLUTION NO. 18",
       60:"PASSENGER SHIP",70:"CARGO SHIP",80:"TANKER",90:"OTHER VESSEL"}
    if n in m:return m[n]
    if 20<=n<30:return f"WIG {n}"
    if 40<=n<50:return f"HSC {n}"
    if 60<=n<70:return f"PASSENGER SHIP {n}"
    if 70<=n<80:return f"CARGO SHIP {n}"
    if 80<=n<90:return f"TANKER {n}"
    if 90<=n<100:return f"OTHER VESSEL {n}"
    return "OTHER VESSEL"
NAV={0:"UNDER WAY USING ENGINE",1:"ANCHORED",2:"NOT UNDER COMMAND",3:"RESTRICTED MANOEUVRABILITY",4:"CONSTRAINED BY HER DRAUGHT",
     5:"MOORED",6:"AGROUND",7:"ENGAGED IN FISHING",8:"UNDER WAY SAILING",9:"RESERVED FOR FUTURE USE",10:"RESERVED FOR FUTURE USE",
     11:"RESERVED FOR FUTURE USE",12:"RESERVED FOR FUTURE USE",13:"RESERVED FOR FUTURE USE",14:"RESERVED FOR FUTURE USE",15:"NOT DEFINED"}

@dataclass
class R:
    timestamp=None;mmsi=None;imo=None;callsign=None;vessel_name=None;vessel_type=None;latitude=None;longitude=None;sog=None;cog=None;true_heading=None;nav_status=None
    def __init__(self, **kwargs):
        for key,value in kwargs.items(): setattr(self,key,value)
    len_to_bow=None;len_to_stern=None;width_to_port=None;width_to_starboard=None;length=None;width=None;draught=None;destination=None;eta=None;gross_tonnage=None;origin=None;arrival=None;departure=None;altitude=None;app_message_id=None;raw_payload="";etd=None;raw_attributes:dict=field(default_factory=dict)

AIS_CHARSET="@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_ !\"#$%&'()*+,-./0123456789:;<=>?"
def six(payload):
    b=[]
    for c in payload:
        v=ord(c)-48
        if v>40:v-=8
        if not 0<=v<=63:raise ValueError("invalid AIS 6-bit character")
        b.append(f"{v:06b}")
    return "".join(b)
def astr(bits):
    s=""
    for i in range(0,len(bits)-5,6):
        n=int(bits[i:i+6],2)
        if n<len(AIS_CHARSET) and AIS_CHARSET[n]!="@":s+=AIS_CHARSET[n]
    return s.strip()
def sint(bits):
    n=int(bits,2);return n-(1<<len(bits)) if n&(1<<(len(bits)-1)) else n
def checksum(s):
    if "*" not in s:return True
    body,sup=s.rsplit("*",1);x=0
    for c in body[1:]:x^=ord(c)
    try:return x==int(sup[:2],16)
    except:return False

FRAG={}; META={}
def parse_lines(lines):
    out=[]
    for line_no,line in enumerate(lines,1):
        line=line.strip()
        if not line:continue
        tag_ts=None;nmea=line
        if line.startswith("\\"):
            e=line.find("\\",1)
            if e>=0:
                tag=line[1:e];nmea=line[e+1:].lstrip();m=re.search(r"\bc:(\d+)\b",tag)
                if m:tag_ts=datetime.fromtimestamp(int(m.group(1)),timezone.utc).isoformat()
        if not nmea.startswith(("!","$")):raise ValueError("Malformed NMEA prefix")
        if not checksum(nmea):raise ValueError("NMEA checksum validation failed")
        p=nmea.split(",")
        if len(p)<6:raise ValueError("Malformed NMEA sentence")
        total=int(p[1]) if p[1].isdigit() else 1;seq=int(p[2]) if p[2].isdigit() else 1;sid=p[3];payload=p[5];fill=0
        if len(p)>6:
            try:fill=int(p[6].split("*",1)[0] or 0)
            except:fill=0
        ts=tag_ts or datetime.now(timezone.utc).isoformat()
        if total>1:
            key=(sid,total);FRAG.setdefault(key,{})[seq]=(payload,ts)
            if seq==1:
                bb=six(payload)
                if len(bb)>=38:META[key]=(int(bb[:6],2),int(bb[8:38],2))
            if len(FRAG[key])<total:
                mt=META.get(key,(None,None));out.append(R(timestamp=ts,mmsi=mt[1],app_message_id=mt[0],raw_payload=line,
                    raw_attributes={"multipart":True,"fragment_number":seq,"fragment_count":total,"sequence_id":sid,"complete_decode":False}));continue
            payload="".join(FRAG[key][i][0] for i in range(1,total+1));ts=FRAG[key][1][1];FRAG.pop(key,None);META.pop(key,None)
        bits=six(payload)
        if fill:bits=bits[:-fill]
        if len(bits)<38:raise ValueError("AIS payload too short")
        typ=int(bits[:6],2);mmsi=int(bits[8:38],2);r=R(timestamp=ts,mmsi=mmsi,app_message_id=typ,raw_payload=line)
        if typ in (1,2,3) and len(bits)>=137:
            r.nav_status=int(bits[38:42],2);v=int(bits[50:60],2);r.sog=v/10 if v!=1023 else None
            lo=sint(bits[61:89]);la=sint(bits[89:116]);r.longitude=round(lo/600000,6) if lo!=-0x6791AC0 else None;r.latitude=round(la/600000,6) if la!=-0x3412140 else None
            c=int(bits[116:128],2);r.cog=c/10 if c!=3600 else None;h=int(bits[128:137],2);r.true_heading=float(h) if h!=511 else None
        elif typ==5 and len(bits)>=422:
            r.imo=int(bits[40:70],2) or None;r.callsign=astr(bits[70:112]) or None;r.vessel_name=astr(bits[112:232]) or None;r.vessel_type=int(bits[232:240],2) or None
            r.len_to_bow=int(bits[240:249],2);r.len_to_stern=int(bits[249:258],2);r.width_to_port=int(bits[258:264],2);r.width_to_starboard=int(bits[264:270],2)
            r.length=(r.len_to_bow+r.len_to_stern) or None;r.width=(r.width_to_port+r.width_to_starboard) or None;d=int(bits[294:302],2);r.draught=d/10 if d else None;r.destination=astr(bits[302:422]) or None
        elif typ==18 and len(bits)>=133:
            v=int(bits[46:56],2);r.sog=v/10 if v!=1023 else None;lo=sint(bits[57:85]);la=sint(bits[85:112]);r.longitude=round(lo/600000,6) if lo!=-0x6791AC0 else None;r.latitude=round(la/600000,6) if la!=-0x3412140 else None
            c=int(bits[112:124],2);r.cog=c/10 if c!=3600 else None;h=int(bits[124:133],2);r.true_heading=float(h) if h!=511 else None
        elif typ==19 and len(bits)>=309:
            v=int(bits[46:56],2);r.sog=v/10 if v!=1023 else None;lo=sint(bits[57:85]);la=sint(bits[85:112]);r.longitude=round(lo/600000,6) if lo!=-0x6791AC0 else None;r.latitude=round(la/600000,6) if la!=-0x3412140 else None
            c=int(bits[112:124],2);r.cog=c/10 if c!=3600 else None;h=int(bits[124:133],2);r.true_heading=float(h) if h!=511 else None;r.vessel_name=astr(bits[143:263]) or None;r.vessel_type=int(bits[263:271],2) or None
            bo=int(bits[271:280],2);st=int(bits[280:289],2);po=int(bits[289:295],2);sa=int(bits[295:301],2);r.length=(bo+st) or None;r.width=(po+sa) or None
        elif typ==21 and len(bits)>=272:
            r.vessel_type=int(bits[38:42],2) or None;r.vessel_name=astr(bits[43:163]) or None;lo=sint(bits[164:192]);la=sint(bits[192:219]);r.longitude=round(lo/600000,6) if lo!=-0x6791AC0 else None;r.latitude=round(la/600000,6) if la!=-0x3412140 else None
        elif typ==24 and len(bits)>=160:
            part=int(bits[38:40],2)
            if part==0:r.vessel_name=astr(bits[40:160]) or None
            elif part==1:r.vessel_type=int(bits[40:48],2) or None;r.callsign=astr(bits[90:132]) or None
        elif typ==27 and len(bits)>=104:
            v=int(bits[46:54],2);r.sog=float(v) if v!=127 else None;c=int(bits[55:64],2);r.cog=c*2 if c!=511 else None;lo=sint(bits[64:84]);la=sint(bits[84:104]);r.longitude=round(lo/600,6) if lo else None;r.latitude=round(la/600,6) if la else None
        out.append(r)
    return out


def parse_vatms_west(lines):
    out=[]
    for line_no,line in enumerate(lines,1):
        line=line.strip()
        if not line: continue
        if line.startswith("$TMVTD"):
            p=line.split(",")
            if len(p)<14: raise ValueError("TMVTD has fewer than 14 fields")
            if not checksum(line): raise ValueError("TMVTD checksum validation failed")
            if any(x.startswith("D*") for x in p[-2:]) or "D*" in p[-1]: continue
            ts=datetime.now(timezone.utc).isoformat()
            ds=p[1].strip() if len(p)>1 else "";tsv=p[2].strip() if len(p)>2 else ""
            if len(ds)==6 and len(tsv)>=6:
                ts=f"20{ds[:2]}-{ds[2:4]}-{ds[4:6]}T{tsv[:2]}:{tsv[2:4]}:{tsv[4:6]}Z"
            def dm(s,hemi,lon=False):
                try:
                    deg=float(s[:3] if lon else s[:2]);minutes=float(s[3:] if lon else s[2:]);v=deg+minutes/60.0
                    return -v if hemi in ("S","W") else v
                except:return None
            r=R(timestamp=ts,mmsi=num(p[20],True) if len(p)>20 and p[20].strip().isdigit() else None,imo=num(p[23],True) if len(p)>23 and p[23].strip().isdigit() else None)
            r.vessel_name=clean(p[5]) if len(p)>5 else None;r.latitude=dm(p[6],p[7] if len(p)>7 else "N");r.longitude=dm(p[8],p[9] if len(p)>9 else "E",True)
            r.cog=num(p[10]) if len(p)>10 else None;r.sog=num(p[12]) if len(p)>12 else None;r.vessel_type=clean(p[14]) if len(p)>14 else None;r.callsign=clean(p[15]) if len(p)>15 else None
            r.length=num(p[16])/100.0 if len(p)>16 and p[16].strip() else None;r.width=num(p[17])/100.0 if len(p)>17 and p[17].strip() else None;r.draught=num(p[18])/100.0 if len(p)>18 and p[18].strip() else None;r.raw_payload=line;out.append(r)
        elif line.startswith("!"):
            out.extend(parse_lines([line]))
    return out

class Ref:
    def __init__(self):
        self.c=psycopg.connect(host=PG_HOST,port=PG_PORT,dbname=PG_DATABASE,user=PG_USER,password=PG_PASSWORD,row_factory=dict_row)
    def v(self,d,*names):
        low={str(k).lower():v for k,v in (d or {}).items()}
        for n in names:
            x=low.get(n.lower())
            if x not in (None,"","-","N/A","None"):return x
    def one(self,table,where,args):
        rows=self.c.execute(f"SELECT * FROM {table} WHERE {where} LIMIT 2",args).fetchall();return rows[0] if len(rows)==1 else None
    def resolve(self,mmsi,imo,callsign,name):
        x={"WRS":False,"PANS":False,"NSC":False}
        # WRS correlation: MMSI -> IMO -> CALLSIGN -> VESSEL_NAME
        row=None;method=None
        for fld,val,label in (("mmsi",mmsi,"MMSI"),("imo",imo,"IMO"),("callsign",callsign,"CALLSIGN"),("vessel_name",name,"VESSEL_NAME")):
            if val in (None,""):continue
            where=f"dataset_name='VESSELS' AND {fld}=%s" if fld!="vessel_name" else "dataset_name='VESSELS' AND upper(vessel_name)=upper(%s)"
            row=self.one("reference_wrs_current",where,(val,))
            if row:method=label;break
        if row:
            x["WRS"]=True;x["wrs_match_method"]=method;d=row["data"] or {};x["wrs_vessel_id"]=row.get("vessel_id");x["wrs_mmsi"]=row.get("mmsi");x["wrs_imo"]=row.get("imo");x["wrs_callsign"]=row.get("callsign");x["wrs_vessel_name"]=row.get("vessel_name")
            x["wrs_vessel_type"]=self.v(d,"VESSEL_TYPE");x["wrs_status"]=self.v(d,"STATUS")
            vid=row.get("vessel_id")
            def aux(ds):
                return self.c.execute("SELECT * FROM reference_wrs_current WHERE dataset_name=%s AND vessel_id=%s ORDER BY updated_at DESC LIMIT 1",(ds,vid)).fetchone() if vid else None
            for ds,target,names in (("VESSEL_DIMENSIONS","dims",("LOA","BREADTH_EXTREME","DRAFT")),("VIGILANCE","vig",("SCORE",)),("CALLINGS","call",("PLACE","ARRIVAL_DATE","SAILING_DATE")),("DECODE_VESSEL_STATUS","status",("STATUS_DECODE",))):
                z=aux(ds)
                if z:
                    dd=z["data"] or {}
                    if target=="dims":x.update(wrs_loa=num(self.v(dd,"LOA")),wrs_breadth=num(self.v(dd,"BREADTH_EXTREME")),wrs_draft=num(self.v(dd,"DRAFT")))
                    elif target=="vig":x["wrs_vigilance_score"]=num(self.v(dd,"SCORE"))
                    elif target=="call":x.update(wrs_calling_place=self.v(dd,"PLACE"),wrs_calling_arrival=self.v(dd,"ARRIVAL_DATE"),wrs_calling_sailing=self.v(dd,"SAILING_DATE"))
                    else:x["wrs_status_decode"]=self.v(dd,"STATUS_DECODE")
            for ds,key in (("AISSPOOFING_RISK","wrs_ais_spoofing_detail"),("AIS_GAP_RISK","wrs_ais_gap_detail"),("AIS_MNPTN_RISK","wrs_ais_identity_detail"),("VESSEL_SANCTIONS","wrs_sanctions_detail")):
                z=aux(ds)
                if z:
                    dd=z["data"] or {};x[key]=" | ".join(f"{k}={v}" for k,v in dd.items() if k!="VESSEL_ID" and v not in (None,"")) or "PRESENT"
        # PANS correlation: IMO -> MMSI -> CALLSIGN -> VESSEL_NAME
        row=None;method=None
        for fld,val,label in (("imo",imo,"IMO"),("mmsi",mmsi,"MMSI"),("callsign",callsign,"CALLSIGN"),("vessel_name",name,"VESSEL_NAME")):
            if val in (None,""):continue
            where=f"document_type='VESPRO' AND {fld}=%s" if fld!="vessel_name" else "document_type='VESPRO' AND upper(vessel_name)=upper(%s)"
            row=self.one("reference_pans_current",where,(val,))
            if row:method=label;break
        if row:
            x["PANS"]=True;x["pans_match_method"]=method;d=row["data"] or {};x.update(pans_vessel_name=self.v(d,"VesselName"),pans_callsign=self.v(d,"CallSign"),pans_beam=num(self.v(d,"Beam")),pans_loa=num(self.v(d,"LOA")),pans_max_draft=num(self.v(d,"MaxDraft")),pans_grt=num(self.v(d,"GRT")),pans_vessel_type=self.v(d,"VesselType"),pans_imo=num(self.v(d,"IMONumber"),True),pans_mmsi=num(self.v(d,"MMSINumber"),True))
            pimo=x.get("pans_imo") or imo;pcs=x.get("pans_callsign") or callsign
            def pa(ds):
                if pimo:return self.one("reference_pans_current","document_type=%s AND imo=%s",(ds,pimo))
                if pcs:return self.one("reference_pans_current","document_type=%s AND upper(callsign)=upper(%s)",(ds,pcs))
            z=pa("CALINV")
            if z:x["pans_vcn"]=self.v(z["data"],"VCN")
            z=pa("CALINF")
            if z:x.update(pans_org_dep=self.v(z["data"],"OriginalPortOfDep"),pans_lpc=self.v(z["data"],"LastPortOfCall"),pans_npc=self.v(z["data"],"DockORTOCode"),pans_eta=self.v(z["data"],"EDTA","VOYAGE_ETA"),pans_etd=self.v(z["data"],"EDTD","VOYAGE_ETD"))
            z=pa("BERMAN")
            if z:x.update(pans_berman_dest=self.v(z["data"],"DestinationPortl","DestinationPort"),pans_berman_lpc=self.v(z["data"],"Portcode"),pans_berman_eta=self.v(z["data"],"EDTA"),pans_berman_etd=self.v(z["data"],"EDTD"),pans_draft_fwd=num(self.v(z["data"],"DraftFwd")),pans_draft_aft=num(self.v(z["data"],"DraftAft")),pans_vcn=self.v(z["data"],"VCN") or x.get("pans_vcn"),pans_cargo_description=self.v(z["data"],"CargoDescription"),pans_cargo_tonnage=num(self.v(z["data"],"TotalCargoTonnage")),pans_hazardous=self.v(z["data"],"HazCargoOnBoard"))
        # NSC correlation: MMSI -> IMO -> CALLSIGN -> VESSEL_NAME
        row=None;method=None
        for fld,val,label in (("mmsi",mmsi,"MMSI"),("imo",imo,"IMO"),("callsign",callsign,"CALLSIGN"),("vessel_name",name,"VESSEL_NAME")):
            if val in (None,""):continue
            where=f"{fld}=%s" if fld!="vessel_name" else "upper(vessel_name)=upper(%s)"
            row=self.one("reference_nsc_current",where,(val,))
            if row:method=label;break
        if row:
            x["NSC"]=True;x["nsc_match_method"]=method;d=row["data"] or {};x.update(nsc_vessel_name=self.v(d,"VESSEL_NAME"),nsc_imo=num(self.v(d,"ID_IMO"),True),nsc_mmsi=num(self.v(d,"ID_MMSI"),True),nsc_callsign=self.v(d,"ID_CALLSIGN"),nsc_type=self.v(d,"TYPE"),nsc_region=self.v(d,"SOURCE_REGION"),nsc_begin_date=self.v(d,"BEGIN_DATE"),nsc_end_date=self.v(d,"END_DATE"))
        return x

def state(conn,mmsi):
    if not valid_mmsi(mmsi):return {}
    r=conn.execute("SELECT values_json FROM mmsi_history WHERE mmsi=%s",(int(mmsi),)).fetchone()
    if not r:return {}
    return r["values_json"] if isinstance(r["values_json"],dict) else json.loads(r["values_json"])
def save_state(conn,mmsi,vals,ts):
    if not valid_mmsi(mmsi):return
    old=state(conn,mmsi);old.update({k:v for k,v in vals.items() if v not in (None,"")})
    conn.execute("""INSERT INTO mmsi_history(mmsi,values_json,last_tx_iso,last_source,updated_at) VALUES(%s,%s::jsonb,%s,%s,now())
                    ON CONFLICT(mmsi) DO UPDATE SET values_json=EXCLUDED.values_json,last_tx_iso=EXCLUDED.last_tx_iso,last_source=EXCLUDED.last_source,updated_at=now()""",
                 (int(mmsi),json.dumps(old,ensure_ascii=False,default=str),str(ts or ""),SOURCE_NAME))

def fallback(ctx,logical,*names):
    orders={"id.imo":("NSC","PANS","WRS"),"id.callsign":("NSC","PANS","WRS"),"vessel.name":("NSC","PANS","WRS"),"vessel.description":("NSC","PANS","WRS"),"ais.typeAndCargo":("NSC","PANS","WRS"),
    "vessel.length":("WRS","PANS","NSC"),"vessel.beam":("WRS","PANS","NSC"),"vessel.draft":("PANS","WRS","NSC"),"vessel.grosstonnage":("WRS","PANS","NSC"),
    "voyage.arrival":("NSC","PANS","WRS"),"voyage.departure":("NSC","PANS","WRS"),"voyage.destination":("NSC","PANS","WRS"),"voyage.eta":("NSC","PANS","WRS"),"voyage.etd":("NSC","PANS","WRS"),"voyage.origin":("NSC","PANS","WRS"),
    "cat.annotation":("WRS","PANS","NSC"),"cat.identity":("WRS","PANS","NSC"),"id.mmsi.destination":("WRS","PANS","NSC"),"foreign.track.number":("NSC","PANS","WRS")}
    for src in orders.get(logical,("NSC","PANS","WRS")):
        if not ctx.get(src):continue
        for n in names:
            v=ctx.get(src.lower()+"_"+n)
            if v not in (None,""):return v
    return None

def enrich(r,ctx,conn,h):
    effective=r.mmsi if valid_mmsi(r.mmsi) else next((int(v) for v in (ctx.get("nsc_mmsi"),ctx.get("pans_mmsi"),ctx.get("wrs_mmsi")) if valid_mmsi(v)),None)
    r.callsign=clean(r.callsign) or clean(fallback(ctx,"id.callsign","callsign"));r.imo=int(r.imo) if valid_imo(r.imo) else fallback(ctx,"id.imo","imo")
    r.vessel_name=clean(r.vessel_name);r.vessel_name=r.vessel_name if r.vessel_name and r.vessel_name.upper() not in ("UNKNOWN","N/A","NONE","-") else clean(fallback(ctx,"vessel.name","vessel_name")) or "UNKNOWN"
    r.vessel_type=r.vessel_type if r.vessel_type not in (None,"") else fallback(ctx,"ais.typeAndCargo","vessel_type");r.length=r.length if r.length is not None else num(fallback(ctx,"vessel.length","loa"))
    r.width=r.width if r.width is not None else num(fallback(ctx,"vessel.beam","breadth","beam"));r.draught=r.draught if r.draught is not None else num(fallback(ctx,"vessel.draft","draft","max_draft"));r.gross_tonnage=r.gross_tonnage if r.gross_tonnage is not None else num(fallback(ctx,"vessel.grosstonnage","gross","grt"))
    if r.destination is None:r.destination=fallback(ctx,"voyage.destination","berman_dest","npc","calling_place")
    if r.origin is None:r.origin=fallback(ctx,"voyage.origin","org_dep","calling_place")
    if r.departure is None:r.departure=fallback(ctx,"voyage.departure","lpc","berman_lpc","calling_sailing")
    if r.arrival is None:r.arrival=fallback(ctx,"voyage.arrival","berman_eta","calling_arrival")
    if r.eta is None:r.eta=fallback(ctx,"voyage.eta","eta","berman_eta")
    if r.etd is None:r.etd=fallback(ctx,"voyage.etd","etd","berman_etd")
    if ctx.get("wrs_status_decode"):r.raw_attributes["cat_annotation"]=ctx["wrs_status_decode"]
    score=ctx.get("wrs_vigilance_score");r.raw_attributes["vigilance_score"]=score
    r.cat_identity=(1 if float(score)<300 else 4 if float(score)>600 else 3) if score is not None else "Unknown"
    # Position-history validation; dynamic XML kinematics remain incoming-only.
    try:
        if h.get("_track_lat") is not None and h.get("_track_lon") is not None and r.latitude is not None and r.longitude is not None:
            t1=iso_ms(h.get("_track_ts"));t2=iso_ms(r.timestamp)
            if t1 is not None and t2 is not None and t2>t1:
                p1=math.radians(float(h["_track_lat"]));p2=math.radians(float(r.latitude));dp=math.radians(float(r.latitude)-float(h["_track_lat"]));dl=math.radians(float(r.longitude)-float(h["_track_lon"]))
                aa=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2;dist=3440.065*2*math.atan2(math.sqrt(aa),math.sqrt(max(0.0,1.0-aa)));calc=dist/((t2-t1)/3600000.0);limit=MAX_SPEED_KNOTS["default"];vt=type_text(r.vessel_type).lower()
                for kk in ("high_speed","passenger","tanker","cargo","commercial","fishing"):
                    if kk in vt:limit=MAX_SPEED_KNOTS[kk];break
                if calc>limit:r.raw_attributes["positional_spoofing"]={"calculated_speed_knots":round(calc,3),"distance_nm":round(dist,3),"elapsed_seconds":round((t2-t1)/1000.0,3),"threshold_knots":limit,"reported_sog_knots":num(r.sog)}
    except (TypeError,ValueError,ZeroDivisionError):
        pass
    # final persistent MMSI fallback; never copy dynamic position/course/speed/heading/timestamps
    for k in ("len_to_bow","len_to_stern","nav_status","vessel_type","width_to_port","width_to_starboard","length","width","draught","gross_tonnage","callsign","imo","vessel_name","destination","origin" ,"arrival","departure","eta","etd"):
        if getattr(r,k,None) in (None,"") and h.get(k) not in (None,""):setattr(r,k,h[k])
    lines=[f"WRS      | AIS SPOOFING RISK   : {ctx.get('wrs_ais_spoofing_detail') or 'NONE'}",f"WRS      | AIS GAP RISK        : {ctx.get('wrs_ais_gap_detail') or 'NONE'}",
           f"WRS      | VIGILANCE SCORE    : {ctx.get('wrs_vigilance_score') if ctx.get('wrs_vigilance_score') is not None else 'NONE'}",f"WRS      | SANCTIONS          : {ctx.get('wrs_sanctions_detail') or 'NONE'}"]
    vp=[];d=ctx.get("pans_berman_dest") or ctx.get("pans_npc")
    if d:vp.append("NEXT PORT="+str(d))
    if ctx.get("pans_eta") or ctx.get("pans_berman_eta"):vp.append("ETA="+str(ctx.get("pans_eta") or ctx.get("pans_berman_eta")))
    if ctx.get("pans_etd") or ctx.get("pans_berman_etd"):vp.append("ETD="+str(ctx.get("pans_etd") or ctx.get("pans_berman_etd")))
    if ctx.get("pans_vcn"):vp.append("VCN="+str(ctx["pans_vcn"]))
    lines.append("PANS     | VOYAGE             : "+(" | ".join(vp) if vp else "UNAVAILABLE"))
    cp=[]; 
    if ctx.get("pans_cargo_description"):cp.append(str(ctx["pans_cargo_description"]))
    if ctx.get("pans_cargo_tonnage") is not None:cp.append(f"{ctx['pans_cargo_tonnage']:g} MT")
    if ctx.get("pans_hazardous"):cp.append("HAZARDOUS="+("YES" if str(ctx["pans_hazardous"]).upper() in ("Y","YES","TRUE","1") else "NO"))
    lines.append("PANS     | CARGO             : "+(" | ".join(cp) if cp else "UNAVAILABLE"))
    lines.append("NSC      | REGION            : "+str(ctx.get("nsc_region") or "UNAVAILABLE"));lines.append("NSC      | VALIDITY          : "+((str(ctx.get("nsc_begin_date") or "UNKNOWN")+" TO "+str(ctx.get("nsc_end_date") or "UNKNOWN")) if (ctx.get("nsc_begin_date") or ctx.get("nsc_end_date")) else "UNAVAILABLE"))
    lines.append("SOURCE   | FEED              : IMAC VATMSW");r.vessel_remarks="\n".join(lines);r.foreign_track_number=r.mmsi if valid_mmsi(r.mmsi) else effective
    return effective

def logical(r,receipt,effective):
    return {"ais.lenToBow":num(r.len_to_bow,True),"ais.lenToStern":num(r.len_to_stern,True),"ais.navStatus":NAV.get(int(r.nav_status),str(r.nav_status)) if r.nav_status not in (None,"") else None,
    "ais.typeAndCargo":type_text(r.vessel_type) if r.vessel_type not in (None,"") else None,"ais.widthToPort":num(r.width_to_port),"ais.widthToStarboard":num(r.width_to_starboard),"app.message.id":r.app_message_id,
    "cat.annotation":r.raw_attributes.get("cat_annotation"),"cat.category":"Surface","cat.identity":r.cat_identity,"foreign.track.number":r.foreign_track_number,"id.callsign":clean(r.callsign),
    "id.imo":num(r.imo,True),"id.mmsi":num(r.mmsi,True),"id.mmsi.destination":r.raw_attributes.get("vigilance_score"),"kinematic.course.true":math.radians(float(r.cog)) if r.cog is not None else None,
    "kinematic.flag.3d":r.altitude is not None,"kinematic.heading.true":math.radians(float(r.true_heading)) if r.true_heading is not None else None,"kinematic.pos.lla.alt":num(r.altitude),
    "kinematic.pos.lla.lat":math.radians(float(r.latitude)) if r.latitude is not None else None,"kinematic.pos.lla.lon":math.radians(float(r.longitude)) if r.longitude is not None else None,
    "kinematic.speed":float(r.sog)*0.514444 if r.sog is not None else None,"sys.source.id":223,"sys.track.number":num(r.mmsi,True),"timestamp.receipt":receipt,"timestamp.source":iso_ms(r.timestamp),
    "track.flag.active":True,"track.quality":15,"vessel.beam":num(r.width),"vessel.description":type_text(r.vessel_type) if r.vessel_type not in (None,"") else None,
    "vessel.draft":num(r.draught),"vessel.grosstonnage":num(r.gross_tonnage),"vessel.length":num(r.length),"vessel.name":clean(r.vessel_name),"vessel.remarks":clean(r.vessel_remarks),
    "voyage.arrival":clean(r.arrival),"voyage.departure":clean(r.departure),"voyage.destination":clean(r.destination),"voyage.eta":r.eta,"voyage.etd":r.etd,"voyage.origin":clean(r.origin)}

def xml(logical):
    def val(kind,v):
        if v is None or (isinstance(v,str) and not v.strip()):return None
        if kind=="bv":return "true" if bool(v) else "false"
        if kind=="tv":return str(iso_ms(v)) if iso_ms(v) is not None else None
        if kind=="iv":
            try:return str(int(float(v)))
            except:return None
        if kind=="qv":
            try:return str(v) if math.isfinite(float(v)) else None
            except:return None
        return escape(clean(v))
    lines=['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',f'<ns2:XTracks xmlns="{NSC}" xmlns:ns2="{NSX}">','    <ns2:XTrack verbose="true">']
    for f in FIELDS:
        k,u=SPECS[f];v=val(k,logical.get(f))
        if v is not None:lines += ['        <ns2:A>',f'            <id>{f}</id>',f'            <{k}{(" u="+chr(34)+u+chr(34)) if u else ""}>{v}</{k}>','        </ns2:A>']
    lines += ['    </ns2:XTrack>','</ns2:XTracks>'];text="\n".join(lines)
    import xml.etree.ElementTree as ET
    root=ET.fromstring(text);xt=[n for n in root.iter() if n.tag.endswith("XTrack")]
    if len(xt)!=1:raise ValueError("XTrack count != 1")
    seen=set()
    for a in xt[0]:
        ids=[c for c in a if c.tag.endswith("id")]
        if len(ids)!=1 or ids[0].text in seen:raise ValueError("invalid/duplicate XML field")
        seen.add(ids[0].text)
    return text

def process_records(records,msg,ref,conn):
    made=0
    for i,r in enumerate(records,1):
        try:
            h=state(conn,r.mmsi)
            ctx=ref.resolve(r.mmsi,r.imo,clean(r.callsign),clean(r.vessel_name))
            eff=enrich(r,ctx,conn,h)
            l=logical(r,int(datetime.now(timezone.utc).timestamp()*1000),eff)
            if eff and valid_mmsi(eff):
                ts=l["timestamp.source"];l["track.flag.active"]=(ts is None or int(datetime.now(timezone.utc).timestamp()*1000)-int(ts)<ACTIVE_THRESHOLD_SECONDS*1000)
                save_state(conn,eff,{k:l[k] for k in l if k in ("ais.lenToBow","ais.lenToStern","ais.navStatus","ais.typeAndCargo","ais.widthToPort","ais.widthToStarboard","cat.annotation","cat.category","cat.identity","foreign.track.number","id.callsign","id.imo","id.mmsi","id.mmsi.destination","vessel.beam","vessel.description","vessel.draft","vessel.grosstonnage","vessel.length","vessel.name","voyage.arrival","voyage.departure","voyage.destination","voyage.eta","voyage.etd","voyage.origin")}|{"_track_lat":r.latitude,"_track_lon":r.longitude,"_track_ts":r.timestamp},r.timestamp)
            x=xml(l);name=re.sub(r"[^A-Za-z0-9_.-]+","_",f"VATMS_WEST_{msg}_{i}_{l.get('id.mmsi') or 'unknown'}");p=OUT/(name+"_"+hashlib.sha256(x.encode()).hexdigest()[:16]+".xml")
            tmp=p.with_suffix(".tmp");tmp.write_text(x,encoding="utf-8");tmp.replace(p)
            if FORWARDING_ENABLED:
                if FORWARDING_TYPE=="FOLDER":q=Path(FORWARDING_FOLDER);q.mkdir(parents=True,exist_ok=True);(q/p.name).write_text(x,encoding="utf-8")
                elif FORWARDING_TYPE=="TCP":
                    with socket.create_connection((FORWARDING_HOST,FORWARDING_PORT),5) as s:s.sendall(x.encode()+b"\n")
            made+=1
        except Exception:log.exception("Record %d rejected",i)
    conn.commit();return made

def process_file(p,done,ref,conn):
    try:
        if time.time()-p.stat().st_mtime<FILE_STABILITY_SECONDS:return
        h=hashlib.sha256(p.read_bytes()).hexdigest()
        if h in done:return
        lines=p.read_text(encoding="utf-8",errors="replace").splitlines();records=parse_vatms_west(lines);n=process_records(records,p.stem,ref,conn);done.add(h);DONE_FILE.write_text(json.dumps(sorted(done)),encoding="utf-8");log.info("Processed %s: records=%d xml=%d",p.name,len(records),n)
    except Exception:log.exception("File failed %s",p)

def run():
    done=set(json.loads(DONE_FILE.read_text()) if DONE_FILE.exists() else [])
    ref=Ref();conn=psycopg.connect(host=PG_HOST,port=PG_PORT,dbname=PG_DATABASE,user=PG_USER,password=PG_PASSWORD,row_factory=dict_row)
    try:
        if INPUT_TYPE=="FOLDER":
            folder=ROOT/INPUT_FOLDER;folder.mkdir(parents=True,exist_ok=True)
            while True:
                for p in sorted(folder.glob("*.csv")):process_file(p,done,ref,conn)
                if RUN_ONCE: break
                time.sleep(POLL_SECONDS)
        else:
            with socket.socket() as s:
                s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind((TCP_HOST,TCP_PORT));s.listen(10);log.info("Listening %s:%s",TCP_HOST,TCP_PORT)
                while True:
                    c,_=s.accept()
                    with c:
                        data=c.recv(65536)
                        if data:process_records(parse_lines(data.decode("utf-8","replace").splitlines()),"tcp_"+str(int(time.time()*1000)),ref,conn)
    finally:ref.c.close();conn.close()
if __name__=="__main__":run()
