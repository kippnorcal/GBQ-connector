import logging
from os import getenv
from time import sleep
from typing import Union, Dict, List

from google import auth
from google.cloud import bigquery
from google.cloud import storage
import pandas as pd

from gbq_connector.exceptions import NoSchemaError

logger = logging.getLogger(__name__)


class GBQConnectionClient:

    def __init__(self, project: Union[str, None] = None, dataset: Union[str, None] = None):
        self._project = project or getenv("GBQ_PROJECT")
        self._dataset = dataset or getenv("GBQ_DATASET")
        self._bq_client = self._build_big_query_client()
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

    @property
    def dataset(self) -> Union[str, None]:
        return self._dataset

    @dataset.setter
    def dataset(self, dataset: str) -> None:
        self._dataset = dataset

    def _build_big_query_client(self):
        credentials, project = auth.default(
            scopes=[
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/bigquery",
            ]
        )

        return bigquery.Client(credentials=credentials, project=self._project)

    def _build_table_ref(self, table_name, project: Union[str, None], dataset: Union[str, None]) -> str:
        project = project or self._project
        dataset = dataset or self._dataset
        return f"{project}.{dataset}.{table_name}"

    def create_table(self,
                     table_name,
                     data: Union[dict, None] = None,
                     schema: Union[dict, None] = None,
                     project: Union[str, None] = None,
                     dataset: Union[str, None] = None
                     ) -> None:
        pass

    def get_table_as_df(self, table_name, project: Union[str, None] = None, dataset: Union[str, None] = None) -> Union[None, pd.DataFrame]:
        table_ref = self._build_table_ref(table_name, project=project, dataset=dataset)
        return self.query(f"SELECT * FROM `{table_ref}`")

    def insert_df_into_table(
            self,
            table_name: str,
            data: pd.DataFrame,
            project: Union[str, None] = None,
            dataset: Union[str, None] = None
    ) -> None:
        table_ref = self._build_table_ref(table_name, project, dataset)
        table = bigquery.Table(table_ref)
        job_config = bigquery.LoadJobConfig(write_disposition='WRITE_APPEND')
        job = self._bq_client.load_table_from_dataframe(data, table, job_config=job_config)
        self._job_loop(job)

    def merge_df_into_table(
            self,
            table_name: str,
            data: pd.DataFrame,
            id_col: str,
            project: Union[str, None] = None,
            dataset: Union[str, None] = None
    ) -> None:
        merged_data = self.merge_table_data_into_df(table_name, data, id_col, project=project, dataset=dataset)
        self.truncate_load(table_name, merged_data, project=project, dataset=dataset)

    def merge_table_data_into_df(
            self,
            table_name: str,
            data: pd.DataFrame,
            id_col: str,
            project: Union[str, None] = None,
            dataset: Union[str, None] = None
    ) -> pd.DataFrame:
        original_data = self.get_table_as_df(table_name, project, dataset)
        if original_data is not None:
            updated_data = self._merge_update_data(original_data, data, id_col)
            new_records = self._merge_query_for_new_records(updated_data, data, id_col)
            merged_data = pd.concat([updated_data, new_records])
        else:
            merged_data = data
        return merged_data

    @staticmethod
    def _merge_query_for_new_records(updated_data: pd.DataFrame, new_data: pd.DataFrame, id_col: str) -> pd.DataFrame:
        ids_df = updated_data[[id_col]].copy()
        result = pd.merge(
            new_data,
            ids_df,
            indicator=True,
            how="outer",
            on=[id_col]).query("_merge=='left_only'")
        result.drop(["_merge"], axis=1, inplace=True)
        return result

    @staticmethod
    def _merge_update_data(old_data: pd.DataFrame, new_data: pd.DataFrame, id_col: str) -> pd.DataFrame:
        df = old_data.copy()
        df.set_index(id_col, inplace=True)
        new_data.set_index(id_col, inplace=True)
        df.update(new_data)
        df.reset_index(inplace=True)
        return df

    def drop_table(self,  table_name, project: Union[str, None] = None, dataset: Union[str, None] = None) -> None:
        pass

    def _build_truncate_query(
            self,
            table_name: str,
            project: Union[str, None] = None,
            dataset: Union[str, None] = None
    ) -> str:
        table_ref = self._build_table_ref(table_name, project, dataset)
        return f"TRUNCATE TABLE `{table_ref}`"

    def truncate_load(self, table_name, data, project: Union[str, None] = None, dataset: Union[str, None] = None) -> None:
        query = self._build_truncate_query(table_name, project, dataset)
        self.query(query)
        self.insert_df_into_table(table_name, data, project, dataset)

    def create_partition_table(
            self,
            table_name: str,
            schema: Union[Dict[str, str], None] = None,
            data: Union[str, None] = None,
            partition_field: Union[str, None] = None,
            partition_type: Union[str, None] = None,
            project: Union[str, None] = None,
            dataset: Union[str, None] = None
    ) -> None:
        partition_obj = bigquery.TimePartitioning()
        if partition_type is not None:
            partition_obj.type_ = self._create_time_partitioning_type(partition_type)

        if partition_field is not None:
            partition_obj.field = partition_field

        schema_obj = SchemaConverter(schema, data)

        table_ref = self._build_table_ref(project, dataset, table_name)
        table = bigquery.Table(table_ref, schema=schema_obj,)

        table.time_partitioning = partition_obj
        self._bq_client.create_table(table)

    @staticmethod
    def _create_time_partitioning_type(partition_type: str):
        if partition_type.upper() == "DAY":
            return bigquery.TimePartitioningType.DAY
        elif partition_type.upper() == "YEAR":
            return bigquery.TimePartitioningType.DAY
        elif partition_type.upper() == "HOUR":
            return bigquery.TimePartitioningType.DAY
        elif partition_type.upper() == "YEAR":
            return bigquery.TimePartitioningType.DAY

    def add_columns(self, table_name, data=None, schema=None, project: Union[str, None] = None, dataset: Union[str, None] = None) -> None:
        pass

    def drop_columns(self, table_name, columns, project: Union[str, None] = None, dataset: Union[str, None] = None) -> None:
        pass

    def rename_columns(self, table_name, cols: dict, project: Union[str, None] = None, dataset: Union[str, None] = None) -> None:
        pass

    def query(self, query):
        job = self._bq_client.query(query=query)
        result = self._job_loop(job)
        if result is None:
            return None
        else:
            df = job.to_dataframe()
            if df.empty:
                return None
            else:
                return df

    def _job_loop(self, job):
        # Exponential backoff parameters
        base_delay = 1  # Initial waiting time (seconds)
        max_delay = 60  # Maximum waiting time (seconds)
        delay_multiplier = 2  # Multiplier for exponential backoff
        max_checks = 10  # Maximum possible number of checks before failing

        total_delay = 0  # Total waiting time
        while not job.done():
            if total_delay > max_checks * max_delay:
                logger.error(f"[GBQ-Connector]: {job.job_type} job exceeded maximum waiting time.")
                return None

            delay = min(base_delay * delay_multiplier ** total_delay, max_delay)
            total_delay += delay

            logger.debug(f"[GBQ-Connector]: Waiting {delay} seconds for {job.job_type} job completion...")
            sleep(delay)
            job.reload()  # Refresh job status

        logger.debug(f"[GBQ-Connector]: {job.job_type} job completed.")
        return job.result()
