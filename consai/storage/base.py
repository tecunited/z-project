from abc import ABC, abstractmethod
from pathlib import Path


class StorageBackend(ABC):
    """Abstract base — all storage backends implement this interface."""

    @abstractmethod
    def upload(self, local_path: Path, remote_path: str) -> str:
        """
        Upload a file to storage.
        Returns the public/signed URL of the uploaded file.
        """
        pass

    @abstractmethod
    def exists(self, remote_path: str) -> bool:
        """Check if a file exists in storage."""
        pass

    @abstractmethod
    def delete(self, remote_path: str) -> bool:
        """Delete a file from storage. Returns True if successful."""
        pass

    @abstractmethod
    def get_url(self, remote_path: str) -> str:
        """Get the public URL for a remote path."""
        pass