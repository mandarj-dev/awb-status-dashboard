#!/usr/bin/env python3
"""
AWB Status Dashboard launcher — same command on Windows, macOS, Linux and the server.

    python start.py              run locally  -> http://localhost:8000 (opens browser)
    python start.py --server     run on a server -> 0.0.0.0:8010, no browser
    python start.py --check      only check setup + database connections
    python start.py --port 9000  pick a port (also: PORT=... in .env)

First run installs everything; database details are entered on the Setup page in the browser.
"""
import argparse
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
VENV = ROOT / ".venv"
ENV_FILE = ROOT / ".env"
DIST = ROOT / "frontend" / "dist" / "index.html"
IS_WIN = os.name == "nt"
VENV_PY = VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")
STAMP = VENV / ".requirements.sha"
IN_VENV_FLAG = "AWB_DASH_IN_VENV"


def say(msg="", kind=""):
    tag = {"ok": "[ OK ]", "warn": "[WARN]", "err": "[FAIL]", "step": "  >>  "}.get(kind, "      ")
    print(f"{tag} {msg}" if kind else msg, flush=True)


def die(msg, hint=None):
    say(msg, "err")
    if hint:
        for line in hint.strip().splitlines():
            say("       " + line)
    sys.exit(1)


# --------------------------------------------------------------------- stage 1: system python
def ensure_python():
    if sys.version_info < (3, 9):
        die(f"Python 3.9 or newer is needed (found {sys.version.split()[0]}).",
            "Install it from https://www.python.org/downloads/ and run this again.")


def ensure_venv():
    if not VENV_PY.exists():
        say("Creating virtual environment (one time)...", "step")
        try:
            subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
        except subprocess.CalledProcessError:
            shutil.rmtree(VENV, ignore_errors=True)
            die("Could not create the virtual environment.",
                "On Ubuntu/Debian run:  sudo apt install -y python3-venv python3-pip\n"
                "then run this command again.")
    req = (BACKEND / "requirements.txt").read_bytes()
    sha = hashlib.sha256(req).hexdigest()
    if not STAMP.exists() or STAMP.read_text().strip() != sha:
        say("Installing packages (first run takes a minute)...", "step")
        pip = [str(VENV_PY), "-m", "pip", "install", "--disable-pip-version-check"]
        subprocess.call(pip + ["-q", "--upgrade", "pip"])
        if subprocess.call(pip + ["-q", "-r", str(BACKEND / "requirements.txt")]) != 0:
            die("Package installation failed (see the error above).",
                "Usually: no internet / company proxy blocking pypi.org.\n"
                "Behind a proxy, set it first, e.g.  set HTTPS_PROXY=http://proxy:port  (Windows)\n"
                "or  export HTTPS_PROXY=http://proxy:port  (Mac/Linux), then run again.")
        STAMP.write_text(sha)
    say("Python packages ready", "ok")


def relaunch_in_venv():
    env = dict(os.environ, **{IN_VENV_FLAG: "1"})
    cmd = [str(VENV_PY), str(Path(__file__).resolve())] + sys.argv[1:]
    try:
        sys.exit(subprocess.call(cmd, env=env))
    except KeyboardInterrupt:
        sys.exit(0)


# --------------------------------------------------------------------- stage 2: inside venv
def ensure_env_file():
    if not ENV_FILE.exists():
        shutil.copy(ROOT / ".env.example", ENV_FILE)


def check_frontend():
    if DIST.exists():
        say("Frontend build found", "ok")
    else:
        say("frontend/dist is missing - the API will run but the web page won't load.", "warn")
        say("Fix: re-extract the zip, or build it with:  cd frontend && npm install && npm run build")


def check_databases() -> bool:
    sys.path.insert(0, str(BACKEND))
    os.chdir(BACKEND)
    from pymongo import MongoClient  # noqa: E402
    from app import config  # noqa: E402
    from app.mongo_errors import explain  # noqa: E402

    if not config.CONFIGURED:
        say("Databases are not connected yet - this is done on the Setup page in the browser.", "warn")
        return False
    all_ok = True
    for src in config.SOURCES.values():
        name = f"{src.label} ({src.db_name}.{src.collection})"
        if not src.enabled:
            say(f"{name}: not configured in .env", "warn"); all_ok = False; continue
        try:
            c = MongoClient(src.mongo_uri, serverSelectionTimeoutMS=8000, connectTimeoutMS=8000)
            coll = c[src.db_name][src.collection]
            c.admin.command("ping")
            doc = coll.find_one({}, {src.awb_field: 1})
            if doc is None:
                say(f"{name}: connected, but the collection is EMPTY or the name is wrong", "warn")
                existing = c[src.db_name].list_collection_names()[:15]
                say(f"       collections in {src.db_name}: {', '.join(existing) or '(none)'}")
                all_ok = False
            elif src.awb_field not in doc:
                say(f"{name}: connected, but documents have no '{src.awb_field}' field", "warn")
                keys = [k for k in coll.find_one({}).keys()][:25]
                say(f"       fields seen: {', '.join(keys)}")
                say("       fix it on the Settings page in the browser")
                all_ok = False
            else:
                say(f"{name}: connected", "ok")
            c.close()
        except Exception as ex:  # noqa: BLE001
            msg = str(ex).split(", Timeout:")[0][:250]
            say(f"{name}: cannot connect", "err")
            say(f"       {msg}")
            say(f"       -> {explain(msg)}")
            all_ok = False
    return all_ok


def free_port(host: str, port: int) -> int:
    for p in range(port, port + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host if host != "0.0.0.0" else "", p))
                return p
            except OSError:
                if p == port:
                    say(f"Port {port} is busy, trying the next one...", "warn")
    die(f"No free port found between {port} and {port + 19}.")


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "<this-machine-ip>"


def run_server(args, configured: bool):
    import uvicorn  # noqa: E402

    host = args.host or os.getenv("HOST") or ("0.0.0.0" if args.server else "127.0.0.1")
    port = free_port(host, int(args.port or os.getenv("PORT") or (8010 if args.server else 8000)))
    url = f"http://localhost:{port}" + ("" if configured else "/setup")
    say()
    say("=" * 60)
    if args.server:
        say(f"Dashboard is running.  Open in your browser:  http://{lan_ip()}:{port}", "ok")
        say("(if that doesn't open, use the server's public IP and allow the port in the firewall)")
    else:
        say(f"Dashboard is running at  {url}", "ok")
        say("Your browser should open by itself. Keep THIS window open while you use the dashboard.")
        say("To stop: close this window (or press Ctrl+C).")
    if not configured:
        say("First time? The page will ask for your database details (Setup).")
    say("=" * 60)
    say()
    if not args.server and not args.no_browser:
        import threading
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run("app.main:app", host=host, port=port, workers=1, log_level="warning",
                proxy_headers=True, forwarded_allow_ips="*")


def main():
    ap = argparse.ArgumentParser(description="AWB Status Dashboard launcher")
    ap.add_argument("--server", action="store_true", help="bind 0.0.0.0:8010, no browser")
    ap.add_argument("--check", action="store_true", help="only run setup checks")
    ap.add_argument("--host"); ap.add_argument("--port", type=int)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--skip-install", action="store_true", help="don't touch the venv (systemd)")
    args = ap.parse_args()

    if os.getenv(IN_VENV_FLAG) != "1":
        print("\n=== AWB Status Dashboard ===\n")
        ensure_python()
        say(f"Python {sys.version.split()[0]}", "ok")
        if not args.skip_install:
            ensure_venv()
        if Path(sys.prefix).resolve() != VENV.resolve():
            relaunch_in_venv()

    ensure_env_file()
    check_frontend()
    say("Checking database connections...", "step")
    db_ok = check_databases()
    from app import config  # noqa: E402  (imported by check_databases)
    if args.check:
        say()
        say("All checks passed." if db_ok else "Some checks need attention (see above).", "ok" if db_ok else "warn")
        sys.exit(0 if db_ok else 1)
    if config.CONFIGURED and not db_ok:
        say("Starting anyway - fix the database settings on the Settings page.", "warn")
    run_server(args, config.CONFIGURED)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
