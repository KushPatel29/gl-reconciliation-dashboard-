"""Scaled FinOps invariants: the engine recovers EXACTLY the anomaly
manifest (nothing missed, nothing invented), and allocation coverage ties
to the bill and ledger dollar for dollar."""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
FINOPS = ROOT / "finops"
sys.path.insert(0, str(FINOPS))

import generate_focus_data  # noqa: E402
import run_finops_recon  # noqa: E402


@pytest.fixture(scope="module")
def run():
    gen = generate_focus_data.main()
    result = run_finops_recon.main()
    return gen, result


def test_manifest_recovered_exactly(run):
    gen, result = run
    manifest = gen["manifest"]
    exceptions = result["exceptions"]

    flagged = {t[:-4] if t.endswith("-DUP") else t
               for t in exceptions["transaction_id"]}
    planted = set(manifest["charge_id"])
    assert flagged == planted, (
        f"missed: {planted - flagged} | invented: {flagged - planted}")

    types = (exceptions.groupby("transaction_id")["exception_type"]
             .agg(set).to_dict())
    for _, m in manifest.iterrows():
        got = types.get(m["charge_id"], set())
        assert m["expected_classification"] in got, (
            f"{m['charge_id']} ({m['anomaly']}): expected "
            f"{m['expected_classification']}, engine said {got}")


def test_timing_anomalies_also_flag_as_missing_in_origin_month(run):
    """An accrual booked a month late genuinely is absent from the billed
    month — the engine reports both facts and so does the doc."""
    gen, result = run
    manifest = gen["manifest"]
    types = (result["exceptions"].groupby("transaction_id")["exception_type"]
             .agg(set).to_dict())
    timing = manifest[manifest["expected_classification"] == "Timing difference"]
    assert len(timing) >= 2
    for cid in timing["charge_id"]:
        assert types[cid] == {"Timing difference", "Missing in subledger"}


def test_allocation_coverage_ties_to_the_penny(run):
    gen, result = run
    bill, manifest = gen["bill"], gen["manifest"]
    cov = result["coverage"]

    # billed total ties to the bill
    assert cov["billed_total"].sum() == pytest.approx(
        round(bill["BilledCost"].sum(), 2), abs=0.05)
    # untagged total ties to the manifest's untagged dollars
    untagged = manifest[manifest["anomaly"] == "untagged_spend"]["dollars"].sum()
    assert cov["untagged_total"].sum() == pytest.approx(untagged, abs=0.05)
    # allocated + untagged = billed, per month
    assert ((cov["allocated_total"] + cov["untagged_total"]
             - cov["billed_total"]).abs() < 0.05).all()
    assert cov["coverage_pct"].between(0.9, 1.0).all()


def test_anomaly_rates_are_realistic_not_theatrical(run):
    """A demo where 20% of the bill is broken stops being credible. Keep the
    planted anomaly count in the low single digits as a share of lines."""
    gen, _ = run
    rate = len(gen["manifest"]) / len(gen["bill"])
    assert 0.01 <= rate <= 0.10, f"anomaly rate {rate:.1%} out of range"


def test_scaled_run_reuses_the_untouched_engine():
    engine_src = (ROOT / "engine" / "run_reconciliation.py").read_text(encoding="utf-8")
    for token in ("focus", "FOCUS", "finops", "FinOps", "coverage"):
        assert token not in engine_src
