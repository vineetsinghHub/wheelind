import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from app.core.database import db
from app.core.deps import require_roles
from app.integrations.stubs import storage
from app.models.enums import DocumentType

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _now():
    return datetime.now(timezone.utc).isoformat()


class DocumentCreate(BaseModel):
    doc_type: str
    file_key: str  # object storage key (stub); real upload deferred
    number: str | None = None

    @field_validator("doc_type")
    @classmethod
    def valid(cls, v):
        if v not in [t.value for t in DocumentType]:
            raise ValueError("invalid doc_type")
        return v


@router.post("/upload-url")
async def get_upload_url(doc_type: str, content_type: str = "image/jpeg", user: dict = Depends(require_roles("driver", "rider"))):
    key = f"kyc/{user['id']}/{doc_type}/{uuid.uuid4().hex}"
    return await storage.upload(key, content_type)


@router.post("")
async def submit_document(body: DocumentCreate, user: dict = Depends(require_roles("driver", "rider"))):
    doc = {
        "id": str(uuid.uuid4()),
        "owner_id": user["id"],
        "owner_type": user["role"],
        "doc_type": body.doc_type,
        "file_key": body.file_key,
        "number": body.number,
        "status": "pending",
        "review_reason": None,
        "created_at": _now(),
    }
    await db.documents.insert_one(dict(doc))
    # move driver KYC to submitted
    if user["role"] == "driver":
        await db.drivers.update_one(
            {"user_id": user["id"], "kyc_status": {"$in": ["pending", "rejected"]}},
            {"$set": {"kyc_status": "submitted", "updated_at": _now()}},
        )
    doc.pop("_id", None)
    return doc


@router.get("")
async def list_my_documents(user: dict = Depends(require_roles("driver", "rider"))):
    return await db.documents.find({"owner_id": user["id"]}, {"_id": 0}).to_list(100)
