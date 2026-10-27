"""End-to-end smoke test against a throwaway local MongoDB.

    cd backend
    TEST_MONGO_URI=mongodb://localhost:27017 python -m tests.smoke_test

It creates/drops databases `awbdash_test_st` and `awbdash_test_pf` only.
"""
import os

URI = os.getenv("TEST_MONGO_URI", "mongodb://localhost:27017")
os.environ.update({"ST_MONGO_URI": URI, "PF_MONGO_URI": URI, "ST_DB_NAME": "awbdash_test_st",
                   "PF_DB_NAME": "awbdash_test_pf", "ST_COLLECTION": "shipments", "PF_COLLECTION": "shipments",
                   "MONGO_READ_PREFERENCE": "primary"})

from datetime import datetime, timedelta, timezone  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from pymongo import MongoClient  # noqa: E402

from app.main import app  # noqa: E402

now = datetime.now(timezone.utc).replace(tzinfo=None)
mc = MongoClient(URI)
for name in ("awbdash_test_st", "awbdash_test_pf"):
    mc.drop_database(name)
st, pf = mc.awbdash_test_st.shipments, mc.awbdash_test_pf.shipments


def mk(awb, status, hrs, courier="Delhivery", created_days=3):
    return {"airwaybilno": awb, "courier_name": courier, "created_at": now - timedelta(days=created_days),
            "status": {"dispatch_status": status, "status_date": now - timedelta(hours=hrs),
                       "pickup_date": now - timedelta(days=2)},
            "tracking": [{"status": "Picked Up", "status_date": now - timedelta(days=2), "location": "Surat",
                          "status_created_date": now - timedelta(days=2), "parent_status_code": "2"},
                         {"status": status, "status_date": now - timedelta(hours=hrs), "location": "Mumbai Hub",
                          "status_created_date": now - timedelta(hours=hrs - 1)}]}


st.insert_many([mk("1001", "In Transit", 10), mk("1002", "Delivered", 2), mk("1003", "Out For Delivery", 80, "BlueDart"),
                mk(1004, "in transit ", 200), mk("1005", "RTO Delivered", 5), mk("1006", "Pending", 30, "Ekart"),
                mk("OLD1", "In Transit", 900, created_days=400), {"airwaybilno": "1007", "courier_name": " delhivery"}])
pf.insert_many([
    {"airwaybilno": "1001", "courier_name": "Delhivery", "created_at": now,
     "status": {"dispatch_status": "In Transit",
                "status_date": (now + timedelta(hours=5, minutes=30) - timedelta(hours=9)).strftime("%d-%m-%Y %H:%M:%S")}},
    {"airwaybilno": "1003", "created_at": now, "status": {"dispatch_status": "Undelivered"}},
    {"airwaybilno": "9999", "created_at": now, "status": {"dispatch_status": "Booked"},
     "last_tracked_at": int((datetime.now(timezone.utc) - timedelta(hours=50)).timestamp() * 1000)}])
st.create_index("airwaybilno"); pf.create_index("airwaybilno")

ok = True


def check(label, cond):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + label)


with TestClient(app) as c:
    j = c.post("/api/awb/check", json={"awbs": ["1001, 1002\n1003 1004", "9999", "0000", "1001"]}).json()
    rows = {r["awb"]: r for r in j["rows"]}
    print(j["counts"])
    check("dedupes input", j["counts"]["total"] == 6)
    check("string + numeric AWB found", rows["1004"]["smart_tracking"]["found"])
    check("match / mismatch", rows["1001"]["sync"] == "match" and rows["1003"]["sync"] == "mismatch")
    check("platform-only & not-found", rows["9999"]["sync"] == "only_platform" and rows["0000"]["sync"] == "not_found")
    check("tracking newest first", rows["1001"]["smart_tracking"]["tracking"][0]["location"] == "Mumbai Hub")
    check("dd-mm-yyyy string parsed as IST", rows["1001"]["platform"]["status_datetime"].endswith("+05:30"))
    check("epoch last-track parsed", rows["9999"]["platform"]["last_track_datetime"] is not None)
    print(" sample:", {k: v for k, v in rows["1001"]["smart_tracking"].items() if k != "tracking"})
    check("export csv", c.post("/api/awb/export", json={"awbs": ["1001", "1003"]}).text.count("\n") == 3)
    check("too many AWBs rejected", c.post("/api/awb/check", json={"awbs": [str(i) for i in range(1001 + 1000)]}).status_code == 400)

    s = c.get("/api/open-cases/summary").json()
    print(" summary:", s["total"], s["by_status"], s["by_courier"], [(a["key"], a["count"]) for a in s["aging"]])
    # open = 1001,1003,1004,1006 (1002/1005 closed, OLD1 outside lookback, 1007 no status)
    check("open total", s["total"] == 4)
    check("status variants merged", any(x["count"] == 2 and x["label"].lower().startswith("in transit") for x in s["by_status"]))
    check("aging buckets", {a["key"]: a["count"] for a in s["aging"]} == {"lt1d": 1, "1to2d": 1, "2to3d": 0, "3to5d": 1, "gt5d": 1, "nodate": 0})

    l = c.get("/api/open-cases/list?page_size=2&sort=stale").json()
    check("list paging", l["total"] == 4 and len(l["rows"]) == 2 and l["rows"][0]["awb"] == "1004")
    check("list enriched with platform", any(r["other"]["found"] for r in c.get("/api/open-cases/list").json()["rows"]))
    check("aging filter", c.get("/api/open-cases/list?aging=3to5d").json()["total"] == 1)
    check("courier filter (case-insensitive)", c.get("/api/open-cases/summary?courier=bluedart").json()["total"] == 1)
    check("status filter", c.get("/api/open-cases/summary?status=IN TRANSIT").json()["total"] == 2)
    d = (now - timedelta(days=500)).date().isoformat()
    check("date range overrides lookback", c.get(f"/api/open-cases/summary?date_from={d}").json()["total"] == 5)
    check("filters endpoint", "BlueDart" in c.get("/api/open-cases/filters").json()["couriers"])
    e = c.get("/api/open-cases/export").text
    check("open export csv", e.count("\n") == 5 and "Platform Status" in e)
    p = c.get("/api/open-cases/summary?source=platform").json()
    check("platform source", p["total"] == 3)
    check("health", c.get("/api/health").json()["sources"]["smart_tracking"]["ok"])

    # dispatch status codes from Dispatch-status-Mapping.xlsx (5,13,14,15,16 = closed)
    st.insert_many([mk("C2", 2, 5), mk("C5", "5", 5), mk("C13", 13, 5), mk("C16", "16", 5), mk("C7", 7, 5)])
    j = c.post("/api/awb/check", json={"awbs": ["C2", "C5", "C13", "C7"]}).json()
    rows = {r["awb"]: r for r in j["rows"]}
    check("code 2 shown as its name", rows["C2"]["smart_tracking"]["current_status"] == "In-transit")
    check("closed codes flagged (number + text)", rows["C5"]["closed"] and rows["C13"]["closed"] and not rows["C2"]["closed"])
    check("unmapped code labelled", rows["C7"]["smart_tracking"]["current_status"] == "Status 7 (not in mapping)")
    s2 = c.get("/api/open-cases/summary").json()
    check("closed codes skipped in open cases", s2["total"] == 6)
    check("filter by mapped name", c.get("/api/open-cases/summary?status=In-transit").json()["total"] == 1)

for name in ("awbdash_test_st", "awbdash_test_pf"):
    mc.drop_database(name)
print("\nALL PASSED" if ok else "\nSOME CHECKS FAILED")
raise SystemExit(0 if ok else 1)
