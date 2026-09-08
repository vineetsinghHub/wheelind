import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.core.database import db
from app.core.deps import get_current_user, require_roles
from app.core.audit import audit_log
from app.core.security import generate_trip_otp
from app.core.ws import manager
from app.core.redis_client import set_driver_status, get_trip_path, clear_trip_path
from app.models.enums import VehicleType, PaymentMethod
from app.services.fare_service import get_active_config, compute_breakup, compute_earning
from app.services.wallet_service import post_transaction, record_driver_earning
from app.services.dispatch_service import dispatch
from app.integrations.stubs import maps

router = APIRouter(prefix="/api", tags=["rides"])


def _now():
    return datetime.now(timezone.utc).isoformat()


class GeoPoint(BaseModel):
    lng: float
    lat: float
    address: str | None = None


class RideCreate(BaseModel):
    pickup: GeoPoint
    drop: GeoPoint
    vehicle_type: str
    city: str = "Bangalore"
    payment_method: str = "cash"

    @field_validator("vehicle_type")
    @classmethod
    def valid_vt(cls, v):
        if v not in [t.value for t in VehicleType]:
            raise ValueError("invalid vehicle_type")
        return v

    @field_validator("payment_method")
    @classmethod
    def valid_pm(cls, v):
        if v not in [t.value for t in PaymentMethod]:
            raise ValueError("invalid payment_method")
        return v


class IncreaseFare(BaseModel):
    amount: float = Field(gt=0, le=1000)


class StartTrip(BaseModel):
    otp: str


class CompleteTrip(BaseModel):
    distance_km: float | None = None
    duration_min: float | None = None


def _to_dt(v):
    dt = datetime.fromisoformat(v) if isinstance(v, str) else v
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _notify_rider(rider_id, status, ride_id, extra=None):
    msg = {"type": "ride_update", "ride_id": ride_id, "status": status}
    if extra:
        msg.update(extra)
    await manager.send_to_user(rider_id, msg)


# ----------------- rider: create & manage ride -----------------
@router.post("/rides")
async def create_ride(body: RideCreate, user: dict = Depends(require_roles("rider"))):
    config = await get_active_config(body.city, body.vehicle_type)
    if not config:
        raise HTTPException(status_code=400, detail="No active fare config for city/vehicle_type")

    route = await maps.estimate_route([body.pickup.lng, body.pickup.lat], [body.drop.lng, body.drop.lat])
    breakup = compute_breakup(config, route["distance_km"], route["duration_min"], rider_added=0.0)

    ride_id = str(uuid.uuid4())
    ride = {
        "id": ride_id,
        "rider_id": user["id"],
        "driver_id": None,
        "driver_user_id": None,
        "city": body.city,
        "vehicle_type": body.vehicle_type,
        "payment_method": body.payment_method,
        "pickup": body.pickup.model_dump(),
        "drop": body.drop.model_dump(),
        "route": route,
        "fare_config_snapshot": config,
        "rider_added": 0.0,
        "fare_estimate": breakup,
        "fare_final": None,
        "path": [],
        "trip_otp": generate_trip_otp(),
        "status": "searching",
        "dispatch_attempt": 0,
        "offered_drivers": [],
        "current_offer_id": None,
        "status_history": [{"status": "requested", "at": _now()}, {"status": "searching", "at": _now()}],
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.rides.insert_one(dict(ride))
    await audit_log("ride.create", user["id"], "rider", "ride", ride_id, {"vehicle_type": body.vehicle_type})
    await dispatch(ride_id)
    return await db.rides.find_one({"id": ride_id}, {"_id": 0})


@router.get("/rides")
async def list_rides(user: dict = Depends(get_current_user)):
    if user["role"] == "rider":
        q = {"rider_id": user["id"]}
    elif user["role"] == "driver":
        d = await db.drivers.find_one({"user_id": user["id"]}, {"_id": 0})
        q = {"driver_id": d["id"] if d else "__none__"}
    else:
        q = {}
    return await db.rides.find(q, {"_id": 0, "trip_otp": 0}).sort("created_at", -1).to_list(200)


@router.get("/rides/{ride_id}")
async def get_ride(ride_id: str, user: dict = Depends(get_current_user)):
    ride = await db.rides.find_one({"id": ride_id}, {"_id": 0})
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if user["role"] == "driver":
        d = await db.drivers.find_one({"user_id": user["id"]}, {"_id": 0})
        if not d or ride.get("driver_id") != d["id"]:
            raise HTTPException(status_code=403, detail="Not your ride")
    elif user["role"] == "rider" and ride["rider_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Not your ride")
    return ride


@router.post("/rides/{ride_id}/increase-fare")
async def increase_fare(ride_id: str, body: IncreaseFare, user: dict = Depends(require_roles("rider"))):
    ride = await db.rides.find_one({"id": ride_id, "rider_id": user["id"]}, {"_id": 0})
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride["status"] not in ("searching", "no_drivers"):
        raise HTTPException(status_code=400, detail="Can only increase fare while searching")

    rider_added = round(ride.get("rider_added", 0.0) + body.amount, 2)
    breakup = compute_breakup(ride["fare_config_snapshot"], ride["route"]["distance_km"], ride["route"]["duration_min"], rider_added=rider_added)
    await db.rides.update_one(
        {"id": ride_id}, {"$set": {"rider_added": rider_added, "fare_estimate": breakup, "status": "searching", "updated_at": _now()}}
    )
    await audit_log("ride.increase_fare", user["id"], "rider", "ride", ride_id, {"added": body.amount})
    return await dispatch(ride_id)


@router.post("/rides/{ride_id}/dispatch-next")
async def dispatch_next(ride_id: str, user: dict = Depends(get_current_user)):
    ride = await db.rides.find_one({"id": ride_id}, {"_id": 0})
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if user["role"] == "rider" and ride["rider_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Not your ride")
    return await dispatch(ride_id)


@router.post("/rides/{ride_id}/cancel")
async def cancel_ride(ride_id: str, user: dict = Depends(get_current_user)):
    ride = await db.rides.find_one({"id": ride_id}, {"_id": 0})
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride["status"] in ("completed", "cancelled", "expired", "no_drivers"):
        raise HTTPException(status_code=400, detail="Ride cannot be cancelled")
    await db.offers.update_many({"ride_id": ride_id, "status": "pending"}, {"$set": {"status": "expired"}})
    await db.rides.update_one(
        {"id": ride_id},
        {"$set": {"status": "cancelled", "cancelled_by": user["role"], "updated_at": _now()}, "$push": {"status_history": {"status": "cancelled", "at": _now()}}},
    )
    if ride.get("driver_id"):
        await db.driver_presence.update_one({"driver_id": ride["driver_id"]}, {"$set": {"status": "online"}})
        await set_driver_status(ride["driver_id"], "online")
        if ride.get("driver_user_id"):
            await manager.send_to_user(ride["driver_user_id"], {"type": "ride_update", "ride_id": ride_id, "status": "cancelled"})
    await _notify_rider(ride["rider_id"], "cancelled", ride_id)
    await audit_log("ride.cancel", user["id"], user["role"], "ride", ride_id)
    return {"message": "Ride cancelled"}


# ----------------- driver: offers -----------------
@router.get("/driver/offers")
async def my_offers(user: dict = Depends(require_roles("driver"))):
    d = await db.drivers.find_one({"user_id": user["id"]}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Driver profile not found")
    now = datetime.now(timezone.utc)
    offers = await db.offers.find({"driver_id": d["id"], "status": "pending"}, {"_id": 0}).to_list(20)
    return [o for o in offers if _to_dt(o["expires_at"]) > now]


@router.post("/offers/{offer_id}/accept")
async def accept_offer(offer_id: str, user: dict = Depends(require_roles("driver"))):
    d = await db.drivers.find_one({"user_id": user["id"]}, {"_id": 0})
    offer = await db.offers.find_one({"id": offer_id}, {"_id": 0})
    if not offer or (d and offer["driver_id"] != d["id"]):
        raise HTTPException(status_code=404, detail="Offer not found")
    if offer["status"] != "pending" or _to_dt(offer["expires_at"]) < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Offer expired or unavailable")

    ride = await db.rides.find_one({"id": offer["ride_id"]}, {"_id": 0})
    if not ride or ride["status"] != "searching":
        await db.offers.update_one({"id": offer_id}, {"$set": {"status": "expired"}})
        raise HTTPException(status_code=400, detail="Ride no longer available")

    await db.offers.update_one({"id": offer_id}, {"$set": {"status": "accepted", "accepted_at": _now()}})
    await db.offers.update_many({"ride_id": ride["id"], "status": "pending"}, {"$set": {"status": "expired"}})
    await db.rides.update_one(
        {"id": ride["id"]},
        {"$set": {"driver_id": d["id"], "driver_user_id": user["id"], "status": "driver_assigned", "updated_at": _now()}, "$push": {"status_history": {"status": "driver_assigned", "at": _now()}}},
    )
    await db.driver_presence.update_one({"driver_id": d["id"]}, {"$set": {"status": "on_trip"}})
    await set_driver_status(d["id"], "on_trip")
    driver_info = {"driver_name": d.get("name"), "rating": d.get("rating"), "driver_id": d["id"]}
    await _notify_rider(ride["rider_id"], "driver_assigned", ride["id"], driver_info)
    await audit_log("ride.assigned", user["id"], "driver", "ride", ride["id"])
    return await db.rides.find_one({"id": ride["id"]}, {"_id": 0})


@router.post("/offers/{offer_id}/reject")
async def reject_offer(offer_id: str, user: dict = Depends(require_roles("driver"))):
    d = await db.drivers.find_one({"user_id": user["id"]}, {"_id": 0})
    offer = await db.offers.find_one({"id": offer_id}, {"_id": 0})
    if not offer or (d and offer["driver_id"] != d["id"]):
        raise HTTPException(status_code=404, detail="Offer not found")
    await db.offers.update_one({"id": offer_id}, {"$set": {"status": "rejected"}})
    await dispatch(offer["ride_id"])
    return {"message": "Offer rejected"}


# ----------------- driver: trip lifecycle -----------------
async def _driver_and_ride(user, ride_id, expected_status):
    d = await db.drivers.find_one({"user_id": user["id"]}, {"_id": 0})
    ride = await db.rides.find_one({"id": ride_id}, {"_id": 0})
    if not ride or not d or ride.get("driver_id") != d["id"]:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride["status"] != expected_status:
        raise HTTPException(status_code=400, detail=f"Ride must be in '{expected_status}' state")
    return d, ride


@router.post("/rides/{ride_id}/arrived")
async def arrived(ride_id: str, user: dict = Depends(require_roles("driver"))):
    d, ride = await _driver_and_ride(user, ride_id, "driver_assigned")
    await db.rides.update_one(
        {"id": ride_id}, {"$set": {"status": "arrived", "arrived_at": _now(), "updated_at": _now()}, "$push": {"status_history": {"status": "arrived", "at": _now()}}}
    )
    await _notify_rider(ride["rider_id"], "arrived", ride_id)
    return {"message": "Marked as arrived"}


@router.post("/rides/{ride_id}/start")
async def start_trip(ride_id: str, body: StartTrip, user: dict = Depends(require_roles("driver"))):
    d, ride = await _driver_and_ride(user, ride_id, "arrived")
    if body.otp != ride["trip_otp"]:
        raise HTTPException(status_code=400, detail="Invalid trip OTP")
    await db.rides.update_one(
        {"id": ride_id},
        {"$set": {"status": "in_progress", "started_at": _now(), "updated_at": _now()}, "$push": {"status_history": {"status": "trip_started", "at": _now()}}},
    )
    await _notify_rider(ride["rider_id"], "in_progress", ride_id)
    await audit_log("ride.start", user["id"], "driver", "ride", ride_id)
    return {"message": "Trip started"}


@router.post("/rides/{ride_id}/complete")
async def complete_trip(ride_id: str, body: CompleteTrip, user: dict = Depends(require_roles("driver"))):
    d, ride = await _driver_and_ride(user, ride_id, "in_progress")

    distance_km = body.distance_km if body.distance_km is not None else ride["route"]["distance_km"]
    duration_min = body.duration_min if body.duration_min is not None else ride["route"]["duration_min"]
    breakup = compute_breakup(ride["fare_config_snapshot"], distance_km, duration_min, rider_added=ride.get("rider_added", 0.0))
    total = breakup["total"]

    sub = await db.driver_subscriptions.find_one({"driver_id": d["id"], "active": True}, {"_id": 0})
    zero_commission = bool(sub and sub.get("plan") == "zero_commission")
    commission_pct = float(ride["fare_config_snapshot"].get("commission_percent", 0))
    earning = compute_earning(total, commission_pct, zero_commission)
    await record_driver_earning(d["id"], ride_id, earning)

    cashback = 0.0
    if ride["payment_method"] == "wallet":
        await post_transaction(ride["rider_id"], total, "debit", "ride_payment", "ride", ride_id, "Ride payment")
        await post_transaction(user["id"], earning["net_earning"], "credit", "driver_earning", "ride", ride_id, "Trip earning")
        cashback = round(min(total * 0.02, 20.0), 2)
        if cashback > 0:
            await post_transaction(ride["rider_id"], cashback, "credit", "cashback", "ride", ride_id, "Ride cashback")
    else:
        if earning["commission_amount"] > 0:
            await post_transaction(user["id"], earning["commission_amount"], "debit", "commission", "ride", ride_id, "Platform commission (cash ride)", allow_negative=True)

    # Persist live trip path from Redis hot layer to MongoDB, then clear hot state
    path = await get_trip_path(ride_id)
    await clear_trip_path(ride_id)

    await db.rides.update_one(
        {"id": ride_id},
        {"$set": {"status": "completed", "fare_final": breakup, "earning": earning, "cashback": cashback, "path": path, "completed_at": _now(), "updated_at": _now()}, "$push": {"status_history": {"status": "completed", "at": _now()}}},
    )
    await db.driver_presence.update_one({"driver_id": d["id"]}, {"$set": {"status": "online"}})
    await set_driver_status(d["id"], "online")
    await db.drivers.update_one({"id": d["id"]}, {"$inc": {"total_trips": 1}})
    await db.riders.update_one({"user_id": ride["rider_id"]}, {"$inc": {"total_trips": 1}})
    await _notify_rider(ride["rider_id"], "completed", ride_id, {"fare_final": breakup})
    await audit_log("ride.complete", user["id"], "driver", "ride", ride_id, {"total": total, "net": earning["net_earning"]})

    return {"message": "Trip completed", "fare_final": breakup, "earning": earning, "cashback": cashback, "path_points": len(path)}
