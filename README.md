# BatchFlow

**From Order to Audit.**

BatchFlow is a planned, lightweight manufacturing operations and audit-support system for small packaged-food manufacturers. It connects field sales orders, order verification, GST billing, dispatch, production, inventory, costing, collections and monthly reporting.

> **Project status: Requirements and planning baseline.** The product requirements are documented in [Requirements.md](./Requirements.md). Application modules, deployment instructions and live workflows are not yet implemented. This README will be updated as the system is built.

---

## Table of contents

- [Problem](#problem)
- [Product goals](#product-goals)
- [Core workflows](#core-workflows)
- [Planned features](#planned-features)
- [Technology choices](#technology-choices)
- [Architecture principles](#architecture-principles)
- [Repository structure](#repository-structure)
- [Benchmark scenario](#benchmark-scenario)
- [Development roadmap](#development-roadmap)
- [Requirements and project status](#requirements-and-project-status)
- [Security and data policy](#security-and-data-policy)
- [Documentation](#documentation)

---

## Problem

Small food manufacturers often operate sales, billing, inventory and production through disconnected tools and manual records.

This creates recurring problems:

- Sales orders are received through calls or messaging and entered again by factory staff.
- Sales, invoices, stock and production records do not share one reliable transaction history.
- Actual raw-material consumption is not compared consistently with the Bill of Materials (BOM).
- Wastage and production yield variance are difficult to identify.
- Cost per finished packet is unclear.
- Month-end sales, GST, stock and collection reports require manual reconciliation.

BatchFlow aims to connect these activities through a single, traceable workflow.

## Product goals

1. Capture a salesman's order once and make it available to the factory.
2. Give factory administrators a controlled order-review, invoicing and dispatch workflow.
3. Record production against a BOM and compare planned with actual consumption and output.
4. Maintain a source-linked inventory ledger for raw materials, packaging and finished goods.
5. Calculate production cost using documented material valuation and overhead rules.
6. Make sales, GST, stock, production and collection information available for audit-oriented reporting.
7. Preserve transaction history and prevent silent changes to posted business records.

The mandatory benchmark and detailed acceptance criteria are defined in [Requirements.md](./Requirements.md).

## Core workflows

### Sales workflow

`Salesman order → Admin review → Stock check → Approval → GST invoice → Dispatch → Receivable/payment`

### Production workflow

`Purchase receipt → Raw-material stock → BOM-based issue → Production run → Finished goods → Variance and costing`

Both workflows meet at finished-goods inventory. Their transactions feed the reporting layer.

## Planned features

The following is the intended product scope. It is not a claim that these features are already implemented.

### MVP — mandatory foundation

- Authentication and backend-enforced role-based access.
- Product, customer, raw-material, packaging and BOM masters.
- Mobile-friendly online order entry for salesmen.
- Admin order review, approval and rejection.
- Finished-goods availability checks.
- GST invoice PDF generation.
- Dispatch and finished-goods stock deduction.
- Purchase receipt and raw-material inventory.
- BOM-based production recording.
- Planned-versus-actual consumption and yield variance.
- Source-linked stock ledger and stock summary.
- Benchmark payment and outstanding calculation.
- Production costing.
- Sales and stock exports.
- Seed data and reproducible benchmark tests.

### Additional planned capabilities

- Supplier and purchase registers.
- GST summary reports.
- Customer-wise and product-wise sales reports.
- Collections and receivables ageing.
- Owner summary dashboard.
- Auditor read-only reporting.
- PDF report exports.

### Deferred enhancements

These will be considered only after the mandatory workflows are correct:

- Offline order capture and synchronization.
- Batch and expiry tracking / FEFO dispatch.
- Reorder alerts and production planning.
- Salesman route or visit logging.
- Tally-compatible export.
- e-Invoice / e-Way Bill data-format support.
- Tamil-language interface.

## Technology choices

The planned stack is:

| Layer | Planned technology | Responsibility |
|---|---|---|
| Backend API | Python + FastAPI | HTTP API, validation, authentication and application services |
| Frontend | React + TypeScript | Role-specific web interfaces and mobile-friendly order entry |
| Database | PostgreSQL | Authoritative transactional business data |
| Deployment | Docker Compose (planned) | Reproducible local development and demo environment |

### Why this stack?

FastAPI provides a clear Python API layer and a practical foundation for domain services and automated tests. React with TypeScript supports role-specific interfaces and a responsive salesman workflow. PostgreSQL provides relational constraints and transactional guarantees needed for inventory, invoices and production posting.

This is a modular-monolith design. Distributed services and infrastructure are deliberately avoided until there is a demonstrated need.

## Architecture principles

The implementation will follow these constraints:

1. **Ledger-first inventory:** stock movements are authoritative. A stored balance is only a projection that must reconcile with the ledger.
2. **Transactional posting:** production and dispatch must either commit all related business and stock records or commit none.
3. **Exact arithmetic:** use decimal or integer-paisa arithmetic for money; do not use binary floating point for financial calculations.
4. **Source traceability:** every stock movement references its source document.
5. **Backend authorization:** permissions are enforced in API/service operations, not only by hiding frontend controls.
6. **Auditable corrections:** posted invoices and production records are not silently overwritten or deleted.
7. **Idempotency:** retried requests must not create duplicate orders, stock issues, dispatches or payments.
8. **Reproducible data:** benchmark seed data and tests must allow the scenario to be rerun.
9. **Correctness before polish:** core inventory, production and financial calculations take priority over dashboards and stretch features.

## Repository structure

The repository is being built incrementally. The following is the intended high-level structure, not a representation of files that already exist:

```text
BatchFlow/
├── README.md
├── Requirements.md
├── backend/                 # Planned FastAPI application
├── frontend/                # Planned React + TypeScript application
├── database/                # Planned migrations and seed data
├── docs/                    # Planned design note and diagrams
├── tests/                   # Planned unit and integration tests
└── docker-compose.yml        # Planned local development environment
```

The final structure may be refined as implementation decisions are made.

## Benchmark scenario

BatchFlow is being designed around the benchmark in the internship problem statement.

**Product:** Murukku 200 g  
**Expected output:** 200 packets per batch  
**Factory state:** Tamil Nadu  
**Exercise GST rate:** 5%

### Production inputs

| Component | Standard BOM quantity |
|---|---:|
| Flour | 40 kg |
| Cooking oil | 10 L |
| Salt and spice mix | 1.2 kg |
| 200 g pouches | 200 pieces |
| Cartons (20 packets each) | 10 pieces |

### Benchmark events

1. Purchase 60 kg flour at ₹45/kg.
2. Run one batch using 40 kg flour, 10.5 L oil and 1.2 kg spice mix.
3. Record 188 good packets, six damaged pouches and nine cartons used.
4. Submit Retailer A's order for 150 packets in Tamil Nadu.
5. Approve, invoice and dispatch the order.
6. Submit Distributor B's order for 120 packets in Karnataka and show the stock shortage.
7. Record a ₹4,000 payment from Retailer A.
8. Allocate ₹1,200 labour and ₹600 gas/power to the production run.
9. Generate the relevant reports.

### Expected checks

| Check | Expected result |
|---|---:|
| Flour closing stock | 120 kg |
| Oil closing stock | 19.5 L |
| Spice mix closing stock | 3.8 kg |
| Pouch closing stock | 306 pieces |
| Carton closing stock | 21 pieces |
| Finished goods after production | 238 packets |
| Finished goods after Retailer A dispatch | 88 packets |
| Yield variance | −6% |
| Oil consumption variance | +5% |
| Retailer A invoice total | ₹7,875 |
| Retailer A outstanding after payment | ₹3,875 |
| Distributor B shortage | 32 packets |
| Approximate production cost per good packet | ₹31.14 |

The costing baseline uses weighted-average flour valuation and assigns the benchmark labour and gas/power costs to the single production run. The assumptions and calculation details are documented in [Requirements.md](./Requirements.md).

These are acceptance targets for the planned implementation, not results from a running application.

## Development roadmap

Implementation will proceed in dependency order:

| Phase | Focus | Exit condition |
|---|---|---|
| 1 | Requirements and data model | Domain model and transaction rules reviewed |
| 2 | Backend foundation | FastAPI project, PostgreSQL migrations and authentication |
| 3 | Master data and inventory | Masters, units and source-linked stock ledger |
| 4 | Production engine | BOM, production posting, yield and consumption variance tests |
| 5 | Sales workflow | Order submission, admin review and stock checks |
| 6 | Billing and dispatch | GST invoice PDF and safe stock deduction |
| 7 | Payments and costing | Payment allocation, outstanding and production cost |
| 8 | Frontend and reports | Role-specific screens and report exports |
| 9 | Verification and delivery | Benchmark passes, documentation and demo are complete |

**Implementation rule:** production and inventory correctness must be established before spending significant time on dashboard polish or stretch goals.

## Requirements and project status

| Artifact / capability | Status |
|---|---|
| Product requirements | Documented in [Requirements.md](./Requirements.md) |
| Architecture design | Documented in [docs/architecture.md](./docs/architecture.md) |
| Database schema design | Documented in [docs/database-schema.md](./docs/database-schema.md); migrations not implemented |
| Backend API | Not implemented |
| Frontend application | Not implemented |
| Authentication and RBAC | Not implemented |
| Production and inventory engine | Not implemented |
| Sales, invoice and dispatch workflow | Not implemented |
| Reports and exports | Not implemented |
| Automated benchmark tests | Not implemented |
| Deployment and demo | Not implemented |

This table will be updated as verified work is committed.

## Security and data policy

- Use only dummy benchmark data and invented demo data.
- Do not commit real customer, supplier or company information.
- Do not commit passwords, API keys, tokens, database credentials or private environment files.
- Keep secrets in local environment configuration and provide a safe example configuration when the application is implemented.
- Use backend authorization and audit records for sensitive business operations.

## Documentation

- [Product Requirements — Requirements.md](./Requirements.md): detailed scope, functional and non-functional requirements, benchmark scenario, assumptions and acceptance tests.
- [System Architecture — docs/architecture.md](./docs/architecture.md): proposed modules, layers, transaction boundaries, security and testing strategy.
- [Database Schema — docs/database-schema.md](./docs/database-schema.md): proposed entities, relationships, constraints, inventory ledger and migration order.

Setup, API contract, transaction-design, testing and deployment documentation will be added as implementation progresses.

---

**BatchFlow** — a traceable path from order to production, stock, billing and audit.
