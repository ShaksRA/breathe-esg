"""
Utility Electricity parser.

Format choice: Portal CSV export.

Why portal CSV over PDF or API:
  - PDF: requires OCR; bill layouts vary wildly by utility. Fragile.
  - Utility API (Green Button / ESPI standard): not universally available.
    Major US utilities (PG&E, Con Ed) offer it; UK/EU coverage is patchy.
    Enterprise clients usually don't have API credentials set up.
  - Portal CSV: most large utilities (EDF, E.ON, SSE, PG&E, Duke, BESCOM)
    offer a "Download usage data" CSV from their business portal. This is
    the format a facilities team actually uses.

Real-world columns (composite of EDF Business, Octopus for Business, PG&E):
  account_number, meter_id, site_name/address, billing_period_start,
  billing_period_end, read_type (Actual/Estimated/Customer), consumption_kwh,
  demand_kw (peak), unit_rate (p/kWh or $/kWh), standing_charge, total_cost, currency

Key complications handled:
  - Billing periods don't align with calendar months. A bill might cover
    32 days (Nov 1 – Dec 2). We record period_start/period_end, not a
    single month. The analyst proration is a separate concern.
  - Units: always kWh for electricity in scope 2. Some older exports use MWh.
  - "Estimated" meter reads: flagged for review (not rejected — common and valid).
  - Demand (kW) is separate from consumption (kWh); we store consumption only
    for emissions. Demand is stored in raw_data.
  - Market-based vs location-based accounting: we only compute location-based
    here (grid emission factor). Renewable energy certificates / PPAs would
    require a separate field. Flagged in notes.
"""

import csv
import io
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Optional

DATE_FORMATS = [
    '%Y-%m-%d',
    '%d/%m/%Y',
    '%m/%d/%Y',
    '%d-%m-%Y',
    '%d %b %Y',   # "01 Jan 2024"
    '%b %d, %Y',  # "Jan 01, 2024"
]

UNIT_TO_KWH = {
    'kwh': Decimal('1'),
    'kw.h': Decimal('1'),
    'mwh': Decimal('1000'),
    'gj': Decimal('277.778'),
}

# UK grid average emission factor, kgCO2e per kWh — DEFRA 2023
# Location-based (not market-based)
GRID_FACTOR_DEFAULT = Decimal('0.207')

COLUMN_ALIASES = {
    'account_number': ['account_number', 'Account Number', 'AccountNo', 'Account No',
                       'account_no', 'ACCOUNT'],
    'meter_id': ['meter_id', 'Meter ID', 'MeterID', 'meter_serial', 'MPAN', 'MPRN',
                 'Meter Number', 'meter_number'],
    'site_name': ['site_name', 'Site', 'Site Name', 'Address', 'Facility', 'Location',
                  'site_address', 'premise'],
    'period_start': ['period_start', 'Bill From', 'BillFrom', 'Start Date', 'Read Date From',
                     'billing_start', 'From', 'ServiceFrom', 'service_from'],
    'period_end': ['period_end', 'Bill To', 'BillTo', 'End Date', 'Read Date To',
                   'billing_end', 'To', 'ServiceTo', 'service_to', 'Statement Date'],
    'read_type': ['read_type', 'ReadType', 'Read Type', 'Reading Type', 'Basis',
                  'EstimatedActual', 'read_basis'],
    'consumption': ['consumption_kwh', 'Usage', 'kWh', 'KWH', 'consumption',
                    'Energy Used', 'energy_used', 'USE', 'units_used', 'net_usage_kwh',
                    'Total kWh', 'total_kwh'],
    'unit': ['unit', 'Unit', 'UoM', 'consumption_unit'],
    'total_cost': ['total_cost', 'Total Cost', 'Amount', 'Bill Amount', 'total_charge',
                   'TotalAmount'],
    'currency': ['currency', 'Currency', 'CURR'],
    'tariff_code': ['tariff_code', 'Tariff', 'TariffCode', 'Rate Code'],
    'country_code': ['country_code', 'Country', 'CountryCode'],
}


def _resolve_columns(headers):
    header_lower = {h.lower().strip(): h for h in headers}
    resolved = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias.lower() in header_lower:
                resolved[canonical] = header_lower[alias.lower()]
                break
    return resolved


def _parse_date(raw: str) -> Optional[date]:
    raw = raw.strip()
    if not raw:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_decimal(raw: str) -> Optional[Decimal]:
    if raw is None:
        return None
    raw = raw.strip().replace(',', '').replace('\xa0', '')
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def parse_utility_csv(file_content: bytes):
    """
    Yields ParsedRow dicts (same schema as sap_parser for consistency).
    """
    for enc in ['utf-8-sig', 'utf-8', 'latin-1']:
        try:
            text = file_content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        yield {
            'row_index': 0, 'raw_data': {}, 'parsed_fields': None,
            'errors': ['Could not decode file'], 'warnings': [], 'status': 'failed',
        }
        return

    # Skip header comment rows common in utility portal exports
    lines = text.splitlines()
    start_line = 0
    for i, line in enumerate(lines):
        # Look for a row that looks like actual headers
        if any(kw in line.lower() for kw in ['kwh', 'meter', 'account', 'period', 'usage', 'consumption']):
            start_line = i
            break

    text = '\n'.join(lines[start_line:])

    # Detect delimiter
    sample = text[:1000]
    delimiter = '\t' if sample.count('\t') > sample.count(',') else ','

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = reader.fieldnames or []
    col_map = _resolve_columns(headers)

    seen_meter_periods = set()

    for row_index, row in enumerate(reader):
        raw_data = dict(row)
        errors = []
        warnings = []

        # Skip blank rows
        if not any(v.strip() for v in row.values() if v):
            yield {'row_index': row_index, 'raw_data': raw_data, 'parsed_fields': None,
                   'errors': [], 'warnings': [], 'status': 'skipped'}
            continue

        # --- Period ---
        period_start_raw = row.get(col_map.get('period_start', ''), '').strip()
        period_end_raw = row.get(col_map.get('period_end', ''), '').strip()
        period_start = _parse_date(period_start_raw)
        period_end = _parse_date(period_end_raw)

        if not period_start:
            errors.append(f"Cannot parse period start '{period_start_raw}'")
        if not period_end:
            errors.append(f"Cannot parse period end '{period_end_raw}'")

        if period_start and period_end:
            days = (period_end - period_start).days
            if days <= 0:
                errors.append(f"Period end ({period_end}) is not after start ({period_start})")
            elif days > 100:
                warnings.append(f"Billing period is {days} days — unusually long. "
                                 "Verify this isn't two bills combined.")
            elif days < 20:
                warnings.append(f"Billing period is only {days} days — shorter than typical month. "
                                 "Could be a partial or amended bill.")

        # --- Consumption ---
        consumption_raw = row.get(col_map.get('consumption', ''), '').strip()
        consumption_kwh = _parse_decimal(consumption_raw)
        if consumption_kwh is None:
            errors.append(f"Cannot parse consumption '{consumption_raw}'")
        elif consumption_kwh < 0:
            errors.append(f"Negative consumption: {consumption_kwh}")
        elif consumption_kwh == 0:
            warnings.append("Zero consumption — verify this isn't a missed read.")

        # --- Unit normalization ---
        unit_raw = row.get(col_map.get('unit', ''), 'kWh').strip()
        unit_lower = unit_raw.lower()
        consumption_kwh_normalized = None
        if consumption_kwh is not None:
            factor = UNIT_TO_KWH.get(unit_lower, None)
            if factor is None:
                warnings.append(f"Unknown unit '{unit_raw}' — assuming kWh")
                consumption_kwh_normalized = consumption_kwh
                unit_lower = 'kwh'
            else:
                consumption_kwh_normalized = consumption_kwh * factor

        # --- Read type ---
        read_type = row.get(col_map.get('read_type', ''), '').strip()
        if read_type.lower() in ('e', 'estimated', 'est', 'estimate'):
            warnings.append("Estimated meter read (not actual). "
                            "Value may be corrected in next bill.")

        # --- Duplicate check ---
        meter_id = row.get(col_map.get('meter_id', ''), '').strip()
        dupe_key = (meter_id, period_start_raw, period_end_raw)
        if dupe_key in seen_meter_periods:
            warnings.append(f"Duplicate meter/period combination for meter '{meter_id}' "
                            f"({period_start_raw}–{period_end_raw}). Possible double-upload.")
        seen_meter_periods.add(dupe_key)

        # --- CO2e ---
        co2e_kg = None
        if consumption_kwh_normalized is not None:
            co2e_kg = consumption_kwh_normalized * GRID_FACTOR_DEFAULT

        status = 'failed' if errors else ('warning' if warnings else 'ok')
        # Use midpoint of period as activity_date
        activity_date = period_start
        if period_start and period_end:
            midpoint_days = (period_end - period_start).days // 2
            from datetime import timedelta
            activity_date = period_start + timedelta(days=midpoint_days)

        site_name = row.get(col_map.get('site_name', ''), '').strip()
        account_number = row.get(col_map.get('account_number', ''), '').strip()

        parsed_fields = None if errors else {
            'activity_date': activity_date,
            'period_start': period_start,
            'period_end': period_end,
            'scope': 2,
            'category': 'electricity',
            'facility_name': site_name or account_number,
            'cost_centre': '',
            'supplier_name': '',  # utility provider name not always in export
            'description': f"Electricity {period_start}–{period_end}" if period_start else '',
            'reference_id': meter_id or account_number,
            'quantity_original': consumption_kwh,
            'unit_original': unit_raw or 'kWh',
            'quantity_normalized': consumption_kwh_normalized,
            'unit_normalized': 'kWh',
            'emission_factor': GRID_FACTOR_DEFAULT,
            'emission_factor_source': 'DEFRA 2023 grid average (location-based)',
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
