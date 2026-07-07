"""
Synthetic data generator for the GL/P&L Reconciliation Dashboard project.

Simulates a common finance-ops problem: the same underlying transactions
exist in two source systems (an ERP general ledger and a subledger/AP
feed) that are supposed to tie out but don't, due to timing differences,
missing postings, amount mismatches, and duplicates. The SQL in
sql/reconciliation_checks.sql detects and quantifies these discrepancies.

Usage:
    python generate_gl_data.py
"""

import numpy as np
import pandas as pd
from faker import Faker
from pathlib import Path

fake = Faker()
Faker.seed(7)
np.random.seed(7)

OUT_DIR = Path(__file__).resolve().parent.parent / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PERIODS = pd.period_range("2025-01", "2025-06", freq="M")

ACCOUNTS = [
    # account_code, account_name, account_type, statement
    ("4000", "Product Revenue", "Revenue", "P&L"),
    ("4010", "Service Revenue", "Revenue", "P&L"),
    ("5000", "COGS - Materials", "COGS", "P&L"),
    ("5010", "COGS - Freight", "COGS", "P&L"),
    ("6000", "Salaries & Wages", "OpEx", "P&L"),
    ("6010", "Rent & Facilities", "OpEx", "P&L"),
    ("6020", "Marketing", "OpEx", "P&L"),
    ("6030", "IT & Software", "OpEx", "P&L"),
    ("1000", "Accounts Receivable", "Asset", "Balance Sheet"),
    ("2000", "Accounts Payable", "Liability", "Balance Sheet"),
]

COST_CENTERS = ["Sales", "Operations", "Finance", "Supply Chain", "IT", "Marketing"]
N_TRANSACTIONS_PER_MONTH = 900


def gen_dim_account():
    rows = [
        {"account_id": i + 1, "account_code": code, "account_name": name,
         "account_type": atype, "statement": stmt}
        for i, (code, name, atype, stmt) in enumerate(ACCOUNTS)
    ]
    return pd.DataFrame(rows)


def gen_dim_cost_center():
    return pd.DataFrame([
        {"cost_center_id": i + 1, "cost_center_name": cc}
        for i, cc in enumerate(COST_CENTERS)
    ])


def gen_source_erp(accounts: pd.DataFrame, cost_centers: pd.DataFrame):
    """The ERP GL is treated as the source of truth."""
    rows = []
    txn_id = 1
    for period in PERIODS:
        for _ in range(N_TRANSACTIONS_PER_MONTH):
            account = accounts.sample(1).iloc[0]
            cost_center = cost_centers.sample(1).iloc[0]
            sign = -1 if account["account_type"] in ("Revenue", "Liability") else 1
            # Revenue/liability amounts stored as negative per double-entry convention
            amount = round(sign * abs(np.random.lognormal(mean=7.5, sigma=1.1)), 2)
            posted_date = fake.date_between_dates(
                date_start=period.start_time, date_end=period.end_time
            )
            rows.append({
                "transaction_id": f"ERP-{txn_id:06d}",
                "period": str(period),
                "account_id": account["account_id"],
                "cost_center_id": cost_center["cost_center_id"],
                "amount": amount,
                "posted_date": posted_date,
                "description": f"{account['account_name']} - {fake.bs()}",
            })
            txn_id += 1
    return pd.DataFrame(rows)


def gen_source_subledger(erp: pd.DataFrame):
    """
    Derived from ERP but with intentional discrepancies:
      ~1% missing (posted in subledger a period later -> timing difference)
      ~1% amount mismatch (data entry / FX rounding)
      ~1% duplicated
      ~97% clean matches
    """
    rows = []
    rand = np.random.random(len(erp))

    for idx, (_, txn) in enumerate(erp.iterrows()):
        r = rand[idx]
        row = txn.to_dict()
        row["transaction_id"] = txn["transaction_id"]  # same natural key, different source

        if r < 0.01:
            # Timing difference: shift to next period, will show up as "missing this period"
            next_period = (pd.Period(txn["period"]) + 1)
            if next_period <= PERIODS[-1]:
                row["period"] = str(next_period)
            rows.append(row)
        elif r < 0.02:
            # Amount mismatch: small data-entry/rounding error
            error_pct = np.random.choice([-1, 1]) * np.random.uniform(0.01, 0.15)
            row["amount"] = round(txn["amount"] * (1 + error_pct), 2)
            rows.append(row)
        elif r < 0.03:
            # Duplicate posting
            rows.append(row)
            dup = row.copy()
            dup["transaction_id"] = txn["transaction_id"] + "-DUP"
            rows.append(dup)
        elif r < 0.035:
            # Missing entirely (never made it to the subledger feed)
            continue
        else:
            rows.append(row)

    return pd.DataFrame(rows)


def main():
    accounts = gen_dim_account()
    cost_centers = gen_dim_cost_center()
    erp = gen_source_erp(accounts, cost_centers)
    subledger = gen_source_subledger(erp)

    accounts.to_csv(OUT_DIR / "dim_account.csv", index=False)
    cost_centers.to_csv(OUT_DIR / "dim_cost_center.csv", index=False)
    erp.to_csv(OUT_DIR / "source_erp_gl.csv", index=False)
    subledger.to_csv(OUT_DIR / "source_subledger_gl.csv", index=False)

    print(f"dim_account: {len(accounts)} rows")
    print(f"dim_cost_center: {len(cost_centers)} rows")
    print(f"source_erp_gl: {len(erp):,} rows (source of truth)")
    print(f"source_subledger_gl: {len(subledger):,} rows (contains intentional discrepancies)")
    print(f"\nWrote CSVs to {OUT_DIR}")


if __name__ == "__main__":
    main()
