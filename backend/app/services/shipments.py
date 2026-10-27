"""Reading and normalising shipment documents from Smart Tracking / Platform."""
import asyncio
from typing import Any, Optional

from .. import config, db, status_map
from ..utils import (awb_key, awb_variants, clean_str, first_value, fmt,
                     get_path, norm_status, to_dt)


def _roots(paths: list[str]) -> set[str]:
    return {p.split(".")[0] for p in paths if p}


def projection(src: config.SourceConfig, with_tracking: bool = True) -> dict:
    roots = _roots(
        [src.awb_field] + src.courier_fields + src.status_fields + src.status_code_fields
        + src.status_date_fields + src.pickup_date_fields + src.last_track_fields
        + src.created_fields + ([src.order_date_field] if src.order_date_field else [])
    )
    proj = {r: 1 for r in roots}
    if src.tracking_field:
        if with_tracking:
            proj[src.tracking_field] = 1
        else:
            # light mode: only the date keys of each event (for last-track fallback)
            for k in set(src.track_date_keys + src.track_sync_keys):
                proj[f"{src.tracking_field}.{k}"] = 1
    # a parent key and a child key can't both be projected
    for r in list(proj):
        if "." in r and r.split(".")[0] in proj:
            proj.pop(r)
    return proj


def _events(doc: dict, src: config.SourceConfig) -> list[dict]:
    raw = get_path(doc, src.tracking_field) if src.tracking_field else None
    if not isinstance(raw, list):
        return []
    out = []
    for e in raw:
        if not isinstance(e, dict):
            continue
        dt = to_dt(first_value(e, src.track_date_keys))
        sync = to_dt(first_value(e, src.track_sync_keys))
        out.append({
            "_dt": dt, "_sync": sync,
            "datetime": fmt(dt),
            "status": clean_str(first_value(e, src.track_status_keys)),
            "code": clean_str(first_value(e, src.track_code_keys)),
            "location": clean_str(first_value(e, src.track_location_keys)),
            "remark": clean_str(first_value(e, src.track_remark_keys)),
        })
    out.sort(key=lambda x: (x["_dt"] is not None, x["_dt"].timestamp() if x["_dt"] else 0), reverse=True)
    return out


def normalize(doc: Optional[dict], src: config.SourceConfig, include_tracking: bool = True) -> dict:
    if not doc:
        return {"found": False}
    events = _events(doc, src)
    latest_event = next((e for e in events if e["_dt"]), None)

    status_dt = to_dt(first_value(doc, src.status_date_fields)) or (latest_event or {}).get("_dt")
    last_track = to_dt(first_value(doc, src.last_track_fields))
    if not last_track and events:
        cands = [e["_sync"] or e["_dt"] for e in events if (e["_sync"] or e["_dt"])]
        last_track = max(cands) if cands else None

    raw_status = first_value(doc, src.status_fields)
    if raw_status in (None, "") and latest_event:
        # No status field: use the latest tracking event's dispatch code (e.g. 2 -> In-transit),
        # or its text if the code isn't in the mapping file.
        ev_code = status_map.code_key(latest_event.get("code"))
        raw_status = ev_code if ev_code in status_map.CODE_TO_LABEL else latest_event.get("status")
    code = status_map.code_key(raw_status)
    status = status_map.label(raw_status) or (latest_event or {}).get("status")
    rec = {
        "found": True,
        "awb": clean_str(get_path(doc, src.awb_field)),
        "courier": clean_str(first_value(doc, src.courier_fields)),
        "current_status": status,
        "status_code": code if code is not None else clean_str(first_value(doc, src.status_code_fields)),
        "closed": status_map.is_closed(raw_status),
        "status_unmapped": bool(status_map.CODE_TO_LABEL) and raw_status not in (None, "") and code is None
                           and status_map._norm(raw_status) not in status_map.LABEL_TO_CODES,
        "status_datetime": fmt(status_dt),
        "pickup_date": fmt(to_dt(first_value(doc, src.pickup_date_fields))),
        "last_track_datetime": fmt(last_track),
        "created_at": fmt(to_dt(first_value(doc, src.created_fields))),
        "order_date": fmt(to_dt(get_path(doc, src.order_date_field))) if src.order_date_field else None,
        "tracking_count": len(events),
    }
    if include_tracking:
        rec["tracking"] = [{k: v for k, v in e.items() if not k.startswith("_")} for e in events]
    return rec


def _recency(doc: dict, src: config.SourceConfig) -> float:
    for paths in (src.last_track_fields, src.status_date_fields, src.created_fields):
        dt = to_dt(first_value(doc, paths))
        if dt:
            return dt.timestamp()
    oid = doc.get("_id")
    return oid.generation_time.timestamp() if hasattr(oid, "generation_time") else 0.0


async def fetch_by_awbs(src: config.SourceConfig, awbs: list[str],
                        with_tracking: bool = True) -> dict[str, dict]:
    """Returns {AWB_KEY: normalized record}. Queries in batches with $in on the
    (indexed) AWB field. If several docs share an AWB, the most recent wins and
    the count is reported."""
    if not src.enabled or not awbs:
        return {}
    coll = db.get_collection(src)
    proj = projection(src, with_tracking)
    size = max(1, config.QUERY_BATCH_SIZE)
    batches = [awbs[i:i + size] for i in range(0, len(awbs), size)]

    async def run(batch: list[str]) -> list[dict]:
        cur = coll.find({src.awb_field: {"$in": awb_variants(batch)}}, proj,
                        max_time_ms=config.MONGO_MAX_TIME_MS)
        return await cur.to_list(length=None)

    grouped: dict[str, list[dict]] = {}
    for docs in await asyncio.gather(*(run(b) for b in batches)):
        for d in docs:
            grouped.setdefault(awb_key(get_path(d, src.awb_field)), []).append(d)

    out = {}
    for k, docs in grouped.items():
        docs.sort(key=lambda d: _recency(d, src), reverse=True)
        rec = normalize(docs[0], src, include_tracking=with_tracking)
        rec["records_found"] = len(docs)
        out[k] = rec
    return out


def sync_state(st: dict, pf: dict) -> str:
    a, b = st.get("found"), pf.get("found")
    if not a and not b:
        return "not_found"
    if a and not b:
        return "only_smart_tracking"
    if b and not a:
        return "only_platform"
    return "match" if norm_status(st.get("current_status")) == norm_status(pf.get("current_status")) else "mismatch"


async def check_awbs(awbs: list[str]) -> list[dict[str, Any]]:
    st_map, pf_map = await asyncio.gather(
        fetch_by_awbs(config.SMART_TRACKING, awbs),
        fetch_by_awbs(config.PLATFORM, awbs),
    )
    rows = []
    for a in awbs:
        k = awb_key(a)
        st = st_map.get(k, {"found": False})
        pf = pf_map.get(k, {"found": False})
        # Closed = Smart Tracking's current status is closed (Platform's if not in Smart Tracking).
        closed = bool(st.get("closed")) if st.get("found") else bool(pf.get("closed"))
        rows.append({"awb": a, "smart_tracking": st, "platform": pf, "sync": sync_state(st, pf), "closed": closed})
    return rows
