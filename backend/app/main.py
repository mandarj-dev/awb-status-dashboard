import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pymongo.errors import PyMongoError

from . import config, db, settings_store, status_map
from .routers import awb, open_cases, setup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings_store.ensure_env_file()
    yield
    db.close_all()


app = FastAPI(title=config.APP_TITLE, lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


def require_configured():
    if not config.CONFIGURED:
        raise HTTPException(503, "Setup required: open the Setup page to connect your databases.")


app.include_router(setup.router)
app.include_router(awb.router, dependencies=[Depends(require_configured)])
app.include_router(open_cases.router, dependencies=[Depends(require_configured)])


@app.exception_handler(PyMongoError)
async def mongo_error(_, exc: PyMongoError):
    logging.getLogger("mongo").exception("Mongo error")
    return JSONResponse(status_code=503, content={"detail": f"Database error: {str(exc)[:300]}"})


@app.get("/api/health")
async def health():
    if not config.CONFIGURED:
        return {"ok": True, "configured": False, "sources": {}}
    return {"ok": True, "configured": True, "sources": await db.ping_all()}


@app.get("/api/config")
async def public_config():
    return {
        "title": config.APP_TITLE,
        "configured": config.CONFIGURED,
        "max_awbs": config.MAX_AWBS_PER_REQUEST,
        "sources": {k: {"label": s.label, "enabled": s.enabled} for k, s in config.SOURCES.items()},
        "open_lookback_days": config.OPEN_LOOKBACK_DAYS,
        "closed_statuses": [f"{c['label'] or 'Status'} ({c['code']})" for c in status_map.closed_summary()]
                           + config.OPEN_EXCLUDE_STATUSES,
        "status_mapping": status_map.table(),
        "status_mapping_error": status_map.LOAD_ERROR,
    }


# ---- serve the built Vue app (frontend/dist) from the same port
dist = Path(config.FRONTEND_DIST)
if dist.is_dir():
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        f = dist / full_path
        if full_path and f.is_file() and dist in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(dist / "index.html")
