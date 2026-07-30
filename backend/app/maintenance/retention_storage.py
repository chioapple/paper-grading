"""保留清理专用的 Supabase Storage 适配器。"""

from app.maintenance.retention import RetentionStorageTimeout, StorageDeleteResult
from app.storage.supabase import SupabaseObjectStorage, SupabaseStorageTimeout


class SupabaseRetentionStorage:
    """只暴露单对象幂等删除，并保留超时结果未知的语义。"""

    def __init__(self, storage: SupabaseObjectStorage) -> None:
        self._storage = storage

    async def delete(self, object_key: str) -> StorageDeleteResult:
        try:
            return await self._storage.delete_with_result(object_key)
        except SupabaseStorageTimeout as error:
            raise RetentionStorageTimeout("retention_storage_timeout") from error
