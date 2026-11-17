# ADR-009: Deterministic moving weighted-average costing and rounding

- **Status:** Accepted
- **Date:** 2026-11-17
- **Decision owners:** BatchFlow project

## Context

BatchFlow maintains an append-only physical stock ledger and a transactionally updated valuation projection. Purchase receipts, production consumption/output, dispatch and reversals must produce deterministic costs that can be reconciled and reproduced. Binary floating-point and undocumented rounding boundaries would make totals dependent on execution details and could cause ledger/projection drift.

## Decision

Use moving weighted-average cost (WAC) per inventory item and location. All calculations use Python `Decimal` and PostgreSQL `NUMERIC`; binary floating-point is prohibited.

### Numeric scales and rounding mode

- Quantity: `NUMERIC(18,6)` in the inventory base unit.
- Persisted average/unit cost: `NUMERIC(18,6)`.
- Stock-movement `unit_cost`: `NUMERIC(18,6)`.
- Inventory value and stock-movement `extended_cost`: `NUMERIC(18,2)`.
- Python calculation context: 28 significant digits for intermediate Decimal arithmetic.
- Rounding mode at defined persistence boundaries: `ROUND_HALF_UP`.
- Use one shared costing domain module; do not duplicate rounding logic across endpoints/repositories.

### Receipt

For current valued quantity (Q), current inventory value (V), receipt quantity (q), and receipt unit rate (c):

1. Compute receipt extended value (E = q 	imes c) using Decimal.
2. Quantize (E) to 0.01 with ROUND_HALF_UP.
3. Set (Q' = Q + q), (V' = V + E).
4. If (Q' > 0), set persisted average cost to ((V'/Q')) quantized to 0.000001 with ROUND_HALF_UP.

The stock movement records receipt unit rate to six places and extended cost to two places.

### Issue

For issue quantity (q), derive working WAC from the locked valuation row using the high-precision ratio (V/Q), not the six-place persisted/display average:

1. Calculate (E = q 	imes (V/Q)) at the 28-significant-digit Decimal context.
2. Quantize (E) to 0.01 with ROUND_HALF_UP.
3. Reduce valued quantity by (q) and inventory value by (E).
4. Recompute persisted average cost from the resulting value/quantity ratio and quantize to six places with ROUND_HALF_UP.

If the issue depletes the entire valued quantity, use the entire remaining inventory value as the issue extended cost and set quantity, value and average cost to zero. This avoids residual value caused by rounding.

The movement's six-place unit-cost snapshot is informational; its two-place extended cost is authoritative for valuation and reconciliation. Therefore quantity multiplied by the rounded unit-cost snapshot may differ from extended cost by a sub-cent amount.

### Production output

- Production-run total cost is the sum of already-rounded material/packaging issue extended costs plus production cost lines, with each cost line rounded to currency precision.
- Persist `total_run_cost` to two places and `cost_per_good_unit` to six places.
- Add the actual good-output quantity and the full rounded run cost to finished-goods valuation in the same transaction as the positive output movement.
- Recompute WAC after the addition.

### Reversals

A reversal is not recalculated using today's WAC. It uses the original movement's exact quantity and extended-cost snapshot with opposite signs. Reject a reversal that would create negative quantity or inventory value. Original movements remain immutable. The service validates item, location, quantity, sign and single-reversal uniqueness.

### Concurrency

Lock the item/location valuation row before calculating receipt/issue values. All balance, valuation and ledger writes occur in the same transaction. Lock multiple item/location rows in deterministic item-id/location-id order.

## Consequences

**Positive**
- One deterministic and testable valuation policy.
- Persisted transaction values are reproducible and ledger-linked.
- Full depletion does not leave rounding residue.
- Reports can replay valuation in posted transaction order.

**Trade-offs**
- The six-place unit-cost snapshot is not guaranteed to multiply back to the exact two-place extended cost.
- Currency rounding can produce small differences versus calculations performed with unrounded values throughout.
- WAC is order-dependent; reconciliation must replay movements in posting order, not simply sum costs.

## Required tests

1. Benchmark flour receipt: 100 kg at ₹42/kg plus 60 kg at ₹45/kg gives 160 kg, ₹6,900.00 and WAC ₹43.125000/kg.
2. Half-cent and exact-half-cent cases verify ROUND_HALF_UP.
3. Repeated partial issues verify the persisted valuation and average-cost recomputation.
4. Full depletion leaves quantity, value and average cost exactly zero.
5. Production output adds the run's rounded total cost and actual good output atomically.
6. Reversal uses the original extended cost, not current WAC.
7. Concurrent receipts/issues serialize correctly under row locks.
8. Replaying the posted ledger in transaction order reproduces the valuation projection exactly.
