# Schedule Run Scripts

Scheduled previous-month flow for `sql/schedule_prev_month.sql`.

<!-- ====================================================================== -->
<!-- Parameters                                                             -->
<!-- ====================================================================== -->

## Parameters

```text
COUNTRYCODE
```

`YEARID` and `MONTHID` are calculated in SQL using the previous calendar month.

<!-- ====================================================================== -->
<!-- Commands                                                               -->
<!-- ====================================================================== -->

## Commands

BigQuery to GCS:

```powershell
python python_files\schedule_run_script\schedule_bigquery_to_gcs.py --countrycode BD
```

GCS to Google Drive:

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

Keep credentials and project settings in `.env` or Airflow 3.x configuration.

When `COMPOSE_GCS_SHARDS=true`, CSV shards are combined into one final file.
