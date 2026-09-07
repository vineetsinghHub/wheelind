import uuid
from datetime import datetime, timezone

from fastapi import HTTPException

from app.core.database import db


def _now():
    return datetime.now(timezone.utc).isoformat()


async def get_or_create_wallet(user_id: str) -> dict:
    wallet = await db.wallets.find_one({"user_id": user_id}, {"_id": 0})
    if wallet:
        return wallet
    wallet = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "balance": 0.0,
        "currency": "INR",
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.wallets.insert_one(dict(wallet))
    return wallet


async def post_transaction(
    user_id: str,
    amount: float,
    txn_type: str,  # credit | debit
    category: str,
    ref_type: str | None = None,
    ref_id: str | None = None,
    description: str = "",
    allow_negative: bool = False,
) -> dict:
    wallet = await get_or_create_wallet(user_id)
    signed = amount if txn_type == "credit" else -amount
    new_balance = round(wallet["balance"] + signed, 2)
    if new_balance < 0 and not allow_negative:
        raise HTTPException(status_code=400, detail="Insufficient wallet balance")

    txn = {
        "id": str(uuid.uuid4()),
        "wallet_id": wallet["id"],
        "user_id": user_id,
        "type": txn_type,
        "category": category,
        "amount": round(amount, 2),
        "balance_after": new_balance,
        "ref_type": ref_type,
        "ref_id": ref_id,
        "description": description,
        "created_at": _now(),
    }
    await db.transactions.insert_one(dict(txn))
    await db.wallets.update_one(
        {"id": wallet["id"]}, {"$set": {"balance": new_balance, "updated_at": _now()}}
    )
    txn.pop("_id", None)
    return txn


async def record_driver_earning(driver_id: str, ride_id: str, earning: dict) -> dict:
    record = {
        "id": str(uuid.uuid4()),
        "driver_id": driver_id,
        "ride_id": ride_id,
        **earning,
        "payout_status": "pending",
        "created_at": _now(),
    }
    await db.driver_earnings.insert_one(dict(record))
    record.pop("_id", None)
    return record
