# Manual Run Scripts

<!-- ====================================================================== -->
<!-- Purpose                                                                -->
<!-- ====================================================================== -->

## Purpose

This folder contains scripts for manually exporting one parameterized BigQuery
query and uploading the result to Google Drive.

The SQL template is stored in:

```text
sql/manual_run.sql
```

The required runtime parameters are:

```text
COUNTRYCODE
YEARID
MONTHID
```

<!-- ====================================================================== -->
<!-- Files                                                                  -->
<!-- ====================================================================== -->

## Files

```text
manual_bigquery_to_gcs.py      Export sql/manual_run.sql from BigQuery to GCS.
manual_gcs_to_google_drive.py  Upload a manual GCS export file to Google Drive.
manual_execute_export_flow.py  Run both steps with one command.
```

<!-- ====================================================================== -->
<!-- Complete flow                                                          -->
<!-- ====================================================================== -->

## Run Complete Flow

Run the manual BigQuery export and Google Drive upload together:

```powershell
python python_files\manual_run_script\manual_execute_export_flow.py --countrycode MY --yearid 2026 --monthid 6
```

The complete flow:

```text
sql/manual_run.sql
        |
        v
manual_bigquery_to_gcs.py
        |
        v
Final GCS CSV URI
        |
        v
manual_gcs_to_google_drive.py
        |
        v
Google Drive
```

<!-- ====================================================================== -->
<!-- BigQuery to GCS                                                        -->
<!-- ====================================================================== -->

## Export BigQuery To GCS

Run the manual BigQuery export:

```powershell
python python_files\manual_run_script\manual_bigquery_to_gcs.py --countrycode MY --yearid 2026 --monthid 6
```

The script reads `sql/manual_run.sql` and replaces:

```text
{COUNTRYCODE}
{YEARID}
{MONTHID}
```

BigQuery exports the CSV as shard files first. When `COMPOSE_GCS_SHARDS=true`
in `.env`, the script combines the shards into one final CSV in GCS and logs the
final `gs://...csv` URI.

<!-- ====================================================================== -->
<!-- GCS to Google Drive                                                    -->
<!-- ====================================================================== -->

## Upload GCS To Google Drive

Use the final GCS URI from the export step:

```powershell
python python_files\manual_run_script\manual_gcs_to_google_drive.py --gcs-uri gs://your-bucket/path/final-file.csv
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

The manual functions can be imported into Airflow 3.x tasks:

```python
from python_files.manual_run_script.manual_bigquery_to_gcs import (
    export_manual_bigquery_to_gcs,
)
from python_files.manual_run_script.manual_gcs_to_google_drive import (
    transfer_manual_gcs_to_google_drive,
)
from python_files.manual_run_script.manual_execute_export_flow import (
    execute_manual_export_flow,
)


def run_manual_export() -> None:
    gcs_uri = export_manual_bigquery_to_gcs(
        country_code="MY",
        year_id=2026,
        month_id=6,
    )
    transfer_manual_gcs_to_google_drive(gcs_uri)


def run_complete_manual_flow() -> None:
    execute_manual_export_flow(
        country_code="MY",
        year_id=2026,
        month_id=6,
    )
```

Use Airflow Variables, environment variables, or a secret backend for runtime
configuration.
