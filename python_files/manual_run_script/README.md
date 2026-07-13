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

Latest merged GCS file to Google Drive:

```powershell
python python_files\manual_run_script\manual_gcs_to_google_drive.py --countrycode BD --yearid 2026 --monthid 6
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
The GCS shard folder is cleared before each successful BigQuery export starts.
The final GCS filename uses `GCS_FILE_NAME_TEMPLATE`.
The final Google Drive filename uses `DRIVE_FILE_NAME_TEMPLATE`.
`PIPELINE_NAME` can be reused inside both templates.
