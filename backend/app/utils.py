import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

from bson import ObjectId
from dateutil import parser as dtparser

from . import config

DISPLAY_TZ = ZoneInfo(config.DISPLAY_TZ)
STRING_TZ = ZoneInfo(config.DATE_STRINGS_TZ)
_EMPTY = {"", "na", "n/a", "null", "none", "-", "nan", "undefined"}


def get_path(doc: Any, path: str) -> Any:
    """Read a dot-notation path. Numeric parts index into lists; on a list
    without an index, the last element is used."""
    cur = doc
    for part in path.split("."):
        if cur is None:
            return None
        if isinstance(cur, list):
            if part.lstrip("-").isdigit():
                i = int(part)
                cur = cur[i] if -len(cur) <= i < len(cur) else None
                continue
            cur = cur[-1] if cur else None
            if cur is None:
                return None
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def is_empty(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str) and v.strip().lower() in _EMPTY:
        return True
    if isinstance(v, (list, dict)) and not v:
        return True
    return False


def first_value(doc: Any, paths: Iterable[str]) -> Any:
    for p in paths:
        v = get_path(doc, p)
        if not is_empty(v):
            return v
    return None


def clean_str(v: Any) -> Optional[str]:
    if is_empty(v):
        return None
    return re.sub(r"\s+", " ", str(v)).strip() or None


def to_dt(v: Any) -> Optional[datetime]:
    """Best-effort conversion of whatever is stored into an aware datetime."""
    if is_empty(v):
        return None
    try:
        if isinstance(v, dict) and "$date" in v:
            v = v["$date"]
        if isinstance(v, datetime):
            # PyMongo returns naive datetimes in UTC
            return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        if isinstance(v, ObjectId):
            return v.generation_time
        if isinstance(v, (int, float)):
            ts = float(v)
            if ts > 1e12:
                ts /= 1000.0
            if ts < 1e8:
                return None
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        if isinstance(v, str):
            s = v.strip()
            if s.isdigit():
                return to_dt(int(s))
            # dd-mm-yyyy / dd/mm/yyyy are the common Indian courier formats
            dayfirst = bool(re.match(r"^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}", s))
            dt = dtparser.parse(s, dayfirst=dayfirst)
            return dt if dt.tzinfo else dt.replace(tzinfo=STRING_TZ)
    except (ValueError, OverflowError, TypeError):
        return None
    return None


def fmt(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(DISPLAY_TZ).isoformat(timespec="seconds") if dt else None


def parse_awb_input(raw: Iterable[str]) -> list[str]:
    """Split pasted text on whitespace/commas, strip quotes, dedupe (keep order)."""
    seen, out = set(), []
    for chunk in raw:
        for token in re.split(r"[\s,;|]+", str(chunk or "")):
            t = token.strip().strip("'\"`")
            if not t:
                continue
            k = t.upper()
            if k not in seen:
                seen.add(k)
                out.append(t)
    return out


def awb_key(v: Any) -> str:
    return str(v).strip().upper()


def awb_variants(awbs: Iterable[str]) -> list[Any]:
    """AWBs may be stored as strings or numbers, and in either case."""
    vals: list[Any] = []
    for a in awbs:
        vals.extend({a, a.upper(), a.lower()})
        if a.isdigit() and not a.startswith("0") and len(a) < 19:
            vals.append(int(a))
    return vals


def norm_status(v: Any) -> str:
    return re.sub(r"[\s_\-]+", " ", str(v or "")).strip().lower()


def exact_ci_regex(value: str) -> re.Pattern:
    return re.compile(r"^\s*" + re.escape(value.strip()) + r"\s*$", re.IGNORECASE)
