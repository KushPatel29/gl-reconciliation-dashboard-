"""
FinOps reconciliation run — the scaled FOCUS dataset through the unmodified
engine, plus the one KPI reconciliation alone doesn't give you: allocation
coverage.

Coverage is the FinOps allocation metric — what share of each month's
billed cloud spend actually reached a cost-center owner. A charge line is
"allocated" iff its charge id appears in the chargeback ledger; untagged
resources don't, and they are exactly the gap between the invoice total and
what chargeback can see.

Outputs (finops/output/):
    gl_control_totals.csv             cloud account x month, billed vs allocated
    gl_reconciliation_exceptions.csv  the categorized cloud exception log
    allocation_coverage.csv           month, billed, allocated, untagged, coverage %
    summary.txt                       engine summary (written by the engine)

Run generate_focus_data.py first. The engine module is imported verbatim
and repointed at the mapped staging files — no engine code is touched.

Usage:
    python finops/run_finops_recon.py
"""

import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
STAGING = HERE / "staging"
FINOPS_OUT = HERE / "output"

sys.path.insert(0, str(HERE))
from focus_mapping import write_staging  # noqa: E402


def run_engine_unmodified() -> dict:
    sys.path.insert(0, str(ROOT / "engine"))
    import run_reconciliation as engine

    FINOPS_OUT.mkdir(exist_ok=True)
    saved = (engine.DATA, engine.OUT)
    engine.DATA, engine.OUT = STAGING, FINOPS_OUT
    try:
        return engine.main()
    finally:
        engine.DATA, engine.OUT = saved


def allocation_coverage(bill: pd.DataFrame, ledger: pd.DataFrame) -> pd.DataFrame:
    allocated_ids = set(ledger["charge_id"].str.replace(r"-DUP$", "", regex=True))
    b = bill.assign(month=bill["ChargePeriodStart"].str[:7],
                    allocated=bill["x_ChargeId"].isin(allocated_ids))
    cov = (b.groupby("month")
             .apply(lambda g: pd.Series({
                 "billed_total": g["BilledCost"].sum(),
                 "allocated_total": g.loc[g["allocated"], "BilledCost"].sum(),
                 "untagged_total": g.loc[~g["allocated"], "BilledCost"].sum(),
             }), include_groups=False)
             .reset_index())
    cov["coverage_pct"] = (cov["allocated_total"] / cov["billed_total"]).round(4)
    for c in ("billed_total", "allocated_total", "untagged_total"):
        cov[c] = cov[c].round(2)
    return cov


def main() -> dict:
    bill = pd.read_csv(HERE / "focus_billing_export.csv")
    ledger = pd.read_csv(HERE / "chargeback_ledger.csv")

    write_staging(bill, ledger, STAGING)
    result = run_engine_unmodified()

    cov = allocation_coverage(bill, ledger)
    cov.to_csv(FINOPS_OUT / "allocation_coverage.csv", index=False)

    print("\nALLOCATION COVERAGE (the FinOps allocation KPI)")
    print("=" * 56)
    for _, r in cov.iterrows():
        print(f"  {r['month']}   billed ${r['billed_total']:>12,.2f}   "
              f"untagged ${r['untagged_total']:>9,.2f}   "
              f"coverage {r['coverage_pct']:>7.2%}")
    total_cov = cov["allocated_total"].sum() / cov["billed_total"].sum()
    print("=" * 56)
    print(f"  Overall coverage: {total_cov:.2%} "
          f"(target in most FinOps maturity models: >= 90% tagged/allocated)")

    result["coverage"] = cov
    return result


if __name__ == "__main__":
    main()
