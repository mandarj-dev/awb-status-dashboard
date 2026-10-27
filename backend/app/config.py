"""
All configuration comes from .env in the project folder (filled in by the Setup page).

Every *_FIELDS / *_KEYS setting is a comma-separated list of candidate paths
(dot-notation supported, e.g. status.dispatch_status). The first non-empty
value wins, so the same build works even if the two systems store things
under different names.
"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR.parent / ".env"   # project root, next to run.bat
load_dotenv(ENV_PATH)


def env(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def env_list(key: str, default: str = "") -> list[str]:
    return [x.strip() for x in env(key, default).split(",") if x.strip()]


def env_int(key: str, default: int) -> int:
    try:
        return int(env(key, str(default)))
    except ValueError:
        return default


def is_vercel() -> bool:
    """True when running as a Vercel Function (read-only filesystem, env from dashboard)."""
    return bool(os.getenv("VERCEL") or os.getenv("VERCEL_ENV"))


# ---------------------------------------------------------------- app-level
APP_TITLE = env("APP_TITLE", "AWB Status Dashboard")
CORS_ORIGINS = env_list("CORS_ORIGINS", "*")
MAX_AWBS_PER_REQUEST = env_int("MAX_AWBS_PER_REQUEST", 1000)
QUERY_BATCH_SIZE = env_int("QUERY_BATCH_SIZE", 200)
MONGO_TIMEOUT_MS = env_int("MONGO_TIMEOUT_MS", 15000)
# Cap Mongo time under Vercel function maxDuration (default 60s in vercel.json).
MONGO_MAX_TIME_MS = env_int(
    "MONGO_MAX_TIME_MS",
    45000 if is_vercel() else 60000,
)
MONGO_READ_PREFERENCE = env("MONGO_READ_PREFERENCE", "secondaryPreferred")
DISPLAY_TZ = env("DISPLAY_TZ", "Asia/Kolkata")
# Timezone assumed for date *strings* stored without an offset
DATE_STRINGS_TZ = env("DATE_STRINGS_TZ", "Asia/Kolkata")
FRONTEND_DIST = env("FRONTEND_DIST", str(BASE_DIR.parent / "frontend" / "dist"))

# ---------------------------------------------------------------- open cases
# A shipment is "open" unless its current dispatch status is one of these codes.
# Names for the codes come from Dispatch-status-Mapping.xlsx (5 Delivered, 13 RTO Delivered,
# 14 Pickup Cancelled, 15 Lost, 16 Damaged). These AWBs are skipped on both pages.
CLOSED_STATUS_CODES = env_list("CLOSED_STATUS_CODES", "5,13,14,15,16")
# Optional extra status *names* to treat as closed (for a system that stores text, not codes).
OPEN_EXCLUDE_STATUSES = env_list("OPEN_EXCLUDE_STATUSES", "")
OPEN_LOOKBACK_DAYS = env_int("OPEN_LOOKBACK_DAYS", 60)
# AWB used as the sample shipment on the Setup page
SETUP_SAMPLE_AWB = env("SETUP_SAMPLE_AWB", "1095160")  # (re-read on reload)
EXPORT_MAX_ROWS = env_int("EXPORT_MAX_ROWS", 50000)
FILTER_CACHE_SECONDS = env_int("FILTER_CACHE_SECONDS", 300)


@dataclass
class SourceConfig:
    key: str
    label: str
    mongo_uri: str
    db_name: str
    collection: str
    awb_field: str
    courier_fields: list[str]
    status_fields: list[str]
    status_code_fields: list[str]
    status_date_fields: list[str]
    pickup_date_fields: list[str]
    last_track_fields: list[str]
    created_fields: list[str]
    order_date_field: str
    tracking_field: str
    track_status_keys: list[str]
    track_code_keys: list[str]
    track_date_keys: list[str]
    track_sync_keys: list[str]
    track_location_keys: list[str]
    track_remark_keys: list[str]

    @property
    def enabled(self) -> bool:
        return bool(self.mongo_uri and self.db_name and self.collection)


def _load_source(prefix: str, key: str, label: str, d: dict) -> SourceConfig:
    g = lambda name: env(f"{prefix}_{name}", d.get(name, ""))  # noqa: E731
    gl = lambda name: env_list(f"{prefix}_{name}", d.get(name, ""))  # noqa: E731
    return SourceConfig(
        key=key,
        label=env(f"{prefix}_LABEL", label),
        mongo_uri=g("MONGO_URI"),
        db_name=g("DB_NAME"),
        collection=g("COLLECTION"),
        awb_field=g("AWB_FIELD"),
        courier_fields=gl("COURIER_FIELDS"),
        status_fields=gl("STATUS_FIELDS"),
        status_code_fields=gl("STATUS_CODE_FIELDS"),
        status_date_fields=gl("STATUS_DATE_FIELDS"),
        pickup_date_fields=gl("PICKUP_DATE_FIELDS"),
        last_track_fields=gl("LAST_TRACK_FIELDS"),
        created_fields=gl("CREATED_FIELDS"),
        order_date_field=g("ORDER_DATE_FIELD"),
        tracking_field=g("TRACKING_FIELD"),
        track_status_keys=gl("TRACK_STATUS_KEYS"),
        track_code_keys=gl("TRACK_CODE_KEYS"),
        track_date_keys=gl("TRACK_DATE_KEYS"),
        track_sync_keys=gl("TRACK_SYNC_KEYS"),
        track_location_keys=gl("TRACK_LOCATION_KEYS"),
        track_remark_keys=gl("TRACK_REMARK_KEYS"),
    )


_COMMON_DEFAULTS = {
    "AWB_FIELD": "airwaybilno",
    "COURIER_FIELDS": "courier_name,courier,courier_code",
    "STATUS_FIELDS": "status.dispatch_status,dispatch_status,current_status",
    "STATUS_CODE_FIELDS": "status.dispatch_status_code,dispatch_status_code",
    "STATUS_DATE_FIELDS": "status.status_date,status_date,status.dispatch_status_date",
    "PICKUP_DATE_FIELDS": "status.pickup_date,pickup_date",
    "LAST_TRACK_FIELDS": "last_tracked_at,last_track_date,updated_at",
    "CREATED_FIELDS": "created_at,created_date,booking_date",
    # Open Cases date range (and the 60-day window) uses this field
    "ORDER_DATE_FIELD": "status.order_date",
    "TRACKING_FIELD": "tracking",
    "TRACK_STATUS_KEYS": "courier_status,status,status_description",
    "TRACK_CODE_KEYS": "parent_status_code,status_code",
    "TRACK_DATE_KEYS": "status_date,date,event_date,status_created_date",
    "TRACK_SYNC_KEYS": "status_created_date,created_at",
    "TRACK_LOCATION_KEYS": "location,city,current_location",
    "TRACK_REMARK_KEYS": "remark,remarks,status_description",
}

SMART_TRACKING: SourceConfig
PLATFORM: SourceConfig
SOURCES: dict
CONFIGURED: bool
SETUP_PIN_HASH: str


def _build_sources() -> None:
    """(Re)build source settings from the environment. Called at import and
    after the Setup page saves, so changes apply without a restart."""
    global SMART_TRACKING, PLATFORM, SOURCES, CONFIGURED, SETUP_PIN_HASH, SETUP_SAMPLE_AWB
    SMART_TRACKING = _load_source(
        "ST", "smart_tracking", "Smart Tracking",
        {**_COMMON_DEFAULTS, "MONGO_URI": "", "DB_NAME": "", "COLLECTION": ""},
    )
    # Platform (Instalogix). If PF_MONGO_URI is blank, it reuses the Smart Tracking URI.
    PLATFORM = _load_source(
        "PF", "platform", "Platform",
        {**_COMMON_DEFAULTS, "MONGO_URI": SMART_TRACKING.mongo_uri, "DB_NAME": "", "COLLECTION": ""},
    )
    SOURCES = {SMART_TRACKING.key: SMART_TRACKING, PLATFORM.key: PLATFORM}
    CONFIGURED = SMART_TRACKING.enabled and "user:pass@host" not in SMART_TRACKING.mongo_uri
    SETUP_PIN_HASH = env("SETUP_PIN_HASH", "")
    SETUP_SAMPLE_AWB = env("SETUP_SAMPLE_AWB", "1095160")


def reload() -> None:
    load_dotenv(ENV_PATH, override=True)
    _build_sources()


_build_sources()
