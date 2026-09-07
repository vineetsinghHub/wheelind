from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.database import db
from app.core.deps import require_roles

router = APIRouter(prefix="/api/riders", tags=["riders"])


class RiderUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    home_address: str | None = None


@router.get("/me")
async def get_my_profile(user: dict = Depends(require_roles("rider"))):
    profile = await db.riders.find_one({"user_id": user["id"]}, {"_id": 0})
    return {"user": user, "profile": profile}


@router.patch("/me")
async def update_my_profile(body: RiderUpdate, user: dict = Depends(require_roles("rider"))):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if updates:
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        await db.riders.update_one({"user_id": user["id"]}, {"$set": updates})
    profile = await db.riders.find_one({"user_id": user["id"]}, {"_id": 0})
    return {"profile": profile}
