"""Execute the complete BigQuery to GCS to Google Drive flow."""

# =============================================================================
# Flow imports
# =============================================================================

from bigquery_to_gcs import export_bigquery_to_gcs
from gcs_to_google_drive import transfer_gcs_to_google_drive


# =============================================================================
# Complete flow
# =============================================================================

def main() -> None:
    """Run step 1, then pass every generated GCS URI to step 2."""

    gcs_uris = export_bigquery_to_gcs()
    for gcs_uri in gcs_uris:
        transfer_gcs_to_google_drive(gcs_uri)


# =============================================================================
# Script entry point
# =============================================================================

if __name__ == "__main__":
    main()
