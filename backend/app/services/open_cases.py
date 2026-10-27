"""Open-case aggregations. Every pipeline starts with a $match on the status
field (+ a created-date window) so production load stays bounded."""
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional
from zoneinfo import ZoneInfo

from .. import config, db, status_map
from ..utils import awb_key, clean_str, exact_ci_regex, get_path, norm_status
from .shipments import fetch_by_awbs, normalize, projection

log = logging.getLogger("open_cases")

AGING_BUCKETS = [  # (key, label, min_hours, max_hours)
    ("lt1d", "< 1 day", 0, 24),
    ("1to2d", "1–2 days", 24, 48),
    ("2to3d", "2–3 days", 48, 72),
    ("3to5d", "3–5 days", 72, 120),
    ("gt5d", "5+ days", 120, None),
    ("nodate", "No update date", None, None),
]

_kind_cache: dict[tuple, tuple[float, Optional[str], Any]] = {}
_filter_cache: dict[tuple, tuple[float, dict]] = {}


def other_source(src: config.SourceConfig) -> config.SourceConfig:
    return config.PLATFORM if src.key == config.SMART_TRACKING.key else config.SMART_TRACKING


async def _field_kind(src: config.SourceConfig, path: str) -> tuple[Optional[str], Any]:
    """Sample one document to learn how a date field is stored."""
    ck = (src.key, path)
    hit = _kind_cache.get(ck)
    if hit and time.time() - hit[0] < 3600:
        return hit[1], hit[2]
    doc = await db.get_collection(src).find_one({path: {"$exists": True, "$ne": None}}, {path: 1})
    v = get_path(doc, path) if doc else None
    kind = ("date" if isinstance(v, datetime) else "number" if isinstance(v, (int, float))
            else "string" if isinstance(v, str) else None)
    _kind_cache[ck] = (time.time(), kind, v)
    return kind, v


async def _date_condition(src: config.SourceConfig, start: Optional[datetime],
                          end: Optional[datetime]) -> Optional[tuple[str, dict]]:
    """Date window on the order date (status.order_date by default)."""
    path = src.order_date_field or (src.created_fields[0] if src.created_fields else "")
    if not path or not (start or end):
        return None
    kind, sample = await _field_kind(src, path)
    if kind is None and src.created_fields and path != src.created_fields[0]:
        # this collection has no order date at all - use the created date instead of hiding everything
        log.warning("%s has no %s; date range uses %s", src.key, path, src.created_fields[0])
        path = src.created_fields[0]
        kind, sample = await _field_kind(src, path)
    if kind is None:
        return None
    cond: dict[str, Any] = {}
    if kind == "date":
        if start: cond["$gte"] = start.astimezone(timezone.utc).replace(tzinfo=None)
        if end: cond["$lt"] = end.astimezone(timezone.utc).replace(tzinfo=None)
    elif kind == "number":
        mult = 1000 if sample and sample > 1e12 else 1
        if start: cond["$gte"] = int(start.timestamp() * mult)
        if end: cond["$lt"] = int(end.timestamp() * mult)
    elif kind == "string" and re.match(r"^\d{4}-\d{2}-\d{2}", sample or ""):
        if start: cond["$gte"] = start.astimezone(ZoneInfo(config.DATE_STRINGS_TZ)).strftime("%Y-%m-%d %H:%M:%S")
        if end: cond["$lt"] = end.astimezone(ZoneInfo(config.DATE_STRINGS_TZ)).strftime("%Y-%m-%d %H:%M:%S")
    else:
        # other text formats (e.g. 24-10-2026 12:47): convert inside MongoDB
        d = _date_expr([path])
        conds = [{"$ne": [d, None]}]
        if start: conds.append({"$gte": [d, start.astimezone(timezone.utc)]})
        if end: conds.append({"$lt": [d, end.astimezone(timezone.utc)]})
        return "$expr", {"$and": conds}
    return path, cond


def _status_condition() -> dict:
    """Skip closed AWBs: codes 5,13,14,15,16 stored as number or text, or their names."""
    return {"$nin": status_map.closed_db_values() + [None, ""]}


def _event_mode(src: config.SourceConfig) -> bool:
    return bool(src.status_fields) and src.status_fields[0] == status_map.LATEST_EVENT


def _latest_event_code_expr(src: config.SourceConfig) -> dict:
    """Code of the newest tracking event (by its date), as text."""
    date_key = src.track_date_keys[0] if src.track_date_keys else "status_date"
    code_key = src.track_code_keys[0] if src.track_code_keys else "parent_status_code"
    newest = {"$reduce": {"input": {"$ifNull": [f"${src.tracking_field}", []]}, "initialValue": None, "in": {
        "$cond": [{"$or": [{"$eq": ["$$value", None]},
                           {"$gte": [f"$$this.{date_key}", f"$$value.{date_key}"]}]}, "$$this", "$$value"]}}}
    return {"$toString": {"$getField": {"field": code_key, "input": newest}}}


def _status_value_expr(src: config.SourceConfig):
    return _latest_event_code_expr(src) if _event_mode(src) else f"${src.status_fields[0]}"


def _status_clauses(src: config.SourceConfig, wanted: list) -> list:
    if not _event_mode(src):
        path = src.status_fields[0]
        out = [{path: _status_condition()}]
        if wanted:
            out.append({path: {"$in": [v for x in wanted for v in status_map.db_values(x)]}})
        return out
    code = _latest_event_code_expr(src)
    closed = [str(c) for c in status_map.closed_codes()]
    conds = [{"$not": [{"$in": [code, closed + ["", "null"]]}]}, {"$ne": [code, None]}]
    if wanted:
        codes = [str(v) for x in wanted for v in status_map.db_values(x) if isinstance(v, str)]
        conds.append({"$in": [code, codes]})
    return [{"$expr": {"$and": conds}}]


@dataclass
class Filters:
    """Everything the user can filter on: the top bar plus every column header."""
    courier: list = field(default_factory=list)       # Courier column (multi)
    status: list = field(default_factory=list)        # Status column (multi)
    awb: str = ""                                     # AWB column (starts with)
    date_from: Optional[date] = None                  # created date (top bar)
    date_to: Optional[date] = None
    status_from: Optional[date] = None                # Status Datetime column
    status_to: Optional[date] = None
    pickup_from: Optional[date] = None                # Pickup Date column
    pickup_to: Optional[date] = None
    track_from: Optional[date] = None                 # Last Track column
    track_to: Optional[date] = None
    aging: list = field(default_factory=list)         # Since Update column (multi)
    other: list = field(default_factory=list)         # other system: match / mismatch / not_found


def _day_bounds(d_from: Optional[date], d_to: Optional[date]):
    tz = ZoneInfo(config.DISPLAY_TZ)
    start = datetime.combine(d_from, datetime.min.time(), tz) if d_from else None
    end = datetime.combine(d_to + timedelta(days=1), datetime.min.time(), tz) if d_to else None
    return start, end


def _range_expr(paths: list, d_from: Optional[date], d_to: Optional[date]) -> Optional[dict]:
    if not paths or not (d_from or d_to):
        return None
    start, end = _day_bounds(d_from, d_to)
    d = _date_expr(paths)
    conds = []
    if start:
        conds.append({"$gte": [d, start.astimezone(timezone.utc)]})
    if end:
        conds.append({"$lt": [d, end.astimezone(timezone.utc)]})
    conds.append({"$ne": [d, None]})
    return {"$and": conds}


async def base_match(src: config.SourceConfig, f: Optional[Filters] = None) -> dict:
    f = f or Filters()
    if f.date_from or f.date_to:
        start, end = _day_bounds(f.date_from, f.date_to)
    elif config.OPEN_LOOKBACK_DAYS > 0:
        start, end = datetime.now(timezone.utc) - timedelta(days=config.OPEN_LOOKBACK_DAYS), None
    else:
        start = end = None

    clauses: list[dict] = _status_clauses(src, f.status)
    if f.courier and src.courier_fields:
        clauses.append({src.courier_fields[0]: {"$in": [exact_ci_regex(x) for x in f.courier]}})
    if f.awb.strip():
        a = re.escape(f.awb.strip())
        clauses.append({src.awb_field: {"$in": [re.compile("^" + a), re.compile("^" + a.upper()),
                                               re.compile("^" + a, re.I)]}})
    dc = await _date_condition(src, start, end)
    if dc:
        clauses.append({dc[0]: dc[1]})
    exprs = [e for e in (
        _range_expr(src.status_date_fields, f.status_from, f.status_to),
        _range_expr(src.pickup_date_fields, f.pickup_from, f.pickup_to),
        _range_expr(src.last_track_fields + src.status_date_fields, f.track_from, f.track_to),
    ) if e]
    if exprs:
        clauses.append({"$expr": {"$and": exprs}})
    return {"$and": clauses}


def _ifnull_chain(paths: list[str]) -> Any:
    exprs = [f"${p}" for p in paths]
    if not exprs:
        return None
    out: Any = exprs[-1]
    for e in reversed(exprs[:-1]):
        out = {"$ifNull": [e, out]}
    return out


def _date_expr(paths: list) -> dict:
    """First non-null of `paths`, converted to a date whether stored as date, text or epoch."""
    raw = _ifnull_chain(paths)
    as_date = {"$switch": {"branches": [
        {"case": {"$eq": [{"$type": "$$v"}, "date"]}, "then": "$$v"},
        {"case": {"$eq": [{"$type": "$$v"}, "string"]}, "then": {"$dateFromString": {
            "dateString": "$$v", "timezone": config.DATE_STRINGS_TZ, "onError": None, "onNull": None}}},
        {"case": {"$in": [{"$type": "$$v"}, ["long", "int", "double"]]}, "then": {"$toDate": {
            "$cond": [{"$gt": ["$$v", 1e12]}, "$$v", {"$multiply": ["$$v", 1000]}]}}},
    ], "default": None}}
    return {"$let": {"vars": {"v": raw}, "in": as_date}}


def _age_hours_expr(src: config.SourceConfig) -> dict:
    """Hours since last update (last-track field, else status date)."""
    return {"$let": {"vars": {"d": _date_expr(src.last_track_fields + src.status_date_fields)}, "in": {
        "$cond": [{"$eq": ["$$d", None]}, None,
                  {"$divide": [{"$subtract": ["$$NOW", "$$d"]}, 3600000]}]}}}


def _aging_match(buckets: list) -> Optional[dict]:
    ors = []
    for key, _, lo, hi in AGING_BUCKETS:
        if key not in (buckets or []):
            continue
        if key == "nodate":
            ors.append({"_age_h": None})
            continue
        cond: dict = {"$gte": lo}
        if hi is not None:
            cond["$lt"] = hi
        ors.append({"_age_h": cond})
    if not ors:
        return None
    return ors[0] if len(ors) == 1 else {"$or": ors}


def _group_ci(field) -> list[dict]:
    """Group case/whitespace-insensitively, drop blanks, keep a readable label.
    `field` is a field path or an expression."""
    expr = field if isinstance(field, dict) or str(field).startswith("$") else f"${field}"
    return [
        {"$project": {"v": {"$trim": {"input": {"$toString": {"$ifNull": [expr, ""]}}}}}},
        {"$match": {"v": {"$nin": ["", "null", "None", "NA", "N/A", "-"]}}},
        {"$group": {"_id": {"$toLower": "$v"}, "label": {"$first": "$v"}, "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]


async def summary(src: config.SourceConfig, f: Optional[Filters] = None) -> dict:
    match = await base_match(src, f)
    courier_path = f"${src.courier_fields[0]}" if src.courier_fields else "$__none__"
    pipeline = [
        {"$match": match},
        {"$facet": {
            "total": [{"$count": "n"}],
            "by_status": _group_ci(_status_value_expr(src)) + [{"$limit": 200}],
            "by_courier": _group_ci(courier_path) + [{"$limit": 200}],
            "aging": [
                {"$project": {"h": _age_hours_expr(src)}},
                {"$bucket": {"groupBy": {"$ifNull": ["$h", -1]},
                             "boundaries": [-1, 0, 24, 48, 72, 120, 10 ** 9],
                             "default": "future", "output": {"count": {"$sum": 1}}}},
            ],
        }},
    ]
    res = await db.get_collection(src).aggregate(
        pipeline, allowDiskUse=True, maxTimeMS=config.MONGO_MAX_TIME_MS).to_list(length=1)
    f = res[0] if res else {}
    bmap = {-1: "nodate", 0: "lt1d", 24: "1to2d", 48: "2to3d", 72: "3to5d", 120: "gt5d", "future": "lt1d"}
    aging_counts: dict[str, int] = {}
    for b in f.get("aging", []):
        k = bmap.get(b["_id"], "nodate")
        aging_counts[k] = aging_counts.get(k, 0) + b["count"]
    return {
        "source": src.key,
        "source_label": src.label,
        "total": (f.get("total") or [{"n": 0}])[0]["n"] if f.get("total") else 0,
        "by_status": _mapped_status_counts(f.get("by_status", [])),
        "by_courier": [{"label": x["label"], "count": x["count"]} for x in f.get("by_courier", [])],
        "aging": [{"key": k, "label": lbl, "count": aging_counts.get(k, 0)} for k, lbl, _, _ in AGING_BUCKETS],
        "lookback_days": config.OPEN_LOOKBACK_DAYS,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _mapped_status_counts(rows: list) -> list:
    """Raw status values (codes) -> names from the mapping file, merging duplicates."""
    merged: dict = {}
    for x in rows:
        name = status_map.label(x["label"]) or x["label"]
        k = name.lower()
        if k not in merged:
            merged[k] = {"label": name, "code": status_map.code_key(x["label"]), "count": 0}
        merged[k]["count"] += x["count"]
    return sorted(merged.values(), key=lambda r: -r["count"])


async def filter_options(src: config.SourceConfig) -> dict:
    hit = _filter_cache.get((src.key,))
    if hit and time.time() - hit[0] < config.FILTER_CACHE_SECONDS:
        return hit[1]
    s = await summary(src)
    out = {"couriers": sorted({x["label"] for x in s["by_courier"]}, key=str.lower),
           "statuses": sorted({x["label"] for x in s["by_status"]}, key=str.lower),
           "aging": [{"key": k, "label": l} for k, l, _, _ in AGING_BUCKETS]}
    _filter_cache[(src.key,)] = (time.time(), out)
    return out


def _list_pipeline(src, match, aging: list, sort):
    p: list[dict] = [{"$match": match}, {"$addFields": {"_age_h": _age_hours_expr(src)}}]
    am = _aging_match(aging)
    if am:
        p.append({"$match": am})
    return p


async def _enrich(src: config.SourceConfig, rows: list[dict]) -> None:
    other = other_source(src)
    awbs = [r["awb"] for r in rows if r.get("awb")]
    omap = await fetch_by_awbs(other, awbs, with_tracking=False) if other.enabled else {}
    for r in rows:
        o = omap.get(awb_key(r.get("awb") or ""), {})
        found = bool(o.get("found"))
        same = norm_status(o.get("current_status")) == norm_status(r.get("current_status"))
        r["other"] = {"source": other.key, "label": other.label, "found": found,
                      "sync": ("match" if same else "mismatch") if found else "not_found",
                      "current_status": o.get("current_status"),
                      "status_datetime": o.get("status_datetime"),
                      "last_track_datetime": o.get("last_track_datetime")}


def _row(doc: dict, src) -> dict:
    r = normalize(doc, src, include_tracking=False)
    h = doc.get("_age_h")
    r["age_hours"] = round(h, 1) if isinstance(h, (int, float)) else None
    return r


async def _iter_rows(src: config.SourceConfig, f: Filters, sort: str, limit: int) -> AsyncIterator[list]:
    match = await base_match(src, f)
    sort_stage = {"$sort": {"_age_h": -1}} if sort == "stale" else {"$sort": {"_id": -1}}
    pipe = _list_pipeline(src, match, f.aging, sort) + [
        sort_stage, {"$limit": limit},
        {"$project": {**projection(src, with_tracking=False), "_age_h": 1}}]
    cur = db.get_collection(src).aggregate(pipe, allowDiskUse=True, maxTimeMS=config.MONGO_MAX_TIME_MS * 5,
                                           batchSize=500)
    chunk: list[dict] = []
    async for d in cur:
        chunk.append(_row(d, src))
        if len(chunk) >= 500:
            await _enrich(src, chunk)
            yield [r for r in chunk if not f.other or r["other"]["sync"] in f.other]
            chunk = []
    if chunk:
        await _enrich(src, chunk)
        yield [r for r in chunk if not f.other or r["other"]["sync"] in f.other]


async def list_cases(src: config.SourceConfig, page: int, page_size: int, sort: str,
                     f: Optional[Filters] = None) -> dict:
    f = f or Filters()
    if f.other:
        # The other system lives in a different database, so this filter is applied
        # while reading (capped at EXPORT_MAX_ROWS), then paged here.
        rows: list = []
        async for chunk in _iter_rows(src, f, sort, config.EXPORT_MAX_ROWS):
            rows.extend(chunk)
        start = (page - 1) * page_size
        return {"total": len(rows), "page": page, "page_size": page_size,
                "rows": rows[start:start + page_size], "capped": len(rows) >= config.EXPORT_MAX_ROWS}

    match = await base_match(src, f)
    coll = db.get_collection(src)
    base = _list_pipeline(src, match, f.aging, sort)
    sort_stage = {"$sort": {"_age_h": -1}} if sort == "stale" else {"$sort": {"_id": -1}}
    pipe = base + [sort_stage, {"$skip": (page - 1) * page_size}, {"$limit": page_size},
                   {"$project": {**projection(src, with_tracking=False), "_age_h": 1}}]
    kw = dict(allowDiskUse=True, maxTimeMS=config.MONGO_MAX_TIME_MS)
    docs = await coll.aggregate(pipe, **kw).to_list(length=page_size)
    if f.aging:
        cnt = await coll.aggregate(base + [{"$count": "n"}], **kw).to_list(length=1)
        total = cnt[0]["n"] if cnt else 0
    else:
        total = await coll.count_documents(match, maxTimeMS=config.MONGO_MAX_TIME_MS)
    rows = [_row(d, src) for d in docs]
    await _enrich(src, rows)
    return {"total": total, "page": page, "page_size": page_size, "rows": rows}


async def iter_export(src: config.SourceConfig, sort: str, f: Optional[Filters] = None) -> AsyncIterator[list]:
    async for chunk in _iter_rows(src, f or Filters(), sort, config.EXPORT_MAX_ROWS):
        yield chunk


__all__ = ["summary", "list_cases", "iter_export", "filter_options", "AGING_BUCKETS", "clean_str"]
