# Sample Data Files

These three files are ready to upload directly into the app via the **Upload** page. They demonstrate each source type and include deliberate edge cases to show the anomaly detection working.

---

## sap_fuel_sample.txt

**Source type:** SAP Fuel & Procurement  
**Format:** Tab-separated, German column headers (Belegdatum, WERKS, KOSTL etc.), German date format (dd.MM.yyyy)  
**Rows:** 16 across 4 plants (DE01, DE02, DE03, UK01)  
**Fuel types:** Diesel (FUEL01), Petrol (FUEL02), Natural Gas in kWh (FUEL03), LPG (FUEL04)  
**Deliberate anomaly:** Row 11 — Plant DE01, 28 March 2024 — quantity 99,999 litres diesel. This is ~8× the typical monthly purchase and will be flagged as a statistical outlier (z-score > 3).

---

## utility_electricity_sample.csv

**Source type:** Utility Electricity  
**Format:** Portal CSV (EDF/Octopus style), English headers  
**Rows:** 14 across 4 meters, 3 months (Jan–Mar 2024)  
**Sites:** DE01 North Hall, DE01 South Hall, DE02 Main Building, DE03 Production, UK01 Birmingham  
**Deliberate anomalies:**
- MTR-DE02-A January and March: `read_type = Estimated` — flagged as estimated meter reads requiring verification
- Billing periods deliberately offset from calendar months (e.g. Jan 5 → Feb 4) — realistic utility billing behaviour

---

## travel_concur_sample.json

**Source type:** Travel — Concur/Navan  
**Format:** Concur v3 JSON with `Items` wrapper  
**Entries:** 14 expense entries across 8 expense reports  
**Includes:**
- Short-haul economy flight (LHR→FRA)
- Long-haul business class flight (LHR→SIN) — business class multiplier ×2.0 applied
- Return flight (LHR→AMS) — distance doubled automatically
- Long-haul economy (LHR→JFK)
- Hotel stays (2 nights Frankfurt, 3 nights Singapore, 1 night Amsterdam)
- Rail (Eurostar London→Paris, Avanti London→Birmingham)
- Taxi/ride-hail (Uber Frankfurt, NYC cab, Uber Birmingham)
- Rental car (Hertz Germany, 380km)
- **Deliberate anomaly:** RPRT-006-001 — Airfare with no IATA codes. CO2e set to 0, flagged as "missing IATA codes — distance unknown"

---

## How to use

1. Start the app locally or open the live URL
2. Go to **Upload** page
3. Select the correct source type
4. Drag and drop the file
5. Click **Upload & Ingest**
6. Go to **Records** page to see the parsed results and flags
