# Start Guide

<!-- ====================================================================== -->
<!-- Python Environment Setup                                               -->
<!-- ====================================================================== -->

## Python Environment Setup

<!-- ====================================================================== -->
<!-- Create Virtual Environment                                             -->
<!-- ====================================================================== -->

### Create Virtual Environment First Time Only

```bash
python3 -m venv venv
```

<!-- ====================================================================== -->
<!-- Activate Virtual Environment                                           -->
<!-- ====================================================================== -->

### Activate Virtual Environment

```bash
source venv/bin/activate
```

After activation, your terminal should display:

```text
(venv) user@vm:~/project$
```

<!-- ====================================================================== -->
<!-- Install Dependencies                                                   -->
<!-- ====================================================================== -->

### Install Dependencies

```bash
pip install -r requirements.txt
```

<!-- ====================================================================== -->
<!-- Verify Installation                                                    -->
<!-- ====================================================================== -->

### Verify Installation

```bash
python --version
pip --version
```

<!-- ====================================================================== -->
<!-- Run The Project                                                        -->
<!-- ====================================================================== -->

### Run The Project

```bash
python <your_script>.py
```

Example manual full flow:

```bash
python python_files/manual_run_script/manual_execute_export_flow.py \
  --countrycode BN \
  --yearid 2026 \
  --monthid 5
```

Example scheduled full flow for one country:

```bash
python python_files/schedule_run_script/schedule_execute_export_flow.py \
  --countrycode BN
```

Example scheduled full flow for every country code in the config file:

```bash
python python_files/schedule_run_script/schedule_execute_export_flow.py \
  --country-code-file config/schedule_country_codes.txt
```

Run both for every country code in a file:

```powershell
python python_files\schedule_run_script\schedule_execute_export_flow.py --country-code-file config\schedule_country_codes.txt
```

Example scheduled full flow with log append:

```bash
python python_files/schedule_run_script/schedule_execute_export_flow.py \
  --countrycode BN \
  >> /opt/itsd/logs/coa_bq_gcs_gdrive.log 2>&1
```

<!-- ====================================================================== -->
<!-- Tail Logs                                                              -->
<!-- ====================================================================== -->

### Tail Logs

```bash
tail -f /opt/itsd/logs/coa_bq_gcs_gdrive.log
```

<!-- ====================================================================== -->
<!-- Exit Virtual Environment                                               -->
<!-- ====================================================================== -->

### Exit The Virtual Environment

```bash
deactivate
```

<!-- ====================================================================== -->
<!-- Returning To The Project Later                                         -->
<!-- ====================================================================== -->

## Returning To The Project Later

Whenever you reconnect to the VM, activate the virtual environment before
running the project:

```bash
cd /opt/itsd/coa_bq_gdrive/srd_bq_gdrive
source venv/bin/activate
```

You should then see:

```text
(venv) user@vm:~/srd_bq_gdrive$
```

You can now run any Python script using:

```bash
python <script_name>.py
```
