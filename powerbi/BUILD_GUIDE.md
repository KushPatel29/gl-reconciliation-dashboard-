# Power BI Build Guide — GL/P&L Reconciliation Dashboard

## 1. Load data

Run `sql/reconciliation_checks.sql` against a database with `stg_erp_gl` and
`stg_subledger_gl` loaded from the generated CSVs (SQL Server, Fabric
Warehouse, or even SQLite for a quick local test). This produces the tables
Power BI actually connects to:

- `gl_control_totals` — account × period totals from both sources + variance
- `gl_reconciliation_exceptions` — the consolidated exception log
- `dim_account`, `dim_cost_center` — load these directly from their CSVs

Get Data → SQL Server (or your DB of choice) → Import mode → select the
tables above.

## 2. Relationships

`dim_account[account_id]` → `gl_control_totals[account_id]` (1:*)
`dim_account[account_id]` → `gl_reconciliation_exceptions[account_id]` (1:*)

Add a simple `dim_period` table (one row per `YYYY-MM` in the data) and
relate it to both fact tables on `period` for clean month-over-month
slicing — flat text-based period sorting looks wrong in a chart otherwise.

## 3. Report pages

1. **Close Scorecard** — cards: Match Rate, Total Exceptions, Exception
   Dollar Impact, Accounts Out of Tolerance. This is the page a controller
   opens first each month-end.
2. **Variance by Account** — matrix of ERP Total vs Subledger Total vs
   Variance % by account, conditional-formatted red when `Is Out of
   Tolerance = 1`. Drillthrough to the exception list for that account.
3. **Exception Detail** — table of `gl_reconciliation_exceptions` grouped by
   `exception_type`, with a slicer for period/account. This is where the
   analyst does root-cause triage.
4. **Close Insights** — match-rate gauge vs the 98% SLA, variance waterfall
   by account, exception mix and impact trend — whether reconciliation
   health is improving or degrading over time.
5. **Cloud Chargeback (FinOps)** — the same engine run on a FOCUS-shaped
   cloud bill: billed spend, allocation coverage %, untagged dollars,
   exception mix, and the FINOPS-REC-01 evidence list (see `finops/`).

## 4. Why this matters for the interview story

Walk through a screenshot of the Variance by Account page and be ready to
explain, in plain language: "the ERP is source of truth; the subledger feed
had a 0.7% gap this month, mostly from duplicate postings in the Sales cost
center — here's the exception list I'd hand to the AP team to correct." That
narrative — not the DAX — is what a hiring manager is actually screening for.

## 5. Publish

Publish to the Power BI Service, get a shareable link, add it to the repo
README.
