from datetime import datetime, timezone

from app.core.config import settings
from app.core.database import db


async def find_nearby_drivers(lng: float, lat: float, vehicle_type: str, limit: int = 10) -> list[dict]:
    cutoff = datetime.now(timezone.utc)
    query = {
        "status": "online",
        "vehicle_type": vehicle_type,
        "expire_at": {"$gt": cutoff},
        "location": {
            "$near": {
                "$geometry": {"type": "Point", "coordinates": [lng, lat]},
                "$maxDistance": settings.MATCH_RADIUS_METERS,
            }
        },
    }
    docs = await db.driver_presence.find(query, {"_id": 0}).limit(limit).to_list(limit)
    return docs
