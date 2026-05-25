"""
Corporate Travel parser — Concur / Navan JSON export.

Format choice: Concur Expense v3 API JSON export / Navan data export JSON.

Why JSON over CSV:
  Concur's native export format from the API is JSON (v3/v4 Entries endpoint).
  Many corporate travel platforms (Navan, TravelPerk) also export JSON.
  The CSV export from Concur is user-configurable (admins pick columns) so
  its shape is unpredictable client-to-client.
  JSON has explicit typing and nesting (expense report → line items → segments)
  which preserves the relationship between trip and segments.

Concur Expense v3 entry shape (key fields we use):
  {
    "ID": "gWr...",
    "ExpenseTypeName": "Airfare" | "Hotel" | "Taxi" | "Car Rental" | "Train" | "Ground Transport",
    "TransactionDate": "2024-01-15",
    "TransactionAmount": 342.50,
    "TransactionCurrencyCode": "GBP",
    "VendorDescription": "British Airways",
    "LocationName": "London, United Kingdom",
    "Custom1": "cost centre code",  // varies per org
    "Report": { "ID": "...", "Name": "..." },
    // For flights, often in Comment or custom fields:
    "Comment": "LHR-JFK return",
  }

Navan adds trip_segments with origin_iata, destination_iata, cabin_class.
We handle both shapes.

Scope 3 GHG categories:
  - Flights: Category 6 (Business travel)
  - Hotels: Category 6
  - Rail/taxi/rental: Category 6

Emission factors (DEFRA 2023 Travel):
  Short-haul flight economy: 0.255 kgCO2e/passenger-km
  Long-haul flight economy:  0.195 kgCO2e/passenger-km
  International flight:      0.195 kgCO2e/passenger-km (conservative)
  Rail (UK average):         0.041 kgCO2e/passenger-km
  Taxi/ridehail:             0.148 kgCO2e/km
  Rental car (average):      0.168 kgCO2e/km
  Hotel night:               31.0  kgCO2e/room-night (HCMI avg)

Airport distance computation:
  When only IATA codes are given (no distance), we use a lookup table
  of major airports with lat/lon and compute great circle distance.
  We do NOT silently drop records without distance — we flag them.
"""

import json
import re
import math
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, Tuple, List

# Emission factors
EF = {
    'flight_short_haul': Decimal('0.255'),   # ≤ 3700 km, economy
    'flight_long_haul':  Decimal('0.195'),   # > 3700 km, economy
    'flight_business_multiplier': Decimal('2.0'),  # business class ×2
    'flight_first_multiplier':    Decimal('2.9'),
    'rail':         Decimal('0.041'),
    'taxi':         Decimal('0.148'),
    'rental_car':   Decimal('0.168'),
    'hotel_night':  Decimal('31.0'),   # per room-night
}

# Major airport IATA codes → (lat, lon) for distance calculation
# Subset of IATA codes; a real deployment uses a full DB table
AIRPORT_COORDS = {
    'LHR': (51.477, -0.461),  'LGW': (51.148, -0.190),
    'JFK': (40.641, -73.778), 'LAX': (33.943, -118.408),
    'CDG': (49.010, 2.551),   'FRA': (50.033, 8.571),
    'AMS': (52.308, 4.764),   'SIN': (1.350, 103.994),
    'DXB': (25.253, 55.364),  'BOM': (19.089, 72.868),
    'DEL': (28.555, 77.100),  'HKG': (22.308, 113.918),
    'NRT': (35.764, 140.386), 'SYD': (-33.947, 151.179),
    'ORD': (41.978, -87.905), 'ATL': (33.637, -84.428),
    'DFW': (32.899, -97.037), 'MIA': (25.796, -80.287),
    'BOS': (42.366, -71.010), 'SEA': (47.449, -122.309),
    'YYZ': (43.677, -79.631), 'GRU': (-23.432, -46.469),
    'MEX': (19.436, -99.072), 'MAD': (40.472, -3.561),
    'BCN': (41.297, 2.078),   'MXP': (45.630, 8.723),
    'ZRH': (47.458, 8.548),   'BRU': (50.901, 4.486),
    'CPH': (55.618, 12.656),  'ARN': (59.652, 17.919),
    'HEL': (60.317, 24.963),  'IST': (41.275, 28.752),
    'DOH': (25.261, 51.565),  'AUH': (24.433, 54.651),
    'JNB': (-26.134, 28.242), 'NBO': (-1.319, 36.928),
    'CAI': (30.122, 31.406),  'ICN': (37.469, 126.451),
    'PEK': (40.073, 116.598), 'PVG': (31.143, 121.805),
    'BLR': (13.198, 77.706),  'MAA': (12.994, 80.176),
    'HYD': (17.231, 78.430),  'CCU': (22.655, 88.447),
    'MAN': (53.354, -2.275),  'BHX': (52.453, -1.748),
    'EDI': (55.950, -3.373),  'GLA': (55.872, -4.433),
    'DUB': (53.421, -6.270),  'LIS': (38.774, -9.134),
    'VIE': (48.110, 16.570),  'WAW': (52.165, 20.967),
    'PRG': (50.100, 14.260),  'BUD': (47.437, 19.255),
    'ATH': (37.936, 23.945),
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great circle distance in km between two (lat, lon) points."""
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))


def _parse_date(raw) -> Optional[date]:
    if not raw:
        return None
    if isinstance(raw, date):
        return raw
    raw = str(raw).strip()
    for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%Y-%m-%dT%H:%M:%S']:
        try:
            return datetime.strptime(raw[:10], fmt[:10] if len(fmt) > 10 else fmt).date()
        except ValueError:
            continue
    return None


def _extract_iata_codes(text: str) -> List[str]:
    """Pull IATA-looking codes (3 uppercase letters) from a string."""
    return re.findall(r'\b([A-Z]{3})\b', text or '')


def _flight_distance_km(origin: str, dest: str) -> Tuple[Optional[float], List[str]]:
    """Compute distance from IATA codes. Returns (km, warnings)."""
    warnings = []
    o = AIRPORT_COORDS.get(origin.upper())
    d = AIRPORT_COORDS.get(dest.upper())
    if not o:
        warnings.append(f"Airport '{origin}' not in lookup table — cannot compute distance.")
        return None, warnings
    if not d:
        warnings.append(f"Airport '{dest}' not in lookup table — cannot compute distance.")
        return None, warnings
    km = haversine_km(*o, *d)
    return km, warnings


def _classify_expense_type(raw_type: str) -> Optional[str]:
    """
    Map Concur's free-text ExpenseTypeName to our category.
    Concur type names are org-configurable so we do keyword matching.
    """
    t = raw_type.lower()
    if any(k in t for k in ['air', 'flight', 'airline', 'plane']):
        return 'travel_flight'
    if any(k in t for k in ['hotel', 'lodging', 'accommodation', 'motel', 'inn']):
        return 'travel_hotel'
    if any(k in t for k in ['train', 'rail', 'metro', 'underground', 'tube', 'subway', 'tram']):
        return 'travel_rail'
    if any(k in t for k in ['taxi', 'uber', 'lyft', 'rideshare', 'cab', 'ola', 'grab']):
        return 'travel_taxi'
    if any(k in t for k in ['car rental', 'rental car', 'hire car', 'hertz', 'avis', 'enterprise']):
        return 'travel_rental_car'
    if any(k in t for k in ['ground', 'bus', 'coach']):
        return 'travel_taxi'  # approximate with taxi factor
    return None


def _process_flight_entry(entry: dict) -> Tuple[Optional[Decimal], str, str, List[str], List[str]]:
    """
    Returns (co2e_kg, unit_normalized, quantity_normalized, warnings, errors).
    Tries to get distance from:
      1. explicit distance_km field (Navan)
      2. origin/destination IATA from segments
      3. IATA codes parsed from comment/description
    """
    warnings = []
    errors = []

    # Navan-style: segments with IATA
    segments = entry.get('trip_segments') or entry.get('segments') or []
    origin_iata = entry.get('origin_iata') or entry.get('origin')
    dest_iata = entry.get('destination_iata') or entry.get('destination')

    # Try to get pre-computed distance
    distance_km = entry.get('distance_km') or entry.get('distanceKm')

    if not distance_km and origin_iata and dest_iata:
        distance_km, dist_warnings = _flight_distance_km(origin_iata, dest_iata)
        warnings.extend(dist_warnings)

    if not distance_km and segments:
        # Multi-segment: sum legs
        total = 0.0
        for seg in segments:
            o = seg.get('origin_iata') or seg.get('origin', '')
            d = seg.get('destination_iata') or seg.get('destination', '')
            if o and d:
                leg_km, w = _flight_distance_km(o, d)
                warnings.extend(w)
                if leg_km:
                    total += leg_km
        if total > 0:
            distance_km = total

    if not distance_km:
        # Try extracting IATA from comment
        comment = entry.get('Comment') or entry.get('comment') or entry.get('description', '')
        codes = _extract_iata_codes(comment)
        if len(codes) >= 2:
            d, w = _flight_distance_km(codes[0], codes[1])
            warnings.extend(w)
            if d:
                distance_km = d
                warnings.append(f"Distance estimated from IATA codes in comment: {codes[0]}→{codes[1]}")

    if not distance_km:
        warnings.append("Could not determine flight distance — no IATA codes found. "
                        "CO2e set to 0; manual entry required.")
        return Decimal('0'), 'km', '0', warnings, errors

    km = Decimal(str(round(float(distance_km), 2)))

    # Return trip?
    is_return = entry.get('is_return') or entry.get('return_trip', False)
    if is_return:
        km = km * 2
        warnings.append("Return trip detected — distance doubled.")

    # Cabin class
    cabin = (entry.get('cabin_class') or entry.get('CabinClass') or 'economy').lower()
    if distance_km <= 3700:
        base_ef = EF['flight_short_haul']
    else:
        base_ef = EF['flight_long_haul']

    if 'business' in cabin:
        ef = base_ef * EF['flight_business_multiplier']
        warnings.append("Business class detected — emission factor ×2.0 applied.")
    elif 'first' in cabin:
        ef = base_ef * EF['flight_first_multiplier']
        warnings.append("First class detected — emission factor ×2.9 applied.")
    else:
        ef = base_ef

    co2e = km * ef
    return co2e, 'km', str(km), warnings, errors


def parse_travel_json(file_content: bytes):
    """
    Accepts Concur/Navan JSON export. Can be:
      - A JSON array of expense entries
      - {"Items": [...]} (Concur v3 pagination wrapper)
      - {"entries": [...]} (Navan)
    """
    try:
        text = file_content.decode('utf-8')
        data = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        yield {
            'row_index': 0, 'raw_data': {}, 'parsed_fields': None,
            'errors': [f"JSON parse error: {e}"], 'warnings': [], 'status': 'failed',
        }
        return

    # Unwrap envelope
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        entries = (data.get('Items') or data.get('entries') or
                   data.get('expense_entries') or data.get('data') or [data])
    else:
        yield {
            'row_index': 0, 'raw_data': {}, 'parsed_fields': None,
            'errors': ['Unexpected JSON structure — expected array or {Items: [...]}'],
            'warnings': [], 'status': 'failed',
        }
        return

    for row_index, entry in enumerate(entries):
        raw_data = entry if isinstance(entry, dict) else {'value': entry}
        errors = []
        warnings = []

        # --- Date ---
        date_raw = (entry.get('TransactionDate') or entry.get('transaction_date') or
                    entry.get('date') or entry.get('Date') or '')
        activity_date = _parse_date(date_raw)
        if not activity_date:
            errors.append(f"Cannot parse transaction date '{date_raw}'")

        # --- Expense type ---
        type_raw = (entry.get('ExpenseTypeName') or entry.get('expense_type') or
                    entry.get('type') or entry.get('Type') or '')
        category = _classify_expense_type(type_raw)
        if not category:
            warnings.append(f"Unknown expense type '{type_raw}' — cannot compute emissions. "
                            "Set to 'travel_taxi' as placeholder; review required.")
            category = 'travel_taxi'

        # --- Cost centre / employee ---
        cost_centre = (entry.get('Custom1') or entry.get('cost_centre') or
                       entry.get('CostCentre') or entry.get('DepartmentCode') or '')
        employee_id = (entry.get('EmployeeID') or entry.get('employee_id') or '')
        vendor = (entry.get('VendorDescription') or entry.get('vendor') or
                  entry.get('Vendor') or entry.get('supplier') or '')
        description = (entry.get('Comment') or entry.get('comment') or
                       entry.get('description') or type_raw)
        reference_id = (entry.get('ID') or entry.get('id') or entry.get('ReportID') or '')

        # --- Compute CO2e by category ---
        quantity_normalized = Decimal('0')
        unit_normalized = 'unit'
        co2e_kg = Decimal('0')
        emission_factor = Decimal('0')

        if category == 'travel_flight':
            co2e_kg, unit_normalized, qty_str, w, e = _process_flight_entry(entry)
            warnings.extend(w)
            errors.extend(e)
            quantity_normalized = Decimal(qty_str)
            if quantity_normalized > 0:
                emission_factor = co2e_kg / quantity_normalized
            else:
                emission_factor = EF['flight_long_haul']

        elif category == 'travel_hotel':
            nights_raw = (entry.get('nights') or entry.get('Nights') or
                          entry.get('quantity') or 1)
            try:
                nights = Decimal(str(nights_raw))
            except Exception:
                nights = Decimal('1')
                warnings.append("Could not parse number of nights — assumed 1.")
            quantity_normalized = nights
            unit_normalized = 'nights'
            emission_factor = EF['hotel_night']
            co2e_kg = nights * emission_factor

        elif category in ('travel_rail', 'travel_taxi', 'travel_rental_car'):
            dist_raw = (entry.get('distance_km') or entry.get('distanceKm') or
                        entry.get('distance') or None)
            if dist_raw:
                try:
                    distance_km = Decimal(str(dist_raw))
                except Exception:
                    distance_km = None

                if distance_km:
                    ef_key = {'travel_rail': 'rail',
                              'travel_taxi': 'taxi',
                              'travel_rental_car': 'rental_car'}[category]
                    emission_factor = EF[ef_key]
                    co2e_kg = distance_km * emission_factor
                    quantity_normalized = distance_km
                    unit_normalized = 'km'
                else:
                    warnings.append("Distance not provided — CO2e set to 0. Manual entry required.")
            else:
                warnings.append("No distance_km field — CO2e cannot be computed. "
                                "Derive from transaction amount or itinerary.")

        # --- Anomaly checks ---
        if co2e_kg > Decimal('5000'):
            warnings.append(f"Very high CO2e ({co2e_kg} kgCO2e) for single trip — verify correctness.")

        # Original quantity = transaction amount (preserves financial record)
        transaction_amount = Decimal(str(
            entry.get('TransactionAmount') or entry.get('transaction_amount') or
            entry.get('amount') or 0
        ))
        currency = (entry.get('TransactionCurrencyCode') or entry.get('currency') or 'USD')

        status = 'failed' if errors else ('warning' if warnings else 'ok')

        ef_label_map = {
            'travel_flight': 'DEFRA 2023 Flights',
            'travel_hotel': 'HCMI Hotel Carbon Measurement Methodology',
            'travel_rail': 'DEFRA 2023 Rail',
            'travel_taxi': 'DEFRA 2023 Taxi',
            'travel_rental_car': 'DEFRA 2023 Car (average)',
        }

        parsed_fields = None if errors else {
            'activity_date': activity_date,
            'period_start': None,
            'period_end': None,
            'scope': 3,
            'category': category,
            'facility_name': '',
            'cost_centre': cost_centre,
            'supplier_name': vendor,
            'description': description,
            'reference_id': reference_id,
            'quantity_original': transaction_amount,
            'unit_original': currency,
            'quantity_normalized': quantity_normalized,
            'unit_normalized': unit_normalized,
            'emission_factor': emission_factor,
            'emission_factor_source': ef_label_map.get(category, 'DEFRA 2023'),
            'co2e_kg': co2e_kg,
        }

        yield {
            'row_index': row_index,
            'raw_data': raw_data,
            'parsed_fields': parsed_fields,
            'errors': errors,
            'warnings': warnings,
            'status': status,
        }
