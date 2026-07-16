"""FinOps adapter invariants: the FOCUS-shaped demo recovers every planted
cloud anomaly through the UNMODIFIED reconciliation engine, with the right
class and the right dollars, and raises nothing on clean charges."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "finops"))

import focus_demo  # noqa: E402


@pytest.fixture(scope="module")
def result():
    return focus_demo.main()


def _types_by_id(result):
    return (result["exceptions"]
            .groupby("transaction_id")["exception_type"].agg(set).to_dict())


def test_untagged_spend_is_missing_in_chargebacks(result):
    types = _types_by_id(result)
    assert types[focus_demo.UNTAGGED_ID] == {"Missing in subledger"}
    row = result["exceptions"].set_index("transaction_id").loc[focus_demo.UNTAGGED_ID]
    assert row["erp_amount"] == pytest.approx(focus_demo.UNTAGGED_COST)


def test_upfront_commitment_is_a_timing_difference(result):
    types = _types_by_id(result)
    assert "Timing difference" in types[focus_demo.SP_UPFRONT_ID]


def test_unapplied_discount_is_an_amount_mismatch(result):
    exc = result["exceptions"].set_index("transaction_id")
    row = exc.loc[focus_demo.EDP_MISS_ID]
    assert row["exception_type"] == "Amount mismatch"
    # ledger allocated the contracted rate; the bill charged list
    assert row["variance_amount"] == pytest.approx(
        focus_demo.EDP_CONTRACTED - focus_demo.EDP_LIST)


def test_marketplace_double_bill_is_a_duplicate(result):
    types = _types_by_id(result)
    assert "Duplicate posting" in types[focus_demo.DOUBLE_BILL_ID]


def test_no_false_positives_on_clean_charges(result):
    planted = {focus_demo.UNTAGGED_ID, focus_demo.SP_UPFRONT_ID,
               focus_demo.EDP_MISS_ID, focus_demo.DOUBLE_BILL_ID}
    flagged = set(result["exceptions"]["transaction_id"])
    # the duplicate's -DUP twin is the same planted anomaly
    flagged = {f[:-4] if f.endswith("-DUP") else f for f in flagged}
    assert flagged == planted, f"clean charges flagged: {flagged - planted}"


def test_engine_source_is_untouched_by_the_demo():
    """The whole point: this must be the same engine the GL demo uses —
    no FinOps-specific branches hiding inside it."""
    engine_src = (ROOT / "engine" / "run_reconciliation.py").read_text(encoding="utf-8")
    for token in ("focus", "FOCUS", "finops", "FinOps", "cloud"):
        assert token not in engine_src, f"engine grew a '{token}' branch"
