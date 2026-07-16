"""
FinOps demo — the GL reconciliation engine, unmodified, catching cloud-bill
anomalies in a FOCUS-shaped billing export.

The claim this script exists to prove: the four discrepancy classes this
repo detects between an ERP GL and a subledger are the same four failure
modes FinOps teams chase between a cloud provider invoice and the internal
chargeback ledger. Not by analogy — by execution. This script:

  1. Generates a small billing export shaped like the FinOps Foundation's
     FOCUS specification (BilledCost/ListCost/ContractedCost, ChargePeriod,
     ChargeCategory, ServiceCategory, Tags) plus the internal cost-center
     chargeback ledger a finance team would allocate from it.
  2. Plants exactly one instance of each cloud anomaly:
        untagged resource      -> line on the bill, absent from chargebacks
        upfront Savings Plan   -> billed in May, accrued by finance in June
        unapplied EDP discount -> billed at list price, allocated at the
                                  negotiated contracted cost
        marketplace double-bill-> SaaS charge allocated twice (bill + direct
                                  vendor invoice)
  3. Maps both files onto the engine's two staging schemas (the mapping IS
     the documentation — see finops/README.md for the column table).
  4. Points the UNCHANGED engine (engine/run_reconciliation.py) at the
     mapped files and lets it classify the anomalies. No engine code is
     touched; the module's data paths are redirected and main() is called.

Everything is seeded and deterministic; tests/test_finops_adapter.py
asserts each planted anomaly is caught with the right class and dollars.

Usage:
    python finops/focus_demo.py
"""

import json
import random
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
STAGING = HERE / "staging"
FINOPS_OUT = HERE / "output"

SEED = 29
MONTHS = [("2026-05", "2026-05-01", "2026-05-31"), ("2026-06", "2026-06-01", "2026-06-30")]

SERVICES = [
    # (ServiceName, ServiceCategory, ProviderName, monthly cost range)
    ("Amazon EC2", "Compute", "AWS", (800, 6000)),
    ("AWS Lambda", "Compute", "AWS", (50, 400)),
    ("Amazon S3", "Storage", "AWS", (200, 1500)),
    ("Amazon RDS", "Databases", "AWS", (900, 4200)),
    ("Amazon Redshift", "Analytics", "AWS", (1200, 5000)),
]
MARKETPLACE = [("Datadog Pro", "Datadog"), ("Snowflake Capacity", "Snowflake")]
DEPARTMENTS = ["engineering", "data-platform", "marketing"]

# ServiceCategory -> cloud GL account (finops/staging/dim_account.csv)
ACCOUNTS = {
    "Compute":               (61, "6100", "Cloud - Compute"),
    "Storage":               (62, "6110", "Cloud - Storage"),
    "Databases":             (63, "6120", "Cloud - Databases"),
    "Analytics":             (64, "6125", "Cloud - Analytics"),
    "Marketplace Software":  (65, "6130", "Cloud - Marketplace Software"),
    "Commitments":           (66, "6140", "Cloud - Commitment Purchases"),
}
COST_CENTERS = {"engineering": 71, "data-platform": 72, "marketing": 73, "(unallocated)": 79}

# ---- the four planted anomalies ------------------------------------------
UNTAGGED_ID = "focus-2026-06-untagged-ec2"
UNTAGGED_COST = 2340.00
SP_UPFRONT_ID = "focus-2026-05-sp-upfront"
SP_UPFRONT_COST = 18000.00
EDP_MISS_ID = "focus-2026-06-rds-listprice"
EDP_LIST = 4100.00
EDP_CONTRACTED = 3485.00          # the negotiated 15% EDP rate finance allocates at
DOUBLE_BILL_ID = "focus-2026-06-datadog"
DOUBLE_BILL_COST = 1850.00


def money(rng, lo, hi):
    return round(rng.uniform(lo, hi), 2)


def build_focus_bill(rng) -> pd.DataFrame:
    """A FOCUS-shaped export. x_ChargeId is a custom (x_-prefixed) column —
    FOCUS itself has no line identity; in a real AWS CUR the
    identity/line_item_id plays this role."""
    rows = []

    def line(charge_id, month, svc, cat, provider, billed, listed, contracted,
             dept, charge_category="Usage", description=None, resource=None):
        m, start, end = month
        rows.append({
            "x_ChargeId": charge_id,
            "InvoiceIssuerName": "AWS",
            "ProviderName": provider,
            "BillingAccountId": "123456789012",
            "SubAccountId": f"sub-{dept or 'shared'}",
            "ChargePeriodStart": start,
            "ChargePeriodEnd": end,
            "ChargeCategory": charge_category,
            "ChargeDescription": description or f"{svc} usage, {m}",
            "ServiceName": svc,
            "ServiceCategory": cat,
            "ResourceId": resource or f"arn:aws:{svc.split()[-1].lower()}:{charge_id[-8:]}",
            "BilledCost": billed,
            "ListCost": listed,
            "ContractedCost": contracted,
            "Tags": json.dumps({"department": dept} if dept else {}),
        })

    for month in MONTHS:
        m = month[0]
        for svc, cat, provider, (lo, hi) in SERVICES:
            for dept in DEPARTMENTS:
                billed = money(rng, lo, hi)
                line(f"focus-{m}-{svc.split()[-1].lower()}-{dept}", month, svc, cat,
                     provider, billed, round(billed * 1.18, 2), billed, dept)
        for svc, provider in MARKETPLACE:
            if svc == "Datadog Pro" and m == "2026-06":
                continue  # June Datadog is the planted double-bill line below
            billed = money(rng, 1200, 2600)
            line(f"focus-{m}-{svc.split()[0].lower()}", month, svc,
                 "Marketplace Software", provider, billed, billed, billed,
                 "engineering", description=f"{svc} via AWS Marketplace, {m}")

    # Planted 1 — untagged EC2 box: on the bill, invisible to chargeback.
    line(UNTAGGED_ID, MONTHS[1], "Amazon EC2", "Compute", "AWS",
         UNTAGGED_COST, round(UNTAGGED_COST * 1.18, 2), UNTAGGED_COST, dept=None,
         description="EC2 usage, untagged resource", resource="i-0deadbeef7")

    # Planted 2 — annual Savings Plan billed upfront in May.
    line(SP_UPFRONT_ID, MONTHS[0], "AWS Savings Plan", "Commitments", "AWS",
         SP_UPFRONT_COST, SP_UPFRONT_COST, SP_UPFRONT_COST, "engineering",
         charge_category="Purchase",
         description="Compute Savings Plan, 1yr all-upfront")

    # Planted 3 — RDS line billed at LIST price (EDP discount not applied).
    line(EDP_MISS_ID, MONTHS[1], "Amazon RDS", "Databases", "AWS",
         EDP_LIST, EDP_LIST, EDP_CONTRACTED, "data-platform",
         description="RDS db.r6g.2xlarge — billed at list, EDP rate not applied")

    # Planted 4 — June Datadog, billed once on the bill (duplication happens
    # on the allocation side).
    line(DOUBLE_BILL_ID, MONTHS[1], "Datadog Pro", "Marketplace Software",
         "Datadog", DOUBLE_BILL_COST, DOUBLE_BILL_COST, DOUBLE_BILL_COST,
         "engineering", description="Datadog Pro via AWS Marketplace, 2026-06")

    return pd.DataFrame(rows)


def build_chargeback_ledger(bill: pd.DataFrame) -> pd.DataFrame:
    """What the org's allocation process produces from the bill — plus the
    four planted divergences."""
    rows = []
    for _, b in bill.iterrows():
        tags = json.loads(b["Tags"])
        dept = tags.get("department")

        if b["x_ChargeId"] == UNTAGGED_ID:
            continue  # untagged: allocation drops it — nobody owns it

        period = b["ChargePeriodStart"][:7]
        amount = b["BilledCost"]
        if b["x_ChargeId"] == SP_UPFRONT_ID:
            period = "2026-06"  # finance accrued the commitment a month late
        if b["x_ChargeId"] == EDP_MISS_ID:
            amount = EDP_CONTRACTED  # finance allocates the negotiated rate

        rows.append({
            "charge_id": b["x_ChargeId"],
            "billing_month": period,
            "service_category": b["ServiceCategory"],
            "department": dept,
            "allocated_amount": amount,
            "allocation_date": b["ChargePeriodEnd"],
            "memo": b["ChargeDescription"],
        })

        if b["x_ChargeId"] == DOUBLE_BILL_ID:
            # The same Datadog month also arrived as a direct vendor invoice
            # and was keyed in again by AP.
            rows.append({
                "charge_id": f"{b['x_ChargeId']}-DUP",
                "billing_month": period,
                "service_category": b["ServiceCategory"],
                "department": dept,
                "allocated_amount": amount,
                "allocation_date": b["ChargePeriodEnd"],
                "memo": "Datadog direct invoice DD-88231 (also billed via Marketplace)",
            })
    return pd.DataFrame(rows)


def map_to_engine_schema(bill: pd.DataFrame, ledger: pd.DataFrame) -> None:
    """The documented FOCUS -> engine mapping, executed. System A (the
    authoritative side, engine role 'stg_erp_gl') is the provider invoice;
    System B ('stg_subledger_gl') is the internal chargeback ledger."""
    STAGING.mkdir(exist_ok=True)

    def account_id(cat):
        return ACCOUNTS[cat][0]

    erp = pd.DataFrame({
        "transaction_id": bill["x_ChargeId"],
        "period": bill["ChargePeriodStart"].str[:7],
        "account_id": bill["ServiceCategory"].map(account_id),
        "cost_center_id": bill["Tags"].map(
            lambda t: COST_CENTERS.get(json.loads(t).get("department", "(unallocated)"),
                                       COST_CENTERS["(unallocated)"])),
        "amount": bill["BilledCost"],
        "posted_date": bill["ChargePeriodEnd"],
        "description": bill["ServiceName"] + " — " + bill["ChargeDescription"],
    })
    sub = pd.DataFrame({
        "transaction_id": ledger["charge_id"],
        "period": ledger["billing_month"],
        "account_id": ledger["service_category"].map(account_id),
        "cost_center_id": ledger["department"].map(
            lambda d: COST_CENTERS.get(d, COST_CENTERS["(unallocated)"])),
        "amount": ledger["allocated_amount"],
        "posted_date": ledger["allocation_date"],
        "description": ledger["memo"],
    })
    dim = pd.DataFrame(
        [{"account_id": aid, "account_code": code, "account_name": name,
          "account_type": "Expense", "statement": "P&L"}
         for aid, code, name in ACCOUNTS.values()])

    erp.to_csv(STAGING / "source_erp_gl.csv", index=False)
    sub.to_csv(STAGING / "source_subledger_gl.csv", index=False)
    dim.to_csv(STAGING / "dim_account.csv", index=False)


def run_engine_unmodified() -> dict:
    """Redirect the engine's data/output paths and run it. The engine module
    itself is imported verbatim — if this demo needed engine changes, the
    'platform, not script' claim would be false."""
    sys.path.insert(0, str(ROOT / "engine"))
    import run_reconciliation as engine

    FINOPS_OUT.mkdir(exist_ok=True)
    saved = (engine.DATA, engine.OUT)
    engine.DATA, engine.OUT = STAGING, FINOPS_OUT
    try:
        return engine.main()
    finally:
        # restore module state — the GL demo and its tests share this module
        engine.DATA, engine.OUT = saved


def main() -> dict:
    rng = random.Random(SEED)
    bill = build_focus_bill(rng)
    ledger = build_chargeback_ledger(bill)
    bill.to_csv(HERE / "sample_focus_billing.csv", index=False)
    ledger.to_csv(HERE / "sample_chargeback_ledger.csv", index=False)
    map_to_engine_schema(bill, ledger)

    result = run_engine_unmodified()
    # One charge can carry two classifications: an upfront charge accrued a
    # month late genuinely IS missing from May's chargebacks AND a timing
    # difference into June. Collect the set of types per charge.
    types_by_id = (result["exceptions"]
                   .groupby("transaction_id")["exception_type"]
                   .agg(set).to_dict())

    planted = {
        UNTAGGED_ID: "Missing in subledger",
        SP_UPFRONT_ID: "Timing difference",
        EDP_MISS_ID: "Amount mismatch",
        DOUBLE_BILL_ID: "Duplicate posting",
    }
    label = {
        UNTAGGED_ID: "untagged resource (unallocated spend)",
        SP_UPFRONT_ID: "Savings Plan billed upfront, accrued next month",
        EDP_MISS_ID: "EDP discount not applied (list vs contracted)",
        DOUBLE_BILL_ID: "marketplace charge also invoiced directly",
    }

    print("\nFINOPS ANOMALY RECOVERY (planted -> classified)")
    print("=" * 64)
    ok = True
    for cid, expected in planted.items():
        got = types_by_id.get(cid, {"NOT DETECTED"})
        hit = expected in got
        ok &= hit
        print(f"  [{'OK ' if hit else 'FAIL'}] {label[cid]:<48} {' + '.join(sorted(got))}")
    print("=" * 64)
    extras = set(types_by_id) - set(planted)
    print(f"Exceptions raised: {len(result['exceptions'])}, all from the "
          f"{len(planted)} planted anomalies (the upfront charge is counted "
          f"twice — missing from May AND timed into June).")
    if extras:
        ok = False
        print(f"UNEXPECTED exceptions on clean charges: {sorted(extras)}")
    if not ok:
        raise SystemExit("planted anomaly not recovered — mapping or engine broke")
    return result


if __name__ == "__main__":
    main()
