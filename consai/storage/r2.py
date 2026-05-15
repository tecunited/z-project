import logging
import boto3
from pathlib import Path
from botocore.exceptions import ClientError
from consai.config import (
    R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY, R2_BUCKET
)
from consai.storage.base import StorageBackend

logger = logging.getLogger(__name__)


class R2Backend(StorageBackend):

    def __init__(self):
        self.bucket_name = R2_BUCKET
        self.endpoint = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
        self._client = None

    def _get_client(self):
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint,
                aws_access_key_id=R2_ACCESS_KEY_ID,
                aws_secret_access_key=R2_SECRET_ACCESS_KEY,
                region_name="auto",
            )
        return self._client

    def upload(self, local_path: Path, remote_path: str) -> str:
        try:
            client = self._get_client()
            client.upload_file(
                str(local_path),
                self.bucket_name,
                remote_path,
                ExtraArgs={"ContentType": "image/jpeg"}
            )
            url = self.get_url(remote_path)
            logger.info(f"R2 upload: {local_path.name} → {remote_path}")
            return url
        except ClientError as e:
            logger.error(f"R2 upload failed: {e}")
            raise

    def exists(self, remote_path: str) -> bool:
        try:
            self._get_client().head_object(
                Bucket=self.bucket_name,
                Key=remote_path
            )
            return True
        except ClientError:
            return False

    def delete(self, remote_path: str) -> bool:
        try:
            self._get_client().delete_object(
                Bucket=self.bucket_name,
                Key=remote_path
            )
            return True
        except ClientError as e:
            logger.error(f"R2 delete failed: {e}")
            return False

    def get_url(self, remote_path: str) -> str:
        return f"{self.endpoint}/{self.bucket_name}/{remote_path}"