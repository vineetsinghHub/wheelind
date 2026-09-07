import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.core.database import db
from app.core.deps import require_roles
from app.models.enums import VehicleType

router = APIRouter(prefix="/api/vehicles", tags=["vehicles"])


def _now():
    return datetime.now(timezone.utc).isoformat()


class VehicleCreate(BaseModel):
    vehicle_type: str
    make: str
    model: str
    plate_number: str = Field(min_length=3, max_length=20)
    color: str | None = None
    year: int | None = None

    @field_validator("vehicle_type")
    @classmethod
    def valid_type(cls, v):
        if v not in [t.value for t in VehicleType]:
            raise ValueError("invalid vehicle_type")
        return v


async def _driver(user):
    d = await db.drivers.find_one({"user_id": user["id"]}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Driver profile not found")
    return d


@router.post("")
async def add_vehicle(body: VehicleCreate, user: dict = Depends(require_roles("driver"))):
    driver = await _driver(user)
    vehicle = {
        "id": str(uuid.uuid4()),
        "driver_id": driver["id"],
        "vehicle_type": body.vehicle_type,
        "make": body.make,
        "model": body.model,
        "plate_number": body.plate_number.upper(),
        "color": body.color,
        "year": body.year,
        "status": "pending",  # pending -> approved -> rejected
        "is_active": False,
        "created_at": _now(),
    }
    await db.vehicles.insert_one(dict(vehicle))
    vehicle.pop("_id", None)
    return vehicle


@router.get("")
async def list_vehicles(user: dict = Depends(require_roles("driver"))):
    driver = await _driver(user)
    return await db.vehicles.find({"driver_id": driver["id"]}, {"_id": 0}).to_list(100)


@router.post("/{vehicle_id}/activate")
async def activate_vehicle(vehicle_id: str, user: dict = Depends(require_roles("driver"))):
    driver = await _driver(user)
    vehicle = await db.vehicles.find_one({"id": vehicle_id, "driver_id": driver["id"]}, {"_id": 0})
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    if vehicle["status"] != "approved":
        raise HTTPException(status_code=400, detail="Vehicle not approved by admin")
    await db.vehicles.update_many({"driver_id": driver["id"]}, {"$set": {"is_active": False}})
    await db.vehicles.update_one({"id": vehicle_id}, {"$set": {"is_active": True}})
    return {"message": "Vehicle activated", "vehicle_id": vehicle_id}
