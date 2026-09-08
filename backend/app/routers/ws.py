import logging
from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.core.database import db
from app.core.security import decode_token
from app.core.ws import manager
from app.core.redis_client import update_driver_location, push_trip_point

router = APIRouter()
logger = logging.getLogger("wheelind.ws")


def _now():
    return datetime.now(timezone.utc).isoformat()


@router.websocket("/api/ws")
async def ws_endpoint(ws: WebSocket, token: str = Query(...)):
    try:
        payload = decode_token(token)
    except jwt.InvalidTokenError:
        await ws.close(code=4401)
        return
    if payload.get("type") != "access":
        await ws.close(code=4401)
        return

    uid = payload["sub"]
    role = payload.get("role")
    user = await db.users.find_one({"id": uid}, {"_id": 0})
    if not user:
        await ws.close(code=4401)
        return

    driver = await db.drivers.find_one({"user_id": uid}, {"_id": 0}) if role == "driver" else None

    await manager.connect(uid, ws)
    await ws.send_json({"type": "connected", "user_id": uid, "role": role})
    try:
        while True:
            data = await ws.receive_json()
            mtype = data.get("type")

            if mtype == "ping":
                await ws.send_json({"type": "pong"})

            elif mtype == "location" and role == "driver" and driver:
                lng, lat = data.get("lng"), data.get("lat")
                if lng is None or lat is None:
                    continue
                presence = await db.driver_presence.find_one({"driver_id": driver["id"]}, {"_id": 0})
                if presence:
                    await update_driver_location(
                        driver["id"], uid, presence["vehicle_type"], lng, lat, presence.get("status", "online"), settings.HEARTBEAT_TTL_SECONDS
                    )
                    await db.driver_presence.update_one(
                        {"driver_id": driver["id"]},
                        {"$set": {"location": {"type": "Point", "coordinates": [lng, lat]}, "last_heartbeat": _now()}},
                    )
                # relay to rider on the active ride
                ride = await db.rides.find_one(
                    {"driver_id": driver["id"], "status": {"$in": ["driver_assigned", "arrived", "in_progress"]}}, {"_id": 0}
                )
                if ride:
                    if ride["status"] == "in_progress":
                        await push_trip_point(ride["id"], lng, lat, _now())
                    await manager.send_to_user(
                        ride["rider_id"], {"type": "driver_location", "ride_id": ride["id"], "lng": lng, "lat": lat}
                    )
    except WebSocketDisconnect:
        manager.disconnect(uid, ws)
    except Exception as e:  # noqa: BLE001
        logger.warning("ws error for %s: %s", uid, e)
        manager.disconnect(uid, ws)
