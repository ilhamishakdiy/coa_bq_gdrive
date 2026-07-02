-- =============================================================================
-- Manual COA extract query
-- =============================================================================

SELECT *
FROM `prod-shared-dwh01.RptViews_Global.mvw_coa_global_store_sku_sales_month`
WHERE COUNTRYCODE = '{COUNTRYCODE}'
AND YEARID = {YEARID}
AND MONTHID = {MONTHID}
