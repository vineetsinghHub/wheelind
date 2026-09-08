import logging

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import db
from app.core.errors import register_exception_handlers
from app.core.indexes import ensure_indexes
from app.core.security import hash_password, verify_password
from app.core.worker import start_worker, stop_worker
from app.core.redis_client import redis_available, close_redis
from app.routers import (
    admin,
    auth,
    documents,
    drivers,
    fare,
    presence,
    promotions,
    riders,
    rides,
    safety,
    vehicles,
    wallet,
    ws,
)
import uuid
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("wheelind")

app = FastAPI(title="Wheelind API", version="0.1.0")

register_exception_handlers(app)

for r in [auth, riders, drivers, vehicles, documents, admin, presence, rides, fare, wallet, safety, promotions, ws]:
    app.include_router(r.router)


@app.get("/api/")
async def root():
    return {"service": "wheelind-api", "status": "ok", "version": "0.1.0"}


@app.get("/api/health")
async def health():
    await db.command("ping")
    return {"status": "healthy"}


DEFAULT_FARE = {
    "bike": {"base_fare": 20, "per_km": 7, "per_min": 1, "min_fare": 30, "booking_fee": 5, "commission_percent": 15},
    "auto": {"base_fare": 30, "per_km": 11, "per_min": 1.5, "min_fare": 40, "booking_fee": 8, "commission_percent": 18},
    "sedan": {"base_fare": 60, "per_km": 15, "per_min": 2, "min_fare": 100, "booking_fee": 15, "commission_percent": 20},
    "suv": {"base_fare": 90, "per_km": 20, "per_min": 2.5, "min_fare": 150, "booking_fee": 20, "commission_percent": 22},
}


async def seed_admin():
    email = settings.ADMIN_EMAIL.lower()
    existing = await db.users.find_one({"email": email, "role": "admin"})
    if not existing:
        await db.users.insert_one(
            {"id": str(uuid.uuid4()), "email": email, "password_hash": hash_password(settings.ADMIN_PASSWORD), "name": "Super Admin", "role": "admin", "status": "active", "created_at": datetime.now(timezone.utc).isoformat()}
        )
        logger.info("Seeded admin user %s", email)
    elif not verify_password(settings.ADMIN_PASSWORD, existing.get("password_hash", "")):
        await db.users.update_one({"id": existing["id"]}, {"$set": {"password_hash": hash_password(settings.ADMIN_PASSWORD)}})


async def seed_fare_configs():
    for vt, params in DEFAULT_FARE.items():
        exists = await db.fare_configs.find_one({"city": "Bangalore", "vehicle_type": vt, "active": True})
        if not exists:
            await db.fare_configs.insert_one(
                {
                    "id": str(uuid.uuid4()),
                    "city": "Bangalore",
                    "vehicle_type": vt,
                    **params,
                    "surge_multiplier": 1.0,
                    "tax_percent": 5,
                    "currency": "INR",
                    "version": 1,
                    "active": True,
                    "created_by": "system",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
    logger.info("Seeded default fare configs")


@app.on_event("startup")
async def on_startup():
    await ensure_indexes()
    await seed_admin()
    await seed_fare_configs()
    redis_ok = await redis_available()
    logger.info("Redis hot layer: %s", "connected" if redis_ok else "UNAVAILABLE (falling back to Mongo geo)")
    start_worker()
    logger.info("Wheelind API started")


app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def on_shutdown():
    stop_worker()
    await close_redis()
