import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.core.database import db
from app.core.deps import get_current_user, require_roles
from app.core.config import settings
from app.core.audit import audit_log
from app.core.security import generate_trip_otp
from app.models.enums import VehicleType, PaymentMethod, RideStatus
from app.services.fare_service import get_active_config, compute_breakup, compute_earning
from app.services.matching_service import find_nearby_drivers
from app.services.wallet_service import post_transaction, record_driver_earning
from app.integrations.stubs import maps, push

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


# ----------------- dispatch helpers -----------------
async def _create_offer(ride: dict, driver: dict) -> dict:
    offer = {
        "id": str(uuid.uuid4()),
        "ride_id": ride["id"],
        "driver_id": driver["driver_id"],
        "driver_user_id": driver["user_id"],
        "vehicle_type": ride["vehicle_type"],
        "fare_estimate": ride["fare_estimate"]["total"],
        "pickup": ride["pickup"],
        "status": "pending",
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=settings.OFFER_TTL_SECONDS),
        "created_at": _now(),
    }
    await db.offers.insert_one(dict(offer))
    await push.notify(driver["user_id"], "New ride request", f"Fare ~{offer['fare_estimate']}")
    offer.pop("_id", None)
    return offer


async def _dispatch(ride_id: str) -> dict:
    ride = await db.rides.find_one({"id": ride_id}, {"_id": 0})
    if not ride or ride["status"] not in ("searching", "no_drivers"):
        return ride
    attempt = ride.get("dispatch_attempt", 0) + 1
    if attempt > settings.MAX_DISPATCH_ATTEMPTS:
        await db.rides.update_one({"id": ride_id}, {"$set": {"status": "no_drivers", "updated_at": _now()}})
        return await db.rides.find_one({"id": ride_id}, {"_id": 0})

    # expire outstanding pending offers
    await db.offers.update_many({"ride_id": ride_id, "status": "pending"}, {"$set": {"status": "expired"}})

    offered = set(ride.get("offered_drivers", []))
    coords = ride["pickup"]
    candidates = await find_nearby_drivers(coords["lng"], coords["lat"], ride["vehicle_type"], limit=20)
    next_driver = next((c for c in candidates if c["driver_id"] not in offered), None)

    if not next_driver:
        # no candidate this round; keep searching state, bump attempt
        await db.rides.update_one(
            {"id": ride_id}, {"$set": {"status": "searching", "dispatch_attempt": attempt, "updated_at": _now()}}
        )
        return await db.rides.find_one({"id": ride_id}, {"_id": 0})

    offer = await _create_offer(ride, next_driver)
    offered.add(next_driver["driver_id"])
    await db.rides.update_one(
        {"id": ride_id},
        {"$set": {"status": "searching", "dispatch_attempt": attempt, "offered_drivers": list(offered), "current_offer_id": offer["id"], "updated_at": _now()}},
    )
    return await db.rides.find_one({"id": ride_id}, {"_id": 0})


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
    await _dispatch(ride_id)
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
    # Only ride participants (or admin) may view the ride
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
    updated = await _dispatch(ride_id)
    return updated


@router.post("/rides/{ride_id}/dispatch-next")
async def dispatch_next(ride_id: str, user: dict = Depends(get_current_user)):
    ride = await db.rides.find_one({"id": ride_id}, {"_id": 0})
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if user["role"] == "rider" and ride["rider_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Not your ride")
    return await _dispatch(ride_id)


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
    valid = [o for o in offers if _to_dt(o["expires_at"]) > now]
    return valid


def _to_dt(v):
    if isinstance(v, str):
        dt = datetime.fromisoformat(v)
    else:
        dt = v
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


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
    await audit_log("ride.assigned", user["id"], "driver", "ride", ride["id"])
    return await db.rides.find_one({"id": ride["id"]}, {"_id": 0})


@router.post("/offers/{offer_id}/reject")
async def reject_offer(offer_id: str, user: dict = Depends(require_roles("driver"))):
    d = await db.drivers.find_one({"user_id": user["id"]}, {"_id": 0})
    offer = await db.offers.find_one({"id": offer_id}, {"_id": 0})
    if not offer or (d and offer["driver_id"] != d["id"]):
        raise HTTPException(status_code=404, detail="Offer not found")
    await db.offers.update_one({"id": offer_id}, {"$set": {"status": "rejected"}})
    await _dispatch(offer["ride_id"])
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
    await audit_log("ride.start", user["id"], "driver", "ride", ride_id)
    return {"message": "Trip started"}


@router.post("/rides/{ride_id}/complete")
async def complete_trip(ride_id: str, body: CompleteTrip, user: dict = Depends(require_roles("driver"))):
    d, ride = await _driver_and_ride(user, ride_id, "in_progress")

    distance_km = body.distance_km if body.distance_km is not None else ride["route"]["distance_km"]
    duration_min = body.duration_min if body.duration_min is not None else ride["route"]["duration_min"]
    breakup = compute_breakup(ride["fare_config_snapshot"], distance_km, duration_min, rider_added=ride.get("rider_added", 0.0))
    total = breakup["total"]

    # Commission vs subscription (computed regardless of payment mode; recorded in earnings ledger)
    sub = await db.driver_subscriptions.find_one({"driver_id": d["id"], "active": True}, {"_id": 0})
    zero_commission = bool(sub and sub.get("plan") == "zero_commission")
    commission_pct = float(ride["fare_config_snapshot"].get("commission_percent", 0))
    earning = compute_earning(total, commission_pct, zero_commission)
    await record_driver_earning(d["id"], ride_id, earning)

    cashback = 0.0
    if ride["payment_method"] == "wallet":
        # Rider pays platform digitally; platform owes driver the net earning.
        await post_transaction(ride["rider_id"], total, "debit", "ride_payment", "ride", ride_id, "Ride payment")
        await post_transaction(user["id"], earning["net_earning"], "credit", "driver_earning", "ride", ride_id, "Trip earning")
        # Loyalty cashback: 2% up to 20
        cashback = round(min(total * 0.02, 20.0), 2)
        if cashback > 0:
            await post_transaction(ride["rider_id"], cashback, "credit", "cashback", "ride", ride_id, "Ride cashback")
    else:
        # Cash: driver collected full fare in hand and owes the platform its commission.
        if earning["commission_amount"] > 0:
            await post_transaction(user["id"], earning["commission_amount"], "debit", "commission", "ride", ride_id, "Platform commission (cash ride)", allow_negative=True)

    await db.rides.update_one(
        {"id": ride_id},
        {"$set": {"status": "completed", "fare_final": breakup, "earning": earning, "cashback": cashback, "completed_at": _now(), "updated_at": _now()}, "$push": {"status_history": {"status": "completed", "at": _now()}}},
    )
    await db.driver_presence.update_one({"driver_id": d["id"]}, {"$set": {"status": "online"}})
    await db.drivers.update_one({"id": d["id"]}, {"$inc": {"total_trips": 1}})
    await db.riders.update_one({"user_id": ride["rider_id"]}, {"$inc": {"total_trips": 1}})
    await audit_log("ride.complete", user["id"], "driver", "ride", ride_id, {"total": total, "net": earning["net_earning"]})

    return {"message": "Trip completed", "fare_final": breakup, "earning": earning, "cashback": cashback}
