from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app.core.database import db
from app.core.deps import require_roles
from app.core.config import settings
from app.core.redis_client import update_driver_location, remove_driver
from app.core.ws import manager
from app.models.enums import VehicleType

router = APIRouter(prefix="/api/presence", tags=["presence"])


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


class GoOnline(BaseModel):
    lng: float
    lat: float
    vehicle_type: str

    @field_validator("vehicle_type")
    @classmethod
    def valid(cls, v):
        if v not in [t.value for t in VehicleType]:
            raise ValueError("invalid vehicle_type")
        return v


class Heartbeat(BaseModel):
    lng: float
    lat: float


async def _driver(user):
    d = await db.drivers.find_one({"user_id": user["id"]}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Driver profile not found")
    return d


@router.post("/online")
async def go_online(body: GoOnline, user: dict = Depends(require_roles("driver"))):
    driver = await _driver(user)
    if driver.get("kyc_status") != "approved":
        raise HTTPException(status_code=403, detail="KYC not approved")
    active_vehicle = await db.vehicles.find_one(
        {"driver_id": driver["id"], "is_active": True, "status": "approved", "vehicle_type": body.vehicle_type}, {"_id": 0}
    )
    if not active_vehicle:
        raise HTTPException(status_code=400, detail="No active approved vehicle of this type")

    expire_at = datetime.now(timezone.utc) + timedelta(seconds=settings.HEARTBEAT_TTL_SECONDS)
    doc = {
        "driver_id": driver["id"],
        "user_id": user["id"],
        "status": "online",
        "vehicle_type": body.vehicle_type,
        "location": {"type": "Point", "coordinates": [body.lng, body.lat]},
        "last_heartbeat": _now_iso(),
        "expire_at": expire_at,
    }
    await db.driver_presence.update_one({"driver_id": driver["id"]}, {"$set": doc}, upsert=True)
    await update_driver_location(driver["id"], user["id"], body.vehicle_type, body.lng, body.lat, "online", settings.HEARTBEAT_TTL_SECONDS)
    return {"status": "online", "expire_in": settings.HEARTBEAT_TTL_SECONDS}


@router.post("/heartbeat")
async def heartbeat(body: Heartbeat, user: dict = Depends(require_roles("driver"))):
    driver = await _driver(user)
    presence = await db.driver_presence.find_one({"driver_id": driver["id"]}, {"_id": 0})
    if not presence:
        raise HTTPException(status_code=400, detail="Driver is offline; go online first")
    expire_at = datetime.now(timezone.utc) + timedelta(seconds=settings.HEARTBEAT_TTL_SECONDS)
    await db.driver_presence.update_one(
        {"driver_id": driver["id"]},
        {"$set": {"location": {"type": "Point", "coordinates": [body.lng, body.lat]}, "last_heartbeat": _now_iso(), "expire_at": expire_at}},
    )
    await update_driver_location(driver["id"], user["id"], presence["vehicle_type"], body.lng, body.lat, presence.get("status", "online"), settings.HEARTBEAT_TTL_SECONDS)
    return {"status": presence["status"], "expire_in": settings.HEARTBEAT_TTL_SECONDS}


@router.post("/offline")
async def go_offline(user: dict = Depends(require_roles("driver"))):
    driver = await _driver(user)
    await db.driver_presence.delete_one({"driver_id": driver["id"]})
    await remove_driver(driver["id"])
    return {"status": "offline"}


@router.get("/me")
async def my_presence(user: dict = Depends(require_roles("driver"))):
    driver = await _driver(user)
    presence = await db.driver_presence.find_one({"driver_id": driver["id"]}, {"_id": 0})
    return {"presence": presence or {"status": "offline"}}
