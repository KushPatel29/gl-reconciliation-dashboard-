-- =====================================================================
-- GL / Subledger Reconciliation — T-SQL (Fabric Warehouse / SQL Server)
--
-- Assumes source_erp_gl.csv and source_subledger_gl.csv have been loaded
-- into staging tables `stg_erp_gl` and `stg_subledger_gl` with the same
-- columns as the CSVs. The ERP GL is treated as the source of truth;
-- the subledger feed is reconciled against it.
-- =====================================================================

-- ---------- 0. Normalize duplicates ----------
-- The generator tags duplicate postings with a '-DUP' suffix on the
-- transaction_id so they're traceable back to the original. Strip it here
-- to get the "base" transaction id for matching, but keep the raw table
-- around so the duplicate-count check below still sees both rows.

DROP TABLE IF EXISTS stg_subledger_gl_normalized;
SELECT
    *,
    CASE
        WHEN transaction_id LIKE '%-DUP' THEN LEFT(transaction_id, LEN(transaction_id) - 4)
        ELSE transaction_id
    END AS base_transaction_id
INTO stg_subledger_gl_normalized
FROM stg_subledger_gl;

-- ---------- 1. Control totals by account + period ----------
-- The first-line health check: do source and subledger tie out in
-- aggregate? Large dollar variance here is the trigger to drill into the
-- row-level checks below.

DROP TABLE IF EXISTS gl_control_totals;
SELECT
    COALESCE(e.account_id, s.account_id)   AS account_id,
    COALESCE(e.period, s.period)           AS period,
    ISNULL(e.erp_total, 0)                 AS erp_total,
    ISNULL(s.subledger_total, 0)           AS subledger_total,
    ISNULL(s.subledger_total, 0) - ISNULL(e.erp_total, 0) AS variance_amount,
    CASE WHEN ISNULL(e.erp_total, 0) = 0 THEN NULL
         ELSE (ISNULL(s.subledger_total, 0) - ISNULL(e.erp_total, 0)) / ABS(e.erp_total)
    END AS variance_pct
INTO gl_control_totals
FROM (
    SELECT account_id, period, SUM(amount) AS erp_total
    FROM stg_erp_gl
    GROUP BY account_id, period
) e
FULL OUTER JOIN (
    SELECT account_id, period, SUM(amount) AS subledger_total
    FROM stg_subledger_gl_normalized
    GROUP BY account_id, period
) s
    ON e.account_id = s.account_id AND e.period = s.period;

-- ---------- 2. Missing transactions (in ERP, absent from subledger) ----------

DROP TABLE IF EXISTS gl_exceptions_missing;
SELECT
    e.transaction_id,
    e.account_id,
    e.period,
    e.amount,
    'Missing in subledger' AS exception_type
INTO gl_exceptions_missing
FROM stg_erp_gl e
LEFT JOIN stg_subledger_gl_normalized s
    ON e.transaction_id = s.base_transaction_id AND e.period = s.period
WHERE s.base_transaction_id IS NULL;

-- ---------- 3. Timing differences (same transaction id, different period) ----------

DROP TABLE IF EXISTS gl_exceptions_timing;
SELECT
    e.transaction_id,
    e.account_id,
    e.period       AS erp_period,
    s.period       AS subledger_period,
    e.amount,
    'Timing difference' AS exception_type
INTO gl_exceptions_timing
FROM stg_erp_gl e
INNER JOIN stg_subledger_gl_normalized s
    ON e.transaction_id = s.base_transaction_id
WHERE e.period <> s.period;

-- ---------- 4. Amount mismatches (same transaction + period, different amount) ----------

DROP TABLE IF EXISTS gl_exceptions_amount_mismatch;
SELECT
    e.transaction_id,
    e.account_id,
    e.period,
    e.amount        AS erp_amount,
    s.amount        AS subledger_amount,
    s.amount - e.amount AS variance_amount,
    'Amount mismatch' AS exception_type
INTO gl_exceptions_amount_mismatch
FROM stg_erp_gl e
INNER JOIN stg_subledger_gl_normalized s
    ON e.transaction_id = s.base_transaction_id AND e.period = s.period
WHERE ABS(e.amount - s.amount) > 0.01;  -- tolerance: ignore sub-cent rounding noise

-- ---------- 5. Duplicate postings in subledger ----------

DROP TABLE IF EXISTS gl_exceptions_duplicates;
SELECT
    base_transaction_id AS transaction_id,
    account_id,
    period,
    COUNT(*) AS posting_count,
    SUM(amount) AS total_posted_amount,
    'Duplicate posting' AS exception_type
INTO gl_exceptions_duplicates
FROM stg_subledger_gl_normalized
GROUP BY base_transaction_id, account_id, period
HAVING COUNT(*) > 1;

-- ---------- 6. Consolidated exception log (feeds the Power BI dashboard) ----------

DROP TABLE IF EXISTS gl_reconciliation_exceptions;
SELECT transaction_id, account_id, CAST(period AS VARCHAR(10)) AS period,
       exception_type, amount AS erp_amount, CAST(NULL AS DECIMAL(18,2)) AS variance_amount
INTO gl_reconciliation_exceptions
FROM gl_exceptions_missing

UNION ALL
SELECT transaction_id, account_id, CAST(erp_period AS VARCHAR(10)), exception_type,
       amount, NULL
FROM gl_exceptions_timing

UNION ALL
SELECT transaction_id, account_id, CAST(period AS VARCHAR(10)), exception_type,
       erp_amount, variance_amount
FROM gl_exceptions_amount_mismatch

UNION ALL
SELECT transaction_id, account_id, CAST(period AS VARCHAR(10)), exception_type,
       total_posted_amount, NULL
FROM gl_exceptions_duplicates;

-- ---------- 7. Summary — what a reconciliation analyst checks first ----------

SELECT
    exception_type,
    COUNT(*) AS exception_count,
    SUM(ISNULL(variance_amount, erp_amount)) AS total_dollar_impact
FROM gl_reconciliation_exceptions
GROUP BY exception_type
ORDER BY exception_count DESC;
