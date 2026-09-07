from app.core.database import db


async def get_active_config(city: str, vehicle_type: str) -> dict | None:
    return await db.fare_configs.find_one(
        {"city": city, "vehicle_type": vehicle_type, "active": True}, {"_id": 0}
    )


def compute_breakup(config: dict, distance_km: float, duration_min: float, rider_added: float = 0.0) -> dict:
    base = float(config["base_fare"])
    distance_fare = round(float(config["per_km"]) * distance_km, 2)
    time_fare = round(float(config["per_min"]) * duration_min, 2)
    booking_fee = float(config.get("booking_fee", 0))

    subtotal = base + distance_fare + time_fare + booking_fee
    min_fare = float(config.get("min_fare", 0))
    if subtotal < min_fare:
        subtotal = min_fare

    surge_multiplier = float(config.get("surge_multiplier", 1.0))
    surge_amount = round(subtotal * (surge_multiplier - 1.0), 2)

    pre_tax = round(subtotal + surge_amount + rider_added, 2)
    tax_percent = float(config.get("tax_percent", 0))
    tax = round(pre_tax * tax_percent / 100.0, 2)
    total = round(pre_tax + tax, 2)

    return {
        "base_fare": round(base, 2),
        "distance_fare": distance_fare,
        "time_fare": time_fare,
        "booking_fee": round(booking_fee, 2),
        "surge_multiplier": surge_multiplier,
        "surge_amount": surge_amount,
        "rider_added": round(rider_added, 2),
        "subtotal": round(subtotal, 2),
        "tax_percent": tax_percent,
        "tax": tax,
        "total": total,
        "currency": config.get("currency", "INR"),
        "distance_km": distance_km,
        "duration_min": duration_min,
        "fare_config_id": config.get("id"),
        "fare_config_version": config.get("version"),
    }


def compute_earning(total: float, commission_percent: float, zero_commission: bool) -> dict:
    effective_pct = 0.0 if zero_commission else float(commission_percent)
    commission_amount = round(total * effective_pct / 100.0, 2)
    net = round(total - commission_amount, 2)
    return {
        "gross_fare": round(total, 2),
        "commission_percent": effective_pct,
        "commission_amount": commission_amount,
        "net_earning": net,
        "zero_commission": zero_commission,
    }
