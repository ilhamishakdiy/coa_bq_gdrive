# Manual Run Scripts

Manual flow for `sql/manual_run.sql`.

<!-- ====================================================================== -->
<!-- Parameters                                                             -->
<!-- ====================================================================== -->

## Parameters

```text
COUNTRYCODE
YEARID
MONTHID
```

<!-- ====================================================================== -->
<!-- Commands                                                               -->
<!-- ====================================================================== -->

## Commands

BigQuery to GCS:

```powershell
python python_files\manual_run_script\manual_bigquery_to_gcs.py --countrycode BD --yearid 2026 --monthid 6
```

GCS to Google Drive:

```powershell
python python_files\manual_run_script\manual_gcs_to_google_drive.py --gcs-uri gs://your-bucket/path/file.csv
```

Run both:

```powershell
python python_files\manual_run_script\manual_execute_export_flow.py --countrycode BD --yearid 2026 --monthid 6
```

<!-- ====================================================================== -->
<!-- Notes                                                                  -->
<!-- ====================================================================== -->

## Notes

Keep credentials and project settings in `.env` or Airflow 3.x configuration.

When `COMPOSE_GCS_SHARDS=true`, CSV shards are combined into one final file.
