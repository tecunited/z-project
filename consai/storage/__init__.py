from consai.config import STORAGE_BACKEND
from consai.storage.base import StorageBackend


def get_backend() -> StorageBackend:
    """Factory — returns the configured storage backend."""
    if STORAGE_BACKEND == "gcs":
        from consai.storage.gcs import GCSBackend
        return GCSBackend()
    elif STORAGE_BACKEND in ("r2", "s3"):
        from consai.storage.r2 import R2Backend
        return R2Backend()
    else:
        raise ValueError(f"Unknown storage backend: {STORAGE_BACKEND}")