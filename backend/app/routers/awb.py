import csv
import io
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import config
from ..services.shipments import check_awbs
from ..utils import parse_awb_input

router = APIRouter(prefix="/api/awb", tags=["AWB Check"])


class AwbRequest(BaseModel):
    awbs: list[str] = Field(default_factory=list, description="AWB numbers, or raw pasted text")


def _clean(req: AwbRequest) -> list[str]:
    awbs = parse_awb_input(req.awbs)
    if not awbs:
        raise HTTPException(400, "Enter at least one AWB number.")
    if len(awbs) > config.MAX_AWBS_PER_REQUEST:
        raise HTTPException(400, f"Max {config.MAX_AWBS_PER_REQUEST} AWBs per check (got {len(awbs)}).")
    return awbs


@router.post("/check")
async def check(req: AwbRequest):
    awbs = _clean(req)
    rows = await check_awbs(awbs)
    counts = {"total": len(rows),
              "in_smart_tracking": sum(r["smart_tracking"]["found"] for r in rows),
              "in_platform": sum(r["platform"]["found"] for r in rows),
              "closed": sum(r["closed"] for r in rows)}
    for state in ("match", "mismatch", "only_smart_tracking", "only_platform", "not_found"):
        counts[state] = sum(r["sync"] == state for r in rows)
    return {"counts": counts, "labels": {"smart_tracking": config.SMART_TRACKING.label,
                                         "platform": config.PLATFORM.label}, "rows": rows}


@router.post("/export")
async def export(req: AwbRequest):
    awbs = _clean(req)
    rows = await check_awbs(awbs)
    st_l, pf_l = config.SMART_TRACKING.label, config.PLATFORM.label
    cols = ["Courier", "Current Status", "Status Datetime", "Pickup Date", "Last Track Datetime",
            "Latest Tracking Event", "Tracking Events"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["AWB"] + [f"{st_l} - {c}" for c in cols] + [f"{pf_l} - {c}" for c in cols] + ["Sync"])

    def part(r):
        if not r.get("found"):
            return ["Not found"] + [""] * (len(cols) - 1)
        ev = (r.get("tracking") or [{}])[0]
        latest = " | ".join(x for x in [ev.get("datetime"), ev.get("status"), ev.get("location")] if x)
        return [r.get("courier"), r.get("current_status"), r.get("status_datetime"), r.get("pickup_date"),
                r.get("last_track_datetime"), latest, r.get("tracking_count")]

    for r in rows:
        w.writerow([r["awb"]] + part(r["smart_tracking"]) + part(r["platform"]) + [r["sync"]])
    name = f"awb_status_{datetime.now():%Y%m%d_%H%M}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})
