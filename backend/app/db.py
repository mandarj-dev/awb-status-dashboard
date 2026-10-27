from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

from . import config

_clients: dict[str, AsyncIOMotorClient] = {}


def get_client(uri: str) -> AsyncIOMotorClient:
    if uri not in _clients:
        _clients[uri] = AsyncIOMotorClient(
            uri,
            serverSelectionTimeoutMS=config.MONGO_TIMEOUT_MS,
            readPreference=config.MONGO_READ_PREFERENCE,
            appname="awb-status-dashboard",
            maxPoolSize=20,
        )
    return _clients[uri]


def get_collection(src: config.SourceConfig) -> AsyncIOMotorCollection:
    return get_client(src.mongo_uri)[src.db_name][src.collection]


async def ping_all() -> dict:
    out = {}
    for key, src in config.SOURCES.items():
        if not src.enabled:
            out[key] = {"ok": False, "error": "not configured"}
            continue
        try:
            await get_client(src.mongo_uri).admin.command("ping")
            out[key] = {"ok": True, "db": src.db_name, "collection": src.collection}
        except Exception as e:  # noqa: BLE001
            out[key] = {"ok": False, "error": str(e)[:300]}
    return out


def close_all() -> None:
    for c in _clients.values():
        c.close()
    _clients.clear()
