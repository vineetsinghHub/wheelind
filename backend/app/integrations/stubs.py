"""Interface/adapter stubs for pending external integrations.

Real providers (maps, SMS, payment, masked calling, push, storage) are deferred.
Each adapter has a stable interface so real implementations can drop in later.
"""
import logging
import math
import uuid
from typing import Tuple

logger = logging.getLogger("wheelind.integrations")


class SmsProvider:
    name = "stub-sms"

    async def send_otp(self, phone: str, code: str) -> bool:
        logger.info("[SMS STUB] OTP %s -> %s", code, phone)
        return True

    async def send_message(self, phone: str, message: str) -> bool:
        logger.info("[SMS STUB] MSG -> %s: %s", phone, message)
        return True


class MapsProvider:
    name = "stub-maps"

    @staticmethod
    def haversine_km(a: Tuple[float, float], b: Tuple[float, float]) -> float:
        # a, b = (lng, lat)
        r = 6371.0
        lng1, lat1 = a
        lng2, lat2 = b
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlmb = math.radians(lng2 - lng1)
        h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
        return 2 * r * math.asin(math.sqrt(h))

    async def estimate_route(self, origin, destination) -> dict:
        distance_km = round(self.haversine_km(tuple(origin), tuple(destination)), 2)
        duration_min = round(distance_km / 25 * 60, 1)  # assume 25 km/h avg
        return {"distance_km": distance_km, "duration_min": duration_min}


class PaymentProvider:
    name = "stub-payment"

    async def create_order(self, amount: float, currency: str = "INR") -> dict:
        return {"order_id": f"stub_{uuid.uuid4().hex[:12]}", "amount": amount, "currency": currency, "status": "created"}

    async def capture(self, order_id: str) -> dict:
        return {"order_id": order_id, "status": "captured"}


class MaskedCallingProvider:
    name = "stub-masked-calling"

    async def create_session(self, caller: str, callee: str) -> dict:
        return {"session_id": f"call_{uuid.uuid4().hex[:10]}", "virtual_number": "+910000000000"}


class PushProvider:
    name = "stub-push"

    async def notify(self, user_id: str, title: str, body: str, data: dict | None = None) -> bool:
        logger.info("[PUSH STUB] %s: %s - %s", user_id, title, body)
        return True


class StorageProvider:
    name = "stub-storage"

    async def upload(self, key: str, content_type: str) -> dict:
        return {"key": key, "url": f"https://stub-storage.local/{key}", "content_type": content_type}


sms = SmsProvider()
maps = MapsProvider()
payment = PaymentProvider()
masked_calling = MaskedCallingProvider()
push = PushProvider()
storage = StorageProvider()
