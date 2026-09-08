import asyncio
import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.core.database import db
from app.services.dispatch_service import dispatch

logger = logging.getLogger("wheelind.worker")

_task: asyncio.Task | None = None


async def _loop():
    logger.info("Dispatch timeout worker started (poll=%ss)", settings.WORKER_POLL_SECONDS)
    while True:
        try:
            now = datetime.now(timezone.utc)
            rides = await db.rides.find({"status": "searching"}, {"_id": 0, "id": 1}).to_list(500)
            for r in rides:
                pending = await db.offers.find_one(
                    {"ride_id": r["id"], "status": "pending", "expires_at": {"$gt": now}}
                )
                if not pending:
                    await dispatch(r["id"])
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("worker loop error: %s", e)
        await asyncio.sleep(settings.WORKER_POLL_SECONDS)


def start_worker():
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


def stop_worker():
    global _task
    if _task and not _task.done():
        _task.cancel()
    _task = None
