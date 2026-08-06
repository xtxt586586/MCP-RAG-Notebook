from io import BytesIO

from minio import Minio
from starlette.concurrency import run_in_threadpool

from app.core.config import settings


class MinioStorageService:
    def __init__(self) -> None:
        self.bucket_name = settings.minio_bucket

        self.client = Minio(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_root_user,
            secret_key=settings.minio_root_password,
            secure=settings.minio_secure,
        )

    async def ensure_bucket_exists(self) -> None:
        exists = await run_in_threadpool(
            self.client.bucket_exists,
            self.bucket_name,
        )

        if not exists:
            await run_in_threadpool(
                self.client.make_bucket,
                self.bucket_name,
            )

    async def upload_bytes(
        self,
        object_name: str,
        data: bytes,
        content_type: str,
    ) -> None:
        await self.ensure_bucket_exists()

        await run_in_threadpool(
            self.client.put_object,
            self.bucket_name,
            object_name,
            BytesIO(data),
            len(data),
            content_type=content_type,
        )

    def _download_bytes_sync(self, object_name: str) -> bytes:
        response = self.client.get_object(
            self.bucket_name,
            object_name,
        )

        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    async def download_bytes(self, object_name: str) -> bytes:
        return await run_in_threadpool(
            self._download_bytes_sync,
            object_name,
        )

    async def delete_object(self, object_name: str) -> None:
        await run_in_threadpool(
            self.client.remove_object,
            self.bucket_name,
            object_name,
        )


minio_storage = MinioStorageService()