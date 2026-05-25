# DECISIONS.md — Breathe ESG

Every ambiguity I resolved during this build, the choice I made, the rationale, and what I'd have asked the PM.

---

## Source 1: SAP Fuel & Procurement

### Decision: ME2N/ME2L flat-file export, not IDoc or OData

**Alternatives considered:**
- **IDoc** — the inter-system message format SAP uses for EDI. Not a reporting export. You'd use IDocs if Breathe ESG were a connected SAP partner receiving real-time documents via ALE/EDI. We're not; we're an off-system analytics tool receiving periodic data dumps.
- **OData / RFC/BAPI** — possible via SAP Gateway or direct RFC calls, but requires Fiori setup, BASIS team involvement, and firewall rules at the client site. Not realistic for an onboarding task.
- **ME2N tab-separated flat file** — the standard way a procurement controller actually gets data out of SAP. Go to ME2N, set scope, execute, List → Save → Local File. SAP defaults to tab-separated with German column headers (Belegdatum not DocumentDate) and German number format (1.234,56 not 1234.56). This is the realistic shape.

**What subset I handled:**
- Purchase orders for fuel materials (MATKL codes FUEL01–FUEL04)
- Quantity (MENGE), unit (MEINS), plant (WERKS), cost centre (KOSTL), vendor (LIFNR), material description (TXZ01), PO number (EBELN), document date (Belegdatum/BLDAT)
- Not handled: multi-line PO items (EBAN → EKPO join), goods receipts (MIGO) vs orders (this prototype uses the PO quantity, not GR quantity — see TRADEOFFS.md), non-fuel procurements (would require a material group → scope 3 mapping table)

**German encoding choices:**
- Dates: `dd.MM.yyyy` (most common config), also handles `dd/MM/yyyy` and ISO
- Numbers: strip `.` thousand separators, swap `,` decimal to `.`
- Column header aliases: the parser accepts both `Belegdatum` and `BLDAT`, `MENGE` and `Quantity`, etc.

**What I'd ask the PM:**
1. Do they use goods receipt (MIGO/MIGO_GR) quantities or purchase order quantities? GR is more accurate for emissions (what was actually delivered vs. ordered) but requires a different SAP transaction.
2. Are any plants outside DEFRA regions? UK plants use UK grid factor; German plants should use EU ETS factors for electricity — currently I'm using UK grid factor uniformly. That's wrong for production.
3. Is there an existing material group → fuel type mapping in their SAP system, or does the description (TXZ01) have to be parsed with regex?

---

## Source 2: Utility Electricity

### Decision: Portal CSV export, not PDF or Green Button API

**Alternatives considered:**
- **PDF bill** — every major UK/EU utility produces one, but parsing PDFs is fragile (positional layout changes with tariff codes, line breaks in numbers, scanned PDFs need OCR). The signal-to-noise ratio is terrible and it breaks silently when the utility redesigns their bill template. I'd only reach for this if the CSV portal genuinely didn't exist.
- **Green Button API** — US standard (ESPI protocol), used by Pacific Gas & Electric, National Grid, Eversource. No serious UK utility (EDF, Octopus, British Gas Business) has implemented it for enterprise accounts. European utilities have their own customer portal CSV exports. Green Button is the right long-term answer for US deployments, not a UK/EU enterprise client.
- **Portal CSV** — EDF Business, Octopus Energy for Business, E.ON Next all expose a CSV export from their portal with: account number, meter ID, site name, period start/end, read type (Actual/Estimated), consumption in kWh, demand in kW, unit rate, total cost. This is what the facilities team actually sends you.

**What subset I handled:**
- Single-site electricity consumption only (no gas, heat, or water from utility bills)
- kWh/MWh/GJ input units → normalized to kWh
- Billing period vs. calendar month misalignment: `activity_date` = midpoint of billing period, `period_start` and `period_end` preserved
- Estimated read flagging: rows with `read_type = Estimated` get `is_flagged = True` with reason "Estimated meter read — verify against subsequent Actual reading"
- Duplicate detection: same meter × period flagged as potential duplicate

**What I'd ask the PM:**
1. Multiple utilities or a single supplier? (client may have EDF for Germany, Octopus for UK — the currency and rate fields will differ)
2. Do they have solar/onsite generation? If so, the net export vs. gross consumption distinction matters for Scope 2 market-based vs. location-based reporting.
3. Half-hourly AMR data or monthly bills? Half-hourly is better for peak demand analysis but is a different file shape.

---

## Source 3: Corporate Travel — Concur

### Decision: Concur v3 JSON API export format

**Alternatives considered:**
- **CSV admin export** — Concur does produce CSVs, but the column set is admin-configurable (each client has a different schema depending on which fields their Concur admin turned on). The JSON API schema is defined by Concur and consistent.
- **Navan export** — Navan (formerly TripActions) exposes a similar JSON structure. I wrote the parser to handle both by normalising on ingest; Navan uses `trip_type` where Concur uses `ExpenseTypeName`, etc.
- **Concur v4 API** — the newer API, but v3 is still the most widely deployed and documented for expense reports. Same decision as SAP: use what actually exists in the client's system today.

**What subset I handled:**
- Expense types: Airfare, Hotel/Accommodation, Train/Rail, Taxi/Ride-hail, Rental Car. Keywords in `ExpenseTypeName` resolve to category.
- Flights: great-circle distance from IATA codes (airport lookup table with ~60 major airports). If IATA codes are missing, distance defaults to 0 and the record is flagged.
- Cabin class multipliers: economy = 1.0×, business = 2.0×, first = 2.9× (DEFRA radiative forcing uplift applied)
- Return trips: if `Comment` or `VendorDescription` contains "return", distance is doubled
- Hotels: `nights` field from Concur; if absent, 1 night assumed and flagged
- Ground: `distance_km` from Concur if present; otherwise flagged as unknown distance

**Not handled:**
- Multi-segment itineraries in a single record (e.g. LHR→DXB→SIN). The parser sums legs if provided as a list but real Concur data sometimes represents this as a single record with just origin/destination. A proper implementation would integrate with a flight data API (Amadeus, OAG) to break routes into segments.
- Offsetting/purchased offsets — would require a separate source type
- Commuting data — Scope 3 Cat 7, entirely separate from business travel

**What I'd ask the PM:**
1. Is the client's Concur configured with custom fields for trip purpose, project code, cost centre? If yes, those should be captured for cost centre apportionment.
2. Do they want employee-level granularity in the dashboard, or is aggregate by cost centre enough? (Data privacy question — some HR policies prohibit individual-level emissions reporting)
3. Are they currently booking via an agent rather than Concur? Some enterprises still use manual expense claims for non-Concur bookings. If so, we need a manual entry path.

---

## Architecture decisions

### Decision: Synchronous ingestion in prototype, not async

File ingestion runs synchronously in the request/response cycle. A 200-row SAP file takes ~50ms. In production with 50,000-row files, this needs a task queue (Celery + Redis or Django-Q). I left this synchronous deliberately — adding async task processing would require Redis infrastructure, a worker process, and WebSocket or polling for status updates. That's a full week of work for something that doesn't demonstrate the actual domain logic. The code is structured so `run_ingestion(batch)` is a pure function that can be dropped into a Celery task with zero changes.

### Decision: SQLite for prototype, not PostgreSQL

SQLite is fine for a prototype with one demo user. In production: Postgres, with row-level security on the `organisation` column if multi-tenant isolation is a hard requirement. The ORM code is database-agnostic; swapping the `DATABASE` setting is the only change needed.

### Decision: Token authentication, not JWT

DRF's built-in token auth is simpler and sufficient. JWTs add complexity (refresh token rotation, token revocation on logout becomes a blacklist problem). Token auth with short-lived tokens per session is fine for a prototype. Production would want OAuth2 with the client's SSO provider (Okta, Azure AD).

### Decision: DEFRA 2023 factors hardcoded in settings, not a database table

Emission factors will change. DEFRA releases updates annually. In production, factors should be in a versioned database table so you can: (a) apply new factors to historical data and recompute, (b) show auditors exactly which factor version was used for each record. For the prototype, they're in `settings.EMISSION_FACTORS` — this is documented as a deliberate shortcut in TRADEOFFS.md. The model already stores `emission_factor` and `emission_factor_source` per record, which is the right design even if the source is currently a settings dict.

### Decision: Anomaly detection is z-score within batch, not across all historical data

Outlier detection flags records where `|z| > 3` within the same batch and category. This is crude: it won't catch a facility that has been consistently overstating consumption for months, only single-batch spikes. A proper anomaly detector would compare against rolling historical averages. This is a deliberate scope choice — see TRADEOFFS.md.

### Decision: Review states are pending → flagged/approved/rejected → locked

The state machine is intentionally simple. `locked` is terminal; an amendment requires an admin to unlock. In practice, audit lock workflows vary significantly by client (some lock by year, some by report, some by signatory). I've modelled the simplest useful shape: `Organisation.locked_year` marks a reporting year as closed; records in that year cannot transition. Finer-grained locking (by scope, by report) would come from understanding the client's actual audit workflow.

---

## What I'd ask the PM before shipping

1. **Multiple reporting standards?** GHG Protocol and TCFD are different. Does the client report to SECR (UK), CSRD (EU), or both? Scope 2 market-based vs. location-based is mandatory under GHG Protocol Scope 2 Guidance and those require either supplier-specific emission factors (REGOs, PPAs) or residual mix factors — neither is in this prototype.

2. **Base year and intensity metrics?** Most corporate sustainability reports show emissions intensity (kgCO2e per £ revenue, per employee, per unit of production). The data model supports this (co2e_kg is on every record) but the dashboard doesn't show it. Intensity requires a second data series (revenue, headcount) not in scope here.

3. **Who are the auditors?** If they're using a Big 4 firm for limited assurance, the auditors will want: the original source files (we keep these), the calculation methodology (the `emission_factor_source` field), and evidence that no records were changed without audit trail. All three are handled in the current design.

4. **What does "sign off" mean operationally?** Right now an `approved` record is locked at year-end. But does the client want a multi-stage approval — analyst approves, manager countersigns, Finance Director locks? That's a workflow design question, not a technical one.
