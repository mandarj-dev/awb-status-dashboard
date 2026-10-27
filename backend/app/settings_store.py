"""Reading/writing .env for the Setup page, and the settings PIN."""
import hashlib
import hmac
import os
import re
import shutil
import tempfile

from . import config

EXAMPLE = config.ENV_PATH.parent / ".env.example"

# Raised when Setup tries to persist settings on a read-only host (e.g. Vercel).
READONLY_ENV_MSG = (
    "This deployment cannot write a .env file. "
    "Set ST_MONGO_URI, ST_DB_NAME, ST_COLLECTION (and the PF_* equivalents) "
    "in your host's environment variables (Vercel → Project → Settings → Environment Variables), "
    "then redeploy."
)


def ensure_env_file() -> None:
    # Vercel / serverless: filesystem is read-only; env comes from the platform.
    if config.is_vercel():
        return
    if not config.ENV_PATH.exists():
        if EXAMPLE.exists():
            shutil.copy(EXAMPLE, config.ENV_PATH)
        else:
            config.ENV_PATH.write_text("", encoding="utf-8")


def _quote(v: str) -> str:
    v = str(v)
    if v == "" or re.fullmatch(r"[A-Za-z0-9_./:@%?&=,+\-~*!$()\[\]]+", v):
        return v
    if "'" not in v:
        return f"'{v}'"
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def update_env(values: dict) -> None:
    """Set KEY=value lines in .env, keeping every other line and comment."""
    if config.is_vercel():
        raise OSError(READONLY_ENV_MSG)
    ensure_env_file()
    lines = config.ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    pending = dict(values)
    out = []
    for line in lines:
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=", line)
        if m and m.group(1) in pending:
            out.append(f"{m.group(1)}={_quote(pending.pop(m.group(1)))}")
        else:
            out.append(line)
    if pending:
        out.append("")
        out.extend(f"{k}={_quote(v)}" for k, v in pending.items())
    fd, tmp = tempfile.mkstemp(dir=str(config.ENV_PATH.parent), prefix=".env.")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    os.replace(tmp, config.ENV_PATH)


def hash_pin(pin: str) -> str:
    salt = os.urandom(16).hex()
    h = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 200_000).hex()
    return f"{salt}${h}"


def check_pin(pin: str) -> bool:
    stored = config.SETUP_PIN_HASH
    if not stored:
        return True
    try:
        salt, h = stored.split("$", 1)
    except ValueError:
        return False
    calc = hashlib.pbkdf2_hmac("sha256", (pin or "").encode(), salt.encode(), 200_000).hex()
    return hmac.compare_digest(calc, h)


def mask_uri(uri: str) -> str:
    return re.sub(r"(mongodb(?:\+srv)?://[^:/@]+:)([^@]+)(@)", r"\1••••••\3", uri or "")
