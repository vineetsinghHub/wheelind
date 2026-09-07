import uuid
from datetime import datetime, timezone
from typing import Optional

from app.core.database import db


async def audit_log(
    action: str,
    actor_id: Optional[str] = None,
    actor_role: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    meta: Optional[dict] = None,
):
    await db.audit_logs.insert_one(
        {
            "id": str(uuid.uuid4()),
            "action": action,
            "actor_id": actor_id,
            "actor_role": actor_role,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "meta": meta or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
