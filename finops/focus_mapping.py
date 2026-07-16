"""
The FOCUS -> engine mapping, as one importable module.

This file is the load-bearing artifact of FinOps mode: both the didactic
demo (focus_demo.py) and the scaled dataset (generate_focus_data.py /
run_finops_recon.py) import their mapping from here, so the documented
column table in finops/README.md has exactly one executable counterpart —
two copies of a mapping is how the two silently diverge.

System A (authoritative, engine role `source_erp_gl`) is the provider
invoice; System B (`source_subledger_gl`) is the internal chargeback
ledger. See finops/README.md for the column-by-column rationale.
"""

import json

import pandas as pd

# ServiceCategory -> cloud GL account (written to staging dim_account.csv)
ACCOUNTS = {
    "Compute":               (61, "6100", "Cloud - Compute"),
    "Storage":               (62, "6110", "Cloud - Storage"),
    "Databases":             (63, "6120", "Cloud - Databases"),
    "Analytics":             (64, "6125", "Cloud - Analytics"),
    "Networking":            (65, "6128", "Cloud - Networking"),
    "Marketplace Software":  (66, "6130", "Cloud - Marketplace Software"),
    "Commitments":           (67, "6140", "Cloud - Commitment Purchases"),
}

COST_CENTERS = {
    "engineering": 71,
    "data-platform": 72,
    "marketing": 73,
    "finance-it": 74,
    "security": 75,
    "(unallocated)": 79,
}


def account_id(service_category: str) -> int:
    return ACCOUNTS[service_category][0]


def cost_center_id(department) -> int:
    return COST_CENTERS.get(department, COST_CENTERS["(unallocated)"])


def map_bill_to_erp(bill: pd.DataFrame) -> pd.DataFrame:
    """FOCUS billing export -> the engine's source_erp_gl schema."""
    return pd.DataFrame({
        "transaction_id": bill["x_ChargeId"],
        "period": bill["ChargePeriodStart"].str[:7],
        "account_id": bill["ServiceCategory"].map(account_id),
        "cost_center_id": bill["Tags"].map(
            lambda t: cost_center_id(json.loads(t).get("department"))),
        "amount": bill["BilledCost"],
        "posted_date": bill["ChargePeriodEnd"],
        "description": bill["ServiceName"] + " — " + bill["ChargeDescription"],
    })


def map_ledger_to_subledger(ledger: pd.DataFrame) -> pd.DataFrame:
    """Internal chargeback ledger -> the engine's source_subledger_gl schema."""
    return pd.DataFrame({
        "transaction_id": ledger["charge_id"],
        "period": ledger["billing_month"],
        "account_id": ledger["service_category"].map(account_id),
        "cost_center_id": ledger["department"].map(cost_center_id),
        "amount": ledger["allocated_amount"],
        "posted_date": ledger["allocation_date"],
        "description": ledger["memo"],
    })


def staging_dim_account() -> pd.DataFrame:
    return pd.DataFrame(
        [{"account_id": aid, "account_code": code, "account_name": name,
          "account_type": "Expense", "statement": "P&L"}
         for aid, code, name in ACCOUNTS.values()])


def write_staging(bill: pd.DataFrame, ledger: pd.DataFrame, staging_dir) -> None:
    staging_dir.mkdir(exist_ok=True)
    map_bill_to_erp(bill).to_csv(staging_dir / "source_erp_gl.csv", index=False)
    map_ledger_to_subledger(ledger).to_csv(staging_dir / "source_subledger_gl.csv", index=False)
    staging_dim_account().to_csv(staging_dir / "dim_account.csv", index=False)
