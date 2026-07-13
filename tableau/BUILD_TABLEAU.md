# Tableau Close Scorecard — build & publish guide (~15 minutes)

The same close scorecard as the Power BI report, rebuilt in Tableau to show
tool range. Data prep is scripted; the workbook build below is deliberately
click-by-click so the result is native, idiomatic Tableau.

## 0. Prepare the data

```bash
python engine/run_reconciliation.py
python tableau/prepare_tableau_data.py
```

Produces two flat extracts in this folder:
- `control_totals_tableau.csv` — account × period with ERP/subledger totals,
  variance, and an `out_of_tolerance` flag (0.5% materiality, precomputed)
- `exceptions_tableau.csv` — exception log with `impact_amount`
  (ABS(COALESCE(variance, erp_amount)), precomputed)

## 1. Connect (Tableau Desktop 2024.1)

1. **Connect → Text file** → `control_totals_tableau.csv`.
2. **Add** a second connection → `exceptions_tableau.csv` (keep as a
   separate data source — the sheets don't blend).

## 2. Sheets

**Sheet 1 — "Variance by Account"** (bar)
- Rows: `Account Name` · Columns: `SUM(Variance Amount)`
- Color: `MAX(Out Of Tolerance)` — set 1 to red `#C0392B`, 0 to navy `#12436D`
- Sort descending by variance; label bars, format as currency.

**Sheet 2 — "Match Rate KPI"** (text/KPI)
- Data source: exceptions. Create calculated fields:
  - `Total Exceptions` = `COUNT([Transaction Id])`
  - (On the control-totals source) `Match Rate` = `1 - [Total Exceptions] / 20000`
    *(20,000 = ERP transaction count — or blend to compute it live)*
- Show as a big-number text mark.

**Sheet 3 — "Exception Impact by Type"** (bar)
- Rows: `Exception Type` · Columns: `SUM(Impact Amount)`
- Color: `Exception Type` (theme palette below); sort descending.

**Sheet 4 — "Variance Trend"** (line)
- Columns: `Period` · Rows: `SUM(Variance Amount)` (control-totals source)

## 3. Dashboard — "GL Close Scorecard"

- Size: 1280 × 720. Layout: KPI top-left, Variance by Account left,
  Impact by Type top-right, Trend bottom-right.
- Add `Period` as a global filter (applies to both data sources via
  "All Using Related Data Sources").

Theme (matches the portfolio's Meridian palette):
`#12436D` navy · `#28A197` teal · `#F46A25` orange · `#801650` plum ·
background `#F4F6F9` · Segoe UI Semibold titles.

## 4. Publish to Tableau Public

Server → Tableau Public → Save to Tableau Public As… (free account) →
copy the public URL into the repo README badge/link. Tableau Public
requires an extract: it will convert the text connections automatically.

## Why a guide and not a committed .twbx?

A packaged workbook pins absolute local paths and bloats the repo with a
binary diff on every save. The scripted extracts + this guide reproduce the
workbook anywhere in minutes, which is the more honest engineering artifact —
and the published Tableau Public link (step 4) is the showcase.
