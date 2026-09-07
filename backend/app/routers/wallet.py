import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.database import db
from app.core.deps import get_current_user, require_roles
from app.core.audit import audit_log
from app.integrations.stubs import payment
from app.services.wallet_service import get_or_create_wallet, post_transaction

router = APIRouter(prefix="/api", tags=["wallet"])


def _now():
    return datetime.now(timezone.utc).isoformat()


class TopUp(BaseModel):
    amount: float = Field(gt=0, le=100000)


class Subscribe(BaseModel):
    plan: str = "zero_commission"
    days: int = Field(default=30, ge=1, le=365)


# ---------- Wallet (rider & driver share the pattern) ----------
@router.get("/wallet")
async def get_wallet(user: dict = Depends(get_current_user)):
    return await get_or_create_wallet(user["id"])


@router.post("/wallet/topup")
async def topup(body: TopUp, user: dict = Depends(get_current_user)):
    order = await payment.create_order(body.amount)  # stub gateway
    await payment.capture(order["order_id"])
    txn = await post_transaction(user["id"], body.amount, "credit", "wallet_topup", "payment_order", order["order_id"], "Wallet top-up")
    await audit_log("wallet.topup", user["id"], user["role"], "wallet", txn["wallet_id"], {"amount": body.amount})
    return {"order": order, "transaction": txn}


@router.get("/wallet/transactions")
async def transactions(user: dict = Depends(get_current_user)):
    wallet = await get_or_create_wallet(user["id"])
    return await db.transactions.find({"wallet_id": wallet["id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)


# ---------- Driver earnings & payouts ----------
@router.get("/driver/earnings")
async def driver_earnings(user: dict = Depends(require_roles("driver"))):
    d = await db.drivers.find_one({"user_id": user["id"]}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Driver profile not found")
    records = await db.driver_earnings.find({"driver_id": d["id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)
    summary = {
        "trips": len(records),
        "gross": round(sum(r["gross_fare"] for r in records), 2),
        "commission": round(sum(r["commission_amount"] for r in records), 2),
        "net": round(sum(r["net_earning"] for r in records), 2),
        "pending_payout": round(sum(r["net_earning"] for r in records if r.get("payout_status") == "pending"), 2),
    }
    return {"summary": summary, "records": records}


@router.post("/driver/subscriptions")
async def subscribe(body: Subscribe, user: dict = Depends(require_roles("driver"))):
    d = await db.drivers.find_one({"user_id": user["id"]}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Driver profile not found")
    await db.driver_subscriptions.update_many({"driver_id": d["id"], "active": True}, {"$set": {"active": False}})
    sub = {
        "id": str(uuid.uuid4()),
        "driver_id": d["id"],
        "plan": body.plan,
        "active": True,
        "starts_at": _now(),
        "ends_at": (datetime.now(timezone.utc) + timedelta(days=body.days)).isoformat(),
        "created_at": _now(),
    }
    await db.driver_subscriptions.insert_one(dict(sub))
    await audit_log("driver.subscribe", user["id"], "driver", "subscription", sub["id"], {"plan": body.plan})
    sub.pop("_id", None)
    return sub


@router.get("/driver/subscriptions")
async def my_subscriptions(user: dict = Depends(require_roles("driver"))):
    d = await db.drivers.find_one({"user_id": user["id"]}, {"_id": 0})
    return await db.driver_subscriptions.find({"driver_id": d["id"]}, {"_id": 0}).sort("created_at", -1).to_list(50)


# ---------- Admin payouts ----------
@router.get("/admin/payouts")
async def list_payouts(admin: dict = Depends(require_roles("admin"))):
    pipeline = [
        {"$match": {"payout_status": "pending"}},
        {"$group": {"_id": "$driver_id", "amount": {"$sum": "$net_earning"}, "trips": {"$sum": 1}}},
    ]
    rows = await db.driver_earnings.aggregate(pipeline).to_list(500)
    return [{"driver_id": r["_id"], "pending_amount": round(r["amount"], 2), "trips": r["trips"]} for r in rows]


@router.post("/admin/payouts/{driver_id}/settle")
async def settle_payout(driver_id: str, admin: dict = Depends(require_roles("admin"))):
    res = await db.driver_earnings.update_many(
        {"driver_id": driver_id, "payout_status": "pending"}, {"$set": {"payout_status": "paid", "paid_at": _now()}}
    )
    await audit_log("payout.settle", admin["id"], "admin", "driver", driver_id, {"records": res.modified_count})
    return {"message": "Payout settled", "records": res.modified_count}
