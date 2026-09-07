import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, field_validator

from app.core.database import db
from app.core.deps import require_roles
from app.core.security import hash_password
from app.core.audit import audit_log

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _now():
    return datetime.now(timezone.utc).isoformat()


class DocReview(BaseModel):
    status: str  # approved | rejected
    reason: str | None = None

    @field_validator("status")
    @classmethod
    def valid(cls, v):
        if v not in ("approved", "rejected"):
            raise ValueError("status must be approved or rejected")
        return v


class KycDecision(BaseModel):
    status: str  # approved | rejected
    reason: str | None = None

    @field_validator("status")
    @classmethod
    def valid(cls, v):
        if v not in ("approved", "rejected"):
            raise ValueError("status must be approved or rejected")
        return v


class AdminCreate(BaseModel):
    email: EmailStr
    password: str
    name: str


# ---------- Dashboard ----------
@router.get("/dashboard")
async def dashboard(admin: dict = Depends(require_roles("admin"))):
    return {
        "riders": await db.riders.count_documents({}),
        "drivers": await db.drivers.count_documents({}),
        "drivers_online": await db.driver_presence.count_documents({"status": "online"}),
        "kyc_pending": await db.drivers.count_documents({"kyc_status": "submitted"}),
        "rides_total": await db.rides.count_documents({}),
        "rides_active": await db.rides.count_documents(
            {"status": {"$in": ["searching", "driver_assigned", "arrived", "trip_started", "in_progress"]}}
        ),
        "rides_completed": await db.rides.count_documents({"status": "completed"}),
    }


# ---------- Users / RBAC ----------
@router.get("/users")
async def list_users(role: str | None = None, admin: dict = Depends(require_roles("admin"))):
    q = {"role": role} if role else {}
    users = await db.users.find(q, {"_id": 0, "password_hash": 0}).to_list(500)
    return users


@router.post("/admins")
async def create_admin(body: AdminCreate, admin: dict = Depends(require_roles("admin"))):
    email = body.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already exists")
    user_id = str(uuid.uuid4())
    await db.users.insert_one(
        {"id": user_id, "email": email, "password_hash": hash_password(body.password), "name": body.name, "role": "admin", "status": "active", "created_at": _now()}
    )
    await audit_log("admin.create", admin["id"], "admin", "user", user_id, {"email": email})
    return {"id": user_id, "email": email, "role": "admin"}


@router.post("/users/{user_id}/ban")
async def ban_user(user_id: str, admin: dict = Depends(require_roles("admin"))):
    res = await db.users.update_one({"id": user_id}, {"$set": {"status": "banned"}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="User not found")
    await audit_log("user.ban", admin["id"], "admin", "user", user_id)
    return {"message": "User banned"}


@router.post("/users/{user_id}/unban")
async def unban_user(user_id: str, admin: dict = Depends(require_roles("admin"))):
    await db.users.update_one({"id": user_id}, {"$set": {"status": "active"}})
    await audit_log("user.unban", admin["id"], "admin", "user", user_id)
    return {"message": "User unbanned"}


# ---------- KYC review ----------
@router.get("/kyc/pending")
async def kyc_pending(admin: dict = Depends(require_roles("admin"))):
    drivers = await db.drivers.find({"kyc_status": "submitted"}, {"_id": 0}).to_list(200)
    for d in drivers:
        d["documents"] = await db.documents.find({"owner_id": d["user_id"]}, {"_id": 0}).to_list(50)
        d["vehicles"] = await db.vehicles.find({"driver_id": d["id"]}, {"_id": 0}).to_list(50)
    return drivers


@router.post("/documents/{doc_id}/review")
async def review_document(doc_id: str, body: DocReview, admin: dict = Depends(require_roles("admin"))):
    doc = await db.documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.documents.update_one(
        {"id": doc_id}, {"$set": {"status": body.status, "review_reason": body.reason, "reviewed_at": _now(), "reviewed_by": admin["id"]}}
    )
    await audit_log("document.review", admin["id"], "admin", "document", doc_id, {"status": body.status})
    return {"message": "Document reviewed", "status": body.status}


@router.post("/vehicles/{vehicle_id}/review")
async def review_vehicle(vehicle_id: str, body: DocReview, admin: dict = Depends(require_roles("admin"))):
    res = await db.vehicles.update_one(
        {"id": vehicle_id}, {"$set": {"status": body.status, "review_reason": body.reason, "reviewed_at": _now()}}
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return {"message": "Vehicle reviewed", "status": body.status}


@router.post("/drivers/{driver_id}/kyc")
async def decide_kyc(driver_id: str, body: KycDecision, admin: dict = Depends(require_roles("admin"))):
    driver = await db.drivers.find_one({"id": driver_id}, {"_id": 0})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    await db.drivers.update_one(
        {"id": driver_id}, {"$set": {"kyc_status": body.status, "kyc_reason": body.reason, "kyc_reviewed_at": _now(), "kyc_reviewed_by": admin["id"]}}
    )
    await audit_log("driver.kyc", admin["id"], "admin", "driver", driver_id, {"status": body.status})
    return {"message": f"KYC {body.status}", "driver_id": driver_id}


# ---------- Audit ----------
@router.get("/audit-logs")
async def audit_logs(limit: int = 100, admin: dict = Depends(require_roles("admin"))):
    return await db.audit_logs.find({}, {"_id": 0}).sort("created_at", -1).to_list(min(limit, 500))
