import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.database import db
from app.core.deps import get_current_user
from app.core.security import create_access_token, generate_otp, verify_password
from app.core.config import settings
from app.core.audit import audit_log
from app.integrations.stubs import sms
from app.models.enums import Role
from app.services.wallet_service import get_or_create_wallet

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _now():
    return datetime.now(timezone.utc).isoformat()


class OtpRequest(BaseModel):
    phone: str = Field(min_length=8, max_length=20)
    role: str

    @field_validator("role")
    @classmethod
    def valid_role(cls, v):
        if v not in ("rider", "driver"):
            raise ValueError("role must be rider or driver")
        return v


class OtpVerify(BaseModel):
    phone: str
    code: str = Field(min_length=4, max_length=6)
    role: str
    name: str | None = None


class AdminLogin(BaseModel):
    email: EmailStr
    password: str


@router.post("/otp/request")
async def request_otp(body: OtpRequest):
    code = generate_otp()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.OTP_TTL_SECONDS)
    await db.otp_codes.delete_many({"phone": body.phone, "role": body.role})
    await db.otp_codes.insert_one(
        {
            "id": str(uuid.uuid4()),
            "phone": body.phone,
            "role": body.role,
            "code": code,
            "expires_at": expires_at,
            "consumed": False,
            "created_at": _now(),
        }
    )
    await sms.send_otp(body.phone, code)
    resp = {"message": "OTP sent", "expires_in": settings.OTP_TTL_SECONDS}
    if settings.OTP_DEBUG:
        resp["debug_code"] = code
    return resp


@router.post("/otp/verify")
async def verify_otp(body: OtpVerify):
    if body.role not in ("rider", "driver"):
        raise HTTPException(status_code=400, detail="role must be rider or driver")

    otp = await db.otp_codes.find_one({"phone": body.phone, "role": body.role, "consumed": False})
    if not otp or otp["code"] != body.code:
        raise HTTPException(status_code=400, detail="Invalid OTP")
    expires = otp["expires_at"]
    if isinstance(expires, str):
        expires = datetime.fromisoformat(expires)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="OTP expired")

    await db.otp_codes.update_one({"id": otp["id"]}, {"$set": {"consumed": True}})

    user = await db.users.find_one({"phone": body.phone, "role": body.role}, {"_id": 0})
    created = False
    if not user:
        created = True
        user_id = str(uuid.uuid4())
        user = {
            "id": user_id,
            "phone": body.phone,
            "role": body.role,
            "name": body.name or "",
            "status": "active",
            "phone_verified": True,
            "created_at": _now(),
        }
        await db.users.insert_one(dict(user))
        await get_or_create_wallet(user_id)
        if body.role == "rider":
            await db.riders.insert_one(
                {"id": str(uuid.uuid4()), "user_id": user_id, "name": body.name or "", "rating": 5.0, "total_trips": 0, "created_at": _now()}
            )
        else:
            await db.drivers.insert_one(
                {
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "name": body.name or "",
                    "rating": 5.0,
                    "total_trips": 0,
                    "kyc_status": "pending",
                    "is_available": False,
                    "created_at": _now(),
                }
            )
        await audit_log("user.register", user_id, body.role, "user", user_id, {"phone": body.phone})

    user.pop("_id", None)
    token = create_access_token(user["id"], user["role"])
    await audit_log("auth.otp_login", user["id"], user["role"], "user", user["id"])
    return {"access_token": token, "token_type": "bearer", "user": user, "created": created}


@router.post("/admin/login")
async def admin_login(body: AdminLogin):
    email = body.email.lower()
    user = await db.users.find_one({"email": email, "role": "admin"})
    if not user or not verify_password(body.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(user["id"], "admin")
    user.pop("_id", None)
    user.pop("password_hash", None)
    await audit_log("auth.admin_login", user["id"], "admin", "user", user["id"])
    return {"access_token": token, "token_type": "bearer", "user": user}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    profile = None
    if user["role"] == "rider":
        profile = await db.riders.find_one({"user_id": user["id"]}, {"_id": 0})
    elif user["role"] == "driver":
        profile = await db.drivers.find_one({"user_id": user["id"]}, {"_id": 0})
    return {"user": user, "profile": profile}
