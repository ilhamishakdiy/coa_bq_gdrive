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
```

<!-- ====================================================================== -->
<!-- Manual run                                                             -->
<!-- ====================================================================== -->

## Manual Run

Run BigQuery to GCS only:

```powershell
python python_files\manual_run_script\manual_bigquery_to_gcs.py --countrycode BD --yearid 2026 --monthid 6
```

Run GCS to Google Drive only:

```powershell
python python_files\manual_run_script\manual_gcs_to_google_drive.py --gcs-uri gs://your-bucket/path/file.csv
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

Run GCS to Google Drive only:

```powershell
python python_files\schedule_run_script\schedule_gcs_to_google_drive.py --gcs-uri gs://your-bucket/path/file.csv
```

Run both:

```powershell
python python_files\schedule_run_script\schedule_execute_export_flow.py --countrycode BD
```

<!-- ====================================================================== -->
<!-- Notes                                                                  -->
<!-- ====================================================================== -->

## Notes

BigQuery exports CSV shards first. When `COMPOSE_GCS_SHARDS=true`, the scripts
compose those shards into one final CSV before upload.

For Airflow 3.x, import the `execute_*_export_flow` functions and keep secrets
in environment variables, Airflow Variables, or a secret backend.
