"""
Initial migration for Breathe ESG ingestion models.
Generated manually (no network access for makemigrations in build).
"""

import django.db.models.deletion
import django.utils.timezone
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Organisation',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=255)),
                ('slug', models.SlugField(unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('locked_year', models.IntegerField(blank=True, help_text='Fiscal year locked for audit. Records in this year cannot be edited.', null=True)),
            ],
        ),
        migrations.CreateModel(
            name='OrganisationMembership',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(choices=[('admin', 'Admin'), ('analyst', 'Analyst'), ('auditor', 'Auditor (read-only)')], default='analyst', max_length=20)),
                ('joined_at', models.DateTimeField(auto_now_add=True)),
                ('organisation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='memberships', to='ingestion.organisation')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='memberships', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'unique_together': {('user', 'organisation')},
            },
        ),
        migrations.CreateModel(
            name='FacilityLookup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sap_plant_code', models.CharField(max_length=20)),
                ('name', models.CharField(max_length=255)),
                ('country_code', models.CharField(max_length=2)),
                ('address', models.TextField(blank=True)),
                ('is_active', models.BooleanField(default=True)),
                ('organisation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='ingestion.organisation')),
            ],
            options={
                'unique_together': {('organisation', 'sap_plant_code')},
            },
        ),
        migrations.CreateModel(
            name='UploadBatch',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('source_type', models.CharField(choices=[('sap_fuel', 'SAP – Fuel & Procurement'), ('utility_elec', 'Utility – Electricity'), ('travel_concur', 'Travel – Concur/Navan Export')], max_length=30)),
                ('original_filename', models.CharField(max_length=500)),
                ('raw_file', models.FileField(blank=True, null=True, upload_to='raw_uploads/%Y/%m/')),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('processed_at', models.DateTimeField(blank=True, null=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('processing', 'Processing'), ('partial', 'Partial (some rows failed)'), ('complete', 'Complete'), ('failed', 'Failed')], default='pending', max_length=20)),
                ('row_count_total', models.IntegerField(default=0)),
                ('row_count_ok', models.IntegerField(default=0)),
                ('row_count_failed', models.IntegerField(default=0)),
                ('processing_notes', models.TextField(blank=True, help_text='Human-readable summary of ingestion issues, e.g. unit mismatches')),
                ('organisation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='upload_batches', to='ingestion.organisation')),
                ('uploaded_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-uploaded_at'],
            },
        ),
        migrations.CreateModel(
            name='SourceRow',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('row_index', models.IntegerField(help_text='0-based row number in the source file')),
                ('raw_data', models.JSONField(help_text='Original row as key:value dict, keys from source')),
                ('parse_status', models.CharField(choices=[('ok', 'Parsed OK'), ('warning', 'Parsed with warnings'), ('failed', 'Parse failed'), ('skipped', 'Skipped (header/blank)')], default='ok', max_length=10)),
                ('parse_errors', models.JSONField(blank=True, default=list, help_text='List of error strings encountered during parsing')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('batch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='source_rows', to='ingestion.uploadbatch')),
            ],
            options={
                'ordering': ['batch', 'row_index'],
                'unique_together': {('batch', 'row_index')},
            },
        ),
        migrations.CreateModel(
            name='EmissionRecord',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('activity_date', models.DateField(help_text='Date the activity occurred (not the upload date)')),
                ('period_start', models.DateField(blank=True, help_text='For billing-period data like utility: start of period', null=True)),
                ('period_end', models.DateField(blank=True, null=True)),
                ('scope', models.IntegerField(choices=[(1, 'Scope 1 – Direct'), (2, 'Scope 2 – Purchased Energy'), (3, 'Scope 3 – Value Chain')])),
                ('category', models.CharField(choices=[('fuel_diesel', 'Diesel combustion'), ('fuel_petrol', 'Petrol combustion'), ('fuel_natural_gas', 'Natural gas combustion'), ('fuel_lpg', 'LPG combustion'), ('fuel_other', 'Other fuel combustion'), ('electricity', 'Purchased electricity'), ('travel_flight', 'Business travel – flights'), ('travel_rail', 'Business travel – rail'), ('travel_hotel', 'Business travel – hotel stay'), ('travel_taxi', 'Business travel – taxi/ride-hail'), ('travel_rental_car', 'Business travel – rental car'), ('procurement_goods', 'Purchased goods (procurement)')], max_length=40)),
                ('facility_name', models.CharField(blank=True, help_text="e.g. 'Plant DE01' from SAP Werk, or facility address for utility", max_length=255)),
                ('cost_centre', models.CharField(blank=True, help_text='SAP Kostenstelle / cost centre code', max_length=100)),
                ('country_code', models.CharField(blank=True, help_text='ISO 3166-1 alpha-2', max_length=2)),
                ('quantity_original', models.DecimalField(decimal_places=4, max_digits=18)),
                ('unit_original', models.CharField(help_text='Original unit as received from source: L, kWh, km, nights, etc.', max_length=30)),
                ('quantity_normalized', models.DecimalField(decimal_places=4, max_digits=18)),
                ('unit_normalized', models.CharField(max_length=30)),
                ('emission_factor', models.DecimalField(decimal_places=6, help_text='kgCO2e per unit_normalized, from DEFRA 2023 / EPA', max_digits=12)),
                ('emission_factor_source', models.CharField(default='DEFRA 2023', help_text='Attribution for the emission factor used', max_length=100)),
                ('co2e_kg', models.DecimalField(decimal_places=4, help_text='Total kgCO2e = quantity_normalized × emission_factor', max_digits=18)),
                ('supplier_name', models.CharField(blank=True, max_length=255)),
                ('description', models.CharField(blank=True, help_text='Human-readable description of activity, from source', max_length=500)),
                ('reference_id', models.CharField(blank=True, help_text='Original document/transaction reference from source system', max_length=200)),
                ('review_status', models.CharField(choices=[('pending', 'Pending review'), ('flagged', 'Flagged – needs attention'), ('approved', 'Approved'), ('rejected', 'Rejected'), ('locked', 'Locked for audit')], default='pending', max_length=10)),
                ('review_note', models.TextField(blank=True, help_text='Analyst comment when approving/rejecting/flagging')),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('is_flagged', models.BooleanField(default=False)),
                ('flag_reasons', models.JSONField(blank=True, default=list, help_text="List of anomaly reasons: e.g. ['value >3σ above mean', 'missing unit']")),
                ('is_edited', models.BooleanField(default=False)),
                ('original_co2e_kg', models.DecimalField(blank=True, decimal_places=4, help_text='Original computed value before analyst edit', max_digits=18, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('organisation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='emission_records', to='ingestion.organisation')),
                ('source_row', models.OneToOneField(blank=True, help_text='The raw source row this was derived from', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='emission_record', to='ingestion.sourcerow')),
                ('batch', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='emission_records', to='ingestion.uploadbatch')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_records', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-activity_date'],
            },
        ),
        migrations.AddIndex(
            model_name='emissionrecord',
            index=models.Index(fields=['organisation', 'scope', 'activity_date'], name='ingestion_e_organis_3d1234_idx'),
        ),
        migrations.AddIndex(
            model_name='emissionrecord',
            index=models.Index(fields=['organisation', 'review_status'], name='ingestion_e_organis_4e5678_idx'),
        ),
        migrations.AddIndex(
            model_name='emissionrecord',
            index=models.Index(fields=['batch'], name='ingestion_e_batch_i_7f89ab_idx'),
        ),
        migrations.CreateModel(
            name='AuditLog',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('action', models.CharField(choices=[('created', 'Created by ingestion'), ('flagged', 'Flagged by analyst'), ('approved', 'Approved by analyst'), ('rejected', 'Rejected by analyst'), ('edited', 'Value edited by analyst'), ('locked', 'Locked for audit'), ('unlocked', 'Unlocked (amendment)')], max_length=20)),
                ('timestamp', models.DateTimeField(auto_now_add=True)),
                ('note', models.TextField(blank=True)),
                ('snapshot', models.JSONField(blank=True, default=dict, help_text='JSON snapshot of EmissionRecord fields at time of this action')),
                ('record', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='audit_logs', to='ingestion.emissionrecord')),
                ('actor', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['timestamp'],
            },
        ),
    ]
