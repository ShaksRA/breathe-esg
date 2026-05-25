"""
Core data models for Breathe ESG ingestion pipeline.

Design principles:
1. Multi-tenancy via Organisation FK on every data-bearing model
2. Normalized EmissionRecord is the canonical output — source rows map 1:N into it
3. Source-of-truth is preserved: raw bytes/rows never discarded, always traceable
4. Audit trail: every state change to an EmissionRecord is appended to AuditLog
5. Units normalized at ingestion time to kgCO2e; originals kept for re-computation
"""

from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
import uuid


# ---------------------------------------------------------------------------
# Multi-tenancy: Organisation + membership
# ---------------------------------------------------------------------------

class Organisation(models.Model):
    """
    Tenant boundary. All data models FK back to this.
    In a real deployment this is the enterprise client — e.g. "Acme Corp".
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Reporting year for which audit locks apply
    # Lock prevents further edits to records in a closed period
    locked_year = models.IntegerField(null=True, blank=True,
        help_text="Fiscal year locked for audit. Records in this year cannot be edited.")

    def __str__(self):
        return self.name


class OrganisationMembership(models.Model):
    """User ↔ Organisation relationship with role."""
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('analyst', 'Analyst'),
        ('auditor', 'Auditor (read-only)'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='memberships')
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE,
                                     related_name='memberships')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='analyst')
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'organisation')


# ---------------------------------------------------------------------------
# Ingestion: UploadBatch — one per file/pull, before normalization
# ---------------------------------------------------------------------------

class UploadBatch(models.Model):
    """
    Represents a single ingestion event: one SAP export, one utility CSV, etc.
    Keeps the raw file. All SourceRows and eventually EmissionRecords trace back here.
    """
    SOURCE_TYPES = [
        ('sap_fuel', 'SAP – Fuel & Procurement'),
        ('utility_elec', 'Utility – Electricity'),
        ('travel_concur', 'Travel – Concur/Navan Export'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('partial', 'Partial (some rows failed)'),
        ('complete', 'Complete'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE,
                                     related_name='upload_batches')
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    source_type = models.CharField(max_length=30, choices=SOURCE_TYPES)
    original_filename = models.CharField(max_length=500)
    raw_file = models.FileField(upload_to='raw_uploads/%Y/%m/', null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    row_count_total = models.IntegerField(default=0)
    row_count_ok = models.IntegerField(default=0)
    row_count_failed = models.IntegerField(default=0)
    processing_notes = models.TextField(blank=True,
        help_text="Human-readable summary of ingestion issues, e.g. unit mismatches")

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.organisation.slug} / {self.source_type} / {self.uploaded_at:%Y-%m-%d}"


class SourceRow(models.Model):
    """
    One row from the raw source file, stored verbatim as JSON.

    Why store this?  We need to re-derive emission factors when they change,
    debug parser failures, and give auditors a direct line to the original data.
    This is the append-only immutable layer.
    """
    PARSE_STATUS = [
        ('ok', 'Parsed OK'),
        ('warning', 'Parsed with warnings'),
        ('failed', 'Parse failed'),
        ('skipped', 'Skipped (header/blank)'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(UploadBatch, on_delete=models.CASCADE, related_name='source_rows')
    row_index = models.IntegerField(help_text="0-based row number in the source file")
    raw_data = models.JSONField(help_text="Original row as key:value dict, keys from source")
    parse_status = models.CharField(max_length=10, choices=PARSE_STATUS, default='ok')
    parse_errors = models.JSONField(default=list, blank=True,
        help_text="List of error strings encountered during parsing")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['batch', 'row_index']
        unique_together = ('batch', 'row_index')


# ---------------------------------------------------------------------------
# Normalized emission record — the canonical analytical output
# ---------------------------------------------------------------------------

class EmissionRecord(models.Model):
    """
    The normalized, unit-converted, CO2e-computed record.

    This is what analysts review. It references back to the SourceRow
    so we always know where it came from and can reconstruct if needed.

    Scope classification:
      1 = Direct (fuel combustion, fleet, owned facilities)
      2 = Purchased electricity/heat/steam
      3 = Travel, supply chain, waste, etc.
    """
    SCOPE_CHOICES = [
        (1, 'Scope 1 – Direct'),
        (2, 'Scope 2 – Purchased Energy'),
        (3, 'Scope 3 – Value Chain'),
    ]
    CATEGORY_CHOICES = [
        # Scope 1
        ('fuel_diesel', 'Diesel combustion'),
        ('fuel_petrol', 'Petrol combustion'),
        ('fuel_natural_gas', 'Natural gas combustion'),
        ('fuel_lpg', 'LPG combustion'),
        ('fuel_other', 'Other fuel combustion'),
        # Scope 2
        ('electricity', 'Purchased electricity'),
        # Scope 3
        ('travel_flight', 'Business travel – flights'),
        ('travel_rail', 'Business travel – rail'),
        ('travel_hotel', 'Business travel – hotel stay'),
        ('travel_taxi', 'Business travel – taxi/ride-hail'),
        ('travel_rental_car', 'Business travel – rental car'),
        ('procurement_goods', 'Purchased goods (procurement)'),
    ]
    REVIEW_STATUS = [
        ('pending', 'Pending review'),
        ('flagged', 'Flagged – needs attention'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('locked', 'Locked for audit'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE,
                                     related_name='emission_records')
    source_row = models.OneToOneField(SourceRow, on_delete=models.SET_NULL,
                                      null=True, blank=True, related_name='emission_record',
                                      help_text="The raw source row this was derived from")
    batch = models.ForeignKey(UploadBatch, on_delete=models.SET_NULL, null=True,
                              related_name='emission_records')

    # Temporal
    activity_date = models.DateField(
        help_text="Date the activity occurred (not the upload date)")
    period_start = models.DateField(null=True, blank=True,
        help_text="For billing-period data like utility: start of period")
    period_end = models.DateField(null=True, blank=True)

    # Classification
    scope = models.IntegerField(choices=SCOPE_CHOICES)
    category = models.CharField(max_length=40, choices=CATEGORY_CHOICES)

    # Location / business unit context
    facility_name = models.CharField(max_length=255, blank=True,
        help_text="e.g. 'Plant DE01' from SAP Werk, or facility address for utility")
    cost_centre = models.CharField(max_length=100, blank=True,
        help_text="SAP Kostenstelle / cost centre code")
    country_code = models.CharField(max_length=2, blank=True,
        help_text="ISO 3166-1 alpha-2")

    # Quantity in original units (preserved for auditability and re-computation)
    quantity_original = models.DecimalField(max_digits=18, decimal_places=4)
    unit_original = models.CharField(max_length=30,
        help_text="Original unit as received from source: L, kWh, km, nights, etc.")

    # Quantity normalized to SI base for CO2e computation
    # For fuels: litres. For energy: kWh. For travel: km or nights.
    quantity_normalized = models.DecimalField(max_digits=18, decimal_places=4)
    unit_normalized = models.CharField(max_length=30)

    # CO2e output
    emission_factor = models.DecimalField(max_digits=12, decimal_places=6,
        help_text="kgCO2e per unit_normalized, from DEFRA 2023 / EPA")
    emission_factor_source = models.CharField(max_length=100, default='DEFRA 2023',
        help_text="Attribution for the emission factor used")
    co2e_kg = models.DecimalField(max_digits=18, decimal_places=4,
        help_text="Total kgCO2e = quantity_normalized × emission_factor")

    # Source metadata
    supplier_name = models.CharField(max_length=255, blank=True)
    description = models.CharField(max_length=500, blank=True,
        help_text="Human-readable description of activity, from source")
    reference_id = models.CharField(max_length=200, blank=True,
        help_text="Original document/transaction reference from source system")

    # Review workflow
    review_status = models.CharField(max_length=10, choices=REVIEW_STATUS, default='pending')
    review_note = models.TextField(blank=True,
        help_text="Analyst comment when approving/rejecting/flagging")
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='reviewed_records')
    reviewed_at = models.DateTimeField(null=True, blank=True)

    # Anomaly detection flags (set by ingestion pipeline)
    is_flagged = models.BooleanField(default=False)
    flag_reasons = models.JSONField(default=list, blank=True,
        help_text="List of anomaly reasons: e.g. ['value >3σ above mean', 'missing unit']")

    # Was this record edited after ingestion? Track the delta.
    is_edited = models.BooleanField(default=False)
    original_co2e_kg = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True,
        help_text="Original computed value before analyst edit")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-activity_date']
        indexes = [
            models.Index(fields=['organisation', 'scope', 'activity_date']),
            models.Index(fields=['organisation', 'review_status']),
            models.Index(fields=['batch']),
        ]

    def __str__(self):
        return f"{self.category} | {self.activity_date} | {self.co2e_kg} kgCO2e"

    def approve(self, user, note=''):
        """Approve this record and write audit log."""
        if self.review_status == 'locked':
            raise ValueError("Record is locked for audit — cannot modify.")
        self.review_status = 'approved'
        self.review_note = note
        self.reviewed_by = user
        self.reviewed_at = timezone.now()
        self.save()
        AuditLog.objects.create(
            record=self,
            action='approved',
            actor=user,
            note=note,
        )

    def reject(self, user, note=''):
        if self.review_status == 'locked':
            raise ValueError("Record is locked for audit — cannot modify.")
        self.review_status = 'rejected'
        self.review_note = note
        self.reviewed_by = user
        self.reviewed_at = timezone.now()
        self.save()
        AuditLog.objects.create(
            record=self,
            action='rejected',
            actor=user,
            note=note,
        )

    def flag(self, user, note=''):
        self.review_status = 'flagged'
        self.review_note = note
        self.reviewed_by = user
        self.reviewed_at = timezone.now()
        self.save()
        AuditLog.objects.create(
            record=self,
            action='flagged',
            actor=user,
            note=note,
        )


# ---------------------------------------------------------------------------
# Audit log — append-only, never deleted
# ---------------------------------------------------------------------------

class AuditLog(models.Model):
    """
    Append-only log of every state change to an EmissionRecord.
    Auditors read this; no one can delete or update rows.
    In production this table lives in a separate read-only schema.
    """
    ACTION_CHOICES = [
        ('created', 'Created by ingestion'),
        ('flagged', 'Flagged by analyst'),
        ('approved', 'Approved by analyst'),
        ('rejected', 'Rejected by analyst'),
        ('edited', 'Value edited by analyst'),
        ('locked', 'Locked for audit'),
        ('unlocked', 'Unlocked (amendment)'),
    ]

    id = models.BigAutoField(primary_key=True)
    record = models.ForeignKey(EmissionRecord, on_delete=models.CASCADE,
                               related_name='audit_logs')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True)
    # Snapshot of key fields at time of action (for full auditability)
    snapshot = models.JSONField(default=dict, blank=True,
        help_text="JSON snapshot of EmissionRecord fields at time of this action")

    class Meta:
        ordering = ['timestamp']
        # No update/delete permissions should be granted on this table in production

    def __str__(self):
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {self.action} by {self.actor}"


# ---------------------------------------------------------------------------
# Plant / facility lookup (for SAP Werk codes)
# ---------------------------------------------------------------------------

class FacilityLookup(models.Model):
    """
    Maps SAP plant codes (Werk) to human-readable names and countries.
    SAP exports only the code; without this table, 'DE01' means nothing.
    """
    organisation = models.ForeignKey(Organisation, on_delete=models.CASCADE)
    sap_plant_code = models.CharField(max_length=20)
    name = models.CharField(max_length=255)
    country_code = models.CharField(max_length=2)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('organisation', 'sap_plant_code')

    def __str__(self):
        return f"{self.sap_plant_code} — {self.name}"
