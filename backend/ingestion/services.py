"""
Ingestion service — orchestrates parsing and writing to the database.

Called by the upload API view. Handles:
  1. Dispatch to correct parser by source_type
  2. Writing SourceRows (raw, immutable)
  3. Writing EmissionRecords (normalized, reviewable)
  4. Anomaly flagging (statistical outlier detection)
  5. Updating UploadBatch status and counts
"""

import statistics
from decimal import Decimal
from django.utils import timezone
from django.contrib.auth.models import User

from .models import UploadBatch, SourceRow, EmissionRecord, AuditLog, FacilityLookup
from .parsers.sap_parser import parse_sap_csv
from .parsers.utility_parser import parse_utility_csv
from .parsers.travel_parser import parse_travel_json


PARSER_MAP = {
    'sap_fuel': parse_sap_csv,
    'utility_elec': parse_utility_csv,
    'travel_concur': parse_travel_json,
}


def run_ingestion(batch: UploadBatch):
    """
    Main entry point. Reads batch.raw_file, parses it, creates SourceRows
    and EmissionRecords, then flags anomalies.
    """
    batch.status = 'processing'
    batch.save(update_fields=['status'])

    parser = PARSER_MAP.get(batch.source_type)
    if not parser:
        batch.status = 'failed'
        batch.processing_notes = f"No parser for source_type '{batch.source_type}'"
        batch.save(update_fields=['status', 'processing_notes'])
        return

    try:
        file_content = batch.raw_file.read()
    except Exception as e:
        batch.status = 'failed'
        batch.processing_notes = f"Could not read uploaded file: {e}"
        batch.save(update_fields=['status', 'processing_notes'])
        return

    total = ok = failed = 0
    notes = []

    # Facility lookup for SAP plant codes
    facility_lookup = {}
    if batch.source_type == 'sap_fuel':
        facility_lookup = {
            f.sap_plant_code: f
            for f in FacilityLookup.objects.filter(
                organisation=batch.organisation, is_active=True
            )
        }

    emission_records_created = []

    for parsed in parser(file_content):
        status = parsed['status']
        if status == 'skipped':
            continue

        total += 1

        source_row = SourceRow.objects.create(
            batch=batch,
            row_index=parsed['row_index'],
            raw_data=parsed['raw_data'],
            parse_status=status,
            parse_errors=parsed['errors'],
        )

        if status == 'failed':
            failed += 1
            if parsed['errors']:
                notes.append(f"Row {parsed['row_index']}: {'; '.join(parsed['errors'][:2])}")
            continue

        ok += 1
        pf = parsed['parsed_fields']
        warnings = parsed.get('warnings', [])

        # Enrich facility name from lookup table for SAP
        if batch.source_type == 'sap_fuel' and pf.get('facility_name'):
            plant_code = pf['facility_name']
            if plant_code in facility_lookup:
                facility = facility_lookup[plant_code]
                pf['facility_name'] = facility.name
                if not pf.get('country_code'):
                    pf['country_code'] = facility.country_code

        is_flagged = bool(warnings)
        flag_reasons = warnings if warnings else []

        record = EmissionRecord.objects.create(
            organisation=batch.organisation,
            source_row=source_row,
            batch=batch,
            activity_date=pf['activity_date'],
            period_start=pf.get('period_start'),
            period_end=pf.get('period_end'),
            scope=pf['scope'],
            category=pf['category'],
            facility_name=pf.get('facility_name', ''),
            cost_centre=pf.get('cost_centre', ''),
            country_code=pf.get('country_code', ''),
            supplier_name=pf.get('supplier_name', ''),
            description=pf.get('description', ''),
            reference_id=pf.get('reference_id', ''),
            quantity_original=pf.get('quantity_original') or Decimal('0'),
            unit_original=pf.get('unit_original', ''),
            quantity_normalized=pf.get('quantity_normalized') or Decimal('0'),
            unit_normalized=pf.get('unit_normalized', ''),
            emission_factor=pf.get('emission_factor') or Decimal('0'),
            emission_factor_source=pf.get('emission_factor_source', 'DEFRA 2023'),
            co2e_kg=pf.get('co2e_kg') or Decimal('0'),
            is_flagged=is_flagged,
            flag_reasons=flag_reasons,
            review_status='flagged' if is_flagged else 'pending',
        )

        # Write creation audit log
        AuditLog.objects.create(
            record=record,
            action='created',
            actor=batch.uploaded_by,
            note=f"Ingested from batch {batch.id}",
            snapshot={
                'co2e_kg': str(record.co2e_kg),
                'scope': record.scope,
                'category': record.category,
            }
        )

        emission_records_created.append(record)

    # Statistical anomaly detection (requires ≥5 records to be meaningful)
    _flag_statistical_outliers(emission_records_created)

    batch.row_count_total = total
    batch.row_count_ok = ok
    batch.row_count_failed = failed
    batch.processed_at = timezone.now()
    batch.status = 'complete' if failed == 0 else ('failed' if ok == 0 else 'partial')
    batch.processing_notes = '\n'.join(notes[:20])  # cap notes length
    batch.save()


def _flag_statistical_outliers(records: list):
    """
    Simple z-score outlier detection on co2e_kg within a batch.
    Flags records where |z| > 3 (>3 standard deviations from mean).
    Only meaningful with ≥5 records.
    """
    if len(records) < 5:
        return

    # Group by category for per-category outlier detection
    by_category = {}
    for r in records:
        by_category.setdefault(r.category, []).append(r)

    for cat_records in by_category.values():
        if len(cat_records) < 5:
            continue
        values = [float(r.co2e_kg) for r in cat_records]
        mean = statistics.mean(values)
        try:
            stdev = statistics.stdev(values)
        except statistics.StatisticsError:
            continue
        if stdev == 0:
            continue

        for record in cat_records:
            z = abs((float(record.co2e_kg) - mean) / stdev)
            if z > 3:
                reason = (f"Value ({record.co2e_kg:.1f} kgCO2e) is {z:.1f}σ from the "
                          f"batch mean ({mean:.1f} kgCO2e) for category '{record.category}'.")
                if reason not in record.flag_reasons:
                    record.flag_reasons = list(record.flag_reasons) + [reason]
                    record.is_flagged = True
                    record.review_status = 'flagged'
                    record.save(update_fields=['flag_reasons', 'is_flagged', 'review_status'])
