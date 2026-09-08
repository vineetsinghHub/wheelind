import logging

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger("wheelind.redis")

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


async def redis_available() -> bool:
    try:
        r = await get_redis()
        await r.ping()
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("redis unavailable: %s", e)
        return False


def _geo_key(vt: str) -> str:
    return f"drivers:geo:{vt}"


def _hb_key(driver_id: str) -> str:
    return f"driver:hb:{driver_id}"


def _hash_key(driver_id: str) -> str:
    return f"driver:{driver_id}"


def _path_key(ride_id: str) -> str:
    return f"trip:path:{ride_id}"


async def update_driver_location(driver_id, user_id, vehicle_type, lng, lat, status, ttl):
    try:
        r = await get_redis()
        pipe = r.pipeline()
        pipe.geoadd(_geo_key(vehicle_type), (lng, lat, driver_id))
        pipe.hset(
            _hash_key(driver_id),
            mapping={"user_id": user_id, "vehicle_type": vehicle_type, "lng": lng, "lat": lat, "status": status},
        )
        pipe.set(_hb_key(driver_id), status, ex=ttl)
        await pipe.execute()
    except Exception as e:  # noqa: BLE001
        logger.warning("redis update_driver_location failed: %s", e)


async def set_driver_status(driver_id, status):
    try:
        r = await get_redis()
        await r.hset(_hash_key(driver_id), "status", status)
        if await r.exists(_hb_key(driver_id)):
            await r.set(_hb_key(driver_id), status, keepttl=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("redis set_driver_status failed: %s", e)


async def remove_driver(driver_id):
    try:
        r = await get_redis()
        h = await r.hgetall(_hash_key(driver_id))
        vt = h.get("vehicle_type")
        if vt:
            await r.zrem(_geo_key(vt), driver_id)
        await r.delete(_hb_key(driver_id), _hash_key(driver_id))
    except Exception as e:  # noqa: BLE001
        logger.warning("redis remove_driver failed: %s", e)


async def find_nearby(vehicle_type, lng, lat, radius_m, count):
    """Returns nearest ONLINE drivers from the Redis hot layer. Raises on redis error."""
    r = await get_redis()
    res = await r.geosearch(
        _geo_key(vehicle_type),
        longitude=lng,
        latitude=lat,
        radius=radius_m,
        unit="m",
        sort="ASC",
        count=count,
        withdist=True,
        withcoord=True,
    )
    out = []
    for item in res:
        name, dist, coord = item[0], item[1], item[2]
        status = await r.get(_hb_key(name))
        if status is None:
            await r.zrem(_geo_key(vehicle_type), name)  # prune stale/expired
            continue
        if status != "online":
            continue
        h = await r.hgetall(_hash_key(name))
        out.append(
            {
                "driver_id": name,
                "user_id": h.get("user_id"),
                "vehicle_type": vehicle_type,
                "distance_m": round(float(dist), 1),
                "location": {"type": "Point", "coordinates": [float(coord[0]), float(coord[1])]},
            }
        )
    return out


async def push_trip_point(ride_id, lng, lat, ts):
    try:
        import json

        r = await get_redis()
        await r.rpush(_path_key(ride_id), json.dumps({"lng": lng, "lat": lat, "ts": ts}))
    except Exception as e:  # noqa: BLE001
        logger.warning("redis push_trip_point failed: %s", e)


async def get_trip_path(ride_id):
    try:
        import json

        r = await get_redis()
        items = await r.lrange(_path_key(ride_id), 0, -1)
        return [json.loads(i) for i in items]
    except Exception:  # noqa: BLE001
        return []


async def clear_trip_path(ride_id):
    try:
        r = await get_redis()
        await r.delete(_path_key(ride_id))
    except Exception:  # noqa: BLE001
        pass


async def close_redis():
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
