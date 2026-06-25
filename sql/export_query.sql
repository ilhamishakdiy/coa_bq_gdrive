-- ============================================================================
-- BigQuery export query
-- ============================================================================

SELECT
    M_PLUCODE,
    M_BARCODE,
    M_ODESC,
    M_UNITCOST
FROM
    `prod-shared-dwh01.ds_dwh01_test.mvw_coa_bd_mas_stock`;
