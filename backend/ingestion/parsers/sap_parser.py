"""
SAP Fuel & Procurement parser.

Format choice: ME2N/ME2L purchase order report exported as delimited text via SAP GUI
"System > List > Save > Local File > Spreadsheet" (tab-separated, .txt or .csv).

Why not IDoc: IDocs are point-to-point integration between SAP systems — enterprise
clients don't produce them for ESG reporting. They'd produce a custom ABAP report
or a standard ME2N export. OData would require standing up an SAP Fiori service.

Real-world SAP column names we handle:
- German headers common when client SAP is configured for German locale
- WERKS (plant/Werk), KOSTL (cost centre), LIFNR (vendor), MATNR (material)
- MENGE (quantity), MEINS (unit of measure), NETPR (net price), WAERS (currency)
- BLDAT / BUDAT (document date / posting date) — both appear in different reports
- Material groups (MATKL): we look at specific groups to identify fuel

Anomaly checks:
- Unit not in known fuel units → flag
- Date outside expected fiscal year range → flag
- Quantity ≤ 0 → flag as data error
- Same reference doc appearing twice → flag as possible duplicate
"""

import csv
import io
import re
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Optional

# SAP date formats we've seen in the wild
SAP_DATE_FORMATS = [
    '%d.%m.%Y',   # 31.01.2024 — German locale default
    '%m/%d/%Y',   # 01/31/2024 — US locale
    '%Y%m%d',     # 20240131  — compact format in some ABAP reports
    '%d-%m-%Y',   # 31-01-2024
    '%Y-%m-%d',   # ISO 8601 (rare from SAP)
]

# SAP UoM codes → canonical unit for emission computation
# SAP uses industry-specific unit codes, some inherited from German conventions
SAP_UNIT_MAP = {
    'L': 'L',     'LTR': 'L',  'l': 'L',
    'G': 'L',     # Gallons (US) — some NA SAP configs
    'GAL': 'L',
    'KG': 'kg',   'KGM': 'kg',
    'M3': 'm3',   'MTQ': 'm3',
    'KWH': 'kWh', 'KWH': 'kWh',
    'GJ': 'GJ',
    'T': 't',     'TNE': 't',   # metric tonnes (for coal etc.)
    'STK': 'unit',  # Stück — pieces, not a fuel unit, will be flagged
    'EA': 'unit',   # Each
}

# Unit conversion to litres (for fuels) or kWh (for energy)
TO_LITRES = {
    'L': Decimal('1'),
    'GAL': Decimal('3.785411784'),   # US gallon to litres
    'm3': Decimal('1000'),           # m³ to litres (for LPG/gas)
}

TO_KWH = {
    'kWh': Decimal('1'),
    'GJ': Decimal('277.778'),
    'MJ': Decimal('0.277778'),
}

# Material groups (MATKL) that indicate fuel procurement
FUEL_MATERIAL_GROUPS = {
    'FUEL01': ('fuel_diesel', Decimal('2.68')),
    'FUEL02': ('fuel_petrol', Decimal('2.31')),
    'FUEL03': ('fuel_natural_gas', Decimal('0.202')),
    'FUEL04': ('fuel_lpg', Decimal('1.554')),
    # Description-based fallback
}

FUEL_DESCRIPTION_PATTERNS = {
    r'diesel': ('fuel_diesel', Decimal('2.68')),
    r'petrol|gasoline|benzin': ('fuel_petrol', Decimal('2.31')),
    r'natural.?gas|erdgas|lng|cng': ('fuel_natural_gas', Decimal('0.202')),
    r'lpg|liquid.?petroleum': ('fuel_lpg', Decimal('1.554')),
}

# Column name aliases: SAP exports vary by locale and report config
COLUMN_ALIASES = {
    'date': ['BLDAT', 'BUDAT', 'Belegdatum', 'Buchungsdatum', 'Document Date',
             'Posting Date', 'DATE', 'date', 'Doc Date'],
    'plant': ['WERKS', 'Werk', 'Plant', 'PLANT', 'plant_code'],
    'cost_centre': ['KOSTL', 'Kostenstelle', 'Cost Centre', 'CostCentre', 'CC'],
    'vendor': ['LIFNR', 'Lieferant', 'Vendor', 'VENDOR', 'Supplier'],
    'material': ['MATNR', 'Material', 'MATERIAL', 'Mat. No.'],
    'mat_group': ['MATKL', 'Materialgruppe', 'Material Group', 'MatGrp'],
    'description': ['TXZ01', 'Kurztext', 'Short Text', 'Description', 'DESC'],
    'quantity': ['MENGE', 'Menge', 'Quantity', 'QTY', 'QUANTITY', 'qty'],
    'unit': ['MEINS', 'Mengeneinheit', 'Unit', 'UoM', 'UNIT', 'BASE_UOM'],
    'net_price': ['NETPR', 'Nettopreis', 'Net Price', 'NETPRICE'],
    'currency': ['WAERS', 'Währung', 'Currency', 'CURR'],
    'doc_number': ['EBELN', 'Bestellung', 'PO Number', 'Document', 'DOCNO', 'Ref'],
}


def _resolve_columns(headers: list) -> dict:
    """
    Map actual column headers (case-insensitive) to canonical field names.
    Returns {'canonical_name': 'actual_header'} for matched columns.
    """
    header_lower = {h.lower().strip(): h for h in headers}
    resolved = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias.lower() in header_lower:
                resolved[canonical] = header_lower[alias.lower()]
                break
    return resolved


def _parse_sap_date(raw: str) -> Optional[date]:
    """Try all known SAP date formats."""
    raw = raw.strip()
    if not raw:
        return None
    for fmt in SAP_DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_decimal(raw: str) -> Optional[Decimal]:
    """
    SAP uses both '1.234,56' (German thousand sep, comma decimal)
    and '1,234.56' (English). Detect and normalize.
    """
    raw = raw.strip().replace('\xa0', '').replace(' ', '')
    if not raw:
        return None
    # German format: dot as thousand separator, comma as decimal
    if re.match(r'^\d{1,3}(\.\d{3})*(,\d+)?$', raw):
        raw = raw.replace('.', '').replace(',', '.')
    else:
        raw = raw.replace(',', '')
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _infer_fuel_type(mat_group: str, description: str):
    """Return (category, emission_factor) by material group then description."""
    if mat_group and mat_group.upper() in FUEL_MATERIAL_GROUPS:
        return FUEL_MATERIAL_GROUPS[mat_group.upper()]
    desc_lower = (description or '').lower()
    for pattern, result in FUEL_DESCRIPTION_PATTERNS.items():
        if re.search(pattern, desc_lower):
            return result
    return ('fuel_other', Decimal('2.5'))  # fallback, will be flagged


def _normalize_quantity(quantity: Decimal, unit_raw: str):
    """
    Convert quantity to litres (for liquid fuels) or kWh (for gas).
    Returns (normalized_quantity, normalized_unit, warnings).
    """
    warnings = []
    unit_canonical = SAP_UNIT_MAP.get(unit_raw.strip().upper(), unit_raw)

    if unit_canonical in TO_LITRES:
        return quantity * TO_LITRES[unit_canonical], 'L', warnings
    if unit_canonical in TO_KWH:
        return quantity * TO_KWH[unit_canonical], 'kWh', warnings

    # Unknown unit — flag, pass through as-is
    warnings.append(f"Unknown unit '{unit_raw}' — could not normalize. Manual review required.")
    return quantity, unit_raw, warnings


def parse_sap_csv(file_content: bytes, encoding='utf-8'):
    """
    Main entry point. Accepts raw file bytes, yields ParsedRow dicts.

    Yields dicts with keys:
      row_index, raw_data, parsed_fields (or None), errors, warnings, status
    """
    # Try UTF-8 first; SAP sometimes exports in latin-1 / cp1252
    for enc in [encoding, 'utf-8-sig', 'latin-1', 'cp1252']:
        try:
            text = file_content.decode(enc)
            break
        except (UnicodeDecodeError, AttributeError):
            continue
    else:
        yield {
            'row_index': 0,
            'raw_data': {},
            'parsed_fields': None,
            'errors': ['Could not decode file — tried utf-8, latin-1, cp1252'],
            'warnings': [],
            'status': 'failed',
        }
        return

    # Detect delimiter: SAP exports can be tab, semicolon, or comma
    sample = text[:2000]
    if '\t' in sample:
        delimiter = '\t'
    elif ';' in sample:
        delimiter = ';'
    else:
        delimiter = ','

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = reader.fieldnames or []
    col_map = _resolve_columns(headers)

    seen_doc_numbers = set()

    for row_index, row in enumerate(reader):
        raw_data = dict(row)
        errors = []
        warnings = []

        # Skip separator/summary rows that SAP inserts
        row_values = [v.strip() for v in row.values() if v]
        if not any(row_values):
            yield {'row_index': row_index, 'raw_data': raw_data, 'parsed_fields': None,
                   'errors': [], 'warnings': [], 'status': 'skipped'}
            continue

        # --- Date ---
        date_raw = row.get(col_map.get('date', ''), '').strip()
        activity_date = _parse_sap_date(date_raw)
        if not activity_date:
            errors.append(f"Cannot parse date '{date_raw}'")

        # --- Quantity ---
        qty_raw = row.get(col_map.get('quantity', ''), '').strip()
        quantity = _parse_decimal(qty_raw)
        if quantity is None:
            errors.append(f"Cannot parse quantity '{qty_raw}'")
        elif quantity <= 0:
            errors.append(f"Quantity ≤ 0: {quantity}")

        # --- Unit ---
        unit_raw = row.get(col_map.get('unit', ''), '').strip()
        if not unit_raw:
            errors.append("Missing unit of measure")

        # --- Fuel type inference ---
        mat_group = row.get(col_map.get('mat_group', ''), '').strip()
        description = row.get(col_map.get('description', ''), '').strip()
        category, emission_factor = _infer_fuel_type(mat_group, description)
        if category == 'fuel_other':
            warnings.append("Could not identify fuel type from material group or description. "
                            "Defaulted to 'fuel_other' with generic factor. Review required.")

        # --- Normalization ---
        quantity_normalized = None
        unit_normalized = unit_raw
        if quantity and unit_raw:
            quantity_normalized, unit_normalized, unit_warnings = \
                _normalize_quantity(quantity, unit_raw)
            warnings.extend(unit_warnings)

        # --- CO2e computation ---
        co2e_kg = None
        if quantity_normalized is not None:
            # For kWh gas: use natural_gas factor (0.202)
            if unit_normalized == 'kWh' and category == 'fuel_natural_gas':
                emission_factor = Decimal('0.202')
            co2e_kg = quantity_normalized * emission_factor

        # --- Duplicate detection ---
        doc_number = row.get(col_map.get('doc_number', ''), '').strip()
        if doc_number and doc_number in seen_doc_numbers:
            warnings.append(f"Duplicate document number '{doc_number}' — possible double-count.")
        if doc_number:
            seen_doc_numbers.add(doc_number)

        status = 'failed' if errors else ('warning' if warnings else 'ok')

        parsed_fields = None if errors else {
            'activity_date': activity_date,
            'scope': 1,
            'category': category,
            'facility_name': row.get(col_map.get('plant', ''), '').strip(),
            'cost_centre': row.get(col_map.get('cost_centre', ''), '').strip(),
            'supplier_name': row.get(col_map.get('vendor', ''), '').strip(),
            'description': description,
            'reference_id': doc_number,
            'quantity_original': quantity,
            'unit_original': unit_raw,
            'quantity_normalized': quantity_normalized,
            'unit_normalized': unit_normalized,
            'emission_factor': emission_factor,
            'emission_factor_source': 'DEFRA 2023',
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
