import httpx
import uuid
import os
from fastapi import UploadFile
from app.config import get_settings

BUCKET_NAME = "leave-proofs"


async def upload_proof_file(proof_file: UploadFile) -> str:
    """上傳病假證明到 Supabase Storage，回傳公開 URL"""
    settings = get_settings()

    ext = os.path.splitext(proof_file.filename)[1]
    filename = f"{uuid.uuid4()}{ext}"

    content = await proof_file.read()

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{settings.supabase_url}/storage/v1/object/{BUCKET_NAME}/{filename}",
            headers={
                "Authorization": f"Bearer {settings.supabase_service_key}",
                "Content-Type": proof_file.content_type or "application/octet-stream",
            },
            content=content,
        )
        resp.raise_for_status()

    return f"{settings.supabase_url}/storage/v1/object/public/{BUCKET_NAME}/{filename}"
