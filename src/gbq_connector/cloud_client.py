from io import BytesIO
from io import StringIO
from os import getenv
from typing import Union

from google import auth
from google.cloud import storage
import pandas as pd

from gbq_connector.exceptions import CloudFileNotFoundError


class CloudStorageClient:

    def __init__(self, project: Union[str, None] = None):
        self._project = project or getenv("GBQ_PROJECT")
        self._storage_client = self._build_storage_client()

    @staticmethod
    def _build_storage_client():
        credentials, project = auth.default(
            scopes=[
                "https://www.googleapis.com/auth/cloud-platform"
            ]
        )

        return storage.Client(credentials=credentials, project=project)

    @property
    def project(self) -> str:
        return self._project

    @project.setter
    def project(self, project: str) -> None:
        self._project = project

    def load_file_to_cloud(self, bucket: str, blob: str, local_file_path: str):
        """Loads file of any type to Google Cloud Storage"""
        bucket = self._storage_client.bucket(bucket)
        blob: storage.Blob = bucket.blob(blob)
        blob.upload_from_file(local_file_path)

    def load_in_memory_file_to_cloud(self, bucket: str, blob: str, file_object: BytesIO):
        """Loads in-memory byte file to Google Cloud Storage"""
        bucket = self._storage_client.bucket(bucket)
        blob: storage.Blob = bucket.blob(blob)
        blob.upload_from_file(file_object, rewind=True)

    def load_dataframe_to_cloud_as_csv(self, bucket: str, blob: str, df: pd.DataFrame):
        """Ingests Pandas Dataframe and loads to Google Cloud Storage as csv file"""
        csv_buffer = StringIO()
        df.to_csv(csv_buffer, index=False)
        csv_buffer.seek(0)

        bucket = self._storage_client.bucket(bucket)
        blob: storage.Blob = bucket.blob(blob)
        blob.upload_from_string(csv_buffer.getvalue(), content_type="text/csv")

    def delete_file(self, bucket: str, blob: str) -> None:
        """Deletes a file from a bucket in cloud storage"""
        bucket = self._storage_client.bucket(bucket)
        blob = bucket.blob(blob)
        generation_match_precondition = None


        try:
            blob.reload()  # Fetch blob metadata to use in generation_match_precondition.
            generation_match_precondition = blob.generation

            blob.delete(if_generation_match=generation_match_precondition)
        except Exception as e:
            # Catching exception from Google is tricky. Some exceptions are wrapped in another exception.
            raise CloudFileNotFoundError(f"Error deleting file: {blob.name}: {e}")

    def delete_folder(self, bucket: str, folder_prefix: str) -> None:
        bucket = self._storage_client.bucket(bucket)

        # List all objects with the given prefix
        blobs = bucket.list_blobs(prefix=folder_prefix)

        # Delete each blob
        for blob in blobs:
            try:
                blob.delete()
            except Exception as e:
                # Catching exception from Google is tricky. Some exceptions are wrapped in another exception.
                raise CloudFileNotFoundError(f"Error deleting file: {blob.name}: {e}")
