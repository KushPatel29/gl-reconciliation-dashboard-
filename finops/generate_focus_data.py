"""
Scaled FOCUS dataset generator — six months of cloud billing with anomalies
at realistic rates, and a manifest that makes every one of them testable.

Where focus_demo.py plants exactly four hand-picked anomalies to teach the
mapping, this generator produces the dataset the dashboard runs on: ~400
FOCUS-shaped charge lines (2026-01 .. 2026-06, ~$700K billed) and the chargeback ledger an
allocation process would derive from them, with:

    untagged resources      ~1.5% of usage lines  (drop out of chargeback)
    late accruals           quarterly Savings-Plan purchases booked a month
                            late, plus a few ordinary lines accrued late
    unapplied EDP rate      ~0.8% of lines billed at list price while the
                            ledger allocates the contracted rate
    marketplace double-bill a handful of marketplace charges also keyed in
                            from the direct vendor invoice ('-DUP' twin)

Every injected anomaly is written to finops/anomaly_manifest.csv with its
charge id, class, and expected engine classification — the test suite
asserts the engine recovers exactly that set: nothing missed, nothing
invented. Seeded and deterministic.

Usage:
    python finops/generate_focus_data.py
"""

import json
import random
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent

SEED = 92
MONTHS = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
MONTH_END = {"2026-01": "2026-01-31", "2026-02": "2026-02-28", "2026-03": "2026-03-31",
             "2026-04": "2026-04-30", "2026-05": "2026-05-31", "2026-06": "2026-06-30"}

SERVICES = [
    ("Amazon EC2", "Compute", (400, 5200), 3),
    ("AWS Lambda", "Compute", (40, 380), 1),
    ("Amazon EKS", "Compute", (600, 2400), 1),
    ("Amazon S3", "Storage", (150, 1400), 2),
    ("Amazon EBS", "Storage", (120, 900), 2),
    ("Amazon RDS", "Databases", (700, 4100), 2),
    ("Amazon Redshift", "Analytics", (900, 4800), 1),
    ("Amazon CloudFront", "Networking", (80, 700), 1),
]
MARKETPLACE = [("Datadog Pro", "Datadog"), ("Snowflake Capacity", "Snowflake"),
               ("PagerDuty", "PagerDuty")]
DEPARTMENTS = ["engineering", "data-platform", "marketing", "finance-it", "security"]

# quarterly all-upfront Savings Plans, booked by finance a month late
SP_PURCHASES = [("2026-01", 18000.00), ("2026-04", 21000.00)]

UNTAGGED_RATE = 0.015
EDP_MISS_RATE = 0.008
LATE_ACCRUAL_EXTRA = 3      # ordinary lines accrued a month late, besides SPs
DOUBLE_BILL_COUNT = 4       # marketplace lines also keyed from direct invoices
EDP_DISCOUNT = 0.15         # negotiated enterprise rate vs list


def next_month(m: str) -> str:
    i = MONTHS.index(m)
    return MONTHS[i + 1] if i + 1 < len(MONTHS) else m


def build_bill(rng: random.Random) -> tuple[pd.DataFrame, list]:
    rows, manifest = [], []

    def line(charge_id, month, svc, cat, provider, billed, listed, contracted,
             dept, charge_category="Usage", description=None, resource=None):
        rows.append({
            "x_ChargeId": charge_id,
            "InvoiceIssuerName": "AWS",
            "ProviderName": provider,
            "BillingAccountId": "123456789012",
            "SubAccountId": f"sub-{dept or 'shared'}",
            "ChargePeriodStart": f"{month}-01",
            "ChargePeriodEnd": MONTH_END[month],
            "ChargeCategory": charge_category,
            "ChargeDescription": description or f"{svc} usage, {month}",
            "ServiceName": svc,
            "ServiceCategory": cat,
            "ResourceId": resource or f"arn:aws:{svc.split()[-1].lower()}:{charge_id[-10:]}",
            "BilledCost": billed,
            "ListCost": listed,
            "ContractedCost": contracted,
            "Tags": json.dumps({"department": dept} if dept else {}),
        })

    for month in MONTHS:
        for svc, cat, (lo, hi), n_resources in SERVICES:
            for dept in DEPARTMENTS:
                for r in range(n_resources):
                    cid = f"focus-{month}-{svc.split()[-1].lower()}-{dept}-{r}"
                    contracted = round(rng.uniform(lo, hi), 2)
                    listed = round(contracted / (1 - EDP_DISCOUNT), 2)
                    roll = rng.random()
                    if roll < UNTAGGED_RATE:
                        line(cid, month, svc, cat, "AWS", contracted, listed,
                             contracted, dept=None,
                             description=f"{svc} usage, {month} (untagged resource)")
                        manifest.append({"charge_id": cid, "anomaly": "untagged_spend",
                                         "expected_classification": "Missing in subledger",
                                         "month": month, "dollars": contracted})
                    elif roll < UNTAGGED_RATE + EDP_MISS_RATE:
                        # billed at list — the EDP rate was not applied
                        line(cid, month, svc, cat, "AWS", listed, listed,
                             contracted, dept,
                             description=f"{svc} usage, {month} (billed at list)")
                        manifest.append({"charge_id": cid, "anomaly": "unapplied_edp_rate",
                                         "expected_classification": "Amount mismatch",
                                         "month": month,
                                         "dollars": round(contracted - listed, 2)})
                    else:
                        line(cid, month, svc, cat, "AWS", contracted, listed,
                             contracted, dept)

        for svc, provider in MARKETPLACE:
            cid = f"focus-{month}-{svc.split()[0].lower()}"
            billed = round(rng.uniform(1100, 2700), 2)
            line(cid, month, svc, "Marketplace Software", provider, billed,
                 billed, billed, "engineering",
                 description=f"{svc} via AWS Marketplace, {month}")

    for month, cost in SP_PURCHASES:
        cid = f"focus-{month}-sp-upfront"
        line(cid, month, "AWS Savings Plan", "Commitments", "AWS", cost, cost,
             cost, "engineering", charge_category="Purchase",
             description="Compute Savings Plan, 1yr all-upfront")
        manifest.append({"charge_id": cid, "anomaly": "upfront_commitment_late_accrual",
                         "expected_classification": "Timing difference",
                         "month": month, "dollars": cost})

    return pd.DataFrame(rows), manifest


def build_ledger(bill: pd.DataFrame, manifest: list, rng: random.Random) -> pd.DataFrame:
    by_anomaly = {m["charge_id"]: m["anomaly"] for m in manifest}

    # pick the extra late accruals and the double-billed marketplace lines
    # from CLEAN lines only, so classes never overlap on one charge
    clean = bill[~bill["x_ChargeId"].isin(by_anomaly)]
    usage_pool = clean[(clean["ChargeCategory"] == "Usage")
                       & (clean["ChargePeriodStart"].str[:7] != MONTHS[-1])
                       & (clean["ServiceCategory"] != "Marketplace Software")]
    late_ids = rng.sample(sorted(usage_pool["x_ChargeId"]), LATE_ACCRUAL_EXTRA)
    mkt_pool = clean[clean["ServiceCategory"] == "Marketplace Software"]
    dup_ids = rng.sample(sorted(mkt_pool["x_ChargeId"]), DOUBLE_BILL_COUNT)

    for cid in late_ids:
        row = bill.set_index("x_ChargeId").loc[cid]
        manifest.append({"charge_id": cid, "anomaly": "late_accrual",
                         "expected_classification": "Timing difference",
                         "month": row["ChargePeriodStart"][:7],
                         "dollars": row["BilledCost"]})
        by_anomaly[cid] = "late_accrual"
    for cid in dup_ids:
        row = bill.set_index("x_ChargeId").loc[cid]
        manifest.append({"charge_id": cid, "anomaly": "marketplace_double_billing",
                         "expected_classification": "Duplicate posting",
                         "month": row["ChargePeriodStart"][:7],
                         "dollars": row["BilledCost"]})
        by_anomaly[cid] = "marketplace_double_billing"

    rows = []
    for _, b in bill.iterrows():
        cid = b["x_ChargeId"]
        anomaly = by_anomaly.get(cid)
        if anomaly == "untagged_spend":
            continue  # never reaches chargeback — nobody owns it

        month = b["ChargePeriodStart"][:7]
        amount = b["ContractedCost"] if anomaly == "unapplied_edp_rate" else b["BilledCost"]
        if anomaly in ("upfront_commitment_late_accrual", "late_accrual"):
            month = next_month(month)

        dept = json.loads(b["Tags"]).get("department")
        rows.append({
            "charge_id": cid,
            "billing_month": month,
            "service_category": b["ServiceCategory"],
            "department": dept,
            "allocated_amount": amount,
            "allocation_date": MONTH_END[month],
            "memo": b["ChargeDescription"],
        })
        if anomaly == "marketplace_double_billing":
            rows.append({
                "charge_id": f"{cid}-DUP",
                "billing_month": month,
                "service_category": b["ServiceCategory"],
                "department": dept,
                "allocated_amount": amount,
                "allocation_date": MONTH_END[month],
                "memo": f"{b['ProviderName']} direct invoice (also billed via Marketplace)",
            })
    return pd.DataFrame(rows)


def main() -> dict:
    rng = random.Random(SEED)
    bill, manifest = build_bill(rng)
    ledger = build_ledger(bill, manifest, rng)

    bill.to_csv(HERE / "focus_billing_export.csv", index=False)
    ledger.to_csv(HERE / "chargeback_ledger.csv", index=False)
    mdf = pd.DataFrame(manifest).sort_values("charge_id")
    mdf.to_csv(HERE / "anomaly_manifest.csv", index=False)

    print(f"focus_billing_export.csv : {len(bill):,} charge lines, "
          f"${bill['BilledCost'].sum():,.2f} billed over {len(MONTHS)} months")
    print(f"chargeback_ledger.csv    : {len(ledger):,} allocations")
    print(f"anomaly_manifest.csv     : {len(mdf)} planted anomalies")
    print(mdf["anomaly"].value_counts().to_string())
    return {"bill": bill, "ledger": ledger, "manifest": mdf}


if __name__ == "__main__":
    main()
