# FinOps mode — the same engine, pointed at a cloud bill

Mature FinOps practice (the *allocation* and *chargeback* capabilities) is,
underneath the tooling, a reconciliation problem: does the cloud provider's
invoice tie to what the organization actually allocated to cost centers?
The four discrepancy classes this repo's engine detects between an ERP GL
and a subledger are the same four failure modes, wearing cloud costumes.

This directory proves that claim by execution, not analogy:
[`focus_demo.py`](focus_demo.py) generates a billing export shaped like the
FinOps Foundation's **FOCUS** specification plus the internal chargeback
ledger derived from it, plants one of each cloud anomaly, maps both onto
the engine's staging schemas, and runs the **unmodified** engine
(a test asserts the engine source contains no FinOps-specific branches).

```bash
python finops/focus_demo.py
```

```
FINOPS ANOMALY RECOVERY (planted -> classified)
  [OK ] untagged resource (unallocated spend)            Missing in subledger
  [OK ] Savings Plan billed upfront, accrued next month  Missing in subledger + Timing difference
  [OK ] EDP discount not applied (list vs contracted)    Amount mismatch
  [OK ] marketplace charge also invoiced directly        Duplicate posting
```

## Column mapping: FOCUS → engine schema

System A (authoritative, engine role `source_erp_gl`) is the **provider
invoice**; System B (`source_subledger_gl`) is the **internal chargeback /
cost-center ledger**.

| Engine column | From the FOCUS export | Notes |
|---|---|---|
| `transaction_id` | `x_ChargeId` (custom column) | FOCUS defines no line identity; in a real AWS CUR, `identity/line_item_id` plays this role, or hash (ResourceId, ChargePeriodStart, ChargeDescription) |
| `period` | `ChargePeriodStart` → `YYYY-MM` | the billing month |
| `account_id` | `ServiceCategory` → GL account map | Compute → 6100, Storage → 6110, … (see `ACCOUNTS` in the script) |
| `cost_center_id` | `Tags["department"]` → cost-center map | untagged lines fall to an *(unallocated)* placeholder on the bill side — and are absent from the chargeback side, which is the point |
| `amount` | `BilledCost` | invoice reconciliation is about cash billed; the chargeback side carries what finance allocated (usually `ContractedCost`) — the gap between them is exactly what the Amount-mismatch check catches |
| `posted_date` | `ChargePeriodEnd` | |
| `description` | `ServiceName` + `ChargeDescription` | |

## The four discrepancy classes, in cloud terms

| Engine classification | Standard accounting cause | Cloud billing cause |
|---|---|---|
| **Missing in subledger** | Transaction missing from the AP feed | **Untagged / unallocated spend** — a resource spun up without a department tag is on the master bill but invisible to chargeback |
| **Timing difference** | Posted in the following period | **Upfront commitments** — a Reserved Instance / Savings Plan billed as one cash spike, accrued by finance in a different month |
| **Amount mismatch** | Data-entry / rounding error | **Unapplied negotiated discount** — billed at list price while finance allocates the contracted (EDP) rate |
| **Duplicate posting** | Keyed twice in the subledger | **Marketplace double-billing** — a SaaS charge arriving both via the cloud marketplace and a direct vendor invoice |

## The scaled dataset and the coverage KPI

`focus_demo.py` teaches the mapping with four hand-planted anomalies;
`generate_focus_data.py` + `run_finops_recon.py` run FinOps mode at dataset
scale: six months, ~410 FOCUS lines, ~$700K billed, anomalies injected at
realistic rates (1.5% untagged, 0.8% unapplied EDP rate, quarterly upfront
Savings Plans accrued late, a few marketplace double-bills). Every injected
anomaly is written to `anomaly_manifest.csv`, and the tests assert the
engine recovers exactly that set — the manifest is what makes a synthetic
benchmark falsifiable instead of decorative.

The run also computes `allocation_coverage.csv`: per month, how much of the
billed spend reached a cost-center owner. That's the FinOps allocation KPI
— reconciliation tells you *what broke*; coverage tells you *how much of
the bill anyone owns*. Both feed the dashboard's Cloud Chargeback page.

## Honest scope notes

- The sample is *FOCUS-shaped synthetic data*, not a real CUR/EA export. A
  real bill adds volume (millions of lines), grain decisions (reconcile at
  line, resource, or service × month level), and messier tag hygiene — the
  mapping above is where those decisions get made, and the engine consumes
  whatever grain you land on.
- Column names follow the FOCUS 1.x core set (`BilledCost`, `ListCost`,
  `ContractedCost`, `ChargePeriodStart`, `ChargeCategory`, `ServiceCategory`,
  `Tags`); check the current spec at focus.finops.org before mapping a
  production export.
- The upfront-commitment anomaly is classified twice, deliberately: it
  genuinely *is* missing from the month the provider billed it **and** a
  timing difference into the month finance accrued it. Both statements are
  true, and an analyst wants to see both.
