"""Position-based AIS anomaly detection using Haversine distance and source time."""
from __future__ import annotations
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
import yaml

EARTH_RADIUS_NM = 3440.065

def _number(value: Any) -> Optional[float]:
    try:
        if value in (None, ""): return None
        return float(value)
    except (TypeError, ValueError): return None

def parse_timestamp(value: Any) -> Optional[datetime]:
    if value in (None, ""): return None
    if isinstance(value, datetime): dt = value
    else:
        text = str(value).strip()
        try:
            numeric = float(text)
            if numeric > 10_000_000_000: numeric /= 1000.0
            return datetime.fromtimestamp(numeric, tz=timezone.utc)
        except ValueError:
            try: dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError: return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)

def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlambda = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlambda/2)**2
    return EARTH_RADIUS_NM * 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0-a)))

class PositionalSpoofingDetector:
    DEFAULT_MAX_SPEED_KNOTS = 50.0
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = Path(config_path) if config_path else Path(__file__).resolve().parents[2] / "config" / "spoofing.yaml"
        self.config = self._load_config()
    def _load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists(): return {"enabled": True, "max_speed_knots": {"default": self.DEFAULT_MAX_SPEED_KNOTS}}
        try:
            with self.config_path.open("r", encoding="utf-8") as fh: data = yaml.safe_load(fh) or {}
            return data.get("positional_spoofing", data) or {}
        except Exception: return {"enabled": True, "max_speed_knots": {"default": self.DEFAULT_MAX_SPEED_KNOTS}}
    def _threshold(self, vessel_type: Any) -> float:
        limits = self.config.get("max_speed_knots") or {}
        text = str(vessel_type or "").lower()
        for key in ("high_speed", "passenger", "tanker", "cargo", "commercial", "fishing"):
            if key in text and limits.get(key) is not None: return float(limits[key])
        try: return float(limits.get("default", self.DEFAULT_MAX_SPEED_KNOTS))
        except (TypeError, ValueError): return self.DEFAULT_MAX_SPEED_KNOTS
    def check(self, previous: Optional[Dict[str, Any]], current: Any) -> Optional[Dict[str, Any]]:
        if not self.config.get("enabled", True) or not previous: return None
        cur_lat, cur_lon = _number(getattr(current, "latitude", None)), _number(getattr(current, "longitude", None))
        cur_ts = parse_timestamp(getattr(current, "timestamp", None))
        prev_lat = _number(previous.get("last_position_latitude", previous.get("latitude")))
        prev_lon = _number(previous.get("last_position_longitude", previous.get("longitude")))
        prev_ts = parse_timestamp(previous.get("last_position_timestamp"))
        if None in (cur_lat, cur_lon, cur_ts, prev_lat, prev_lon, prev_ts): return None
        if not (-90 <= cur_lat <= 90 and -180 <= cur_lon <= 180 and -90 <= prev_lat <= 90 and -180 <= prev_lon <= 180): return None
        elapsed = (cur_ts-prev_ts).total_seconds()
        if elapsed <= 0: return None
        distance_nm = haversine_nm(prev_lat, prev_lon, cur_lat, cur_lon)
        speed_knots = distance_nm/(elapsed/3600.0)
        threshold = self._threshold(getattr(current, "vessel_type", None))
        reported_sog = _number(getattr(current, "sog", None))
        if speed_knots <= threshold: return None
        return {"flagged": True, "reason": "POSITIONAL SPOOFING", "distance_nm": round(distance_nm,3),
                "elapsed_seconds": round(elapsed,3), "calculated_speed_knots": round(speed_knots,3),
                "reported_sog_knots": round(reported_sog,3) if reported_sog is not None else None,
                "threshold_knots": threshold, "previous_timestamp": prev_ts.isoformat(), "current_timestamp": cur_ts.isoformat()}
