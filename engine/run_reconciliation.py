"""
Local reconciliation engine — runs the full GL/subledger reconciliation
end-to-end with no database required, using SQLite as the SQL engine so
the logic stays in actual SQL (translated from sql/reconciliation_checks.sql,
which remains the T-SQL reference for SQL Server / Fabric Warehouse).

Outputs, written to output/:
    gl_control_totals.csv             account x period totals + variance
    gl_reconciliation_exceptions.csv  consolidated categorized exception log
    summary.txt                       exception counts + dollar impact

Usage:
    python engine/run_reconciliation.py
"""

import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "output"
OUT.mkdir(exist_ok=True)


def load_staging(conn: sqlite3.Connection) -> None:
    pd.read_csv(DATA / "source_erp_gl.csv").to_sql("stg_erp_gl", conn, index=False)
    pd.read_csv(DATA / "source_subledger_gl.csv").to_sql("stg_subledger_gl", conn, index=False)
    pd.read_csv(DATA / "dim_account.csv").to_sql("dim_account", conn, index=False)


# SQLite translation of sql/reconciliation_checks.sql — same checks, same
# names, adapted syntax (no SELECT INTO / ISNULL; SQLite uses CREATE TABLE
# AS / COALESCE).
RECONCILIATION_SQL = """
CREATE TABLE stg_subledger_gl_normalized AS
SELECT *,
       CASE WHEN transaction_id LIKE '%-DUP'
            THEN substr(transaction_id, 1, length(transaction_id) - 4)
            ELSE transaction_id END AS base_transaction_id
FROM stg_subledger_gl;

CREATE TABLE gl_control_totals AS
SELECT
    COALESCE(e.account_id, s.account_id) AS account_id,
    COALESCE(e.period, s.period)         AS period,
    COALESCE(e.erp_total, 0)             AS erp_total,
    COALESCE(s.subledger_total, 0)       AS subledger_total,
    COALESCE(s.subledger_total, 0) - COALESCE(e.erp_total, 0) AS variance_amount,
    CASE WHEN COALESCE(e.erp_total, 0) = 0 THEN NULL
         ELSE (COALESCE(s.subledger_total, 0) - COALESCE(e.erp_total, 0)) / ABS(e.erp_total)
    END AS variance_pct
FROM (SELECT account_id, period, SUM(amount) AS erp_total
      FROM stg_erp_gl GROUP BY account_id, period) e
LEFT JOIN (SELECT account_id, period, SUM(amount) AS subledger_total
           FROM stg_subledger_gl_normalized GROUP BY account_id, period) s
    ON e.account_id = s.account_id AND e.period = s.period;

CREATE TABLE gl_exceptions_missing AS
SELECT e.transaction_id, e.account_id, e.period, e.amount,
       'Missing in subledger' AS exception_type
FROM stg_erp_gl e
LEFT JOIN stg_subledger_gl_normalized s
    ON e.transaction_id = s.base_transaction_id AND e.period = s.period
WHERE s.base_transaction_id IS NULL;

CREATE TABLE gl_exceptions_timing AS
SELECT e.transaction_id, e.account_id, e.period AS erp_period,
       s.period AS subledger_period, e.amount,
       'Timing difference' AS exception_type
FROM stg_erp_gl e
JOIN stg_subledger_gl_normalized s ON e.transaction_id = s.base_transaction_id
WHERE e.period <> s.period;

CREATE TABLE gl_exceptions_amount_mismatch AS
SELECT e.transaction_id, e.account_id, e.period,
       e.amount AS erp_amount, s.amount AS subledger_amount,
       s.amount - e.amount AS variance_amount,
       'Amount mismatch' AS exception_type
FROM stg_erp_gl e
JOIN stg_subledger_gl_normalized s
    ON e.transaction_id = s.base_transaction_id AND e.period = s.period
WHERE ABS(e.amount - s.amount) > 0.01;

CREATE TABLE gl_exceptions_duplicates AS
SELECT base_transaction_id AS transaction_id, account_id, period,
       COUNT(*) AS posting_count, SUM(amount) AS total_posted_amount,
       'Duplicate posting' AS exception_type
FROM stg_subledger_gl_normalized
GROUP BY base_transaction_id, account_id, period
HAVING COUNT(*) > 1;

CREATE TABLE gl_reconciliation_exceptions AS
SELECT transaction_id, account_id, period, exception_type,
       amount AS erp_amount, NULL AS variance_amount
FROM gl_exceptions_missing
UNION ALL
SELECT transaction_id, account_id, erp_period, exception_type, amount, NULL
FROM gl_exceptions_timing
UNION ALL
SELECT transaction_id, account_id, period, exception_type, erp_amount, variance_amount
FROM gl_exceptions_amount_mismatch
UNION ALL
SELECT transaction_id, account_id, period, exception_type, total_posted_amount, NULL
FROM gl_exceptions_duplicates;
"""


def main() -> dict:
    conn = sqlite3.connect(":memory:")
    load_staging(conn)
    conn.executescript(RECONCILIATION_SQL)

    control_totals = pd.read_sql("SELECT * FROM gl_control_totals", conn)
    exceptions = pd.read_sql("SELECT * FROM gl_reconciliation_exceptions", conn)
    summary = pd.read_sql(
        """
        SELECT exception_type,
               COUNT(*) AS exception_count,
               ROUND(SUM(COALESCE(variance_amount, erp_amount)), 2) AS total_dollar_impact
        FROM gl_reconciliation_exceptions
        GROUP BY exception_type
        ORDER BY exception_count DESC
        """,
        conn,
    )
    conn.close()

    control_totals.to_csv(OUT / "gl_control_totals.csv", index=False)
    exceptions.to_csv(OUT / "gl_reconciliation_exceptions.csv", index=False)

    lines = ["GL RECONCILIATION SUMMARY", "=" * 40]
    for _, row in summary.iterrows():
        lines.append(f"{row['exception_type']:<25} {row['exception_count']:>5}  "
                     f"${row['total_dollar_impact']:>14,.2f}")
    lines.append("=" * 40)
    lines.append(f"{'Total exceptions':<25} {len(exceptions):>5}")
    report = "\n".join(lines)
    (OUT / "summary.txt").write_text(report)
    print(report)
    print(f"\nOutputs written to {OUT}/ — point Power BI at these CSVs.")

    return {
        "control_totals": control_totals,
        "exceptions": exceptions,
        "summary": summary,
    }


if __name__ == "__main__":
    main()
