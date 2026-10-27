"""Dispatch status code -> display name, read from Dispatch-status-Mapping.xlsx
in the project folder, plus the list of closed codes (skipped everywhere).

The Excel needs two columns: the dispatch status code and the text to show.
Edit it in Excel and restart the dashboard to change the names.
"""
import logging
import re
from pathlib import Path
from typing import Any, Optional

from . import config

log = logging.getLogger("status_map")

MAPPING_FILE = Path(config.env("STATUS_MAPPING_FILE", str(config.ENV_PATH.parent / "Dispatch-status-Mapping.xlsx")))

# Saved as the status field when a system keeps its dispatch code only in the tracking events.
LATEST_EVENT = "@latest_tracking_event"

CODE_TO_LABEL: dict = {}      # "5" -> "Delivered"
LABEL_TO_CODES: dict = {}     # "delivered" -> ["5"]
LOADED_FROM: Optional[str] = None
LOAD_ERROR: Optional[str] = None


def code_key(v: Any) -> Optional[str]:
    """5, 5.0, "5", " 05 " -> "5"; anything that isn't a whole number -> None."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else None
    s = str(v).strip()
    if re.fullmatch(r"[+-]?\d+(\.0+)?", s):
        return str(int(float(s)))
    return None


def _norm(s: Any) -> str:
    return re.sub(r"[\s_\-]+", " ", str(s or "")).strip().lower()


def load() -> None:
    global LOADED_FROM, LOAD_ERROR
    CODE_TO_LABEL.clear(); LABEL_TO_CODES.clear()
    LOADED_FROM = LOAD_ERROR = None
    if not MAPPING_FILE.exists():
        LOAD_ERROR = f"{MAPPING_FILE.name} not found - status codes will be shown as numbers."
        log.warning(LOAD_ERROR)
        return
    try:
        import openpyxl
        wb = openpyxl.load_workbook(MAPPING_FILE, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = [r for r in ws.iter_rows(values_only=True) if r and any(c is not None for c in r)]
        wb.close()
    except Exception as ex:  # noqa: BLE001
        LOAD_ERROR = f"Couldn't read {MAPPING_FILE.name}: {ex}"
        log.error(LOAD_ERROR)
        return
    if not rows:
        LOAD_ERROR = f"{MAPPING_FILE.name} is empty."
        return
    # Find the code column and the text column (header names if present, else first two columns).
    header = [_norm(c) for c in rows[0]]
    code_col, text_col = 0, 1
    has_header = code_key(rows[0][0]) is None
    if has_header:
        for i, h in enumerate(header):
            if "dispatch" in h or h in ("code", "status code", "dispatch status"):
                code_col = i
                break
        for i, h in enumerate(header):
            if i != code_col and h and ("status" in h or "name" in h or "text" in h or "label" in h):
                text_col = i
                break
    for r in rows[1 if has_header else 0:]:
        if max(code_col, text_col) >= len(r):
            continue
        code, text = code_key(r[code_col]), r[text_col]
        if code is None or text is None or not str(text).strip():
            continue
        label = re.sub(r"\s+", " ", str(text)).strip()
        CODE_TO_LABEL[code] = label
        LABEL_TO_CODES.setdefault(_norm(label), []).append(code)
    LOADED_FROM = str(MAPPING_FILE)
    log.info("Loaded %d status names from %s", len(CODE_TO_LABEL), MAPPING_FILE.name)


def label(v: Any) -> Optional[str]:
    """Display text for a stored status (code or text)."""
    if v is None:
        return None
    k = code_key(v)
    if k is not None:
        return CODE_TO_LABEL.get(k, f"Status {k} (not in mapping)" if CODE_TO_LABEL else k)
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s or None


def closed_codes() -> list:
    return [c for c in (code_key(x) for x in config.CLOSED_STATUS_CODES) if c is not None]


def is_closed(raw: Any) -> bool:
    """True for a closed code (5,13,...) or for its mapped name if the system stores text."""
    k = code_key(raw)
    codes = set(closed_codes())
    if k is not None:
        return k in codes
    n = _norm(raw)
    if not n:
        return False
    names = {_norm(CODE_TO_LABEL.get(c, "")) for c in codes} | {_norm(x) for x in config.OPEN_EXCLUDE_STATUSES}
    return n in names


def db_values(display: str) -> list:
    """Everything a stored status can look like for a display name: the code(s) as text and
    number, and the name itself (case-insensitive). Used to build MongoDB filters."""
    out: list = []
    m = re.fullmatch(r"Status (\d+) \(not in mapping\)", display or "")
    codes = [m.group(1)] if m else list(LABEL_TO_CODES.get(_norm(display), []))
    if code_key(display) is not None:
        codes.append(code_key(display))
    for c in codes:
        out += [c, int(c)]
    if not m and code_key(display) is None:
        out.append(re.compile(r"^\s*" + re.escape(display.strip()) + r"\s*$", re.I))
    return out


def closed_db_values() -> list:
    out: list = []
    for c in closed_codes():
        out += db_values(c)
        if c in CODE_TO_LABEL:
            out += db_values(CODE_TO_LABEL[c])
    for name in config.OPEN_EXCLUDE_STATUSES:
        out += db_values(name)
    return out


def closed_summary() -> list:
    return [{"code": c, "label": CODE_TO_LABEL.get(c, "")} for c in closed_codes()]


def table() -> list:
    closed = set(closed_codes())
    return [{"code": c, "label": l, "closed": c in closed}
            for c, l in sorted(CODE_TO_LABEL.items(), key=lambda x: int(x[0]))]


load()
