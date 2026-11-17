# BatchFlow — Transaction Design

**Document:** docs/transaction-design.md  
**Product:** BatchFlow  
**Status:** Proposed transaction and posting rules  
**Version:** 1.0  
**Last updated:** 2026-11-17  
**Related documents:** [Requirements.md](../Requirements.md) · [System Architecture](./architecture.md) · [Database Schema](./database-schema.md)

> This document defines the full intended application/database behavior. The implemented inventory slice includes stock-adjustment/opening-balance creation and posting, supplier purchase-receipt creation and posting, PostgreSQL row locks, atomic ledger/balance/valuation updates, the ADR-009 moving-WAC policy, audit events, idempotency and ledger-to-projection quantity/value reconciliation. Movement reversals, reservations, production, invoice, dispatch and payment transaction services remain design-only until implemented and verified against PostgreSQL integration tests.

---

## 1. Purpose and scope

This document specifies the transactional behavior for BatchFlow's critical workflows:

1. Inventory receipt and stock adjustment.
2. Sales-order approval and stock reservation.
3. Production-run posting.
4. Invoice issuance and invoice-number allocation.
5. Dispatch posting.
6. Payment recording and allocation.
7. Weighted-average inventory valuation and production costing.
8. Idempotency, concurrency, audit events, rollback and reconciliation.

The objective is not merely to make individual SQL statements succeed. A business operation must preserve all related records and invariants as one unit of work.

## 2. Normative rules

The words MUST, MUST NOT, SHOULD and MAY express implementation requirements.

### 2.1 Transaction ownership

- The application service owns the transaction boundary.
- API routers MUST NOT commit partial business operations.
- Repositories MUST NOT independently commit.
- Domain calculations SHOULD be deterministic functions that do not perform database writes.
- A posting service MUST commit all required business records, stock movements, balance/valuation projections, idempotency result and audit event together.
- An exception before commit MUST roll back the entire transaction.
- External side effects (email, file upload, messaging) MUST NOT be performed inside a database transaction. They are outside the MVP or require a later outbox design.

### 2.2 Source of truth

- Posted stock movements are the authoritative history of physical stock changes.
- Inventory balances are projections and MUST be updated in the same transaction as their movements.
- Inventory valuation projections are derived state and MUST be updated in the same transaction as valuation-affecting movements.
- Active reservations affect available-to-promise, not physical on-hand stock.
- Invoice totals and payment allocations are the source for receivable calculations; an independently editable outstanding amount is prohibited.
- Posted documents are immutable. Corrections use explicit reversal/correction records, not silent edits.

### 2.3 Exact arithmetic

- Money and quantities MUST use Python Decimal and PostgreSQL NUMERIC.
- Binary floating-point MUST NOT be used in financial or inventory calculations.
- WAC calculations MUST use a 28-significant-digit Decimal local context.
- Persist extended currency values to 2 decimal places and unit costs to 6 decimal places using ROUND_HALF_UP.
- Recompute WAC from the rounded inventory value and valued quantity after each posting; full depletion clears quantity, value and average cost to zero.
- Rounding boundaries MUST be explicit and covered by PostgreSQL integration tests.
- The backend MUST recalculate authoritative totals; client-supplied totals are never trusted.
- The detailed costing and rounding decision is recorded in [ADR-009](./adr/ADR-009-wac-rounding-policy.md); authentication is recorded in [ADR-008](./adr/ADR-008-bearer-token-authentication.md).

## 3. Transaction and locking conventions

### 3.1 PostgreSQL transaction isolation

Use PostgreSQL READ COMMITTED as the initial default isolation level, with explicit row locks and conditional updates for stock-sensitive operations.

READ COMMITTED is sufficient only when each critical operation follows the locking/recheck protocol below. A preliminary availability query without a lock is not a guarantee.

Do not switch the entire application to SERIALIZABLE as a substitute for correct lock design. If a later operation requires SERIALIZABLE, document its retry behavior and test serialization failures.

### 3.2 Lock order

To reduce deadlocks, operations touching multiple rows MUST acquire locks in a deterministic order:

1. Idempotency record/key (or its unique-key claim).
2. Business document header, where an existing document is being posted.
3. Inventory balance rows sorted by inventory_item_id, then inventory_location_id.
4. Inventory valuation rows in the same item/location order.
5. Invoice-series row when issuing an invoice.
6. Other dependent rows in a stable primary-key order.

A workflow should avoid locking unrelated rows. If two operations require the same lock classes, they must use the same ordering.

### 3.3 Stock balance locking

For each item/location pair:

1. Ensure an inventory_balances row exists. Creation must be protected by its composite primary key.
2. Select the row FOR UPDATE.
3. Re-read on_hand_qty after the lock is acquired.
4. Compute the proposed new balance.
5. Reject if the operation would make on-hand negative.
6. Insert the stock movement and update the balance in the same transaction.

A conditional UPDATE that checks on_hand_qty + delta >= 0 can be used as an additional guard, but it does not replace ledger insertion and reconciliation.

### 3.4 Deadlocks and transient database errors

- PostgreSQL deadlock or serialization errors may be retried only at the application-service transaction boundary.
- Retry the complete transaction, never only the last SQL statement.
- Use a small bounded retry count with jitter.
- The operation must be idempotent before automatic retry is enabled.
- Validation errors, insufficient stock, permission failures and constraint violations caused by invalid input are not retryable.
- Log the request/correlation ID and final failure category without exposing credentials or sensitive data.

### 3.5 Transaction duration

Do not perform network calls, PDF rendering, large report generation or user interaction while holding database locks. Calculate and persist the invoice snapshot inside the transaction; render its PDF after commit from the immutable invoice data.

## 4. Idempotency protocol

Idempotency is required for operations whose retry could create a second business effect, especially order submission, receipt posting, production posting, invoice issuance, dispatch and payment recording.

### 4.1 Request contract

The client sends an Idempotency-Key header for a supported create/post operation. The server derives the actor from the authenticated principal and the operation from the route/domain operation; neither is trusted from client-supplied key text. The database uniqueness scope is the tuple (actor_user_id, operation, idempotency_key). For example, user 42 may submit key abc123 for order.submit, while user 17 may independently use the same key for production.post.

The server computes a stable request hash from the validated, canonical request body and relevant operation scope. The client must not supply the hash.

### 4.2 Processing algorithm

Within one database transaction:

1. Attempt to insert an idempotency_records row for the authenticated actor, stable operation identifier and client key.
2. The unique constraint on (actor_user_id, operation, idempotency_key) arbitrates concurrent requests using the same actor/operation/key tuple.
3. If the key already exists, load its record.
4. If request_hash differs, reject with an idempotency-key-reuse conflict.
5. If the same request has completed, return the stored response status/body without repeating the business operation.
6. If the same request is still in progress, wait for the competing transaction/unique-key resolution, then return its completed result or a retryable conflict according to the API contract.
7. For a new key, execute the business operation.
8. Store the final response status/body and completed_at in the same transaction as the business changes.
9. Commit.

If the business transaction rolls back, the idempotency record created within it rolls back too. A retry can then safely attempt the operation again.

### 4.3 Retention and security

- Retain idempotency records long enough to cover realistic client retries and the business risk of duplicate posting. The initial MVP policy is 30 days; confirm this before implementation.
- Never store passwords, tokens, or secrets in response_body.
- Store only the response fields needed to reproduce the original API result.
- Idempotency is not a substitute for business uniqueness constraints. Both are required.

### 4.4 Business uniqueness

In addition to idempotency keys, enforce natural/business uniqueness where appropriate:

- Unique order, receipt, run, dispatch and invoice numbers.
- One invoice per sales order in the MVP.
- One stock movement per posted source line and movement purpose.
- One active posting for a source document.
- Unique payment reference only when the source actually guarantees that reference is unique; do not invent a global uniqueness rule for references that may repeat.

## 5. Inventory posting protocol

### 5.1 General stock movement rule

Every physical stock change MUST be represented by:

1. A persisted source document and source line.
2. Exactly one stock_movement row linked to that source line.
3. A corresponding inventory_balances update.
4. A corresponding inventory_valuations update where the movement affects valued stock.
5. An audit event.
6. A committed posting status.

All required records are written in one transaction.

The stock ledger row is append-only. A posted source line must not be posted a second time. A unique constraint on its source reference prevents duplicate movements even if application-level idempotency fails.

### 5.2 Signed quantity convention

| Event | quantity_delta |
|---|---:|
| Opening receipt / positive adjustment | Positive |
| Purchase receipt | Positive |
| Production raw-material issue | Negative |
| Production packaging issue | Negative |
| Finished-goods production output | Positive |
| Finished-goods dispatch | Negative |
| Reversal | Opposite sign to original movement |

All quantities are stored in the inventory item's base unit.

### 5.3 Inventory availability

Define:

- On-hand = sum of posted stock movement quantity_delta for the item/location.
- Reserved = sum of quantities in active reservations not yet consumed or released.
- Available-to-promise (ATP) = on-hand − active reserved quantity.

The balance projection stores on-hand. Reservation totals are derived from reservation records or a separately maintained projection only if it is transactionally reconciled.

A reservation does not create a stock movement and does not reduce on-hand. Dispatch reduces on-hand.

### 5.4 Stock movement uniqueness

The database schema defines five explicit source-line foreign keys on stock_movements. Enforce exactly one non-NULL source-line FK with a CHECK constraint, and create a partial unique index for each source FK where it is non-NULL. This gives one movement per source line even if application idempotency fails.

A reversal is a new movement with movement_type = REVERSAL, sourced from a dedicated stock-adjustment line, and reverses_movement_id pointing to the original movement. A partial unique index on reverses_movement_id prevents a second reversal of the same movement. The posting service verifies the same item/location, equal absolute quantity and opposite sign. Do not use a generic source_type/source_id pair for physical stock movements.

## 6. Purchase receipt posting

### 6.1 Preconditions

- Receipt exists in DRAFT state.
- Receipt contains at least one valid line.
- Each item is active and is eligible for procurement.
- Received quantities are positive and expressed/converted into the item's base unit.
- Unit rates are non-negative and use the configured currency.
- The actor is authorized to post receipts.

### 6.2 Atomic posting sequence

Within one transaction:

1. Claim/check the idempotency key.
2. Lock the purchase receipt header FOR UPDATE.
3. Verify status is DRAFT and it has not already been posted.
4. Validate and normalize all line quantities and rates.
5. Lock affected item/location balance and valuation rows in deterministic order.
6. For each line, calculate extended receipt value using the documented rounding rule.
7. Insert one positive stock movement linked to the receipt line.
8. Increase on_hand_qty by the received base-unit quantity.
9. Update moving weighted-average valuation using the receipt's unit rate.
10. Set receipt status to POSTED and populate posted_at/posted_by_user_id.
11. Insert audit event and idempotency response.
12. Commit.

If any line fails, no line is posted and no balance/valuation is changed.

### 6.3 WAC receipt formula

Let:

- Q be current valued quantity before receipt.
- V be current inventory value before receipt.
- q be received quantity.
- c be received unit rate.

Then:

[
Q_{new}=Q+q
]

[
V_{new}=V+(q 	imes c)
]

[
WAC_{new}=rac{V_{new}}{Q_{new}}
]

Use Python Decimal with a local context precision of 28 significant digits. Quantize currency values to 0.01 and persisted unit costs to 0.000001 with ROUND_HALF_UP. For a receipt, round q × c to cents as the receipt-line extended cost, add that amount to V, then compute WAC = V_new / Q_new and persist its six-place rounded value. The benchmark flour receipt remains exactly ₹2,700.00, giving Q_new = 160 kg, V_new = ₹6,900.00 and WAC = ₹43.125000/kg.

For the benchmark flour:

- Opening: 100 kg at ₹42/kg = ₹4,200.
- Receipt: 60 kg at ₹45/kg = ₹2,700.
- New quantity: 160 kg.
- New value: ₹6,900.
- WAC: ₹43.125/kg.

## 7. Sales-order approval and reservation

### 7.1 Chosen MVP policy

The MVP uses reservation on approval. Approval must atomically confirm ATP and create reservation records for the approved quantities.

A reservation is a commitment against existing finished goods; it is not a physical issue. The application must never deduct stock at order approval.

The MVP supports full approval or rejection for each order. Partial order approval and partial dispatch are deferred unless separately approved as a scope change.

### 7.2 Submission

Order submission transaction:

1. Claim idempotency key.
2. Verify authenticated user has the salesman role.
3. Verify customer is active and assigned to that salesman.
4. Validate active products, positive quantities and price source.
5. Persist order header and line snapshots in SUBMITTED state; initialize immutable submitted_quantity/submitted_unit_price alongside the current quantity/unit_price values.
6. Record audit event and idempotency response.
7. Commit.

Submission does not reserve or deduct stock.

### 7.2.1 Admin review edits

Before approval, an authorized admin may revise order-line quantity and/or unit price. Each review-edit transaction must:

1. Lock the order header FOR UPDATE and verify status is SUBMITTED.
2. Load the affected line and retain its current quantity/unit price as the before snapshot.
3. Validate the new quantity against the selected unit's input precision and validate the price.
4. Update only the current quantity/unit_price fields; submitted_quantity/submitted_unit_price remain immutable.
5. Insert a SALES_ORDER_LINES_REVISED audit event. before_data and after_data must include each affected line ID and the complete prior/new quantity and unit-price values.
6. Commit the line changes and audit event atomically.

After approval or rejection, order-line values are immutable. Multiple review edits are allowed while SUBMITTED; each edit creates its own audit event, so the sequence can be reconstructed without a separate order-revision table.

### 7.3 Approval

Approval transaction:

1. Claim idempotency key.
2. Lock order header FOR UPDATE.
3. Verify status is SUBMITTED.
4. Verify reviewer has the required permission.
5. Load approved order lines and map them to finished-good inventory items.
6. Lock all relevant inventory balance rows in deterministic order.
7. Calculate ATP using current on-hand less active reservations.
8. If any line has insufficient ATP, do not approve and do not create any reservation. Return a structured shortage result.
9. If all lines are available, create reservation rows for every line.
10. Set order status to APPROVED and record reviewer/time.
11. Insert audit event and idempotency response.
12. Commit.

Approval is all-or-nothing. It must not reserve only some lines.

### 7.4 Rejection, cancellation and release

- A SUBMITTED order may be rejected without reservation.
- An APPROVED order may be cancelled before invoice issuance; lock the order, release all ACTIVE reservations, record reason/actor, update state and write the audit event atomically.
- An INVOICED order may be cancelled only through the full invoice-cancellation workflow in §9.5. Direct order cancellation after invoice issuance is prohibited.
- A REJECTED order cannot be approved without a new submission/revision workflow.
- The cancellation transition and reservation release are enforced by service guards and PostgreSQL integration tests.

### 7.5 Unit input precision

Validate the entered quantity against the selected input unit before unit conversion:

- KG and L accept at most three decimal places.
- G, PCS, PACKET and CARTON accept whole-number input.
- Excess decimal places are rejected with a validation error; do not silently round user input.
- Convert accepted quantities to the inventory item's canonical base unit and persist normalized values at six decimal places.
- Quantity arithmetic after normalization uses Decimal, never binary floating point.

### 7.6 Reservation invariants

For each reservation:

[
0 leq quantity_consumed leq quantity_reserved
]

Only ACTIVE reservations reduce ATP. CONSUMED and RELEASED reservations do not.

When dispatch is posted, the relevant reservation is consumed in the same transaction as the physical stock issue. It must not be counted twice as both active reserved stock and a second deduction from available stock.

## 8. Production-run posting

### 8.1 Preconditions

- Production run is DRAFT.
- Selected BOM belongs to the selected product and is active/effective for the production date.
- BOM snapshot/version is stored on the run.
- Batch multiplier is positive.
- Actual quantities are valid and non-negative.
- Actual good output is recorded.
- The actor is authorized as a production supervisor.
- Sufficient raw-material and packaging on-hand stock exists.
- All quantities are normalized to inventory base units.

### 8.2 Planned versus actual quantities

For each BOM line:

[
planned_qty = quantity_per_batch 	imes batch_multiplier
]

The run stores this planned quantity as a snapshot. Actual consumption is entered/recorded separately.

Variance:

[
variance_qty = actual_qty - planned_qty
]

For positive planned quantity:

[
variance_% = rac{actual_qty-planned_qty}{planned_qty}	imes100
]

A positive consumption variance means more material was consumed than planned. A negative value means less was consumed.

Yield variance:

[
yield_variance_% =
rac{actual_good_output-expected_output}{expected_output}	imes100
]

The benchmark expected output is 200 and actual good output is 188, giving −6%.

Variance flags use the configured tolerance (3% for the benchmark). The tolerance determines alert status; it must not alter the recorded actual quantities.

### 8.3 Atomic posting sequence

Within one transaction:

1. Claim idempotency key.
2. Lock production run header FOR UPDATE.
3. Verify DRAFT state and authorization.
4. Validate the BOM/product relationship and persisted BOM snapshot.
5. Recalculate planned quantities from the snapshotted BOM and batch multiplier; do not trust client-calculated planned values.
6. Validate actual consumption and output.
7. Lock all affected inventory balance and valuation rows in deterministic item/location order.
8. Re-check sufficient on-hand quantities for every material and packaging item.
9. Calculate actual material/packaging issue valuation using the current WAC immediately before each issue.
10. Insert negative stock movements for every actual consumed material and packaging line, including damaged pouches.
11. Decrease on-hand balances for all issued items.
12. Update raw-material/packaging valuation quantity and value for each issue.
13. Insert the finished-goods output record.
14. Calculate total production cost from material/packaging issue costs plus production cost lines.
15. Insert the positive finished-goods stock movement, with unit cost derived from the run's total cost divided by actual good output when output is greater than zero.
16. Increase finished-goods on-hand and valuation projections.
17. Persist run variances, total_run_cost, cost_per_good_unit and POSTED state. The persisted total is material/packaging issue cost plus production cost lines; cost_per_good_unit is total_run_cost divided by positive actual_good_output_qty using the documented precision.
18. Insert audit event and idempotency response.
19. Commit.

If any step fails, the entire posting rolls back. No material issue may remain without its finished output, and no output may remain without its associated consumption/cost records.

### 8.4 Material issue valuation

For an issue quantity q, derive the working WAC from the locked valuation row as the high-precision Decimal ratio V / Q (do not use the six-place display/persisted average for the multiplication). Calculate issue_value = q × (V / Q) at the 28-significant-digit working precision, then quantize issue_value to cents using ROUND_HALF_UP. Subtract that rounded amount from V and reduce Q by q. If q exactly equals Q, set issue_value to the entire remaining V so the final valuation is exactly zero; set both valued_qty and inventory_value to zero and average_unit_cost to zero. Otherwise recompute average_unit_cost = V_new / Q_new and quantize it to six decimal places using ROUND_HALF_UP.

The movement stores unit_cost as the six-place snapshot of the pre-issue WAC and extended_cost as the authoritative two-place issue value. This means quantity × displayed unit_cost may differ by a fraction of a cent from extended_cost; the extended cost is authoritative for inventory value and reconciliation. The issue uses the locked valuation row, and the stock movement, balance projection and valuation projection update in one transaction.

### 8.5 Zero output

The MVP must reject a production posting with zero good output if the run includes positive production cost, because cost per good packet is undefined and finished-goods valuation cannot be assigned under the selected policy.

A zero-output loss/failed-batch workflow is deferred. It requires an explicit expense/scrap valuation policy before implementation.

### 8.6 Benchmark production calculation

Under the documented benchmark assumptions:

| Component | Actual quantity | Unit rate / valuation | Cost |
|---|---:|---:|---:|
| Flour | 40 kg | ₹43.125/kg | ₹1,725 |
| Oil | 10.5 L | ₹140/L | ₹1,470 |
| Spice mix | 1.2 kg | ₹200/kg | ₹240 |
| Pouches | 194 pieces | ₹2.50 | ₹485 |
| Cartons | 9 pieces | ₹15 | ₹135 |
| Material and packaging | | | ₹4,055 |
| Labour | | | ₹1,200 |
| Gas/power | | | ₹600 |
| **Total run cost** | | | **₹5,855** |

[
cost_per_good_packet = rac{₹5,855}{188} approx ₹31.14
]

The six damaged pouches are additional packaging consumption. The 188 good packets are finished output. Nine cartons are consumed; eight packets remain loose under the benchmark assumption.

### 8.7 Finished-goods valuation

For a production output of q good units with total run cost C:

[
finished_unit_cost = rac{C}{q}
]

The finished-goods receipt adds q units and C value to the finished-goods valuation projection. Retain the unit cost and extended cost on the production-output stock movement.

The chosen approach capitalizes the benchmark's material, packaging and allocated overhead into the finished-goods cost. This is a project costing assumption, not a claim that the MVP is a statutory accounting system.

## 9. Invoice issuance and numbering

### 9.1 Preconditions

- Sales order is APPROVED.
- No invoice already exists for the order.
- Customer and seller tax/state data are available.
- Invoice lines and amounts are valid.
- Actor is authorized to issue invoices.
- Order reservation is active and consistent with the approved order quantity.

### 9.2 Atomic issuance sequence

Within one transaction:

1. Claim idempotency key.
2. Lock sales order FOR UPDATE.
3. Verify APPROVED status and absence of an existing invoice.
4. Load approved line snapshots and customer/seller tax data.
5. Determine intra-state versus inter-state treatment using the configured state codes.
6. Calculate taxable value and GST components using Decimal and the configured rounding rule.
7. Lock invoice_series row FOR UPDATE for the selected series/financial year.
8. Read next_number and construct invoice number.
9. Increment next_number.
10. Insert immutable invoice header and line snapshots.
11. Set sales order state to INVOICED.
12. Insert audit event and idempotency response.
13. Commit.

The invoice-series increment and invoice insert must commit together. If invoice issuance fails, the number allocation rolls back and the number may be reused because no invoice was issued. Once committed, the issued number is never reused.

### 9.3 Tax rules for the MVP

- The benchmark rate is 5%.
- Same-state benchmark sale: split tax into CGST and SGST.
- Inter-state benchmark sale: use IGST.
- Invoice lines and header preserve the applied rate, treatment, taxable values and tax amounts.
- Tax calculation and rounding are performed by one domain service.
- This is an assessment exercise implementation, not a complete statutory GST engine.

For the Retailer A benchmark:

- Taxable value: ₹7,500.
- CGST: ₹187.50.
- SGST: ₹187.50.
- Grand total: ₹7,875.

Invoice issuance does not deduct physical stock.

### 9.4 Invoice immutability

- Issued invoice header/lines are immutable to ordinary application operations.
- No hard delete is allowed.
- A draft invoice may be discarded before issuance because it has no issued invoice number or posting effect.
- Do not silently edit an issued invoice or reset its number.

### 9.5 Full invoice cancellation through a credit note

The MVP supports one full-value credit note per invoice, only before dispatch and payment allocation. Partial credit notes, post-dispatch returns, refunds and general GST adjustment workflows are deferred.

Preconditions:

- Invoice status is ISSUED and no dispatch exists.
- No payment allocation references the invoice.
- The associated order is INVOICED and its reservation remains ACTIVE and unconsumed.
- The actor is authorized to cancel invoices and supplies a non-empty reason.
- No credit note already exists for the invoice.

Within one transaction:

1. Claim the idempotency key.
2. Lock invoice, order, reservation rows and the credit-note series row in a deterministic order.
3. Re-check all preconditions, including absence of dispatch and payment allocations.
4. Allocate a credit-note number from its own financial-year series; increment the series in this transaction.
5. Copy every original invoice line into credit_note_lines with identical quantities, prices, taxable values, GST rates, tax components and line totals. Do not recalculate tax.
6. Insert the full-value credit-note header with totals exactly equal to the original invoice totals.
7. Set invoice status to CANCELLED; never delete or edit its original snapshot.
8. Release all ACTIVE order reservations, set the sales order status to CANCELLED, and record the cancellation reason.
9. Insert INVOICE_CANCELLED and CREDIT_NOTE_ISSUED audit events plus the idempotency response.
10. Commit.

The invoice and credit-note numbers are separate sequences. A committed credit-note number is never reused. If any step fails, the credit note, invoice/order state changes and reservation release all roll back. The credit note is an assessment-MVP full reversal representation, not a complete statutory GST or sales-return engine.

## 10. Dispatch posting

### 10.1 Chosen MVP policy

The initial MVP supports one full dispatch per invoice. Partial dispatch is deferred. This keeps order reservation, invoice fulfilment and stock movement rules deterministic.

If a future scope change adds partial dispatch, it must introduce cumulative dispatched quantity checks per invoice line and explicit reservation consumption/release semantics.

### 10.2 Preconditions

- Invoice exists and is ISSUED (a CANCELLED invoice is never dispatchable).
- Invoice has not already been dispatched.
- The associated order is INVOICED.
- Dispatch quantities match the full undelivered invoice quantities.
- Active reservation quantities cover the dispatch quantities.
- Finished-goods on-hand stock is sufficient.
- Actor is authorized to post dispatch.

### 10.3 Atomic posting sequence

Within one transaction:

1. Claim idempotency key.
2. Lock invoice and associated order FOR UPDATE.
3. Verify invoice is ISSUED and no dispatch exists.
4. Lock relevant inventory balance and valuation rows in deterministic order.
5. Verify on-hand stock and active reservation quantity.
6. Insert dispatch header and lines.
7. Insert negative stock movements linked to dispatch lines.
8. Decrease finished-goods on-hand balance and valuation projection using the current finished-goods WAC.
9. Mark matching reservations CONSUMED and set consumed quantity to reserved quantity.
10. Mark dispatch POSTED and order DISPATCHED.
11. Insert audit event and idempotency response.
12. Commit.

The dispatch, stock movement, balance, valuation, reservation and state updates are one transaction.

### 10.4 Reservation accounting during dispatch

Before dispatch, ATP is on-hand less active reservation.

During dispatch, the transaction creates a physical issue and consumes the reservation. After commit:

- On-hand decreases by dispatched quantity.
- Active reserved quantity decreases by the same quantity.
- ATP remains consistent with the other outstanding commitments.

Do not subtract the same reservation twice. Do not release a reservation before the physical issue has been validated and posted.

### 10.5 Benchmark dispatch

Before Retailer A dispatch:

- Finished goods after production: 238 packets.
- Retailer A approved reservation: 150 packets.
- ATP before dispatch, assuming no other reservations: 88 packets.

After full dispatch:

- On-hand: 88 packets.
- Retailer A reservation: consumed.
- Distributor B order for 120 packets cannot be approved in full; shortage is 32 packets.

The system must not silently approve or fully dispatch Distributor B's order.

## 11. Payment recording and allocation

### 11.1 Chosen MVP policy

The MVP supports a payment allocated to one or more invoices for the same customer. It does not support over-allocation, unallocated customer credits, refunds or allocation reversal in the first release.

For the benchmark, the ₹4,000 receipt is fully allocated to Retailer A's invoice.

### 11.2 Preconditions

- Payment amount is positive.
- Customer is active.
- Invoice belongs to the same customer.
- Invoice is ISSUED and not CANCELLED.
- Allocation amount is positive.
- Total new allocation plus existing allocations does not exceed invoice outstanding.
- Sum of allocations for a payment does not exceed payment amount.
- Actor is authorized to record payments.

### 11.3 Atomic sequence

Within one transaction:

1. Claim idempotency key.
2. Lock payment/invoice-related records in a stable order.
3. Validate customer ownership and current invoice outstanding.
4. Insert payment record.
5. Insert payment allocation rows.
6. Recalculate derived outstanding from invoice grand total less valid allocations.
7. Insert audit event and idempotency response.
8. Commit.

If any allocation fails, the payment and all allocations roll back. The MVP must not retain a payment record with a partially applied allocation unless the user explicitly selected a supported unallocated-payment workflow.

### 11.4 Benchmark result

[
outstanding = ₹7,875 - ₹4,000 = ₹3,875
]

Outstanding is a query result, not a mutable source field.

## 12. Opening balances and stock adjustments

Opening balances must be posted as a controlled stock adjustment document. Do not seed inventory_balances directly.

For each opening item:

1. Create stock adjustment header/lines.
2. Record positive opening quantity.
3. Record opening valuation rate where applicable.
4. Post a positive stock movement.
5. Update on-hand and valuation projections.
6. Record actor/system seed context and audit event.

The seed process must be repeatable on a clean/reset database. It must not be run twice against an already initialized database without an explicit reset or duplicate-protection mechanism.

Later count corrections use adjustment documents with a reason and actor. They must not edit historical movement rows.

## 13. Reversal and correction policy

### 13.1 General rule

A posted operation is corrected by a new, linked compensating record. The original document and movement remain visible.

A reversal must:

- Reference the original source/movement.
- Use opposite stock quantity for a stock movement.
- Preserve actor, timestamp and reason.
- Be unique so the same posting cannot be reversed twice.
- Update balance and valuation projections in the same transaction.
- Create an audit event.

### 13.2 Production-run correction workflow

The MVP permits one correction per posted production run. Correction is performed through a linked PRODUCTION_REVERSAL stock-adjustment document; the original production run, cost lines, output/consumption snapshots and stock movements remain immutable. The original run transitions to REVERSED, and an optional corrected replacement is a new production run posted through the ordinary workflow.

Preconditions:

- The original run is POSTED and has no existing correction record.
- None of its finished-good output has been reserved or dispatched.
- The current unreserved on-hand quantity is sufficient to remove the original output.
- Reversing every material/packaging issue and finished-good output movement will not create negative quantity or inventory value.
- The actor is authorized and provides a reason.

Because the MVP does not track finished goods by batch, any reservation or dispatch of the same finished-good item after the original run's posting is a conservative blocker, even if unrelated stock may have existed. This avoids pretending to know which physical units were consumed.

Atomic correction sequence:

1. Claim the idempotency key and lock the production run.
2. Verify the preconditions and lock every affected item/location balance and valuation row in deterministic item order.
3. Create one stock-adjustment header with reason PRODUCTION_REVERSAL.
4. For every original production issue/output movement, create one adjustment line and one REVERSAL movement linked through reverses_movement_id. Use the exact opposite quantity and the original movement's exact extended_cost; do not recalculate historical cost using current WAC.
5. Update inventory balances and valuations under the ADR-009 rules. Reject if any resulting quantity or value would be negative.
6. Create the production_run_corrections record linking original run and reversal adjustment; set original run status to REVERSED.
7. Write PRODUCTION_RUN_REVERSED and STOCK_MOVEMENT_REVERSED audit events and the idempotency response.
8. Commit.

A replacement run may be created afterward and linked to the correction record. It is a new source document with new consumption/output snapshots and a new posting transaction; it does not mutate the original run. A correction record cannot be repeated for the same original run.

### 13.3 Other MVP limits

- Invoice cancellation is supported only by the full credit-note workflow in §9.5, before dispatch and payment allocation.
- Reversing a dispatch, cancelling after dispatch, refunding payments, or reversing payment allocations is not supported.
- Generic undo of arbitrary posted documents is not supported.

If a correction case is not implemented, reject the action and preserve the original records. Manual database edits are not an acceptable operational workaround.

## 14. Audit event requirements

Each successful critical operation writes an audit event in the same transaction as the business effect.

Minimum fields:

- actor_user_id (nullable only for controlled seed/system operation)
- action
- entity_type
- entity_id
- occurred_at
- request_id/correlation ID
- relevant before/after values or structured metadata, excluding secrets

Minimum event examples:

- SALES_ORDER_SUBMITTED
- SALES_ORDER_APPROVED
- SALES_ORDER_REJECTED
- SALES_ORDER_LINES_REVISED
- SALES_ORDER_CANCELLED
- PURCHASE_RECEIPT_POSTED
- PRODUCTION_RUN_POSTED
- PRODUCTION_RUN_REVERSED
- INVOICE_ISSUED
- INVOICE_CANCELLED
- CREDIT_NOTE_ISSUED
- DISPATCH_POSTED
- PAYMENT_RECORDED
- STOCK_ADJUSTMENT_POSTED
- STOCK_MOVEMENT_REVERSED

A failed transaction must not leave a success audit event. Security logging for failed authentication/authorization may use a separate safe logging path because no business transaction is committed.

## 15. Failure handling and API outcomes

The API should distinguish business conflicts from unexpected system errors.

| Condition | Expected behavior |
|---|---|
| Invalid input / invalid quantity | 422 validation response; no writes |
| Unauthenticated request | 401; no business writes |
| Authenticated but unauthorized | 403; no business writes |
| Document already posted | 409 conflict or return original idempotent result |
| Insufficient stock | 409 business conflict with item-level shortage details |
| Same idempotency key, different payload | 409 conflict |
| Duplicate business number/source posting | 409 conflict or safe idempotent result |
| Invoice/order state invalid | 409 conflict |
| Deadlock/serialization transient error | Bounded full-transaction retry if idempotent |
| Database unavailable | 503 or standard service-unavailable response |
| Unexpected exception | 500 with correlation ID; no internal details exposed |

Error responses must not leak SQL, stack traces, password hashes, tokens or secrets.

## 16. Reconciliation and operational checks

The application must provide repeatable checks to detect projection drift and benchmark errors.

### 16.1 Stock balance reconciliation

For each item/location:

[
ledger_qty = sum posted stock_movement.quantity_delta
]

Compare ledger_qty with inventory_balances.on_hand_qty. Any mismatch is a defect and must be investigated; do not silently overwrite the ledger.

### 16.2 Inventory valuation reconciliation

For each item/location, compare inventory_valuations with the replayed valuation result from posted receipts, issues, production output and reversals under the chosen WAC policy.

Because WAC is order-dependent, the replay must use posted transaction order and the same rounding rules. A simple sum of movement quantities is not sufficient to reconstruct moving-average value.

### 16.3 Reservation reconciliation

For each order line:

- Active reservation quantity must not exceed approved undelivered quantity.
- Consumed quantity must not exceed reserved quantity.
- Dispatched quantity must match consumed reservation quantity under full-dispatch MVP behavior.
- Rejected/cancelled orders must not retain active reservations.

### 16.4 Invoice and receivable reconciliation

- Invoice header totals equal the sum of invoice line totals.
- Tax component totals reconcile with line tax values.
- A credit note exactly reverses every line and tax component of its original invoice; its header totals equal the original invoice totals.
- A CANCELLED invoice has exactly one issued full credit note and has no dispatch or payment allocations.
- Payment allocations do not exceed payment amount.
- Invoice outstanding equals invoice grand total less valid allocations; cancelled invoices are excluded from collectible outstanding.

### 16.5 Production reconciliation

- Every posted production run has its planned and actual consumption snapshot.
- Material/packaging issue movements match actual run line quantities.
- Finished-goods output movement matches actual good output.
- Total run cost equals material/packaging issue costs plus production cost lines.
- Cost per good unit equals total run cost divided by good output when output is positive.

## 17. Required concurrency and rollback tests

These are mandatory integration tests against PostgreSQL, not mocks alone.

| Test ID | Scenario | Expected invariant |
|---|---|---|
| TX-001 | Two orders concurrently approve against insufficient combined stock | At most one approval succeeds; no negative ATP |
| TX-002 | Two dispatch attempts for the same invoice | Exactly one dispatch and one stock issue |
| TX-003 | Same idempotency key and same payload submitted concurrently | One business effect; both callers receive same result |
| TX-004 | Same idempotency key with different payloads | Second request rejected |
| TX-005 | Production posting fails after material validation | No material issue, output or cost record committed |
| TX-006 | Production run posted twice with different keys | Second posting rejected by document/source uniqueness |
| TX-007 | Purchase receipt has multiple lines and one line fails validation | No partial receipt posting |
| TX-008 | Two purchases update WAC for same item concurrently | Correct serialized WAC result |
| TX-009 | Invoice issuance requests race for same order | One invoice number and one invoice only |
| TX-010 | Two payments allocate against same remaining invoice balance | Combined allocations do not exceed outstanding |
| TX-011 | Reservation is consumed by dispatch | On-hand and active reservation both change correctly |
| TX-012 | Stock movement inserted but projection update fails | Entire transaction rolls back |
| TX-013 | Audit insertion fails during a critical posting | Business posting rolls back |
| TX-014 | Reversal submitted twice | At most one effective reversal |
| TX-015 | Reconciliation after benchmark | Ledger, balance, valuation, reservation and receivable checks pass |
| TX-016 | Quantity entered with excess precision for selected unit | Request rejected before conversion or writes; valid KG/L precision up to 3 places is accepted |
| TX-017 | Full invoice cancellation before dispatch/payment | One exact full credit note; invoice/order CANCELLED; reservation released; numbers not reused |
| TX-018 | Production correction with downstream reservation/dispatch or insufficient stock/value | Correction rejected with no writes; eligible correction reverses all movements exactly once |
| TX-019 | Admin edits order quantity/price during review | Submitted snapshots remain unchanged; each edit has complete before/after audit data |

Tests TX-001, TX-002, TX-003, TX-005, TX-008, TX-009, TX-010 and TX-012 are release-blocking.

## 18. Resolved MVP decisions

The following decisions are reflected in the reconciled database schema and resolve the corresponding schema-design items.

| Area | MVP decision | Deferred behavior |
|---|---|---|
| Isolation | READ COMMITTED plus explicit row locks/rechecks | Broad SERIALIZABLE use |
| Reservation | Reserve full approved order quantities on approval | Partial approval and complex allocation |
| Rejection/cancellation | Reject submitted order; release reservations on pre-invoice cancellation; post-invoice cancellation only through full credit note before dispatch/payment | Post-dispatch cancellation and refunds |
| Quantity precision | KG/L up to 3 decimal places; G/PCS/PACKET/CARTON whole numbers; reject excess precision | Silent input rounding and arbitrary per-item precision |
| Invoice correction | One full credit note per invoice, only before dispatch/payment; cancel invoice and release reservation atomically | Partial credit notes, returns, refunds and general GST adjustments |
| Production correction | One linked reversal adjustment per posted run; exact original movement values; block if output reserved/dispatched or stock/value would go negative; optional replacement as a new run | Batch-level attribution, corrections after downstream fulfilment |
| Order review history | Immutable submitted values plus before/after audit events for every edit | Separate order-revision table |
| Dispatch | One full dispatch per invoice | Partial/multiple dispatches |
| Invoice | One immutable issued invoice per order | General credit-note engine |
| Payment | Allocated payments only; no over-allocation | Unallocated receipts, refunds and allocation reversal |
| Inventory | One seeded factory location | Multi-warehouse/bin stock |
| WAC | Moving weighted average per item/location; 28-digit Decimal working precision; 2-place currency and 6-place unit-cost persistence; ROUND_HALF_UP; full depletion clears value | FIFO/standard costing |
| Zero-output run | Reject posting under MVP costing policy | Scrap/failed-batch expense policy |
| Correction | Preserve originals; use tested reversal/adjustment operations | Generic undo of every posted document |
| Idempotency | Required for critical post operations; proposed 30-day retention | Long-term request replay archive |

These are project design decisions. They are not claims that the source internship specification mandates these exact implementation choices.

## 19. Schema alignment status

The corresponding changes have been applied to docs/database-schema.md in commit c35253fc0cee621b83aac033ed818bc19221b5af. The schema now records:

1. CANCELLED sales-order status and pre-invoice reservation release.
2. An explicit reservation reference on each dispatch line, with cross-row matching enforced by the service and integration tests.
3. Exactly-one-source-line checks and partial unique indexes for stock movement sources.
4. One full dispatch per invoice, enforced by UNIQUE(invoice_id).
5. Persisted production-run total cost and cost-per-good-unit snapshots.
6. Finished-goods valuation updates tied atomically to the production-output movement.
7. Idempotency uniqueness scoped by actor, operation and key, with request-hash verification.
8. Posting timestamps and status/timestamp consistency requirements.
9. Indexes for stock-balance locks, active reservation queries and payment allocation lookups.

The four previously open schema decisions—unit input precision, invoice cancellation/credit notes, production-run correction and order review history—are now resolved and recorded in database-schema.md §18 and this document. Bearer-token authentication and WAC rounding remain accepted decisions documented in the ADRs. The schema and transaction design must be changed together if any policy changes. ORM and migration work may now begin; do not silently reopen these resolved policies in endpoint code.

## 20. Implementation sequence

Implement in this order:

1. Database session/transaction dependency and service-level commit/rollback conventions.
2. Inventory balance and valuation locking helpers.
3. Stock movement posting primitive and source uniqueness.
4. Opening balance and purchase receipt posting.
5. Reservation and ATP service.
6. Production posting and WAC calculations.
7. Invoice series allocation and immutable invoice issuance.
8. Full dispatch posting and reservation consumption.
9. Payment allocation and outstanding queries.
10. Idempotency middleware/service and audit event integration.
11. PostgreSQL concurrency, rollback and reconciliation tests.
12. Benchmark end-to-end test.

Do not begin with dashboards. Prove the transaction engine first.

---

**BatchFlow — From Order to Audit.**
