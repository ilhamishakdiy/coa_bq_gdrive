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
DEPARTMENT=COA
PIPELINE_NAME=STORE_SKU_SALES_MONTH
PIPELINE_DISPLAY_NAME_TEMPLATE={DEPARTMENT}: {PIPELINE_NAME}
GCS_FILE_NAME_TEMPLATE={PIPELINE_NAME}_{COUNTRYCODE}_{MM}{YYYY}_{TIMESTAMP}.csv
DRIVE_FILE_NAME_TEMPLATE={PIPELINE_NAME}_{COUNTRYCODE}_{MM}{YYYY}.csv
COMPOSE_GCS_SHARDS=true
STREAM_CHUNK_SIZE_MB=8
INTERNAL_LARK_WEBHOOK_URL=your-internal-lark-incoming-webhook-url
USER_LARK_WEBHOOK_URL=your-user-lark-incoming-webhook-url
LARK_TABLE_PAGE_SIZE=
```

<!-- ====================================================================== -->
<!-- Lark notification modules                                              -->
<!-- ====================================================================== -->

## Lark Notification Modules

Lark delivery is split from message formatting so other projects can reuse the
same webhook sender with different message builders.

Use `python_files/lark_delivery.py` to send any prepared Lark payload:

```python
from lark_delivery import send_lark_payload

send_lark_payload(payload=my_lark_payload, notification_name="My notification")
```

Use `python_files/lark_notification.py` only for this pipeline's summary card:

```python
from lark_notification import send_lark_pipeline_notification
```

Set `LARK_TABLE_PAGE_SIZE` when the Lark summary table should paginate at a
fixed row count. Leave it blank to show all rows on one table page.

<!-- ====================================================================== -->
<!-- Output folder and filename                                             -->
<!-- ====================================================================== -->

## Output Folder And Filename

Each country uses its own folder in GCS and Google Drive.

`DEPARTMENT` and `PIPELINE_NAME` control the Lark card title through
`PIPELINE_DISPLAY_NAME_TEMPLATE`, which defaults to
`{DEPARTMENT}: {PIPELINE_NAME}`. They can also be reused inside the filename
templates. Supported filename placeholders are `{DEPARTMENT}`,
`{PIPELINE_NAME}`, `{COUNTRYCODE}`, `{MM}`, `{YYYY}`, `{MONTHID}`, `{YEARID}`,
and `{TIMESTAMP}`.

GCS raw export shards are written under:

```text
gs://<GCS_BUCKET_NAME>/<GCS_OBJECT_PREFIX>/<COUNTRYCODE>/<GCS_FILE_NAME_TEMPLATE stem>_*.csv
```

GCS composed CSV files are written under:

```text
gs://<GCS_BUCKET_NAME>/<GCS_MERGED_OBJECT_PREFIX>/<COUNTRYCODE>/<GCS_FILE_NAME_TEMPLATE>
```

Google Drive uploads go into a child folder named by country code under
`DRIVE_FOLDER_ID`:

```text
<DRIVE_FOLDER_ID>/<COUNTRYCODE>/
```

The default GCS composed CSV filename format is:

```text
STORE_SKU_SALES_MONTH_<COUNTRYCODE>_<MM><YYYY>_<TIMESTAMP>.csv
```

The default Google Drive CSV filename format is:

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

Run BigQuery to GCS only and append output to the VM log file:

```bash
# =============================================================================
# Manual BigQuery to GCS run with log append
# =============================================================================

python python_files/manual_run_script/manual_bigquery_to_gcs.py \
  --countrycode BN \
  --yearid 2026 \
  --monthid 4 \
  >> /opt/itsd/logs/coa_bq_gcs_gdrive.log 2>&1
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
When `INTERNAL_LARK_WEBHOOK_URL` or `USER_LARK_WEBHOOK_URL` is set, each manual
or scheduled country run sends a summary card with BigQuery-to-GCS and
GCS-to-Drive status to every configured webhook. `LARK_WEBHOOK_URL` remains as
a backward-compatible fallback.

For Airflow 3.x, import the `execute_*_export_flow` functions and keep secrets
in environment variables, Airflow Variables, or a secret backend.
