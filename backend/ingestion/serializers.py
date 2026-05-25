from rest_framework import serializers
from django.contrib.auth.models import User
from .models import (
    Organisation, OrganisationMembership, UploadBatch, SourceRow,
    EmissionRecord, AuditLog, FacilityLookup
)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']


class OrganisationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organisation
        fields = ['id', 'name', 'slug', 'locked_year', 'created_at']


class UploadBatchSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.SerializerMethodField()
    source_type_display = serializers.CharField(source='get_source_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = UploadBatch
        fields = [
            'id', 'organisation', 'uploaded_by', 'uploaded_by_name',
            'source_type', 'source_type_display', 'original_filename',
            'uploaded_at', 'processed_at', 'status', 'status_display',
            'row_count_total', 'row_count_ok', 'row_count_failed',
            'processing_notes',
        ]
        read_only_fields = [
            'id', 'uploaded_at', 'processed_at', 'status',
            'row_count_total', 'row_count_ok', 'row_count_failed',
        ]

    def get_uploaded_by_name(self, obj):
        if obj.uploaded_by:
            return obj.uploaded_by.get_full_name() or obj.uploaded_by.username
        return None


class SourceRowSerializer(serializers.ModelSerializer):
    class Meta:
        model = SourceRow
        fields = ['id', 'batch', 'row_index', 'raw_data', 'parse_status', 'parse_errors', 'created_at']


class EmissionRecordListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views — excludes heavy nested objects."""
    scope_display = serializers.CharField(source='get_scope_display', read_only=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    review_status_display = serializers.CharField(source='get_review_status_display', read_only=True)
    reviewed_by_name = serializers.SerializerMethodField()
    batch_filename = serializers.SerializerMethodField()

    class Meta:
        model = EmissionRecord
        fields = [
            'id', 'organisation', 'batch', 'batch_filename',
            'activity_date', 'period_start', 'period_end',
            'scope', 'scope_display', 'category', 'category_display',
            'facility_name', 'cost_centre', 'country_code',
            'quantity_original', 'unit_original',
            'quantity_normalized', 'unit_normalized',
            'emission_factor', 'emission_factor_source',
            'co2e_kg',
            'supplier_name', 'description', 'reference_id',
            'review_status', 'review_status_display',
            'review_note', 'reviewed_by', 'reviewed_by_name', 'reviewed_at',
            'is_flagged', 'flag_reasons', 'is_edited', 'original_co2e_kg',
            'created_at', 'updated_at',
        ]

    def get_reviewed_by_name(self, obj):
        if obj.reviewed_by:
            return obj.reviewed_by.get_full_name() or obj.reviewed_by.username
        return None

    def get_batch_filename(self, obj):
        if obj.batch:
            return obj.batch.original_filename
        return None


class EmissionRecordDetailSerializer(EmissionRecordListSerializer):
    """Full serializer including source row for detail view."""
    source_row_data = serializers.SerializerMethodField()
    audit_trail = serializers.SerializerMethodField()

    class Meta(EmissionRecordListSerializer.Meta):
        fields = EmissionRecordListSerializer.Meta.fields + ['source_row_data', 'audit_trail']

    def get_source_row_data(self, obj):
        if obj.source_row:
            return {
                'row_index': obj.source_row.row_index,
                'raw_data': obj.source_row.raw_data,
                'parse_status': obj.source_row.parse_status,
                'parse_errors': obj.source_row.parse_errors,
            }
        return None

    def get_audit_trail(self, obj):
        logs = obj.audit_logs.select_related('actor').order_by('timestamp')
        return [
            {
                'action': log.action,
                'actor': log.actor.username if log.actor else 'system',
                'timestamp': log.timestamp,
                'note': log.note,
                'snapshot': log.snapshot,
            }
            for log in logs
        ]


class ReviewActionSerializer(serializers.Serializer):
    """Payload for approve/reject/flag actions."""
    action = serializers.ChoiceField(choices=['approve', 'reject', 'flag'])
    note = serializers.CharField(required=False, allow_blank=True, default='')


class BulkReviewSerializer(serializers.Serializer):
    record_ids = serializers.ListField(child=serializers.UUIDField())
    action = serializers.ChoiceField(choices=['approve', 'reject', 'flag'])
    note = serializers.CharField(required=False, allow_blank=True, default='')


class AuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()
    action_display = serializers.CharField(source='get_action_display', read_only=True)

    class Meta:
        model = AuditLog
        fields = ['id', 'record', 'action', 'action_display', 'actor', 'actor_name',
                  'timestamp', 'note', 'snapshot']

    def get_actor_name(self, obj):
        return obj.actor.username if obj.actor else 'system'


class DashboardStatsSerializer(serializers.Serializer):
    """Summary statistics for the analyst dashboard."""
    total_records = serializers.IntegerField()
    pending_count = serializers.IntegerField()
    flagged_count = serializers.IntegerField()
    approved_count = serializers.IntegerField()
    rejected_count = serializers.IntegerField()
    total_co2e_kg = serializers.DecimalField(max_digits=18, decimal_places=2)
    approved_co2e_kg = serializers.DecimalField(max_digits=18, decimal_places=2)
    scope_breakdown = serializers.DictField()
    category_breakdown = serializers.ListField()
    recent_batches = UploadBatchSerializer(many=True)
    monthly_trend = serializers.ListField()


class FacilityLookupSerializer(serializers.ModelSerializer):
    class Meta:
        model = FacilityLookup
        fields = ['id', 'organisation', 'sap_plant_code', 'name', 'country_code',
                  'address', 'is_active']
