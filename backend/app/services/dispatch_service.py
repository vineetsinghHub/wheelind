import uuid
from datetime import datetime, timezone, timedelta

from app.core.database import db
from app.core.config import settings
from app.core.ws import manager
from app.services.matching_service import find_nearby_drivers
from app.integrations.stubs import push


def _now():
    return datetime.now(timezone.utc).isoformat()


async def create_offer(ride: dict, driver: dict) -> dict:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.OFFER_TTL_SECONDS)
    offer = {
        "id": str(uuid.uuid4()),
        "ride_id": ride["id"],
        "driver_id": driver["driver_id"],
        "driver_user_id": driver["user_id"],
        "vehicle_type": ride["vehicle_type"],
        "fare_estimate": ride["fare_estimate"]["total"],
        "pickup": ride["pickup"],
        "drop": ride["drop"],
        "distance_m": driver.get("distance_m"),
        "status": "pending",
        "expires_at": expires_at,
        "created_at": _now(),
    }
    await db.offers.insert_one(dict(offer))

    ser = {k: v for k, v in offer.items() if k != "_id"}
    ser["expires_at"] = expires_at.isoformat()
    ser["expires_in"] = settings.OFFER_TTL_SECONDS
    await manager.send_to_user(driver["user_id"], {"type": "offer", "offer": ser})
    await push.notify(driver["user_id"], "New ride request", f"Fare ~{offer['fare_estimate']}")
    offer.pop("_id", None)
    return offer


async def dispatch(ride_id: str) -> dict:
    ride = await db.rides.find_one({"id": ride_id}, {"_id": 0})
    if not ride or ride["status"] not in ("searching", "no_drivers"):
        return ride

    attempt = ride.get("dispatch_attempt", 0) + 1
    # expire outstanding pending offers before advancing
    await db.offers.update_many({"ride_id": ride_id, "status": "pending"}, {"$set": {"status": "expired"}})

    if attempt > settings.MAX_DISPATCH_ATTEMPTS:
        await db.rides.update_one(
            {"id": ride_id},
            {"$set": {"status": "no_drivers", "current_offer_id": None, "updated_at": _now()},
             "$push": {"status_history": {"status": "no_drivers", "at": _now()}}},
        )
        rider_id = ride["rider_id"]
        await manager.send_to_user(rider_id, {"type": "ride_update", "ride_id": ride_id, "status": "no_drivers"})
        return await db.rides.find_one({"id": ride_id}, {"_id": 0})

    offered = set(ride.get("offered_drivers", []))
    coords = ride["pickup"]
    candidates = await find_nearby_drivers(coords["lng"], coords["lat"], ride["vehicle_type"], limit=20)
    next_driver = next((c for c in candidates if c["driver_id"] not in offered), None)

    if not next_driver:
        await db.rides.update_one(
            {"id": ride_id}, {"$set": {"status": "searching", "dispatch_attempt": attempt, "current_offer_id": None, "updated_at": _now()}}
        )
        return await db.rides.find_one({"id": ride_id}, {"_id": 0})

    offer = await create_offer(ride, next_driver)
    offered.add(next_driver["driver_id"])
    await db.rides.update_one(
        {"id": ride_id},
        {"$set": {"status": "searching", "dispatch_attempt": attempt, "offered_drivers": list(offered), "current_offer_id": offer["id"], "updated_at": _now()}},
    )
    await manager.send_to_user(ride["rider_id"], {"type": "ride_update", "ride_id": ride_id, "status": "searching", "attempt": attempt})
    return await db.rides.find_one({"id": ride_id}, {"_id": 0})
