# MODEL.md — Breathe ESG Data Model

## Overview

The data model has three layers:

1. **Ingestion layer** — raw files and rows, immutable once written
2. **Normalized layer** — `EmissionRecord`, the canonical analytical row
3. **Audit layer** — `AuditLog`, append-only event stream

---

## Multi-tenancy

All data-bearing models carry a FK to `Organisation`. Queries are always scoped to the authenticated user's organisation (via `OrganisationMembership`). No cross-tenant data leakage is possible without filtering failure in the view layer.

`OrganisationMembership` carries a `role` field (`admin`, `analyst`, `auditor`). The current prototype enforces authentication but not role-based action restrictions (a deliberate tradeoff — see TRADEOFFS.md). An auditor getting a locked read-only view is the next increment.

---

## Ingestion layer

### UploadBatch

One row per file/pull. Tracks:
- `source_type` — which parser to use
- `raw_file` — the original file, kept forever
- `status` — `pending → processing → complete / partial / failed`
- `row_count_total / ok / failed`
- `processing_notes` — human-readable notes from the parser (first 20 issues)

**Why keep the raw file?** Because emission factors change. In 18 months someone will ask "what would our 2024 Scope 1 look like under the 2025 DEFRA factors?" You can only answer that if you kept the original quantities. Also: auditors require source evidence.

### SourceRow

One row per line in the source file. Stores:
- `raw_data` (JSON) — the original key:value dict, verbatim from the source
- `parse_status` — `ok / warning / failed / skipped`
- `parse_errors` — list of strings

`SourceRow` is written even for failed rows. This is intentional: you want to know *what* failed, not just *how many*.

The `OneToOneField` from `EmissionRecord → SourceRow` means you can always trace a normalized record back to its exact source line and show the analyst the original data.

---

## Normalized layer

### EmissionRecord

The central model. Key design decisions:

**Temporal fields:**
- `activity_date` — when the *activity* happened. This is what matters for GHG inventory. It is *not* the upload date or the billing date.
- `period_start / period_end` — for billing-period data (utility bills, which cover 28–35 days). A single activity_date (midpoint) is stored for querying, but the full period is preserved.

**Scope / category:**
- `scope` (1, 2, 3) — GHG Protocol scope. Integer field, not string, so you can filter numerically.
- `category` — more granular: `fuel_diesel`, `electricity`, `travel_flight`, etc. These map to specific emission factors and also to GHG Protocol categories within Scope 3.

**Dual quantity fields:**
- `quantity_original` + `unit_original` — exactly what the source said (e.g. `12500 L`)
- `quantity_normalized` + `unit_normalized` — converted to the unit used for the emission factor (also `L` for diesel, `kWh` for electricity, `km` for flights)

Why keep both? The original is the audit evidence. The normalized is what the computation used. If a dispute arises ("why does this row say 33.5 tCO2e?") you can trace: `12500 L × 2.68 kgCO2e/L = 33,500 kg = 33.5 t`. If you only stored kgCO2e, you'd lose the traceability.

**Emission factor fields:**
- `emission_factor` — the per-unit factor used
- `emission_factor_source` — attribution ("DEFRA 2023", "HCMI", etc.)
- `co2e_kg` — the product

These are denormalized (you could recompute `co2e_kg` from `quantity_normalized × emission_factor`). The denormalization is intentional: if the factor changes, we want to know what the *original* computation produced so we can see the delta. Recomputation against updated factors is a separate batch job.

**Review workflow:**
`review_status` follows this state machine:
```
pending → flagged → approved (terminal for audit)
       → rejected (terminal, excluded from audit submission)
       → approved (from any non-locked state)
locked (set by org admin when submitting to auditor)
```

`locked` records cannot be modified. This is enforced in `EmissionRecord.approve/reject/flag()` with a `ValueError`.

**Anomaly flags:**
- `is_flagged` — boolean, set by parser or statistical outlier detection
- `flag_reasons` — JSON list of human-readable reasons

Parser sets flags for: unknown units, estimated meter reads, duplicate document numbers, zero/negative quantities, unresolvable IATA codes.

Statistical detection flags records where `|z-score| > 3` within the same batch × category grouping. Requires ≥5 records to be meaningful.

**Edit tracking:**
- `is_edited` — set when an analyst changes `co2e_kg` after ingestion
- `original_co2e_kg` — the pre-edit value

---

## Audit layer

### AuditLog

Append-only. Never updated or deleted. Actions: `created`, `flagged`, `approved`, `rejected`, `edited`, `locked`, `unlocked`.

Each row stores a `snapshot` (JSON) of the key fields at time of the action. This means even if the `EmissionRecord` is later edited, the audit trail shows what the value *was* at approval time.

In a production deployment, this table would live in a separate schema with `REVOKE UPDATE, DELETE` granted at the database level.

---

## Supporting models

### FacilityLookup

Maps SAP Werk codes (e.g. `DE01`) to human-readable names and countries. SAP exports only the code. Without this table, the analyst sees `DE01` in the dashboard and has no idea what facility it refers to. The parser enriches `EmissionRecord.facility_name` from this table at ingestion time.

---

## Scope classification mapping

| Source | Category | Scope |
|--------|----------|-------|
| SAP MATKL FUEL01 (Diesel) | fuel_diesel | 1 |
| SAP MATKL FUEL02 (Petrol) | fuel_petrol | 1 |
| SAP MATKL FUEL03 (Natural Gas) | fuel_natural_gas | 1 |
| SAP MATKL FUEL04 (LPG) | fuel_lpg | 1 |
| Utility CSV (electricity) | electricity | 2 |
| Concur Airfare | travel_flight | 3 |
| Concur Hotel | travel_hotel | 3 |
| Concur Rail/Taxi/Car | travel_rail/taxi/rental_car | 3 |

Scope 3 category under GHG Protocol: all travel is Category 6 (Business Travel).

---

## Unit normalization

**Fuels (Scope 1):**
- Litres → L (direct)
- US gallons → ×3.785 → L
- m³ → ×1000 → L (LPG/gas as liquid)
- kWh (natural gas) → stays kWh; factor is 0.202 kgCO2e/kWh

**Electricity (Scope 2):**
- kWh → stays kWh
- MWh → ×1000 → kWh
- GJ → ×277.778 → kWh

**Travel (Scope 3):**
- Flights: passenger-km computed from great circle distance between IATA codes
- Hotels: room-nights (direct from source)
- Rail/taxi/car: km (from source, or estimated)

---

## What would change for production

1. **PostgreSQL not SQLite** — JSON queries, indexing, schema separation for audit table
2. **Emission factor config table** — currently hardcoded constants. Should be a versioned table with `valid_from / valid_to` so you can audit which factor version applied to a given record
3. **Celery for async ingestion** — currently synchronous; large SAP files (100k rows) would time out the HTTP request
4. **Market-based accounting** — `EmissionRecord` currently only holds location-based Scope 2 factor. Add `co2e_kg_market_based` for RE100/renewable certificate accounting
5. **Currency normalization** — travel amounts are stored in original currency (GBP, USD, etc.); a FX rate table would enable cost analysis
