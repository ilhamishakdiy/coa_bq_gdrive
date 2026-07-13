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

Latest merged GCS file to Google Drive:

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

The country-code file supports one country code per line, comments with `#`,
blank lines, and comma-separated values.

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
