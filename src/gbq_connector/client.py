import logging
from os import getenv
from typing import Union, Dict, List

from google.cloud import bigquery
import pandas as pd

from exceptions import NoSchemaError

logger = logging.getLogger(__name__)

class GBQConnectionClient:

    def __init__(self, project: Union[str, None], dataset: Union[str, None]):
        self._gbq_project = project or getenv("GBQ_PROJECT")
        self._gbq_dataset = dataset or getenv("GBQ_DATASET")
        self._bq_client = bigquery.Client()

    def _generate_dataset_path(self, project: Union[str, None], dataset: Union[str, None]) -> str:
        project = project or self._gbq_project
        dataset = dataset or self._gbq_project
        return f"{project}.{dataset}"

    def create_table(self,
                     table_name,
                     data: Union[dict, None] = None,
                     schema: Union[dict, None] = None,
                     project: Union[str, None] = None,
                     dataset: Union[str, None] = None
                     ) -> None:

        pass


    def drop_table(self,  table_name, project: Union[str, None] = None, dataset: Union[str, None] = None) -> None:
        pass

    def get_table_as_df(self, table_name, project: Union[str, None] = None, dataset: Union[str, None] = None):
        pass

    def sql_query(self, query) -> Union[None, pd.DataFrame]:
        pass

    def truncate_load(self, table_name, data, project: Union[str, None] = None, dataset: Union[str, None] = None) -> None:
        pass

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

        table_ref = f"{self._generate_table_ref(project, dataset)}.{table_name}"
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

    def run_query(self, query):
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
        logger.info(f"Executing {job.job_type} on {self._table_ref}.")
        # Exponential backoff parameters
        base_delay = 1  # Initial waiting time (seconds)
        max_delay = 60  # Maximum waiting time (seconds)
        delay_multiplier = 2  # Multiplier for exponential backoff

        total_delay = 0  # Total waiting time
        while not job.done():
            if total_delay > self._max_checks * max_delay:
                logger.error(f"{job.job_type} job exceeded maximum waiting time.")
                return None

            delay = min(base_delay * delay_multiplier ** total_delay, max_delay)
            total_delay += delay

            logger.info(f"Waiting {delay} seconds for {job.job_type} job completion...")
            sleep(delay)
            job.reload()  # Refresh job status

        logger.info(f"{job.job_type} job completed.")
        return job.result()


class SchemaConverter:

    CONVERSION_MAP = {
        "int64": "INTEGER",
        "object": "STRING",
        "float64": "FLOAT",
    }

    def __init__(self):
        self._schema_field_obj = bigquery.SchemaField

    def _eval_fields(self, fields: Dict[str, str]) -> Dict[str, str]:
        bq_types = set(self.CONVERSION_MAP.values())
        for k, v in fields:
            if v.upper() not in bq_types:
                fields[k] = "STRING"
            else:
                fields[k] = v.upper()
        return fields

    def _get_dtypes(self, cols: List[str], data: pd.DataFrame) -> Dict[str, str]:
        dtype_mappings = {}
        for col in cols:
            dtype = data[col].dtype.name
            bq_type = self.CONVERTION_MAP.get(dtype, "STRING")
            dtype_mappings[col] = bq_type
        return dtype_mappings

    def _create_schema_type_objs(
            self,
            schema: Dict[str, str]
    ) -> List[bigquery.SchemaField]:
        schema_container = []
        for k, v in schema:
            schema_obj = self._schema_field_obj(k, v)
            schema_container.append(schema_obj)

    def create_schema(
            self,
            fields: Union[Dict[str, str], None] = None,
            data: Union[pd.DataFrame, None] = None
    ) -> Union[List[bigquery.SchemaField], None]:
        schema = {}
        if fields is not None:
            schema = self._eval_fields(fields)
        if data is not None:
            # filter based on fields
            cols = [x for x in data.columns.to_list() if x not in schema.keys()]
            # get data type dict
            data_dtypes = self._get_dtypes(cols, data)
            schema = {**schema, **data_dtypes}
        if schema:
            return self._create_schema_type_objs(schema)
        else:
            return None

        # If fields and no data, evaluate field values map to a GBQ data type and create empty table with fields passed
        # if data and no fields, evaluate data's columns and datatypes and create table with columns, then load data
        # If both fields and data, evaluate field values, then evaluate data cols if col name doesn't also exist in field.
        #   All cols in data will be in table
        #   Only fields will make it into a table if they exist in data. Fields that don't have a corresponding column in the data will bw dropped.
