from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.database import db
from app.core.deps import require_roles

router = APIRouter(prefix="/api/drivers", tags=["drivers"])


class DriverUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    city: str | None = None


@router.get("/me")
async def get_my_profile(user: dict = Depends(require_roles("driver"))):
    profile = await db.drivers.find_one({"user_id": user["id"]}, {"_id": 0})
    presence = await db.driver_presence.find_one({"driver_id": profile["id"]}, {"_id": 0}) if profile else None
    return {"user": user, "profile": profile, "presence": presence}


@router.patch("/me")
async def update_my_profile(body: DriverUpdate, user: dict = Depends(require_roles("driver"))):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates:
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        await db.drivers.update_one({"user_id": user["id"]}, {"$set": updates})
    profile = await db.drivers.find_one({"user_id": user["id"]}, {"_id": 0})
    return {"profile": profile}


async def get_driver_profile(user: dict) -> dict:
    profile = await db.drivers.find_one({"user_id": user["id"]}, {"_id": 0})
    if not profile:
        raise HTTPException(status_code=404, detail="Driver profile not found")
    return profile
