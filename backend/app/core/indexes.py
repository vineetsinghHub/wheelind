from pymongo import ASCENDING, GEOSPHERE

from app.core.database import db


async def ensure_indexes():
    # Users: admin email unique (sparse), phone+role unique (partial)
    await db.users.create_index(
        [("email", ASCENDING)], unique=True, sparse=True, name="uniq_email"
    )
    await db.users.create_index(
        [("phone", ASCENDING), ("role", ASCENDING)],
        unique=True,
        partialFilterExpression={"phone": {"$exists": True}},
        name="uniq_phone_role",
    )

    # OTP codes TTL
    await db.otp_codes.create_index("expires_at", expireAfterSeconds=0, name="otp_ttl")
    await db.otp_codes.create_index([("phone", ASCENDING), ("role", ASCENDING)])

    # Driver presence: geo + TTL auto-expire
    await db.driver_presence.create_index([("location", GEOSPHERE)], name="presence_geo")
    await db.driver_presence.create_index("expire_at", expireAfterSeconds=0, name="presence_ttl")
    await db.driver_presence.create_index("driver_id", unique=True, name="presence_driver")

    # Core entity ids
    for coll in [
        "riders",
        "drivers",
        "vehicles",
        "documents",
        "rides",
        "transactions",
        "wallets",
        "fare_configs",
        "driver_earnings",
        "driver_subscriptions",
        "offers",
        "promotions",
    ]:
        await db[coll].create_index("id", unique=True, name=f"{coll}_id")

    await db.drivers.create_index("user_id", unique=True)
    await db.riders.create_index("user_id", unique=True)
    await db.wallets.create_index("user_id", unique=True)
    await db.vehicles.create_index("driver_id")
    await db.documents.create_index([("owner_id", ASCENDING), ("owner_type", ASCENDING)])
    await db.rides.create_index("rider_id")
    await db.rides.create_index("driver_id")
    await db.rides.create_index("status")
    await db.offers.create_index([("driver_id", ASCENDING), ("status", ASCENDING)])
    await db.offers.create_index("ride_id")
    await db.transactions.create_index("wallet_id")
    await db.driver_earnings.create_index("driver_id")
    await db.fare_configs.create_index([("city", ASCENDING), ("vehicle_type", ASCENDING), ("active", ASCENDING)])
