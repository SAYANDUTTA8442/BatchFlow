# BatchFlow — Product Requirements Document

**Document:** `Requirements.md`  
**Product:** BatchFlow  
**Version:** 1.0  
**Status:** MVP requirements baseline  
**Purpose:** Internship selection assessment  
**Source specification:** *Internship Problem Statement: Order-to-Audit System for a Small Food Manufacturer*, Centre for Digital Infrastructure, NIT Tiruchirappalli.

---

## 1. Product overview

### 1.1 Product summary

BatchFlow is a lightweight, web-based manufacturing operations and audit-support application for a small packaged-food manufacturer.

The system connects the business workflow from a field salesman's order through order verification, GST invoicing, dispatch, production, inventory, costing, collections and monthly reporting.

The product is designed around two connected business loops:

- **Sales loop:** Order → Verification → GST invoice → Dispatch → Finished-goods stock reduction → Receivables and collections.
- **Production loop:** Purchase → Raw-material receipt → BOM-based issue → Production run → Finished-goods receipt → Consumption/yield variance and production cost.

Both loops meet at finished-goods inventory and feed the monthly reports.

### 1.2 Problem statement

The target business currently uses disconnected processes:

- Salesmen send orders by phone or messaging and an administrator re-enters them.
- Invoices, stock records and production records are maintained in separate tools or manual documents.
- Actual raw-material consumption is not reliably compared with recipe-based expected consumption.
- Wastage and product cost are difficult to identify.
- Month-end sales, GST, stock and collection figures must be assembled manually.

BatchFlow aims to reduce duplicate entry, improve stock accuracy, make production variance visible and make month-end reporting easier.

### 1.3 Product objective

Build a working MVP in which each business transaction is entered at its source and its effects are reflected consistently in the relevant business records.

The MVP must demonstrate the mandatory benchmark scenario in the source specification end to end.

### 1.4 Target business

A hypothetical small-scale manufacturer of packaged South Indian snacks, including murukku, mixture, chips and sweets, with:

- Approximately 5–15 field salesmen.
- One factory.
- An admin/billing desk.
- A production floor.
- An external accountant/auditor.

### 1.5 Product principles

1. Correctness over feature count and visual polish.
2. One authoritative record for each posted business transaction.
3. Stock balances must be derived from, or reconciled against, a stock-movement ledger.
4. Every posted stock movement must be traceable to a source document.
5. Financial calculations must use exact decimal or integer-paisa arithmetic, not binary floating point.
6. Posted invoices and production records must not be silently deleted or overwritten.
7. Role-based access must be enforced by the backend.
8. The MVP must be reproducible from seeded dummy data.
9. The implementation must be explainable by the individual developer during a live interview.

---

## 2. Scope

### 2.1 MVP scope

The MVP will implement the core workflow required to demonstrate the benchmark:

- Login and role-based access for salesman, admin and production users.
- Product, customer, raw-material, packaging-material and BOM masters.
- Mobile-friendly online order entry.
- Admin order review, approval and rejection.
- Finished-goods stock availability checks.
- GST invoice generation as PDF.
- Dispatch and finished-goods stock deduction.
- Purchase receipt and raw-material inventory.
- BOM-based production runs.
- Planned-versus-actual material consumption and yield variance.
- Stock summary and stock ledger.
- Payment recording and customer outstanding balance for the benchmark.
- Basic production costing for the benchmark.
- Sales and stock reports exportable to CSV/Excel.
- Seed data and an end-to-end benchmark demonstration.

### 2.2 Should-have features included when feasible

These features are included in the intended MVP scope if they do not threaten correctness of mandatory workflows:

- Supplier records and purchase register.
- GST summary report.
- Customer-wise and product-wise sales reports.
- Payment allocation and basic receivables ageing.
- Cost per packet including labour and power/gas overheads.
- Owner summary dashboard.
- Auditor read-only access.
- PDF report export.

### 2.3 Explicitly deferred features

The following are not required for the initial MVP:

- Offline order capture and synchronization.
- GPS salesman check-in or route tracking.
- Batch and expiry tracking or FEFO dispatch.
- Advanced reorder planning.
- Automated production planning from pending orders.
- Tally-compatible export.
- e-Invoice/e-Way Bill government API integration.
- Tamil-language interface.
- Advanced analytics platform or separate OLAP database.
- Microservices, message brokers and distributed transactions.
- Multi-factory operations.
- Advanced returns and partial-dispatch workflows.

Deferred features must not be represented as implemented.

### 2.4 Out of scope

- Real customer or company data.
- Live GST portal filing or government API integration.
- Statutory accounting certification.
- Payroll, HR, banking integration or full general-ledger accounting.
- Production scheduling optimization.
- Multi-tenant SaaS billing.

---

## 3. Users and roles

The source specification identifies five user groups.

| Role | Primary device | Responsibilities |
|---|---|---|
| Salesman | Mobile phone | Create orders for assigned customers; view own order status and customer-wise sales |
| Factory admin | Desktop | Review orders, verify prices/quantities/stock, approve or reject, invoice, dispatch and record payments |
| Production supervisor | Desktop/tablet | Record raw-material receipts and issues, production runs, actual output and wastage |
| Accountant/auditor | Desktop | Read monthly reports and export sales, GST, stock, purchase, collection and outstanding information |
| Owner | Any | View orders, stock, variance alerts, cost per packet and outstanding dues |

### 3.1 Authorization baseline

| Capability | Salesman | Admin | Production | Auditor | Owner |
|---|---:|---:|---:|---:|---:|
| Submit sales order | Yes | Yes, if needed for administration | No | No | No |
| View own orders | Yes | Yes | No | Read-only reports | Summary |
| Review/approve/reject order | No | Yes | No | No | Read-only |
| Create/post GST invoice | No | Yes | No | No | Read-only |
| Record dispatch | No | Yes | No | No | Read-only |
| Maintain product/customer masters | No | Yes | Limited if configured | No | Read-only |
| Record purchase/receipt | No | Yes | Receipt entry as permitted | No | Read-only |
| Record production run | No | No | Yes | No | Read-only |
| View stock | Own relevant availability | Yes | Relevant stock | Yes | Yes |
| Record payment | No | Yes | No | No | No |
| View audit reports | No | Yes | Relevant production data | Yes | Yes |

The minimum assessment requirement is at least three roles: salesman, admin and production. Auditor and owner views are included as read-only/summary capabilities where feasible.

Authorization must be checked on backend endpoints and service operations. Hiding a button in the frontend is not authorization.

---

## 4. Functional requirements

Priorities:

- **MUST:** Required for the MVP/shortlisting baseline.
- **SHOULD:** Expected if feasible within the MVP schedule; the source specification labels these as Should Have.
- **COULD:** Optional stretch functionality, deferred unless core requirements are complete.

### FR-001 — Authentication

**Priority:** MUST

The system shall:

1. Require users to authenticate before accessing protected functions.
2. Support the salesman, admin and production roles.
3. Support read-only auditor access and owner summary access where implemented.
4. Enforce role permissions on the backend.
5. Prevent unauthorized users from accessing another salesman's restricted order data.
6. Hash passwords using a suitable password-hashing algorithm.
7. Provide a logout mechanism.

**Acceptance criteria**

- An unauthenticated request to a protected endpoint is rejected.
- A salesman cannot approve or invoice an order.
- A production user cannot post a GST invoice.
- An auditor cannot modify business records.
- A user cannot gain privileges by changing frontend requests.

### FR-002 — Master data management

**Priority:** MUST

The system shall maintain the following master data:

**Products**
- Product name and unique SKU/code.
- Pack size and unit.
- HSN code.
- Selling price or price-list reference.
- Active/inactive status.

**Customers**
- Customer name.
- Customer type: retailer or distributor.
- Billing/shipping address as applicable.
- State.
- GSTIN where applicable.
- Assigned salesman where applicable.
- Active/inactive status.

**Raw materials and packaging**
- Item name and unique code.
- Item category.
- Base stock unit.
- Opening quantity and valuation information.
- Reorder level may be deferred.

**Suppliers**
- Supplier name and contact information.
- Address and GST details where applicable.

**BOM**
- Finished product.
- BOM version/effective record.
- Standard raw-material quantities per batch.
- Standard packaging quantities per batch.
- Expected good output in packets per batch.

**Acceptance criteria**

- An admin can create and update product, customer and material masters.
- A finished product can be associated with a BOM.
- Required master fields are validated.
- Duplicate SKU/code values are rejected.
- Historical posted transactions retain the product/material descriptions and rates needed to explain the transaction.

### FR-003 — Unit definitions and conversion

**Priority:** MUST

The system shall support the units needed by the benchmark:

- Kilograms (kg).
- Grams (g).
- Litres (L).
- Pieces.
- Packets.
- Cartons of packets.

The system shall use explicit conversion rules where units are compatible.

Examples:

- 1 kg = 1,000 g.
- A carton contains 20 packets for the benchmark product.
- Packaging pieces and finished packets are distinct stock items/units.

The system shall not convert between incompatible dimensions (for example, kilograms and litres) without an explicitly defined material-specific conversion rule.

**Acceptance criteria**

- BOM quantities can be converted to the item's inventory base unit.
- Fractional quantities such as 10.5 L are represented without binary floating-point drift.
- Carton-to-packet conversion uses the configured pack capacity.
- Invalid or dimensionally incompatible conversions are rejected.

### FR-004 — Salesman order entry

**Priority:** MUST

The system shall provide a mobile-friendly online order-entry interface.

The salesman shall be able to:

1. Log in.
2. Select an assigned customer.
3. Select one or more products.
4. Enter quantities.
5. See prices from the configured price list.
6. Review the order.
7. Submit the order to the factory.
8. View own order status.
9. View customer-wise sales information permitted to that salesman.

The system shall record the submitting salesman and submission time.

**Acceptance criteria**

- A salesman can submit an order without a phone call or messaging handoff.
- The submitted order appears in the admin order queue.
- The order stores the price/quantity snapshot submitted for review.
- A salesman can view the status of their own orders.
- A salesman cannot view another salesman's restricted orders.

Offline capture and later synchronization are deferred.

### FR-005 — Order verification and approval

**Priority:** MUST

The admin shall be able to:

1. View incoming orders.
2. Inspect customer, product, quantity and price.
3. Edit quantity and price before approval.
4. Check finished-goods availability.
5. Approve or reject the order.
6. Record the acting user and timestamp.
7. Preserve the reviewed/approved order details.

The system shall flag insufficient finished-goods stock before an order is approved for full fulfilment.

**Acceptance criteria**

- The admin can approve a stock-feasible order.
- The admin sees an explicit shortage for an infeasible order.
- Rejected orders cannot be invoiced or dispatched.
- Approval does not itself deduct physical stock.
- The system prevents concurrent approvals/reservations from overselling available stock.

### FR-006 — Order and stock-reservation lifecycle

**Priority:** MUST

The MVP shall distinguish:

- Submitted order.
- Approved order.
- Invoiced order.
- Dispatched order.
- Rejected order.

Where reservation is implemented, reserved quantity shall be distinct from physical on-hand quantity.

The system shall not deduct the same quantity once at approval and again at dispatch. Dispatch is the event that reduces physical finished-goods stock.

**Acceptance criteria**

- Physical stock changes only through a posted stock movement.
- A reservation, if used, reduces available-to-promise quantity but does not create a physical issue.
- A dispatched quantity cannot exceed the quantity authorized for dispatch.
- Duplicate dispatch requests cannot create duplicate stock deductions.

### FR-007 — GST invoice generation

**Priority:** MUST

The system shall generate a tax invoice PDF from an approved order.

The invoice shall support the fields required by the assignment:

- Supplier/business name and GSTIN (dummy seed values for the assessment).
- Customer details and GSTIN where applicable.
- Invoice number and invoice date.
- Financial-year invoice sequence.
- Product description.
- HSN code.
- Quantity and unit price.
- Taxable value.
- Applicable CGST and SGST or IGST.
- Invoice total.

For the mandatory benchmark, assume GST at 5%.

Tax treatment shall be selected using the applicable place-of-supply/state information:

- Tamil Nadu factory to Tamil Nadu Retailer A: CGST + SGST for the benchmark.
- Tamil Nadu factory to Karnataka Distributor B: IGST if an invoice is raised.

The MVP is an assessment prototype. It does not file GST returns or connect to GST government systems.

**Acceptance criteria**

- Retailer A's benchmark invoice has taxable value ₹7,500, CGST ₹187.50, SGST ₹187.50 and total ₹7,875.
- An inter-state invoice uses IGST rather than CGST+SGST.
- Invoice numbering is unique within the configured financial year/series.
- The invoice PDF can be downloaded.
- Posted invoices are not silently deleted or edited.

### FR-008 — Dispatch

**Priority:** MUST

The admin shall be able to record dispatch against an eligible invoiced order.

The system shall:

1. Validate the dispatch quantity.
2. Validate available finished-goods stock.
3. Create a stock movement referencing the dispatch/source document.
4. Reduce finished-goods physical stock.
5. Record dispatch user and timestamp.
6. Update order fulfilment status.

Partial dispatch is deferred unless required to complete the benchmark or resolve a documented business rule.

**Acceptance criteria**

- Dispatch of 150 packets reduces finished-goods stock from 238 to 88.
- Dispatch cannot create a negative stock balance.
- A repeated dispatch submission cannot deduct stock twice.
- The stock ledger identifies the source invoice/order/dispatch.

### FR-009 — Purchase and raw-material receipt

**Priority:** MUST for benchmark purchase; supplier/purchase workflow is SHOULD in the source scope.

The system shall record the benchmark purchase of 60 kg flour at ₹45/kg.

Where the purchase module is implemented, it shall capture:

- Supplier.
- Purchase reference/document number.
- Purchase date.
- Item.
- Quantity and unit.
- Purchase rate.
- Total line value.
- Receipt/posting status.

Posting a purchase receipt shall create a raw-material stock receipt.

**Acceptance criteria**

- Flour stock increases from 100 kg to 160 kg after the benchmark purchase.
- The receipt is traceable to its purchase/source document.
- The purchase rate is available to the costing/valuation calculation.

### FR-010 — Bill of Materials

**Priority:** MUST

Each finished product shall have a BOM defining:

- Standard quantity of each raw material per batch.
- Standard packaging quantity per batch.
- Expected output in good packets per batch.

The BOM shall support batch scaling.

For the benchmark Murukku 200 g BOM:

| Component | Standard quantity per batch |
|---|---:|
| Flour | 40 kg |
| Cooking oil | 10 L |
| Salt and spice mix | 1.2 kg |
| 200 g pouch | 200 pieces |
| Carton (20 packets) | 10 pieces |
| Expected output | 200 packets |

**Acceptance criteria**

- A production run can select the product's BOM.
- Expected consumption and expected output are calculated from the BOM and batch multiplier.
- BOM quantities are converted to inventory units before posting.
- The run retains the BOM values used for its calculation so later master-data changes do not rewrite historical production calculations.

### FR-011 — Production run recording

**Priority:** MUST

A production supervisor shall be able to record:

- Product.
- Batch size/multiplier.
- Planned consumption derived from BOM.
- Actual raw-material quantities issued.
- Actual packaging quantities used.
- Actual good output.
- Damaged packaging.
- Scrap/wastage information.
- Labour and power/gas cost entries where costing is enabled.
- Production date and responsible user.

On posting a production run, the system shall atomically:

1. Validate raw-material and packaging availability.
2. Deduct actual raw-material consumption.
3. Deduct packaging used, including damaged packaging.
4. Add actual good finished-goods output.
5. Record production consumption and output.
6. Calculate planned-versus-actual consumption variance.
7. Calculate planned-versus-actual yield variance.
8. Record the source-linked stock movements.
9. Preserve an audit record.

**Acceptance criteria**

- A failed production posting leaves no partial stock movements.
- The benchmark creates 188 good finished packets.
- Actual flour issue is 40 kg.
- Actual oil issue is 10.5 L.
- Actual spice issue is 1.2 kg.
- 188 pouches are used for good packets and six additional pouches are recorded as damaged.
- The system does not count damaged pouches as good finished output.

### FR-012 — Production variance

**Priority:** MUST

The system shall compare planned and actual consumption for each BOM component.

For a positive planned quantity:

`ConsumptionVariance(\%) =
\frac{Actual-Planned}{Planned}\times100`

Yield variance shall be:

`YieldVariance(\%) =
\frac{ActualGoodOutput-ExpectedOutput}{ExpectedOutput}\times100`

A configurable tolerance shall control variance alerts.

For the benchmark:

- Yield: (188 − 200) / 200 = −6%.
- Oil consumption: (10.5 − 10) / 10 = +5%.

Both must be flagged when the configured example tolerance is 3%.

**Acceptance criteria**

- The system shows planned, actual, difference and percentage variance.
- Negative yield variance is displayed clearly.
- Excess consumption is displayed clearly.
- Variance alerts are generated when absolute percentage variance exceeds the configured threshold.
- Zero planned quantity is handled without division by zero.

### FR-013 — Inventory ledger and stock balances

**Priority:** MUST

The system shall maintain separate inventory for:

- Raw materials.
- Packaging materials.
- Finished goods.
- Work in progress only if chosen; WIP is not required for the MVP.

Every posted stock movement shall include:

- Item.
- Quantity.
- Unit/base unit.
- Movement type.
- Source document type and ID.
- Posting timestamp.
- User responsible.

The stock ledger shall support opening balance, receipts, issues, sales/dispatch and adjustments.

Raw/packaging stock:

`Closing=Opening+Receipts-Issues\pm Adjustments`

Finished-goods stock:

`Closing=Opening+Production-Dispatch\pm Adjustments`

**Acceptance criteria**

- The system can display an item-wise stock summary.
- The system can display movement history and source references.
- The benchmark balances reconcile:
  - Flour: 120 kg.
  - Oil: 19.5 L.
  - Spice mix: 3.8 kg.
  - Pouches: 306 pieces.
  - Cartons: 21 pieces, derived from 30 opening less 9 used.
  - Finished goods after production: 238 packets.
  - Finished goods after Retailer A dispatch: 88 packets.
- No user can silently overwrite the authoritative stock ledger.
- Any cached/materialized balance is reconcilable against ledger movements.

### FR-014 — Payment recording and outstanding

**Priority:** SHOULD in source scope; included for mandatory benchmark demonstration.

The admin shall be able to:

- Record a payment received from a customer.
- Associate the payment with an invoice.
- Allocate a partial payment.
- View invoice outstanding.
- View customer outstanding balance.

For the benchmark:

`Outstanding=₹7,875-₹4,000=₹3,875`

**Acceptance criteria**

- Retailer A's ₹4,000 payment is recorded.
- Retailer A's invoice outstanding is ₹3,875.
- Payment allocation cannot exceed the available unallocated payment or invoice outstanding unless an explicitly supported advance/overpayment workflow is used.
- Payment records are auditable.

### FR-015 — Material valuation and production costing

**Priority:** SHOULD in source scope; included in the MVP because it is part of the benchmark.

The system shall use weighted-average material valuation for the initial MVP.

For an item:

`WeightedAverageRate =
\frac{OpeningValue+ReceiptValue}
{OpeningQuantity+ReceiptQuantity}`

The production run cost shall include:

- Raw-material consumption cost.
- Packaging consumption cost.
- Labour.
- Gas/power and other entered overheads.

The MVP shall document the overhead allocation rule. For the single-product benchmark run, the entered labour and gas/power costs are assigned to that run.

Cost per packet:

`CostPerGoodPacket =
\frac{MaterialCost+PackagingCost+AllocatedOverheads}
{ActualGoodOutput}`

Benchmark assumptions/calculation:

- Flour weighted-average rate: ₹43.125/kg.
- Flour cost for 40 kg: ₹1,725.
- Oil cost for 10.5 L at ₹140/L: ₹1,470.
- Spice cost for 1.2 kg at ₹200/kg: ₹240.
- Pouch cost for 194 pieces at ₹2.50: ₹485.
- Carton cost for 9 pieces at ₹15: ₹135.
- Material and packaging total: ₹4,055.
- Labour: ₹1,200.
- Gas/power: ₹600.
- Total run cost: ₹5,855.
- Good output: 188 packets.
- Approximate cost per good packet: ₹31.14.

**Acceptance criteria**

- The system displays the valuation method.
- The system displays the components of run cost.
- The denominator is actual good output, not total attempted output or packaging count.
- Costing can be reproduced from stored rates and quantities.

### FR-016 — Reports and exports

**Priority:** Sales register and stock report are MUST; remaining reports are SHOULD in source scope.

The MVP shall provide:

- Sales register.
- Customer-wise sales.
- Product-wise sales.
- Stock summary.
- Stock ledger.
- Production report with planned/actual consumption, yield and wastage.
- GST outward-supply summary in a structure mappable to GSTR-1/GSTR-3B.
- Purchase register where purchase module is implemented.
- Payments/collections.
- Customer outstanding and basic ageing where feasible.
- Cost-per-packet report where costing is implemented.

Reports shall be filterable by date range where relevant.

Exports:

- CSV and/or Excel for sales and stock reports (mandatory).
- PDF for GST invoices (mandatory).
- PDF report export is SHOULD.

**Acceptance criteria**

- Sales register totals reconcile with posted invoices.
- Stock report reconciles with stock movements.
- Production report reproduces production-run variances.
- Auditor access is read-only.
- Exported files contain the same filtered records as the displayed report.

### FR-017 — Owner summary dashboard

**Priority:** SHOULD

The owner view should summarize:

- Today's orders.
- Stock levels.
- Production variance alerts.
- Cost per packet.
- Outstanding dues.

The dashboard shall use persisted business records and must not contain hardcoded benchmark values.

### FR-018 — Audit trail and document correction

**Priority:** MUST as a technical expectation

The system shall log significant business actions, including:

- Order approval/rejection.
- Invoice posting/cancellation.
- Dispatch posting.
- Purchase receipt posting.
- Production-run posting/correction.
- Payment recording.
- Stock adjustment.
- Master-data changes that affect future transactions.

Audit information shall include actor, action, timestamp and affected record/reference. Where practical, it should include before/after values.

Posted invoices must not be deleted; cancellation/credit-note handling shall preserve history.

Posted production records must not be silently overwritten. Corrections must preserve the original record and the correction trail.

**Acceptance criteria**

- A posted invoice has an immutable business history.
- A production-run correction does not erase the original posting.
- An auditor can inspect relevant audit records.
- Audit records identify the user and time of the action.

### FR-019 — Seed data and benchmark reset

**Priority:** MUST

The project shall provide a repeatable seed script or data file for the benchmark master data.

The seed data shall include:

- Murukku 200 g product.
- Benchmark BOM.
- Opening raw-material and packaging stocks.
- Opening finished-goods stock.
- Flour opening valuation rate.
- Oil and spice rates.
- Packaging rates.
- Retailer A in Tamil Nadu.
- Distributor B in Karnataka.
- Dummy factory GST details.
- Demo users for required roles.

The benchmark must be rerunnable in a clean database or resettable demo environment without using real customer/company data.

**Acceptance criteria**

- A documented command loads benchmark master data.
- Test/demo credentials are documented separately from production secrets.
- No real customer or company data is included.

### FR-020 — Local deployment and documentation

**Priority:** MUST

The repository shall contain:

- Source code.
- Clear commit history.
- README with stack and rationale.
- Setup instructions.
- Features mapped to Must Have / Should Have / Stretch.
- Assumptions and known gaps.
- Benchmark outputs and explanations of differences.
- Design note (maximum two pages) describing data model, stock/BOM calculations, costing and valuation.
- Demo video link (maximum eight minutes).
- Local run command or hosted demo.
- Test logins for each role.

**Acceptance criteria**

- A reviewer can start the application using documented steps.
- Database migrations and seed data can be run.
- The benchmark can be demonstrated in order.
- The design note is no more than two pages.
- The demo video is no more than eight minutes.

---

## 5. Non-functional requirements

### NFR-001 — Transaction integrity

Critical operations involving stock and business-document posting shall use database transactions.

A production posting shall either record all required stock movements and production records or record none of them.

### NFR-002 — Concurrency safety

The system shall protect stock-sensitive operations against concurrent overselling or duplicate stock deduction.

The implementation may use database row locking, conditional updates, suitable transaction isolation and unique/idempotency constraints.

### NFR-003 — Numeric correctness

- Money shall use integer paise or exact decimal types.
- Quantity shall use an appropriate exact decimal representation.
- Binary floating-point shall not be used for money.
- Rounding rules shall be explicit and consistent.

### NFR-004 — Data integrity

Use primary keys, foreign keys, unique constraints, check constraints and not-null constraints where appropriate.

### NFR-005 — Traceability

Every posted inventory movement must reference its source transaction.

### NFR-006 — Security

- Passwords must be securely hashed.
- Secrets must be supplied through environment configuration and excluded from Git.
- Backend authorization is mandatory.
- Inputs must be validated.
- Error responses must not expose secrets or sensitive internals.

### NFR-007 — Usability

- Sales order entry must be mobile-friendly.
- Admin and production screens must work on desktop/tablet.
- A salesman should be able to submit an ordinary order in under one minute, as targeted by the source specification.

### NFR-008 — Maintainability

The backend shall be a modular monolith with domain-oriented modules and clear separation between API, business logic and persistence.

### NFR-009 — Deployability

The MVP shall be runnable locally with a documented command, preferably Docker Compose.

### NFR-010 — Testability

The project shall include unit tests for calculations and integration tests for database-backed workflows, plus an end-to-end benchmark test.

### NFR-011 — Reproducibility

Benchmark seed data and test procedures shall be deterministic and documented.

### NFR-012 — Auditability

Posted business transactions shall preserve user, time, source and correction history.

---

## 6. Data and transaction rules

### 6.1 Authoritative database

PostgreSQL is the single authoritative transactional database for the MVP.

Logical schemas may separate domains, but the core business workflow remains within one database transaction boundary.

Redis, ClickHouse, MinIO and other independent stores are not part of the initial MVP.

### 6.2 Inventory ledger

The stock-movement ledger is authoritative.

A current balance may be stored for performance, but it must be updated transactionally and reconciled against ledger movements.

### 6.3 Production posting

Production posting must atomically:

- Validate input stock.
- Record actual consumption.
- Record damaged packaging.
- Record good finished output.
- Record production-run details.
- Record variances.
- Record audit information.

### 6.4 Dispatch posting

Dispatch must atomically:

- Validate dispatch eligibility.
- Validate available finished goods.
- Create the source-linked stock movement.
- Update dispatch status.

### 6.5 Invoice posting

Invoice numbers must be unique within the configured financial-year series.

Posted invoices must be corrected through an auditable cancellation/credit-note process, not deletion.

### 6.6 Idempotency

Operations that may be retried (for example, order submission or dispatch posting) should use unique request identifiers or equivalent safeguards to prevent duplicate business effects.

### 6.7 Event-driven architecture

A message broker and distributed event architecture are not required for the MVP.

Direct application-service calls within the modular monolith are preferred for operations requiring immediate consistency.

If asynchronous integrations are added later, a transactional outbox may be introduced.

---

## 7. Benchmark scenario and acceptance baseline

This section preserves the benchmark supplied in the internship problem statement.

### 7.1 Master data

**Product:** Murukku 200 g  
**One batch expected yield:** 200 packets

| Item | BOM quantity per batch | Unit | Rate/stock detail |
|---|---:|---|---|
| Flour | 40 | kg | ₹42 opening rate; ₹45 new purchase rate |
| Cooking oil | 10 | litre | ₹140 |
| Salt and spice mix | 1.2 | kg | ₹200 |
| 200 g pouch | 200 | piece | ₹2.50 |
| Carton (holds 20 packets) | 10 | piece | ₹15 |

Opening stock:

| Item | Opening stock |
|---|---:|
| Flour | 100 kg |
| Cooking oil | 30 L |
| Spice mix | 5 kg |
| Pouches | 500 pieces |
| Cartons | 30 pieces |
| Finished Murukku 200 g | 50 packets |

Selling price: ₹50 per packet before tax.  
GST assumption for exercise: 5%.  
Factory state: Tamil Nadu.

### 7.2 Required benchmark steps

1. Record purchase of 60 kg flour at ₹45/kg.
2. Start one Murukku 200 g production run.
3. Issue 40 kg flour, 10.5 L oil and 1.2 kg spice mix.
4. Record 188 good packets, six damaged pouches and nine cartons used.
5. Salesman A places an order for 150 packets for Retailer A in Tamil Nadu.
6. Admin approves, raises GST invoice with CGST + SGST and records dispatch.
7. Salesman B places an order for 120 packets for Distributor B in Karnataka.
8. Show insufficient-stock handling and the 32-packet shortage.
9. Record ₹4,000 payment from Retailer A.
10. Add ₹1,200 labour and ₹600 gas/power for the production run.
11. Generate monthly reports.

### 7.3 Expected benchmark checks

| Check | Expected result |
|---|---:|
| Flour closing | 120 kg |
| Oil closing | 19.5 L |
| Pouches closing | 306 |
| Finished goods after production | 238 packets |
| Finished goods after Retailer A dispatch | 88 packets |
| Yield variance | 188 vs 200 expected; −6%; flagged |
| Oil consumption variance | 10.5 L vs 10 L; +5%; flagged |
| Retailer A taxable value | ₹7,500 |
| Retailer A CGST | ₹187.50 |
| Retailer A SGST | ₹187.50 |
| Retailer A invoice total | ₹7,875 |
| Retailer A outstanding after payment | ₹3,875 |
| Distributor B shortage | 32 packets |
| Cost per packet | Approximately ₹31.14 under the documented assumptions |

Additional derived balances:

- Spice mix: 5 − 1.2 = 3.8 kg.
- Cartons: 30 − 9 = 21 pieces.

### 7.4 Cost calculation used by the MVP

Weighted-average flour rate:

\[
\frac{100(42)+60(45)}{100+60}=₹43.125/kg
\]

Material and packaging cost:

| Component | Calculation | Cost |
|---|---|---:|
| Flour | 40 × ₹43.125 | ₹1,725 |
| Oil | 10.5 × ₹140 | ₹1,470 |
| Spice mix | 1.2 × ₹200 | ₹240 |
| Pouches | 194 × ₹2.50 | ₹485 |
| Cartons | 9 × ₹15 | ₹135 |
| **Total** | | **₹4,055** |

Total production cost:

\[
₹4,055+₹1,200+₹600=₹5,855
\]

Cost per good packet:

\[
₹5,855/188 approx ₹31.14
\]

### 7.5 Benchmark assumptions requiring explicit documentation

The source specification leaves some details open. The MVP shall document the following assumptions rather than silently treating them as source requirements:

1. **Carton capacity:** Nine cartons hold 180 packets at 20 packets per carton, while actual good output is 188. Provisional demonstration assumption: 180 packets are carton-packed and eight packets remain loose. The system records nine cartons consumed and 188 good packets produced.
2. **Pouch consumption:** 188 good packets consume 188 pouches; six damaged pouches are additional consumption. Total pouch issue is 194.
3. **Variance tolerance:** The source gives 3% as an example. The MVP uses a configurable default of 3% for the benchmark.
4. **Flour valuation:** Weighted-average valuation is selected by the project. The source permits the developer to choose and justify a method.
5. **Overhead allocation:** The benchmark's ₹1,200 labour and ₹600 gas/power are assigned to the single production run.
6. **Distributor B order:** The system flags the 32-packet shortage and prevents full fulfilment. Whether the order is held, rejected or partially fulfilled is an implementation assumption to document.
7. **GST master data:** Dummy GSTINs, HSN and invoice-series configuration are used for the demonstration. The source provides the 5% exercise rate and state locations, not real registration data.
8. **Invoice treatment for Distributor B:** IGST applies if an inter-state invoice is raised, but the shortage must be shown before full dispatch.
9. **Rounding:** Monetary values are calculated exactly and rounded to the applicable invoice precision at defined calculation boundaries.

Any difference from the source's expected numbers must be explained in the README.

---

## 8. System acceptance tests

The following tests define the minimum technical evidence for the assessment.

| Test ID | Scenario | Expected result |
|---|---|---|
| AT-001 | Seed benchmark master data | All benchmark masters load successfully |
| AT-002 | Purchase 60 kg flour at ₹45/kg | Flour becomes 160 kg |
| AT-003 | Produce benchmark batch | 188 good packets recorded |
| AT-004 | Production material posting | Flour 120 kg, oil 19.5 L, spice 3.8 kg |
| AT-005 | Packaging posting | Pouches 306, cartons 21 |
| AT-006 | Yield variance | −6%, flagged |
| AT-007 | Oil variance | +5%, flagged |
| AT-008 | Finished-goods production receipt | 238 packets |
| AT-009 | Retailer A order | 150 packets submitted and reviewed |
| AT-010 | Retailer A invoice | ₹7,875 total with CGST/SGST split |
| AT-011 | Retailer A dispatch | Finished goods become 88 packets |
| AT-012 | Distributor B order | 32-packet shortage flagged |
| AT-013 | Retailer A payment | ₹3,875 outstanding |
| AT-014 | Production costing | ₹5,855 run cost; approximately ₹31.14/packet |
| AT-015 | Stock ledger | Every movement has a source |
| AT-016 | Unauthorized action | Backend rejects operation |
| AT-017 | Failed production transaction | No partial posting |
| AT-018 | Duplicate dispatch request | No duplicate deduction |
| AT-019 | Concurrent stock-sensitive requests | No overselling |
| AT-020 | Sales/stock export | Export reconciles with displayed report |

---

## 9. MVP development priorities

Implementation order:

1. Requirements, assumptions and data model.
2. Project foundation, database migrations and authentication.
3. Master data.
4. Inventory ledger and unit conversion.
5. BOM and production posting.
6. Sales order and admin approval.
7. GST invoice and dispatch.
8. Payment and outstanding.
9. Costing.
10. Reports and exports.
11. Frontend completion.
12. End-to-end benchmark, documentation and demo.

The production and inventory engine shall be tested before extensive dashboard/UI work.

### Release gates

**Gate 1 — Data foundation**
- Database schema and migrations work.
- Authentication and role enforcement work.
- Master data can be seeded.

**Gate 2 — Production correctness**
- Purchase, issue, production output and variance work.
- Stock ledger reconciles.

**Gate 3 — Sales correctness**
- Salesman order reaches admin.
- Approval, invoice and dispatch work.
- Insufficient stock is handled.

**Gate 4 — Financial correctness**
- GST, payment, outstanding and costing match the documented benchmark.

**Gate 5 — Submission readiness**
- Reports export.
- Seed data works.
- README/design note/demo are complete.
- A reviewer can run the system.

---

## 10. Evaluation traceability

The implementation shall provide evidence for each criterion in the source specification.

| Source evaluation criterion | Weight | BatchFlow evidence |
|---|---:|---|
| Benchmark correctness | 30% | Reproducible benchmark and acceptance tests |
| Production and inventory design | 20% | BOM, unit conversion, stock ledger, variance tests |
| Sales-to-invoice flow | 15% | Mobile order, admin approval, GST invoice and dispatch |
| Data model and code quality | 15% | ER diagram, modular code, constraints and tests |
| Usability | 10% | Mobile salesman flow and role-specific interfaces |
| Reports and documentation | 10% | Audit exports, README and design note |

Stretch goals are considered only after the mandatory requirements work.

---

## 11. Deliverables

The final public repository shall contain:

1. Source code with clear commit history.
2. `README.md` with setup, stack rationale, feature scope, assumptions, known gaps and benchmark numbers.
3. Design note of no more than two pages in PDF or Markdown, covering data model, stock/BOM calculations and costing/valuation.
4. Demo video of no more than eight minutes showing the benchmark in order, including mobile salesman and admin views.
5. Hosted demo link or a single documented local run command.
6. Test logins for each role.
7. Seed script/data for the benchmark.

The work is an individual submission. Only dummy data and invented data may be used.

---

## 12. Known limitations and future enhancements

The MVP is not intended to be a complete statutory ERP or a production-certified accounting system.

Potential future improvements, after the assessment MVP is complete:

- Offline salesman order capture and synchronization.
- Batch/expiry tracking and FEFO dispatch.
- Reorder alerts.
- Production planning from pending orders.
- Salesman route/visit logging.
- Tally-compatible export.
- Mock e-Invoice/e-Way Bill data formats.
- Tamil interface.
- More advanced audit controls.
- Analytical data warehouse.

These are future enhancements, not MVP commitments.

---

## 13. Glossary

| Term | Meaning |
|---|---|
| BOM | Bill of Materials: standard material/packaging quantities required for a production batch |
| Finished goods | Completed products available for sale/dispatch |
| Raw materials | Ingredients consumed during production |
| Packaging materials | Pouches, cartons and other packaging items |
| Stock movement | A source-linked receipt, issue, dispatch or adjustment |
| Yield | Good finished output from a production run |
| Consumption variance | Difference between actual and planned material consumption |
| Yield variance | Difference between actual and expected good output |
| Taxable value | Value on which GST is calculated |
| CGST | Central Goods and Services Tax |
| SGST | State Goods and Services Tax |
| IGST | Integrated Goods and Services Tax |
| WAC | Weighted Average Cost valuation method |
| Receivables | Amounts owed by customers |
| Idempotency | Repeating a request does not repeat its business effect |

---

## 14. Source and interpretation

This document is derived from the internship problem statement:

**“Internship Problem Statement: Order-to-Audit System for a Small Food Manufacturer” — Centre for Digital Infrastructure, NIT Tiruchirappalli.**

The source specification defines the business context, roles, functional requirements, benchmark data, scope tiers, technical expectations, deliverables, evaluation weights and submission rules.

Project-specific choices—such as the name BatchFlow, FastAPI/PostgreSQL stack, weighted-average valuation, module boundaries, exact acceptance-test IDs and documented benchmark assumptions—are implementation decisions for this MVP, not claims made by the source specification.

Where the source leaves a rule open, the relevant assumption is explicitly identified in this document and must also be reflected in the implementation README.
