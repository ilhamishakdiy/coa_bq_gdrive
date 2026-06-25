# BigQuery to GCS to Google Drive

This project contains three standalone Python scripts:

1. `python_files/bigquery_to_gcs.py` exports BigQuery data to GCS and contains step logs.
2. `python_files/gcs_to_google_drive.py` transfers GCS files to Drive and contains step logs.
3. `python_files/execute_export_flow.py` calls step 1 and then step 2.

<!-- ====================================================================== -->
<!-- Environment configuration                                              -->
<!-- ====================================================================== -->

## Configuration

Copy the missing settings from `.env.example` into `.env`.

Use `service_account/service-account.example.json` only as a structure
reference. Store the real downloaded key under `service_account/`; real files
in that folder are ignored by Git.

BigQuery and Cloud Storage can be in separate Google Cloud projects:

```dotenv
BQ_PROJECT_ID=your-bigquery-project-id
GCS_PROJECT_ID=your-gcs-project-id
GCS_BUCKET_NAME=your-bucket-name
```

To execute every `.sql` file under the `sql` folder:

```dotenv
BQ_SQL_FOLDER=sql
```

Add as many SQL files as needed. Each SQL file is exported separately, and its
filename is included in the generated CSV object name.

`GCS_EXPORT_URI` is optional. If it is blank, the workflow generates a path
similar to:

```text
gs://your-bucket/exports/bigquery/bigquery_export_20250625T010203Z_*.csv
```

If you provide it, it must use the bucket from `GCS_BUCKET_NAME` and include
a wildcard:

```dotenv
GCS_EXPORT_URI=gs://your-bucket/exports/report_*.csv
```

The export format is CSV and uses a comma delimiter by default:

```dotenv
CSV_DELIMITER=,
```

You can change it to another single character, such as `|`, `;`, or `\t`.

GCS files are streamed directly to Google Drive without creating a complete
temporary local file. Memory usage is bounded by the configured chunk size:

```dotenv
STREAM_CHUNK_SIZE_MB=8
```

<!-- ====================================================================== -->
<!-- Google permissions                                                     -->
<!-- ====================================================================== -->

## Required permissions

The service account needs permission to:

- Run BigQuery jobs and read source data in the BigQuery project.
- Create and read objects in the GCS project bucket.
- Create files in the target Google Drive folder.

The BigQuery dataset and GCS bucket must use compatible locations for a
BigQuery export.

Share the Google Drive folder with the service account email found in its JSON
key. For Google Workspace, a Shared Drive folder is recommended because service
accounts do not have personal Drive storage quota.

<!-- ====================================================================== -->
<!-- Execution                                                              -->
<!-- ====================================================================== -->

## Run the complete flow

```powershell
python python_files/execute_export_flow.py
```

## Run an individual step

```powershell
python python_files/bigquery_to_gcs.py
python python_files/gcs_to_google_drive.py
```

Running `python_files/gcs_to_google_drive.py` directly requires
`GCS_EXPORT_URI` in `.env`.
The complete flow does not require it because step 1 passes the generated URI
directly to step 2.
