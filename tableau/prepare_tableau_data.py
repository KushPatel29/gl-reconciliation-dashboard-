"""
Prepare denormalized extracts for the Tableau version of the close scorecard.

Tableau (unlike the Power BI semantic model) gets flat, analysis-ready
tables: control totals enriched with account attributes, and the exception
log enriched the same way. Run after the reconciliation engine:

    python engine/run_reconciliation.py
    python tableau/prepare_tableau_data.py
"""

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent


def load(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    accounts = {r["account_id"]: r for r in load(ROOT / "data" / "dim_account.csv")}

    controls = load(ROOT / "output" / "gl_control_totals.csv")
    with open(OUT / "control_totals_tableau.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["account_code", "account_name", "account_type", "statement",
                    "period", "erp_total", "subledger_total", "variance_amount",
                    "variance_pct", "out_of_tolerance"])
        for r in controls:
            a = accounts[r["account_id"]]
            oot = abs(float(r["variance_pct"])) > 0.005
            w.writerow([a["account_code"], a["account_name"], a["account_type"],
                        a["statement"], r["period"],
                        round(float(r["erp_total"]), 2),
                        round(float(r["subledger_total"]), 2),
                        round(float(r["variance_amount"]), 2),
                        round(float(r["variance_pct"]), 6), int(oot)])

    exceptions = load(ROOT / "output" / "gl_reconciliation_exceptions.csv")
    with open(OUT / "exceptions_tableau.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["transaction_id", "account_code", "account_name", "account_type",
                    "period", "exception_type", "erp_amount", "variance_amount",
                    "impact_amount"])
        for r in exceptions:
            a = accounts[r["account_id"]]
            impact = r["variance_amount"] or r["erp_amount"] or "0"
            w.writerow([r["transaction_id"], a["account_code"], a["account_name"],
                        a["account_type"], r["period"], r["exception_type"],
                        r["erp_amount"], r["variance_amount"],
                        abs(float(impact))])

    print(f"wrote control_totals_tableau.csv ({len(controls)} rows), "
          f"exceptions_tableau.csv ({len(exceptions)} rows) -> {OUT}")


if __name__ == "__main__":
    main()
