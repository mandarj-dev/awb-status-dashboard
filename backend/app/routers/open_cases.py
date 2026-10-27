import csv
import io
from datetime import date, datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from .. import config
from ..services import open_cases as svc
from ..services.open_cases import Filters

router = APIRouter(prefix="/api/open-cases", tags=["Open Cases"])

SourceKey = Literal["smart_tracking", "platform"]


def _src(source: str) -> config.SourceConfig:
    src = config.SOURCES.get(source)
    if not src or not src.enabled:
        raise HTTPException(400, f"Source '{source}' is not configured.")
    return src


def _clean(values: Optional[List[str]]) -> list:
    return [v for v in (values or []) if v not in (None, "")]


def get_filters(
    courier: Optional[List[str]] = Query(None), status: Optional[List[str]] = Query(None),
    awb: Optional[str] = None,
    date_from: Optional[date] = None, date_to: Optional[date] = None,
    status_from: Optional[date] = None, status_to: Optional[date] = None,
    pickup_from: Optional[date] = None, pickup_to: Optional[date] = None,
    track_from: Optional[date] = None, track_to: Optional[date] = None,
    aging: Optional[List[str]] = Query(None), other: Optional[List[str]] = Query(None),
) -> Filters:
    return Filters(courier=_clean(courier), status=_clean(status), awb=awb or "",
                   date_from=date_from, date_to=date_to, status_from=status_from, status_to=status_to,
                   pickup_from=pickup_from, pickup_to=pickup_to, track_from=track_from, track_to=track_to,
                   aging=_clean(aging), other=_clean(other))


@router.get("/filters")
async def filters(source: SourceKey = "smart_tracking"):
    return await svc.filter_options(_src(source))


@router.get("/summary")
async def summary(source: SourceKey = "smart_tracking", f: Filters = Depends(get_filters)):
    # The aging tiles are themselves the aging filter, so the summary ignores it.
    f.aging = []
    f.other = []
    return await svc.summary(_src(source), f)


@router.get("/list")
async def list_cases(source: SourceKey = "smart_tracking", sort: Literal["recent", "stale"] = "stale",
                     page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                     f: Filters = Depends(get_filters)):
    return await svc.list_cases(_src(source), page, page_size, sort, f)


# Export columns, in display order: key -> (header, value getter)
def _export_columns(src_label: str, other_label: str) -> dict:
    o = lambda r: r.get("other", {})  # noqa: E731
    return {
        "awb": ("AWB", lambda r: r.get("awb")),
        "courier": ("Courier", lambda r: r.get("courier")),
        "status": (f"{src_label} Status", lambda r: r.get("current_status")),
        "order_date": ("Order Date", lambda r: r.get("order_date")),
        "status_datetime": (f"{src_label} Status Datetime", lambda r: r.get("status_datetime")),
        "pickup_date": ("Pickup Date", lambda r: r.get("pickup_date")),
        "last_track": ("Last Track Datetime", lambda r: r.get("last_track_datetime")),
        "age": ("Hours Since Update", lambda r: r.get("age_hours")),
        "other_status": (f"{other_label} Status",
                         lambda r: o(r).get("current_status") if o(r).get("found") else "Not found"),
        "other_sync": ("Status Match", lambda r: {"match": "Match", "mismatch": "Mismatch",
                                                  "not_found": "Not found"}.get(o(r).get("sync"), "")),
        "other_status_datetime": (f"{other_label} Status Datetime", lambda r: o(r).get("status_datetime")),
        "other_last_track": (f"{other_label} Last Track", lambda r: o(r).get("last_track_datetime")),
    }


@router.get("/export")
async def export(source: SourceKey = "smart_tracking", sort: Literal["recent", "stale"] = "stale",
                 columns: Optional[List[str]] = Query(None), f: Filters = Depends(get_filters)):
    src = _src(source)
    other = svc.other_source(src)
    all_cols = _export_columns(src.label, other.label)
    keys = [c for c in (columns or []) if c in all_cols] or list(all_cols)
    if "awb" not in keys:
        keys.insert(0, "awb")
    cols = [all_cols[k] for k in keys]

    async def gen():
        buf = io.StringIO()
        csv.writer(buf).writerow([h for h, _ in cols])
        yield "﻿" + buf.getvalue()  # BOM so Excel opens it as UTF-8
        async for chunk in svc.iter_export(src, sort, f):
            buf = io.StringIO()
            w = csv.writer(buf)
            for r in chunk:
                w.writerow([get(r) for _, get in cols])
            yield buf.getvalue()

    name = f"open_cases_{source}_{datetime.now():%Y%m%d_%H%M}.csv"
    return StreamingResponse(gen(), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})
