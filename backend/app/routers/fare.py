import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.core.database import db
from app.core.deps import get_current_user, require_roles
from app.core.audit import audit_log
from app.models.enums import VehicleType
from app.services.fare_service import get_active_config, compute_breakup

router = APIRouter(prefix="/api", tags=["fare"])


def _now():
    return datetime.now(timezone.utc).isoformat()


class FareEstimate(BaseModel):
    city: str = "Bangalore"
    vehicle_type: str
    distance_km: float = Field(ge=0)
    duration_min: float = Field(ge=0)


class FareConfigCreate(BaseModel):
    city: str
    vehicle_type: str
    base_fare: float = Field(ge=0)
    per_km: float = Field(ge=0)
    per_min: float = Field(ge=0)
    min_fare: float = Field(ge=0)
    booking_fee: float = Field(default=0, ge=0)
    surge_multiplier: float = Field(default=1.0, ge=1.0)
    tax_percent: float = Field(default=0, ge=0)
    commission_percent: float = Field(default=20.0, ge=0, le=100)
    currency: str = "INR"

    @field_validator("vehicle_type")
    @classmethod
    def valid(cls, v):
        if v not in [t.value for t in VehicleType]:
            raise ValueError("invalid vehicle_type")
        return v


@router.post("/fare/estimate")
async def estimate(body: FareEstimate, user: dict = Depends(get_current_user)):
    config = await get_active_config(body.city, body.vehicle_type)
    if not config:
        raise HTTPException(status_code=400, detail="No active fare config")
    return compute_breakup(config, body.distance_km, body.duration_min)


# ---------- Admin fare configuration (versioned + auditable) ----------
@router.post("/admin/fare-configs")
async def create_fare_config(body: FareConfigCreate, admin: dict = Depends(require_roles("admin"))):
    prev = await db.fare_configs.find({"city": body.city, "vehicle_type": body.vehicle_type}).sort("version", -1).to_list(1)
    version = (prev[0]["version"] + 1) if prev else 1
    # deactivate older active versions
    await db.fare_configs.update_many(
        {"city": body.city, "vehicle_type": body.vehicle_type, "active": True}, {"$set": {"active": False}}
    )
    config = {
        "id": str(uuid.uuid4()),
        **body.model_dump(),
        "version": version,
        "active": True,
        "created_by": admin["id"],
        "created_at": _now(),
    }
    await db.fare_configs.insert_one(dict(config))
    await audit_log("fare_config.create", admin["id"], "admin", "fare_config", config["id"], {"city": body.city, "version": version})
    config.pop("_id", None)
    return config


@router.get("/admin/fare-configs")
async def list_fare_configs(city: str | None = None, admin: dict = Depends(require_roles("admin"))):
    q = {"city": city} if city else {}
    return await db.fare_configs.find(q, {"_id": 0}).sort([("city", 1), ("vehicle_type", 1), ("version", -1)]).to_list(500)


@router.post("/admin/fare-configs/{config_id}/activate")
async def activate_config(config_id: str, admin: dict = Depends(require_roles("admin"))):
    config = await db.fare_configs.find_one({"id": config_id}, {"_id": 0})
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    await db.fare_configs.update_many(
        {"city": config["city"], "vehicle_type": config["vehicle_type"], "active": True}, {"$set": {"active": False}}
    )
    await db.fare_configs.update_one({"id": config_id}, {"$set": {"active": True}})
    await audit_log("fare_config.activate", admin["id"], "admin", "fare_config", config_id)
    return {"message": "Activated", "config_id": config_id}
