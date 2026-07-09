"""
Tests for the GL reconciliation engine.

Because the data generator injects discrepancies at known rates, the test
suite can assert the engine finds each class of discrepancy — and, just as
important, that it doesn't invent exceptions for clean rows.

Run locally:
    python data_generator/generate_gl_data.py
    pytest tests/ -v
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "engine"))

from run_reconciliation import main as run_engine  # noqa: E402

EXPECTED_TYPES = {
    "Missing in subledger",
    "Timing difference",
    "Amount mismatch",
    "Duplicate posting",
}


@pytest.fixture(scope="session")
def results():
    if not (ROOT / "data" / "source_erp_gl.csv").exists():
        pytest.skip("Data not generated — run data_generator/generate_gl_data.py first")
    return run_engine()


def test_all_four_exception_types_detected(results):
    found = set(results["summary"]["exception_type"])
    assert found == EXPECTED_TYPES, f"missing exception types: {EXPECTED_TYPES - found}"


def test_exception_rate_is_sane(results):
    """Generator injects ~3.5% discrepancies; the engine should find roughly
    that many — far more means false positives, far fewer means misses."""
    erp_rows = len(pd.read_csv(ROOT / "data" / "source_erp_gl.csv"))
    rate = len(results["exceptions"]) / erp_rows
    assert 0.02 <= rate <= 0.08, f"exception rate {rate:.1%} outside expected band"


def test_control_totals_cover_all_accounts_and_periods(results):
    erp = pd.read_csv(ROOT / "data" / "source_erp_gl.csv")
    expected_pairs = set(zip(erp["account_id"], erp["period"]))
    actual_pairs = set(zip(results["control_totals"]["account_id"],
                           results["control_totals"]["period"]))
    assert expected_pairs <= actual_pairs, "control totals missing account/period combinations"


def test_control_total_variance_reconciles_to_sources(results):
    """The aggregate variance in control totals must equal the difference
    between the two raw source files — the reconciliation must account for
    every dollar, not just the exceptions it happened to find."""
    erp_total = pd.read_csv(ROOT / "data" / "source_erp_gl.csv")["amount"].sum()
    sub_total = pd.read_csv(ROOT / "data" / "source_subledger_gl.csv")["amount"].sum()
    ct = results["control_totals"]
    assert abs((ct["subledger_total"].sum() - ct["erp_total"].sum())
               - (sub_total - erp_total)) < 0.01


def test_no_duplicate_exception_rows(results):
    ex = results["exceptions"]
    assert not ex.duplicated(subset=["transaction_id", "period", "exception_type"]).any()


def test_duplicates_have_posting_count_over_one(results):
    """Every duplicate-posting exception must trace back to 2+ rows in the
    normalized subledger."""
    sub = pd.read_csv(ROOT / "data" / "source_subledger_gl.csv")
    sub["base_id"] = sub["transaction_id"].str.replace("-DUP", "", regex=False)
    counts = sub.groupby(["base_id", "period"]).size()
    dupes = results["exceptions"].query("exception_type == 'Duplicate posting'")
    for _, row in dupes.iterrows():
        assert counts.get((row["transaction_id"], row["period"]), 0) > 1
