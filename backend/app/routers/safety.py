import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.database import db
from app.core.deps import get_current_user, require_roles
from app.core.audit import audit_log
from app.integrations.stubs import masked_calling, push
from app.services.wallet_service import post_transaction

router = APIRouter(prefix="/api", tags=["safety-support"])


def _now():
    return datetime.now(timezone.utc).isoformat()


class SosCreate(BaseModel):
    ride_id: str
    lng: float
    lat: float
    note: str | None = None


class DisputeCreate(BaseModel):
    ride_id: str
    reason: str
    description: str | None = None


class DisputeResolve(BaseModel):
    resolution: str  # refund | reject
    refund_amount: float | None = None
    note: str | None = None


# ---------- SOS ----------
@router.post("/sos")
async def raise_sos(body: SosCreate, user: dict = Depends(get_current_user)):
    ride = await db.rides.find_one({"id": body.ride_id}, {"_id": 0})
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    sos = {
        "id": str(uuid.uuid4()),
        "ride_id": body.ride_id,
        "raised_by": user["id"],
        "role": user["role"],
        "location": {"type": "Point", "coordinates": [body.lng, body.lat]},
        "note": body.note,
        "status": "open",
        "created_at": _now(),
    }
    await db.sos_alerts.insert_one(dict(sos))
    await push.notify(user["id"], "SOS registered", "Safety team notified")
    await audit_log("sos.raise", user["id"], user["role"], "ride", body.ride_id)
    sos.pop("_id", None)
    return sos


@router.get("/admin/sos")
async def list_sos(admin: dict = Depends(require_roles("admin"))):
    return await db.sos_alerts.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)


# ---------- Masked calling ----------
@router.post("/rides/{ride_id}/call")
async def masked_call(ride_id: str, user: dict = Depends(get_current_user)):
    ride = await db.rides.find_one({"id": ride_id}, {"_id": 0})
    if not ride or not ride.get("driver_user_id"):
        raise HTTPException(status_code=400, detail="No driver assigned")
    rider = await db.users.find_one({"id": ride["rider_id"]}, {"_id": 0})
    driver = await db.users.find_one({"id": ride["driver_user_id"]}, {"_id": 0})
    session = await masked_calling.create_session(rider.get("phone", ""), driver.get("phone", ""))
    return session


# ---------- Disputes & refunds ----------
@router.post("/disputes")
async def create_dispute(body: DisputeCreate, user: dict = Depends(get_current_user)):
    ride = await db.rides.find_one({"id": body.ride_id}, {"_id": 0})
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    dispute = {
        "id": str(uuid.uuid4()),
        "ride_id": body.ride_id,
        "raised_by": user["id"],
        "role": user["role"],
        "reason": body.reason,
        "description": body.description,
        "status": "open",
        "created_at": _now(),
    }
    await db.disputes.insert_one(dict(dispute))
    await audit_log("dispute.create", user["id"], user["role"], "ride", body.ride_id)
    dispute.pop("_id", None)
    return dispute


@router.get("/admin/disputes")
async def list_disputes(admin: dict = Depends(require_roles("admin"))):
    return await db.disputes.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)


@router.post("/admin/disputes/{dispute_id}/resolve")
async def resolve_dispute(dispute_id: str, body: DisputeResolve, admin: dict = Depends(require_roles("admin"))):
    dispute = await db.disputes.find_one({"id": dispute_id}, {"_id": 0})
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")
    refund_txn = None
    if body.resolution == "refund" and body.refund_amount and body.refund_amount > 0:
        ride = await db.rides.find_one({"id": dispute["ride_id"]}, {"_id": 0})
        refund_txn = await post_transaction(
            ride["rider_id"], body.refund_amount, "credit", "refund", "ride", dispute["ride_id"], "Dispute refund"
        )
    await db.disputes.update_one(
        {"id": dispute_id},
        {"$set": {"status": "resolved", "resolution": body.resolution, "refund_amount": body.refund_amount, "note": body.note, "resolved_by": admin["id"], "resolved_at": _now()}},
    )
    await audit_log("dispute.resolve", admin["id"], "admin", "dispute", dispute_id, {"resolution": body.resolution})
    return {"message": "Dispute resolved", "refund": refund_txn}
