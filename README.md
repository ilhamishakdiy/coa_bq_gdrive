# BigQuery to GCS to Google Drive

Export BigQuery query results to CSV, compose the CSV in Google Cloud Storage,
and upload the final file to Google Drive.

<!-- ====================================================================== -->
<!-- Project flow                                                           -->
<!-- ====================================================================== -->

## Flow

```text
SQL files in sql/
        |
        v
python_files/bigquery_to_gcs.py
        |
        | 1. Reads every .sql file from BQ_SQL_FOLDER
        | 2. Runs BigQuery EXPORT DATA for each query
        | 3. Writes CSV shards to GCS
        | 4. Composes shards into one final GCS object
        v
GCS bucket
        |
        v
python_files/gcs_to_google_drive.py
        |
        | 5. Reads the exact GCS object produced by the export step
        | 6. Uploads the file to the configured Google Drive folder
        | 7. Deletes the uploaded GCS object after success
        v
Google Drive
```

The full flow is executed by `python_files/execute_export_flow.py`. It calls
`export_bigquery_to_gcs()` first, then passes each returned GCS URI directly to
`transfer_gcs_to_google_drive()`.

<!-- ====================================================================== -->
<!-- Repository structure                                                   -->
<!-- ====================================================================== -->

## Files

```text
python_files/
  bigquery_to_gcs.py        Export BigQuery query results to GCS.
  gcs_to_google_drive.py    Upload GCS objects to Google Drive.
  execute_export_flow.py    Run the full export and upload flow.

sql/
  export_query.sql          Example/source BigQuery SQL file.

service_account/
  service-account.example.json
                            Example JSON key shape only. Do not store real
                            credentials in tracked files.

.env                        Runtime configuration. Keep secrets here only.
requirements.txt            Python dependencies.
```

<!-- ====================================================================== -->
<!-- Configuration                                                          -->
<!-- ====================================================================== -->

## Configuration

Create `.env` in the project root. Keep credentials and project-specific values
there instead of hardcoding them in Python or SQL.

```dotenv
# Google authentication
GOOGLE_APPLICATION_CREDENTIALS=service_account/your-service-account.json

# BigQuery source
BQ_PROJECT_ID=your-bigquery-project-id
BQ_SQL_FOLDER=sql
BQ_LOCATION=

# Cloud Storage destination
GCS_PROJECT_ID=your-gcs-project-id
GCS_BUCKET_NAME=your-gcs-bucket-name
GCS_EXPORT_URI=
GCS_DRIVE_SOURCE_URI=
GCS_OBJECT_PREFIX=exports/bigquery
GCS_MERGED_OBJECT_PREFIX=exports/bigquery_merged
EXPORT_FILE_NAME=bigquery_export
CSV_DELIMITER=,
STREAM_CHUNK_SIZE_MB=8

# GCS compose and cleanup behavior
COMPOSE_GCS_SHARDS=true
DELETE_GCS_SOURCES_AFTER_COMPOSE=true
MERGE_GCS_SHARDS=true
DELETE_GCS_SHARDS_AFTER_MERGE=true
DELETE_GCS_AFTER_DRIVE_UPLOAD=true

# Google Drive destination
DRIVE_FOLDER_ID=your-google-drive-folder-id

# Logging
LOG_LEVEL=INFO

# Backward compatibility when both projects are the same
GCP_PROJECT_ID=
```

<!-- ====================================================================== -->
<!-- BigQuery export behavior                                               -->
<!-- ====================================================================== -->

## BigQuery Export

The export step reads every `.sql` file inside `BQ_SQL_FOLDER`. Each SQL file is
exported independently, and the SQL filename becomes part of the generated CSV
object name.

If `GCS_EXPORT_URI` is blank, the export URI is generated automatically:

```text
gs://your-bucket/exports/bigquery/bigquery_export_export_query_20250625T010203Z_*.csv
```

If `GCS_EXPORT_URI` is configured, it must use the same bucket as
`GCS_BUCKET_NAME` and must include a wildcard:

```dotenv
GCS_EXPORT_URI=gs://your-bucket/exports/report_*.csv
```

When more than one SQL file is exported, the wildcard is expanded with the SQL
filename so each query writes to a separate output group.

<!-- ====================================================================== -->
<!-- GCS compose and cleanup logic                                          -->
<!-- ====================================================================== -->

## GCS Files

BigQuery may export one query into multiple CSV shard files. With the default
configuration, the export step composes those shards into one final object under
`GCS_MERGED_OBJECT_PREFIX`.

```dotenv
COMPOSE_GCS_SHARDS=true
DELETE_GCS_SOURCES_AFTER_COMPOSE=true
```

The composer uploads a small generated CSV header, then uses server-side GCS
compose operations. The shard contents do not pass through local disk.

Cleanup behavior:

- `DELETE_GCS_SOURCES_AFTER_COMPOSE=true` deletes the temporary BigQuery shard
  files and compose temporary objects after the final composed object is built.
- `DELETE_GCS_AFTER_DRIVE_UPLOAD=true` deletes the final uploaded GCS object only
  after the Google Drive upload succeeds.
- `DELETE_GCS_AFTER_DRIVE_UPLOAD=false` keeps the final uploaded GCS object in
  the bucket.

<!-- ====================================================================== -->
<!-- Google Drive upload behavior                                           -->
<!-- ====================================================================== -->

## Google Drive Upload

The Drive step uploads GCS objects to the folder configured by
`DRIVE_FOLDER_ID`. The folder must be shared with the service account email.

When running the complete flow, `execute_export_flow.py` passes the newly
created GCS URI directly to the Drive upload step.

When running `gcs_to_google_drive.py` by itself, the source is resolved in this
order:

1. Function argument passed to `transfer_gcs_to_google_drive(gcs_uri)`.
2. `GCS_DRIVE_SOURCE_URI` from `.env`.
3. Latest object under `GCS_MERGED_OBJECT_PREFIX`.

<!-- ====================================================================== -->
<!-- Permissions                                                            -->
<!-- ====================================================================== -->

## Required Permissions

The service account needs permission to:

- Run BigQuery jobs and read source data in the BigQuery project.
- Create, read, list, compose, and optionally delete objects in the GCS bucket.
- Create files in the target Google Drive folder.

The BigQuery dataset and GCS bucket must use compatible locations for BigQuery
exports.

<!-- ====================================================================== -->
<!-- Running locally                                                        -->
<!-- ====================================================================== -->

## Run Locally

Install dependencies:

```powershell
pip install -r requirements.txt
```

Run the complete flow:

```powershell
python python_files/execute_export_flow.py
```

Run only the BigQuery to GCS export:

```powershell
python python_files/bigquery_to_gcs.py
```

Run only the GCS to Google Drive upload:

```powershell
python python_files/gcs_to_google_drive.py
```

<!-- ====================================================================== -->
<!-- Airflow 3.x usage                                                      -->
<!-- ====================================================================== -->

## Airflow 3.x

The public functions can be imported into Airflow 3.x tasks:

```python
from python_files.bigquery_to_gcs import export_bigquery_to_gcs
from python_files.gcs_to_google_drive import transfer_gcs_to_google_drive


def run_export_flow() -> None:
    exported_uris = export_bigquery_to_gcs()
    for gcs_uri in exported_uris:
        transfer_gcs_to_google_drive(gcs_uri)
```

Keep credentials, bucket names, project IDs, and Drive folder IDs in Airflow
environment variables, Airflow Variables, or a secret backend. Do not hardcode
credentials in the DAG or Python modules.

<!-- ====================================================================== -->
<!-- Billing notes                                                          -->
<!-- ====================================================================== -->

## Billing Notes

BigQuery query processing is charged to `BQ_PROJECT_ID`, because the BigQuery
client runs the export query job from that project.

Cloud Storage object storage and object operations are associated with the GCS
bucket/project configured by `GCS_PROJECT_ID` and `GCS_BUCKET_NAME`.

With `DELETE_GCS_AFTER_DRIVE_UPLOAD=true`, the final uploaded CSV is deleted
from GCS only after the Google Drive upload succeeds. If this is set to `false`,
the final CSV stays in GCS and storage cost continues until the object is
deleted.
