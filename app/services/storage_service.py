import httpx
import uuid
import os
from fastapi import UploadFile
from app.config import get_settings

BUCKET_NAME = "leave-proofs"


async def upload_to_supabase(file: UploadFile, bucket: str, folder: str = "") -> str:
    """上傳檔案到 Supabase Storage，回傳公開 URL"""
    settings = get_settings()

    ext = os.path.splitext(file.filename)[1]
    filename = f"{uuid.uuid4()}{ext}"
    path = f"{folder}/{filename}" if folder else filename

    content = await file.read()

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{settings.supabase_url}/storage/v1/object/{bucket}/{path}",
            headers={
                "Authorization": f"Bearer {settings.supabase_service_key}",
                "Content-Type": file.content_type or "application/octet-stream",
            },
            content=content,
        )
        resp.raise_for_status()

    return f"{settings.supabase_url}/storage/v1/object/public/{bucket}/{path}"


async def upload_proof_file(proof_file: UploadFile) -> str:
    """上傳病假證明到 Supabase Storage，回傳公開 URL"""
    return await upload_to_supabase(proof_file, BUCKET_NAME)
