import logging
from os import getenv
from time import sleep
from typing import Union

from google import auth
from google.cloud import bigquery
import pandas as pd

logger = logging.getLogger(__name__)


class BigQueryClient:

    def __init__(self, project: Union[str, None] = None):
        self._project = project or getenv("GBQ_PROJECT")
        self._bq_client = self._build_big_query_client()

    @staticmethod
    def _build_big_query_client():
        credentials, project = auth.default(
            scopes=[
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/bigquery",
            ]
        )

        return bigquery.Client(credentials=credentials, project=project)

    @property
    def project(self) -> str:
        return self._project

    @project.setter
    def project(self, project: str) -> None:
        self._project = project

    def _build_table_ref(self, table_name, dataset: str, project: Union[str, None]) -> str:
        project = project or self._project
        return f"{project}.{dataset}.{table_name}"

    def create_table(self,
                     table_name,
                     dataset: str,
                     data: pd.DataFrame,
                     project: Union[str, None] = None,
                     ) -> None:
        table_ref = self._build_table_ref(table_name, dataset, project=project)
        job = self._bq_client.load_table_from_dataframe(data, table_ref)
        self._job_loop(job)

    def get_table_as_df(self, table_name, dataset: str, project: Union[str, None] = None) -> Union[None, pd.DataFrame]:
        table_ref = self._build_table_ref(table_name, dataset, project=project)
        return self.query(f"SELECT * FROM `{table_ref}`")

    def insert_df_into_table(
            self,
            table_name: str,
            dataset: str,
            data: pd.DataFrame,
            project: Union[str, None] = None,
    ) -> None:
        table_ref = self._build_table_ref(table_name, dataset, project)
        table = bigquery.Table(table_ref)
        job_config = bigquery.LoadJobConfig(write_disposition='WRITE_APPEND')
        job = self._bq_client.load_table_from_dataframe(data, table, job_config=job_config)
        self._job_loop(job)

    def merge_df_into_table(
            self,
            table_name: str,
            dataset: str,
            data: pd.DataFrame,
            id_col: str,
            project: Union[str, None] = None,
    ) -> None:
        merged_data = self.merge_table_data_into_df(table_name, dataset, data, id_col, project=project)
        self.truncate_load(table_name, merged_data, dataset, project=project)

    def merge_table_data_into_df(
            self,
            table_name: str,
            dataset: str,
            data: pd.DataFrame,
            id_col: str,
            project: Union[str, None] = None,
    ) -> pd.DataFrame:
        original_data = self.get_table_as_df(table_name, dataset, project)
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

    def _build_truncate_query(
            self,
            table_name: str,
            dataset: str,
            project: Union[str, None] = None,
    ) -> str:
        table_ref = self._build_table_ref(table_name, dataset=dataset, project=project)
        return f"TRUNCATE TABLE `{table_ref}`"

    def truncate_load(self,
                      table_name,
                      dataset: str,
                      data: pd.DataFrame,
                      project: Union[str, None] = None
                      ) -> None:
        query = self._build_truncate_query(table_name, dataset=dataset, project=project)
        self.query(query)
        self.insert_df_into_table(table_name, dataset=dataset, data=data, project=project)

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

    @staticmethod
    def _job_loop(job):
        """A loop for checking the status of a job in Big Query"""
        # Exponential backoff parameters
        base_delay = 1
        max_delay = 60
        delay_multiplier = 2
        max_checks = 10
        total_delay = 0

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
