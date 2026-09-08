import logging

from app.core.config import settings
from app.core.database import db
from app.core.redis_client import find_nearby as redis_find_nearby, redis_available

logger = logging.getLogger("wheelind.matching")


async def find_nearby_drivers(lng: float, lat: float, vehicle_type: str, limit: int = 10) -> list[dict]:
    """Nearest online drivers. Redis hot layer is source-of-truth for live location;
    falls back to MongoDB 2dsphere if Redis is unavailable."""
    try:
        if await redis_available():
            return await redis_find_nearby(vehicle_type, lng, lat, settings.MATCH_RADIUS_METERS, limit)
    except Exception as e:  # noqa: BLE001
        logger.warning("redis matching failed, falling back to mongo: %s", e)

    from datetime import datetime, timezone

    query = {
        "status": "online",
        "vehicle_type": vehicle_type,
        "expire_at": {"$gt": datetime.now(timezone.utc)},
        "location": {
            "$near": {
                "$geometry": {"type": "Point", "coordinates": [lng, lat]},
                "$maxDistance": settings.MATCH_RADIUS_METERS,
            }
        },
    }
    return await db.driver_presence.find(query, {"_id": 0}).limit(limit).to_list(limit)
