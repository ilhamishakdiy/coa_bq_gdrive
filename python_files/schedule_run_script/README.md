# Schedule Run Scripts

<!-- ====================================================================== -->
<!-- Purpose                                                                -->
<!-- ====================================================================== -->

## Purpose

This folder contains scripts for the scheduled previous-month export flow.

The SQL file is:

```text
sql/schedule_prev_month.sql
```

Only `COUNTRYCODE` is required at runtime. The SQL calculates the previous
calendar month directly in BigQuery.

<!-- ====================================================================== -->
<!-- Files                                                                  -->
<!-- ====================================================================== -->

## Files

```text
schedule_bigquery_to_gcs.py      Export sql/schedule_prev_month.sql to GCS.
schedule_gcs_to_google_drive.py  Upload a scheduled GCS export file to Drive.
schedule_execute_export_flow.py  Run both steps with one command.
```

<!-- ====================================================================== -->
<!-- Complete flow                                                          -->
<!-- ====================================================================== -->

## Run Complete Flow

Run the scheduled BigQuery export and Google Drive upload together:

```powershell
python python_files\schedule_run_script\schedule_execute_export_flow.py --countrycode BD
```

The complete flow:

```text
sql/schedule_prev_month.sql
        |
        v
schedule_bigquery_to_gcs.py
        |
        v
Final GCS CSV URI
        |
        v
schedule_gcs_to_google_drive.py
        |
        v
Google Drive
```

<!-- ====================================================================== -->
<!-- BigQuery to GCS                                                        -->
<!-- ====================================================================== -->

## Export BigQuery To GCS

Run only the scheduled BigQuery export:

```powershell
python python_files\schedule_run_script\schedule_bigquery_to_gcs.py --countrycode BD
```

The script reads `sql/schedule_prev_month.sql`, replaces `{COUNTRYCODE}`,
exports the result to GCS as CSV shards, and then combines the shards into one
final CSV when `COMPOSE_GCS_SHARDS=true` in `.env`.

<!-- ====================================================================== -->
<!-- GCS to Google Drive                                                    -->
<!-- ====================================================================== -->

## Upload GCS To Google Drive

Use the final GCS URI from the export step:

```powershell
python python_files\schedule_run_script\schedule_gcs_to_google_drive.py --gcs-uri gs://your-bucket/path/final-file.csv
```

If `--gcs-uri` is omitted, the script uses the shared fallback logic:

```text
GCS_DRIVE_SOURCE_URI from .env
Latest object under GCS_MERGED_OBJECT_PREFIX
```

<!-- ====================================================================== -->
<!-- Configuration                                                          -->
<!-- ====================================================================== -->

## Configuration

Keep project IDs, bucket names, Drive folder IDs, and credentials in `.env` or
your Airflow 3.x environment. Do not hardcode credentials in these scripts.

Required shared settings include:

```dotenv
GOOGLE_APPLICATION_CREDENTIALS=service_account/your-service-account.json
BQ_PROJECT_ID=your-bigquery-project-id
GCS_PROJECT_ID=your-gcs-project-id
GCS_BUCKET_NAME=your-gcs-bucket
DRIVE_FOLDER_ID=your-google-drive-folder-id
COMPOSE_GCS_SHARDS=true
```

<!-- ====================================================================== -->
<!-- Airflow 3.x                                                            -->
<!-- ====================================================================== -->

## Airflow 3.x

The scheduled flow can be imported into Airflow 3.x tasks:

```python
from python_files.schedule_run_script.schedule_execute_export_flow import (
    execute_schedule_export_flow,
)


def run_scheduled_export() -> None:
    execute_schedule_export_flow(country_code="BD")
```

Use Airflow Variables, environment variables, or a secret backend for runtime
configuration.
