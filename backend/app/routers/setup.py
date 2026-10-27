"""Browser-based Setup: connect, pick database/collection, preview, save."""
import asyncio
import re
from dataclasses import replace
from datetime import datetime
from typing import Any, Optional

from bson import ObjectId
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from pymongo import MongoClient

from .. import config, db, settings_store
from .. import status_map
from ..mongo_errors import explain
from ..services.shipments import normalize
from ..utils import DISPLAY_TZ, awb_variants, to_dt

router = APIRouter(prefix="/api/setup", tags=["Setup"])

def _rx(p: str) -> re.Pattern:
    return re.compile(p, re.I)


# Every column the dashboard shows, and how to find its field in a shipment document.
#   key, label, .env suffix, SourceConfig attribute, single/list, where (doc|array|event), name hint
FIELD_SPECS = [
    ("awb", "AWB number", "AWB_FIELD", "awb_field", "single", "doc",
     _rx(r"awb|airway|air_way|waybill|way_bill|docket|tracking_?(no|num|id)|lr_?no|cn_?no")),
    ("courier", "Courier name", "COURIER_FIELDS", "courier_fields", "list", "doc",
     _rx(r"courier|carrier|vendor|partner|logistic")),
    ("status", "Current status", "STATUS_FIELDS", "status_fields", "list", "doc", _rx(r"^(.*_)?status$|state")),
    ("status_date", "Status datetime", "STATUS_DATE_FIELDS", "status_date_fields", "list", "doc",
     _rx(r"status.*(date|time)|(date|time).*status")),
    ("pickup_date", "Pickup date", "PICKUP_DATE_FIELDS", "pickup_date_fields", "list", "doc", _rx(r"pick")),
    ("order_date", "Order date", "ORDER_DATE_FIELD", "order_date_field", "single", "doc",
     _rx(r"order.*date|order.*(at|on|time)|booking.*date|created")),
    ("last_track", "Last track datetime", "LAST_TRACK_FIELDS", "last_track_fields", "list", "doc",
     _rx(r"last.*(track|sync|update)|track.*(date|time|_at)|updated_(at|date)|modified")),
    ("tracking", "Tracking list (courier tracking block)", "TRACKING_FIELD", "tracking_field", "single", "array",
     _rx(r"track|history|scan|event|journey")),
    ("track_status", "Tracking event: status", "TRACK_STATUS_KEYS", "track_status_keys", "list", "event",
     _rx(r"status|activity|desc")),
    ("track_date", "Tracking event: date/time", "TRACK_DATE_KEYS", "track_date_keys", "list", "event",
     _rx(r"date|time")),
    ("track_location", "Tracking event: location", "TRACK_LOCATION_KEYS", "track_location_keys", "list", "event",
     _rx(r"loc|city|hub|place|area")),
]
SPEC_BY_KEY = {sp[0]: sp for sp in FIELD_SPECS}


def _saved_fields(src: config.SourceConfig) -> dict:
    out = {}
    for key, _l, _e, attr, kind, _w, _h in FIELD_SPECS:
        v = getattr(src, attr)
        out[key] = (v[0] if v else "") if kind == "list" else (v or "")
    return out


def _guard(pin: Optional[str]) -> None:
    """Before first setup anyone on the machine may configure; afterwards the PIN (if set) is needed."""
    if config.CONFIGURED and config.SETUP_PIN_HASH and not settings_store.check_pin(pin or ""):
        raise HTTPException(401, "Wrong settings PIN.")


def _uri(body_uri: Optional[str], use_saved: Optional[str]) -> str:
    if use_saved:
        src = config.SOURCES.get(use_saved)
        if not src or not src.mongo_uri:
            raise HTTPException(400, "No saved connection to reuse yet.")
        return src.mongo_uri
    uri = clean_pasted_uri(body_uri)
    if not uri:
        raise HTTPException(400, "Please enter the database connection details.")
    return uri


def clean_pasted_uri(raw: Optional[str]) -> str:
    """Accept a line copied from another app's .env, e.g.  MONGO_URI="mongodb://..." """
    s = (raw or "").strip()
    m = re.match(r"^(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=\s*(.*)$", s)
    if m and not s.lower().startswith("mongodb"):
        s = m.group(1).strip()
    return s.strip().strip("'\"").strip()


def _client(uri: str) -> MongoClient:
    return MongoClient(uri, serverSelectionTimeoutMS=8000, connectTimeoutMS=8000, appname="awb-dashboard-setup")


async def _run(fn):
    try:
        return await asyncio.to_thread(fn)
    except HTTPException:
        raise
    except Exception as ex:  # noqa: BLE001
        raw = str(ex).split(", Timeout:")[0]
        return {"ok": False, "message": explain(raw), "detail": raw[:400]}


class ConnReq(BaseModel):
    uri: Optional[str] = None
    use_saved: Optional[str] = None
    db: Optional[str] = None
    collection: Optional[str] = None
    side: Optional[str] = None                      # smart_tracking | platform
    sample_awb: Optional[str] = None                # shipment to show as the sample
    fields: dict[str, str] = {}                     # manual choices, key -> path ("" = automatic)


@router.get("/status")
async def status():
    def side(s):
        return {"label": s.label, "uri_masked": settings_store.mask_uri(s.mongo_uri), "has_uri": bool(s.mongo_uri),
                "db": s.db_name, "collection": s.collection, "fields": _saved_fields(s)}
    pf_same = (not config.env("PF_MONGO_URI")) or config.PLATFORM.mongo_uri == config.SMART_TRACKING.mongo_uri
    return {"configured": config.CONFIGURED, "pin_required": bool(config.CONFIGURED and config.SETUP_PIN_HASH),
            "smart_tracking": side(config.SMART_TRACKING), "platform": side(config.PLATFORM),
            "platform_same_server": pf_same, "sample_awb": config.SETUP_SAMPLE_AWB,
            "readonly_env": config.is_vercel(),
            "field_specs": [{"key": k, "label": l, "where": w} for k, l, _e, _a, _k, w, _h in FIELD_SPECS]}


@router.post("/verify-pin")
async def verify_pin(x_setup_pin: Optional[str] = Header(None)):
    _guard(x_setup_pin)
    return {"ok": True}


@router.post("/test")
async def test(req: ConnReq, x_setup_pin: Optional[str] = Header(None)):
    _guard(x_setup_pin)
    uri = _uri(req.uri, req.use_saved)

    def work():
        c = _client(uri)
        try:
            c.admin.command("ping")
            dbs: list = []
            try:
                dbs = [d for d in c.list_database_names() if d not in ("admin", "local", "config")]
            except Exception:  # noqa: BLE001  (user may lack listDatabases permission)
                try:
                    dbs = [c.get_default_database().name]
                except Exception:  # noqa: BLE001
                    dbs = []
            return {"ok": True, "message": "Connected successfully.", "databases": sorted(dbs)}
        finally:
            c.close()
    return await _run(work)


@router.post("/collections")
async def collections(req: ConnReq, x_setup_pin: Optional[str] = Header(None)):
    _guard(x_setup_pin)
    uri = _uri(req.uri, req.use_saved)
    if not req.db:
        raise HTTPException(400, "Choose a database first.")

    def work():
        c = _client(uri)
        try:
            d = c[req.db]
            names = [n for n in d.list_collection_names() if not n.startswith("system.")][:300]
            out = []
            for n in names:
                try:
                    cnt = d[n].estimated_document_count(maxTimeMS=3000)
                except Exception:  # noqa: BLE001
                    cnt = None
                out.append({"name": n, "count": cnt})
            out.sort(key=lambda x: (x["count"] or 0), reverse=True)
            return {"ok": True, "collections": out}
        finally:
            c.close()
    return await _run(work)


def _flatten(doc: Any, prefix: str = "", depth: int = 0, out: Optional[dict] = None) -> dict:
    out = {} if out is None else out
    if not isinstance(doc, dict) or depth > 2:
        return out
    for k, v in doc.items():
        if k == "_id":
            continue
        p = f"{prefix}{k}"
        if isinstance(v, dict):
            _flatten(v, p + ".", depth + 1, out)
        elif isinstance(v, list):
            out[p] = f"[list of {len(v)}]"
        else:
            if isinstance(v, datetime):
                s = fmt_ist(v)
            elif isinstance(v, ObjectId):
                s = str(v)
            else:
                s = str(v)
            out[p] = s[:60]
    return out


def fmt_ist(v: datetime) -> str:
    """Stored dates come back from MongoDB in UTC; show them in IST like the dashboard."""
    return to_dt(v).astimezone(DISPLAY_TZ).strftime("%d-%m-%Y %H:%M")


def _arrays(doc: Any, prefix: str = "", depth: int = 0, out: Optional[dict] = None) -> dict:
    """Paths of lists whose items are sub-documents (candidates for the tracking list)."""
    out = {} if out is None else out
    if not isinstance(doc, dict) or depth > 2:
        return out
    for k, v in doc.items():
        p = f"{prefix}{k}"
        if isinstance(v, list) and v and isinstance(v[0], dict):
            out[p] = v
        elif isinstance(v, dict):
            _arrays(v, p + ".", depth + 1, out)
    return out


def _auto(fields: dict, hint: re.Pattern, preferred: list) -> str:
    for p in preferred:
        if p in fields and not str(fields[p]).startswith("[list") and fields[p] not in ("", "None"):
            return p
    for p, v in fields.items():
        if hint.search(p.split(".")[-1]) and not str(v).startswith("[list") and v not in ("", "None"):
            return p
    return ""


def _detect(doc: dict, base: config.SourceConfig, manual: dict) -> dict:
    defaults = config._COMMON_DEFAULTS
    fields = _flatten(doc)
    arrays = _arrays(doc)
    chosen: dict = {}

    def preferred(attr: str, env_suffix: str) -> list:
        saved = getattr(base, attr)
        saved = saved if isinstance(saved, list) else [saved]
        return [x for x in saved + defaults[env_suffix].split(",") if x]

    # document-level columns
    for key, _l, env_suffix, attr, _k, where, hint in FIELD_SPECS:
        if where == "doc":
            chosen[key] = manual.get(key) or _auto(fields, hint, preferred(attr, env_suffix))
    # tracking list
    tr_pref = [p for p in preferred("tracking_field", "TRACKING_FIELD") if p in arrays]
    tr_hint = [p for p in arrays if SPEC_BY_KEY["tracking"][6].search(p.split(".")[-1])]
    chosen["tracking"] = manual.get("tracking") or (tr_pref + tr_hint + list(arrays) + [""])[0]
    # keys inside one tracking event
    events = arrays.get(chosen["tracking"]) or []
    event_fields = _flatten(events[-1]) if events else {}
    for key, _l, env_suffix, attr, _k, where, hint in FIELD_SPECS:
        if where == "event":
            chosen[key] = manual.get(key) or _auto(event_fields, hint, preferred(attr, env_suffix))
    return {"chosen": chosen, "fields": fields, "arrays": arrays, "event_fields": event_fields}


def _is_dispatch_status(v: Any) -> bool:
    """True if the value is a code or name from Dispatch-status-Mapping.xlsx."""
    if v in (None, "") or not status_map.CODE_TO_LABEL:
        return False
    k = status_map.code_key(v)
    if k is not None:
        return k in status_map.CODE_TO_LABEL
    return status_map._norm(v) in status_map.LABEL_TO_CODES


def _status_candidates(fields: dict, latest_code: Optional[str]) -> list:
    """Document fields whose value is a real dispatch status, best first."""
    out = []
    for path, v in fields.items():
        if str(v).startswith("[list") or not _is_dispatch_status(v):
            continue
        last = path.split(".")[-1].lower()
        score = 0
        score += 4 if "dispatch" in path.lower() else 0
        score += 2 if "status" in last else 0
        score += 3 if latest_code is not None and status_map.code_key(v) == latest_code else 0
        score -= 3 if any(x in last for x in ("pay", "cod", "rto_", "ndr", "weight", "qty", "count", "type")) else 0
        out.append((score, path, v))
    out.sort(key=lambda x: -x[0])
    return [{"path": p, "sample": v, "label": status_map.label(v)} for sc, p, v in out if sc > 0]


def _apply(base: config.SourceConfig, chosen: dict) -> config.SourceConfig:
    upd = {}
    for key, _l, _e, attr, kind, _w, _h in FIELD_SPECS:
        v = chosen.get(key)
        if not v:
            continue
        if kind == "single":
            upd[attr] = v
        elif key == "status":
            upd[attr] = [v]          # exactly the chosen field - no fallbacks that could read the wrong value
        else:
            upd[attr] = [v] + [x for x in getattr(base, attr) if x != v]
    return replace(base, **upd)


@router.post("/inspect")
async def inspect(req: ConnReq, x_setup_pin: Optional[str] = Header(None)):
    _guard(x_setup_pin)
    uri = _uri(req.uri, req.use_saved)
    if not req.db or not req.collection:
        raise HTTPException(400, "Choose a database and a collection first.")
    base = config.SOURCES.get(req.side or "", config.SMART_TRACKING)
    manual = {k: v for k, v in (req.fields or {}).items() if k in SPEC_BY_KEY and v}

    sample = (req.sample_awb or "").strip()

    def work():
        c = _client(uri)
        coll = c[req.db][req.collection]
        doc, sample_note, sample_field = None, None, ""
        try:
            if sample:
                # Look the sample AWB up in the chosen AWB field (indexed), then the usual names.
                tried = []
                for fld in [manual.get("awb"), base.awb_field, "airwaybilno"]:
                    if not fld or fld in tried:
                        continue
                    tried.append(fld)
                    doc = coll.find_one({fld: {"$in": awb_variants([sample])}}, sort=[("_id", -1)], max_time_ms=10000)
                    if doc:
                        sample_field = fld
                        break
                if not doc:
                    sample_note = (f"AWB {sample} was not found in this collection (looked in: {', '.join(tried)}). "
                                   "Showing the newest shipment instead - check the AWB number, or the database and collection.")
            if not doc:
                doc = coll.find_one({}, sort=[("_id", -1)], max_time_ms=10000)
        finally:
            c.close()
        if not doc:
            return {"ok": False, "message": "This collection is empty. Please choose the collection that holds shipments."}
        if sample_field and "awb" not in manual:
            manual["awb"] = sample_field
        d = _detect(doc, base, manual)
        chosen = d["chosen"]
        preview = normalize(doc, _apply(base, chosen), include_tracking=True)

        # Is the Current status field really a dispatch status from the mapping file?
        latest_code = status_map.code_key(((preview.get("tracking") or [{}])[0]).get("code"))
        if chosen.get("status") == status_map.LATEST_EVENT:
            status_value = latest_code
        else:
            status_value = d["fields"].get(chosen.get("status") or "")
        status_ok = _is_dispatch_status(status_value)
        candidates = [] if status_ok else _status_candidates(d["fields"], latest_code)
        status_note = None
        if not status_ok and not candidates and latest_code in status_map.CODE_TO_LABEL:
            # No field in the record holds it, but the tracking events do.
            candidates = [{"path": status_map.LATEST_EVENT, "sample": latest_code,
                           "label": status_map.label(latest_code), "event": True}]
        if not status_ok and candidates and "status" not in manual:
            # the automatic pick was wrong: switch to the best real dispatch-status field
            chosen["status"] = candidates[0]["path"]
            preview = normalize(doc, _apply(base, chosen), include_tracking=True)
            status_ok, candidates = True, []
        elif not status_ok:
            shown = status_value if status_value not in (None, "") else "nothing"
            status_note = (f"The Current status field ({chosen.get('status') or 'none'}) holds \"{shown}\", which is not "
                           "one of the dispatch statuses in Dispatch-status-Mapping.xlsx. Choose the field that holds "
                           "the dispatch status code.")
        preview["awb"] = d["fields"].get(chosen["awb"]) if chosen["awb"] else None
        preview["tracking"] = (preview.get("tracking") or [])[:3]
        warnings = [w for w in (sample_note, status_note) if w]
        if not chosen["awb"]:
            warnings.append("Couldn't find the AWB number field automatically. Please pick it below.")
        if not preview.get("current_status"):
            warnings.append("Couldn't find the current status automatically. Please pick it below.")
        if not chosen["tracking"]:
            warnings.append("No tracking list found in this shipment - the tracking block will be empty.")
        return {
            "ok": True, "chosen": chosen, "preview": preview, "warnings": warnings,
            "sample_awb": sample if sample_field else None,
            "status_ok": status_ok, "status_suggestions": candidates[:3],
            "fields": [{"path": p, "sample": v} for p, v in d["fields"].items() if not str(v).startswith("[list")],
            "arrays": [{"path": p, "sample": f"list of {len(v)} events"} for p, v in d["arrays"].items()],
            "event_fields": [{"path": p, "sample": v} for p, v in d["event_fields"].items()
                             if not str(v).startswith("[list")],
        }
    return await _run(work)


class Side(BaseModel):
    uri: Optional[str] = None
    use_saved: Optional[str] = None
    db: str
    collection: str
    fields: dict[str, str] = {}


class SaveReq(BaseModel):
    smart_tracking: Side
    platform: Side
    platform_same_server: bool = True
    new_pin: Optional[str] = None
    sample_awb: Optional[str] = None


def _merge(first: Optional[str], defaults: list) -> str:
    vals = ([first] if first else []) + [d for d in defaults if d != first]
    return ",".join(vals)


@router.post("/save")
async def save(req: SaveReq, x_setup_pin: Optional[str] = Header(None)):
    _guard(x_setup_pin)
    st_uri = _uri(req.smart_tracking.uri, req.smart_tracking.use_saved)
    pf_uri = "" if req.platform_same_server else _uri(req.platform.uri, req.platform.use_saved)
    defaults = config._COMMON_DEFAULTS
    values = {"ST_MONGO_URI": st_uri, "PF_MONGO_URI": pf_uri}
    for pre, side in (("ST", req.smart_tracking), ("PF", req.platform)):
        f = side.fields or {}
        if not (side.db and side.collection and f.get("awb")):
            raise HTTPException(400, "Please choose database, collection and AWB field for both systems.")
        values.update({f"{pre}_DB_NAME": side.db, f"{pre}_COLLECTION": side.collection})
        for key, _l, env_suffix, _a, kind, _w, _h in FIELD_SPECS:
            chosen = (f.get(key) or "").strip()
            if kind == "single":
                values[f"{pre}_{env_suffix}"] = chosen or defaults[env_suffix]
            elif key == "status":
                values[f"{pre}_{env_suffix}"] = chosen or status_map.LATEST_EVENT
            else:
                values[f"{pre}_{env_suffix}"] = _merge(chosen, defaults[env_suffix].split(","))
    if req.sample_awb is not None:
        values["SETUP_SAMPLE_AWB"] = req.sample_awb.strip()
    if req.new_pin:
        if len(req.new_pin) < 4:
            raise HTTPException(400, "The PIN must be at least 4 characters.")
        values["SETUP_PIN_HASH"] = settings_store.hash_pin(req.new_pin)
    try:
        settings_store.update_env(values)
    except OSError as ex:
        raise HTTPException(400, str(ex)) from ex
    config.reload()
    db.close_all()
    return {"ok": True, "configured": config.CONFIGURED}
