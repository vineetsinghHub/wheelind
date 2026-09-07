import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.core.database import db
from app.core.deps import get_current_user, require_roles
from app.core.audit import audit_log
from app.services.wallet_service import post_transaction

router = APIRouter(prefix="/api", tags=["promotions"])


def _now():
    return datetime.now(timezone.utc).isoformat()


class PromoCreate(BaseModel):
    code: str = Field(min_length=3, max_length=20)
    title: str
    target: str = "rider"  # rider | driver
    reward_type: str = "cashback"  # cashback | incentive
    amount: float = Field(gt=0)
    max_redemptions: int = Field(default=1000, ge=1)
    budget: float = Field(gt=0)
    active: bool = True

    @field_validator("target")
    @classmethod
    def vt(cls, v):
        if v not in ("rider", "driver"):
            raise ValueError("target must be rider or driver")
        return v


@router.post("/admin/promotions")
async def create_promo(body: PromoCreate, admin: dict = Depends(require_roles("admin"))):
    if await db.promotions.find_one({"code": body.code.upper()}):
        raise HTTPException(status_code=400, detail="Promo code exists")
    promo = {
        "id": str(uuid.uuid4()),
        "code": body.code.upper(),
        **body.model_dump(exclude={"code"}),
        "spent": 0.0,
        "redemptions": 0,
        "created_by": admin["id"],
        "created_at": _now(),
    }
    await db.promotions.insert_one(dict(promo))
    await audit_log("promo.create", admin["id"], "admin", "promotion", promo["id"], {"code": promo["code"]})
    promo.pop("_id", None)
    return promo


@router.get("/promotions")
async def list_active_promos(user: dict = Depends(get_current_user)):
    return await db.promotions.find({"active": True, "target": user["role"]}, {"_id": 0, "budget": 0, "spent": 0}).to_list(100)


@router.get("/admin/promotions")
async def admin_list_promos(admin: dict = Depends(require_roles("admin"))):
    return await db.promotions.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)


@router.post("/promotions/{code}/redeem")
async def redeem_promo(code: str, user: dict = Depends(get_current_user)):
    promo = await db.promotions.find_one({"code": code.upper(), "active": True}, {"_id": 0})
    if not promo:
        raise HTTPException(status_code=404, detail="Promo not found or inactive")
    if promo["target"] != user["role"]:
        raise HTTPException(status_code=400, detail="Promo not applicable")
    if await db.promo_redemptions.find_one({"promo_id": promo["id"], "user_id": user["id"]}):
        raise HTTPException(status_code=400, detail="Already redeemed")
    if promo["redemptions"] >= promo["max_redemptions"] or promo["spent"] + promo["amount"] > promo["budget"]:
        raise HTTPException(status_code=400, detail="Promo budget/limit exhausted")

    txn = await post_transaction(
        user["id"], promo["amount"], "credit",
        "cashback" if promo["reward_type"] == "cashback" else "driver_earning",
        "promotion", promo["id"], f"Promo {promo['code']}",
    )
    await db.promo_redemptions.insert_one(
        {"id": str(uuid.uuid4()), "promo_id": promo["id"], "user_id": user["id"], "amount": promo["amount"], "created_at": _now()}
    )
    await db.promotions.update_one({"id": promo["id"]}, {"$inc": {"redemptions": 1, "spent": promo["amount"]}})
    await audit_log("promo.redeem", user["id"], user["role"], "promotion", promo["id"])
    return {"message": "Promo redeemed", "transaction": txn}
