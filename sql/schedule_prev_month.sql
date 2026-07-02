-- =============================================================================
-- Scheduled COA extract query
-- =============================================================================

SELECT *
FROM `prod-shared-dwh01.RptViews_Global.mvw_coa_global_store_sku_sales_month`
WHERE COUNTRYCODE = '{COUNTRYCODE}'

-- Automatically handles year rollover (e.g. 1 Jan 2027 returns YEARID = 2026)
AND YEARID = EXTRACT(YEAR FROM DATE_SUB(CURRENT_DATE(), INTERVAL 1 MONTH))

-- Always returns the previous calendar month (e.g. any date in July returns MONTHID = 6)
AND MONTHID = EXTRACT(MONTH FROM DATE_SUB(CURRENT_DATE(), INTERVAL 1 MONTH))
