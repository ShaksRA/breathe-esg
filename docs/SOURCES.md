# SOURCES.md — Breathe ESG

For each of the three sources: what real-world format I researched, what I learned, what the sample data looks like and why, and what would break in a real deployment.

---

## Source 1: SAP Fuel & Procurement

### What I researched

SAP purchase order reporting is accessed via transaction **ME2N** (by purchase order number) or **ME2L** (by vendor). Both produce an ALV grid report that can be saved as a local file. The default export format is tab-separated with German column headers in a standard SAP system — this is because the underlying ABAP Dictionary uses German technical names.

Key column names in a real export:
- `Belegdatum` (document date, equivalent to `BLDAT`)
- `WERKS` (plant/Werk code — a 4-character code like `DE01`)
- `KOSTL` (cost centre/Kostenstelle)
- `LIFNR` (vendor number — the internal SAP key, not the vendor name)
- `MATNR` (material number)
- `TXZ01` (short text — the human-readable description)
- `MATKL` (material group — this is how we identify fuel type)
- `MENGE` (quantity)
- `MEINS` (base unit of measure — SAP internal codes: `L`, `KWH`, `KG`, `M3`, `ST`)
- `NETPR` (net price)
- `WAERS` (currency — not the same for every plant in a multinational)
- `EBELN` (purchase order number — 10 digits)

Number format is German: `1.234,56` (period as thousands separator, comma as decimal). Dates are `dd.MM.yyyy`.

I also looked at SAP OData (via SAP Gateway, transaction `/IWFND/MAINT_SERVICE`) and IDocs. OData is the right long-term direction but requires SAP Basis configuration and a transport to production — not a day-one option for a new enterprise onboarding. IDocs are point-to-point EDI messages, not reporting extracts.

### What the sample data looks like and why

16 rows covering January–June 2024, across 4 plants (DE01, DE02, DE03, UK01).

- **Fuel types:** diesel (`MATKL=FUEL01`), petrol (`FUEL02`), natural gas (`FUEL03`, in kWh because the UK gas market sells by kWh), LPG (`FUEL04`)
- **One deliberate anomaly:** row 11 (25.04.2024, DE01) has quantity 99,999 litres of diesel — about 8× the typical monthly purchase for that plant. This triggers the z-score outlier flag in the ingestion service.
- **Currency mix:** German plants in EUR, UK plant in GBP — reflecting how a real multinational SAP instance works with company codes in different countries.
- **German date format:** all dates are `dd.MM.yyyy`.
- **German number format:** quantities use period/comma — `12.500,00` — not entered in the sample because the raw values are integers, but the parser handles it.

### What would break in a real deployment

1. **Column headers vary by SAP configuration.** Some clients have renamed fields via ABAP customising. The parser uses a column alias map but it can't anticipate every possible custom name. We'd need the client to send us a sample export on day 1 so we can add their aliases.

2. **Purchase order vs. goods receipt quantities.** ME2N exports PO quantities — what was ordered, not what was delivered. The accurate figure for emissions is what was received (MIGO_GR). For a manufacturing client with high order-to-delivery gaps, these can diverge significantly. We'd need to ingest from MIGO/MIGO_GR instead, or cross-reference the two.

3. **Non-fuel procurement (Scope 3, Cat 1).** Material groups for goods and services bought would need a separate emission factor mapping table — one factor per material group. This doesn't exist in DEFRA's factor set; it requires spend-based or physical unit factors from databases like Ecoinvent or EEIO tables. Entire separate problem.

4. **Plant codes without a lookup table.** `WERKS = DE01` means nothing without the `FacilityLookup` table. If the client hasn't set up facilities before uploading, plant codes won't resolve to names/countries, and the Scope 2 electricity factor (country-specific) will be wrong.

5. **German characters in descriptions.** `TXZ01` often contains `ü`, `ö`, `ä`, `ß`. The file may be exported as Latin-1 (Windows-1252) rather than UTF-8. The parser needs to handle encoding detection or require UTF-8.

---

## Source 2: Utility Electricity

### What I researched

I looked at how UK and EU utility providers expose electricity data for enterprise accounts:

- **EDF Business (UK):** Customer portal ("MyEDF") has a "Data Download" section, exports CSV with fields: `account_ref`, `meter_serial`, `site_name`, `supply_start`, `supply_end`, `reads_type` (Actual/Estimated/Customer Read), `consumption_kwh`, `max_demand_kw`, `unit_rate_pence`, `standing_charge_pence`, `total_pence`
- **Octopus Energy for Business:** Similar portal CSV, notably with `mpan` (Meter Point Administration Number) instead of `meter_serial`
- **E.ON Next Business:** Uses `HH data` (half-hourly) CSV for AMR meters, monthly summary CSV for quarterly billing
- **PG&E (US reference):** Green Button XML standard — `UsagePoint`, `MeterReading`, `IntervalBlock` — structured but rarely encountered outside the US
- **German utilities (RWE, E.ON Germany):** Portal CSV with billing periods in `dd.MM.yyyy` format, often EUR

Key realities:
- Billing periods are **not** calendar months. A meter read on 2024-01-03 to 2024-02-02 is a 30-day window that spans two calendar months. For monthly reporting you have to decide: assign to the month of the midpoint? Or split the period?
- `read_type = Estimated` means the utility estimated consumption because they couldn't reach the meter. These figures get corrected in a later month. Flagging them is important.
- Large sites often have multiple meters (sub-metering) — the sample has MTR-DE01-A and MTR-DE01-B for the same site.
- Half-hourly interval data exists for AMR-metered large accounts but is a completely different shape (96 readings per day, each in kWh/interval). Not handled in this prototype.

### What the sample data looks like and why

14 rows, 4 meters, 3 months (January–March 2024).

- **4 meters across 3 sites:** DE01 has two meters (North Hall and South Hall) — reflecting a real large plant with sub-metering. DE02, DE03, and UK01 each have one.
- **Billing period misalignment:** DE01-B bills from `2024-01-01` to `2024-02-01` (32 days), then `2024-02-02` to `2024-03-04` (31 days) — the meter read date drifts because the meter reader visits on a rolling schedule. This is intentional.
- **One Estimated row:** `MTR-DE02-A` January and March are `Estimated`. These get `is_flagged = True` with reason "Estimated meter read — verify against subsequent Actual reading."
- **Currency mix:** UK site in GBP, German sites in EUR. The cost fields are for reference only — we compute CO2e from kWh, not from cost.
- **High consumption values:** DE01 North Hall at 184,200 kWh/month is large but realistic for an industrial plant (roughly equivalent to a medium-sized factory running continuous production).

### What would break in a real deployment

1. **Market-based vs. location-based Scope 2.** GHG Protocol Scope 2 Guidance requires companies to report both. Location-based uses the national grid average factor (what we're using: 0.207 kgCO2e/kWh for UK). Market-based uses supplier-specific factors from REGOs (Renewable Energy Guarantees of Origin) or PPAs (Power Purchase Agreements). If the client has a renewable electricity contract, their market-based Scope 2 could be near zero. We don't capture the tariff type, let alone the REGO certificates.

2. **Grid factor by country.** UK grid: 0.207 kgCO2e/kWh. German grid: approximately 0.385 kgCO2e/kWh (Umweltbundesamt 2023). French grid: approximately 0.052 kgCO2e/kWh (very nuclear-heavy). The current parser uses the UK factor for every meter regardless of country. This needs a `country_code → electricity_factor` lookup table.

3. **MPAN/MPRN vs. meter serial.** UK meters are identified by MPAN (Meter Point Administration Number) for electricity and MPRN (Meter Point Reference Number) for gas. These are 13-digit and 10-digit identifiers respectively. The sample uses `meter_id` generically; real data would need MPAN handling to avoid duplicate detection false positives.

4. **Half-hourly data.** Any site with a maximum demand above 100 kW has an AMR meter with half-hourly interval data. The portal CSV for these is 17,520 rows/year per meter. The utility_parser would need a separate ingestion path.

5. **Billing period > 100 days.** Some utilities don't read meters for 3–4 months (especially smaller sites). The parser flags periods > 100 days but doesn't reject them. A proper implementation would split such periods at month boundaries for reporting purposes.

---

## Source 3: Corporate Travel — Concur

### What I researched

Concur (SAP Concur) is the dominant corporate travel and expense platform globally. The relevant API is the [Expense Report v3 API](https://developer.concur.com/api-reference/expense/expense-report/v3.reports.html) and the [Expense Entry v3 API](https://developer.concur.com/api-reference/expense/expense-report/v3.expense-entries.html).

Key findings:
- Concur's `ExpenseTypeName` is **configurable per organisation**. What one client calls "Airfare" another calls "Air Travel - Domestic" or "Flight - International Business". There is no standard taxonomy. Parsing requires keyword matching on the free-text field.
- The v3 JSON structure uses `Items` as the array wrapper for expense entries.
- `TransactionAmount` is in `TransactionCurrencyCode` — not necessarily the reimbursement currency.
- Custom fields (`Custom1`–`Custom40`) are organisation-defined. Cost centre is often in `Custom1` or `Custom4` but varies per client.
- Flight distance is **not** a standard Concur field. Concur knows origin and destination (for compliance and approvals) but doesn't calculate distance. Distance has to be derived from airport codes or provided as a custom field.

I also reviewed the [Navan (TripActions) API](https://developer.navan.com/), which structures expense data similarly but uses different field names (`trip_type` instead of `ExpenseTypeName`, `departure_iata`/`arrival_iata` instead of `origin_iata`/`destination_iata`). The travel_parser handles both schemas.

### What the sample data looks like and why

14 Concur v3 JSON entries across 7 expense reports.

- **Flight variety:** Short-haul economy (LHR→FRA, 0.255 kgCO2e/km), long-haul business (LHR→SIN, 0.195 kgCO2e/km × 2.0 business class multiplier), domestic UK economy, short-haul economy return (LHR→AMS × 2 because "return trip" in comment)
- **Hotel stays:** 2-night Frankfurt stay, 3-night Singapore stay — these use the DEFRA 31 kgCO2e/room-night factor
- **Ground transport mix:** Uber (taxi, distance given), rental car (distance given), Eurostar (rail, distance from IATA-equivalent station codes)
- **One deliberately flagged entry:** entry RPRT-006-001 — a flight with no `origin_iata`/`destination_iata` fields. Parser flags as "missing IATA codes — distance unknown, CO2e computed as 0."
- **Cost centre in Custom1:** mirroring real Concur configuration where cost centre codes sit in Custom1.

### What would break in a real deployment

1. **`ExpenseTypeName` taxonomy.** The keyword classifier in the parser (`airfare`, `hotel`, `train`, etc.) covers the most common terms. A real client will have edge cases: "Client Entertainment" (not travel at all), "Rideshare" (is this taxi?), "Toll" (not a travel category). We'd need to review the client's Concur expense types and map them explicitly before go-live.

2. **Missing IATA codes.** Concur doesn't require itinerary fields for expense claims — an employee can just enter the amount. If the Concur configuration doesn't enforce origin/destination, a large proportion of flights will have no IATA codes and thus no computable distance. The record is flagged but CO2e is 0, which will understate Scope 3.

3. **Multi-segment itineraries.** LHR→DXB→SIN is two legs, but Concur often records it as a single line item with LHR and SIN. The actual CO2e should be computed on each leg separately (different distances, different factors). Currently the parser uses great-circle LHR→SIN, which is a reasonable approximation but not exact.

4. **Radiative forcing (RF) uplift.** DEFRA guidance recommends applying a radiative forcing index (RFI) factor of 1.9× to flight emissions to account for contrails, NOx, etc. Some clients report with RF, some without. Currently we're using DEFRA factors that already include a partial uplift, but whether to apply the full recommended multiplier is a policy decision that needs to be agreed with the client before their first submission.

5. **Employee privacy.** The sample includes `EmployeeID` fields. In some jurisdictions (GDPR in the EU, PDPA in many Asian countries), storing individual-level travel data linked to employee IDs may require explicit consent or pseudonymisation. The current model stores it in `supplier_name` (we're using it for the vendor field). A production system would need DPA guidance on what to retain.
