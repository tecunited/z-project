import logging
from pathlib import Path
from consai.config import GCS_BUCKET, GCS_CREDENTIALS_PATH
from consai.storage.base import StorageBackend

logger = logging.getLogger(__name__)


class GCSBackend(StorageBackend):

    def __init__(self):
        self.bucket_name = GCS_BUCKET
        self._client = None
        self._bucket = None

    def _get_bucket(self):
        if self._bucket is None:
            from google.cloud import storage
            from google.oauth2 import service_account
            credentials = service_account.Credentials.from_service_account_file(
                GCS_CREDENTIALS_PATH
            )
            self._client = storage.Client(credentials=credentials)
            self._bucket = self._client.bucket(self.bucket_name)
        return self._bucket

    def upload(self, local_path: Path, remote_path: str) -> str:
        try:
            bucket = self._get_bucket()
            blob = bucket.blob(remote_path)
            blob.upload_from_filename(str(local_path))
            url = f"https://storage.googleapis.com/{self.bucket_name}/{remote_path}"
            logger.info(f"GCS upload: {local_path.name} → {remote_path}")
            return url
        except Exception as e:
            logger.error(f"GCS upload failed: {e}")
            raise

    def exists(self, remote_path: str) -> bool:
        try:
            bucket = self._get_bucket()
            return bucket.blob(remote_path).exists()
        except Exception as e:
            logger.error(f"GCS exists check failed: {e}")
            return False

    def delete(self, remote_path: str) -> bool:
        try:
            bucket = self._get_bucket()
            bucket.blob(remote_path).delete()
            return True
        except Exception as e:
            logger.error(f"GCS delete failed: {e}")
            return False

    def get_url(self, remote_path: str) -> str:
        return f"https://storage.googleapis.com/{self.bucket_name}/{remote_path}"