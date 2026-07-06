# COA BigQuery To GCS To Google Drive

Export COA data from BigQuery to GCS, compose CSV shards into one file, then
upload the final CSV to Google Drive.

<!-- ====================================================================== -->
<!-- Scripts                                                                -->
<!-- ====================================================================== -->

## Scripts

```text
python_files/manual_run_script/     Manual export with COUNTRYCODE, YEARID, MONTHID
python_files/schedule_run_script/   Previous-month export with COUNTRYCODE only
sql/manual_run.sql                  Manual SQL template
sql/schedule_prev_month.sql         Scheduled previous-month SQL template
```

<!-- ====================================================================== -->
<!-- Setup                                                                  -->
<!-- ====================================================================== -->

## Setup

Install dependencies:

```powershell
pip install -r requirements.txt
```

Create `.env` in the project root. Keep credentials and IDs there, not in code.

Required values:

```dotenv
GOOGLE_APPLICATION_CREDENTIALS=service_account/your-service-account.json
BQ_PROJECT_ID=your-bigquery-project-id
GCS_PROJECT_ID=your-gcs-project-id
GCS_BUCKET_NAME=your-gcs-bucket
DRIVE_FOLDER_ID=your-google-drive-folder-id
COMPOSE_GCS_SHARDS=true
STREAM_CHUNK_SIZE_MB=8
LARK_WEBHOOK_URL=your-lark-incoming-webhook-url
```

<!-- ====================================================================== -->
<!-- Output folder and filename                                             -->
<!-- ====================================================================== -->

## Output Folder And Filename

Each country uses its own folder in GCS and Google Drive.

GCS raw export shards are written under:

```text
gs://<GCS_BUCKET_NAME>/<GCS_OBJECT_PREFIX>/<COUNTRYCODE>/STORE_SKU_SALES_MONTH_<COUNTRYCODE>_<MM><YYYY>_<TIMESTAMP>_*.csv
```

GCS composed CSV files are written under:

```text
gs://<GCS_BUCKET_NAME>/<GCS_MERGED_OBJECT_PREFIX>/<COUNTRYCODE>/STORE_SKU_SALES_MONTH_<COUNTRYCODE>_<MM><YYYY>_<TIMESTAMP>.csv
```

Google Drive uploads go into a child folder named by country code under
`DRIVE_FOLDER_ID`:

```text
<DRIVE_FOLDER_ID>/<COUNTRYCODE>/
```

The GCS composed CSV filename format is:

```text
STORE_SKU_SALES_MONTH_<COUNTRYCODE>_<MM><YYYY>_<TIMESTAMP>.csv
```

The Google Drive CSV filename format is:

```text
STORE_SKU_SALES_MONTH_<COUNTRYCODE>_<MM><YYYY>.csv
```

Raw GCS export shards use the timestamped GCS filename stem with a BigQuery
wildcard suffix while they are waiting to be composed.
The resolved GCS shard folder is cleared after query validation and before each
BigQuery export starts.

`MONTHID` is always two digits. Values `1` to `9` become `01` to `09`;
values `10` to `12` stay as `10` to `12`.

Example for `COUNTRYCODE=BD`, `MONTHID=6`, and `YEARID=2026`:

```text
Google Drive: BD/STORE_SKU_SALES_MONTH_BD_062026.csv
GCS composed: BD/STORE_SKU_SALES_MONTH_BD_062026_20260703T120000Z.csv
```

<!-- ====================================================================== -->
<!-- Manual run                                                             -->
<!-- ====================================================================== -->

## Manual Run

Run BigQuery to GCS only:

```powershell
python python_files\manual_run_script\manual_bigquery_to_gcs.py --countrycode BD --yearid 2026 --monthid 6
```

Run latest merged GCS file to Google Drive only:

```powershell
python python_files\manual_run_script\manual_gcs_to_google_drive.py --countrycode BD --yearid 2026 --monthid 6
```

Run both:

```powershell
python python_files\manual_run_script\manual_execute_export_flow.py --countrycode BD --yearid 2026 --monthid 6
```

<!-- ====================================================================== -->
<!-- Schedule run                                                           -->
<!-- ====================================================================== -->

## Schedule Run

Run BigQuery to GCS only:

```powershell
python python_files\schedule_run_script\schedule_bigquery_to_gcs.py --countrycode BD
```

Run latest merged GCS file to Google Drive only:

```powershell
python python_files\schedule_run_script\schedule_gcs_to_google_drive.py --countrycode BD
```

Run both:

```powershell
python python_files\schedule_run_script\schedule_execute_export_flow.py --countrycode BD
```

Run both for every country code in a file:

```powershell
python python_files\schedule_run_script\schedule_execute_export_flow.py --country-code-file config\schedule_country_codes.txt
```

<!-- ====================================================================== -->
<!-- Notes                                                                  -->
<!-- ====================================================================== -->

## Notes

BigQuery exports CSV shards first. When `COMPOSE_GCS_SHARDS=true`, the scripts
compose those shards into one final CSV before upload.
Google Drive uploads stream from GCS with `STREAM_CHUNK_SIZE_MB=8` by default.
When `LARK_WEBHOOK_URL` is set, each manual or scheduled country run sends a
`coa_bq_to_gdrive` summary card with BigQuery-to-GCS and GCS-to-Drive status.

For Airflow 3.x, import the `execute_*_export_flow` functions and keep secrets
in environment variables, Airflow Variables, or a secret backend.
