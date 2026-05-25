"""
API views for the Breathe ESG ingestion and review system.
"""

from decimal import Decimal
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncMonth
from django.contrib.auth import authenticate, login
from django.utils import timezone
from rest_framework import viewsets, generics, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from .models import (
    Organisation, UploadBatch, SourceRow, EmissionRecord, AuditLog, FacilityLookup
)
from .serializers import (
    OrganisationSerializer, UploadBatchSerializer, SourceRowSerializer,
    EmissionRecordListSerializer, EmissionRecordDetailSerializer,
    ReviewActionSerializer, BulkReviewSerializer, AuditLogSerializer,
    FacilityLookupSerializer, UserSerializer
)
from .services import run_ingestion


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    username = request.data.get('username')
    password = request.data.get('password')
    user = authenticate(request, username=username, password=password)
    if user:
        token, _ = Token.objects.get_or_create(user=user)
        membership = user.memberships.select_related('organisation').first()
        org = membership.organisation if membership else None
        return Response({
            'token': token.key,
            'user': UserSerializer(user).data,
            'organisation': OrganisationSerializer(org).data if org else None,
        })
    return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_view(request):
    request.user.auth_token.delete()
    return Response({'message': 'Logged out'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def me_view(request):
    membership = request.user.memberships.select_related('organisation').first()
    org = membership.organisation if membership else None
    return Response({
        'user': UserSerializer(request.user).data,
        'organisation': OrganisationSerializer(org).data if org else None,
        'role': membership.role if membership else None,
    })


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

class UploadBatchView(generics.ListAPIView):
    serializer_class = UploadBatchSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        membership = self.request.user.memberships.select_related('organisation').first()
        if not membership:
            return UploadBatch.objects.none()
        return UploadBatch.objects.filter(
            organisation=membership.organisation
        ).order_by('-uploaded_at')


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_file(request):
    """
    Upload a file for ingestion.
    Multipart form with: file, source_type
    """
    parser_classes = [MultiPartParser, FormParser]

    membership = request.user.memberships.select_related('organisation').first()
    if not membership:
        return Response({'error': 'User has no organisation'}, status=400)

    file_obj = request.FILES.get('file')
    source_type = request.data.get('source_type')

    if not file_obj:
        return Response({'error': 'No file provided'}, status=400)
    if source_type not in ('sap_fuel', 'utility_elec', 'travel_concur'):
        return Response({'error': 'Invalid source_type'}, status=400)

    batch = UploadBatch.objects.create(
        organisation=membership.organisation,
        uploaded_by=request.user,
        source_type=source_type,
        original_filename=file_obj.name,
        raw_file=file_obj,
    )

    # Run ingestion synchronously for prototype
    # In production: dispatch to Celery task
    try:
        run_ingestion(batch)
    except Exception as e:
        batch.status = 'failed'
        batch.processing_notes = str(e)
        batch.save(update_fields=['status', 'processing_notes'])

    batch.refresh_from_db()
    return Response(UploadBatchSerializer(batch).data, status=201)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def batch_detail(request, batch_id):
    membership = request.user.memberships.select_related('organisation').first()
    if not membership:
        return Response({'error': 'No organisation'}, status=400)
    try:
        batch = UploadBatch.objects.get(id=batch_id, organisation=membership.organisation)
    except UploadBatch.DoesNotExist:
        return Response({'error': 'Not found'}, status=404)
    return Response(UploadBatchSerializer(batch).data)


# ---------------------------------------------------------------------------
# Emission records
# ---------------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def emission_records(request):
    """
    List emission records with filtering.
    Query params: scope, category, review_status, batch_id, is_flagged, year
    """
    membership = request.user.memberships.select_related('organisation').first()
    if not membership:
        return Response({'error': 'No organisation'}, status=400)

    qs = EmissionRecord.objects.filter(
        organisation=membership.organisation
    ).select_related('batch', 'reviewed_by')

    # Filters
    scope = request.query_params.get('scope')
    if scope:
        qs = qs.filter(scope=scope)

    category = request.query_params.get('category')
    if category:
        qs = qs.filter(category=category)

    review_status = request.query_params.get('review_status')
    if review_status:
        qs = qs.filter(review_status=review_status)

    batch_id = request.query_params.get('batch_id')
    if batch_id:
        qs = qs.filter(batch_id=batch_id)

    is_flagged = request.query_params.get('is_flagged')
    if is_flagged == 'true':
        qs = qs.filter(is_flagged=True)

    year = request.query_params.get('year')
    if year:
        qs = qs.filter(activity_date__year=year)

    search = request.query_params.get('search')
    if search:
        qs = qs.filter(
            Q(description__icontains=search) |
            Q(facility_name__icontains=search) |
            Q(supplier_name__icontains=search) |
            Q(reference_id__icontains=search)
        )

    # Pagination
    from rest_framework.pagination import PageNumberPagination
    paginator = PageNumberPagination()
    paginator.page_size = int(request.query_params.get('page_size', 50))
    page = paginator.paginate_queryset(qs, request)
    serializer = EmissionRecordListSerializer(page, many=True)
    return paginator.get_paginated_response(serializer.data)


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def emission_record_detail(request, record_id):
    membership = request.user.memberships.select_related('organisation').first()
    if not membership:
        return Response({'error': 'No organisation'}, status=400)

    try:
        record = EmissionRecord.objects.select_related(
            'source_row', 'batch', 'reviewed_by'
        ).get(id=record_id, organisation=membership.organisation)
    except EmissionRecord.DoesNotExist:
        return Response({'error': 'Not found'}, status=404)

    if request.method == 'GET':
        return Response(EmissionRecordDetailSerializer(record).data)

    # PATCH: analyst edits co2e or metadata
    if record.review_status == 'locked':
        return Response({'error': 'Record is locked for audit'}, status=400)

    original_co2e = record.co2e_kg
    allowed_fields = ['co2e_kg', 'description', 'facility_name', 'cost_centre',
                      'activity_date', 'review_note']
    changed = False
    for field in allowed_fields:
        if field in request.data:
            setattr(record, field, request.data[field])
            changed = True

    if changed:
        if 'co2e_kg' in request.data:
            record.is_edited = True
            record.original_co2e_kg = original_co2e
        record.save()
        AuditLog.objects.create(
            record=record,
            action='edited',
            actor=request.user,
            note=request.data.get('review_note', ''),
            snapshot={'co2e_kg': str(record.co2e_kg), 'original_co2e_kg': str(original_co2e)}
        )

    return Response(EmissionRecordDetailSerializer(record).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def review_action(request, record_id):
    """Apply approve/reject/flag to a single record."""
    membership = request.user.memberships.select_related('organisation').first()
    if not membership:
        return Response({'error': 'No organisation'}, status=400)

    try:
        record = EmissionRecord.objects.get(
            id=record_id, organisation=membership.organisation
        )
    except EmissionRecord.DoesNotExist:
        return Response({'error': 'Not found'}, status=404)

    ser = ReviewActionSerializer(data=request.data)
    ser.is_valid(raise_exception=True)

    action = ser.validated_data['action']
    note = ser.validated_data.get('note', '')

    try:
        if action == 'approve':
            record.approve(request.user, note)
        elif action == 'reject':
            record.reject(request.user, note)
        elif action == 'flag':
            record.flag(request.user, note)
    except ValueError as e:
        return Response({'error': str(e)}, status=400)

    return Response(EmissionRecordDetailSerializer(record).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def bulk_review(request):
    """Apply approve/reject/flag to multiple records at once."""
    membership = request.user.memberships.select_related('organisation').first()
    if not membership:
        return Response({'error': 'No organisation'}, status=400)

    ser = BulkReviewSerializer(data=request.data)
    ser.is_valid(raise_exception=True)

    record_ids = ser.validated_data['record_ids']
    action = ser.validated_data['action']
    note = ser.validated_data.get('note', '')

    records = EmissionRecord.objects.filter(
        id__in=record_ids,
        organisation=membership.organisation,
    ).exclude(review_status='locked')

    updated = 0
    for record in records:
        try:
            if action == 'approve':
                record.approve(request.user, note)
            elif action == 'reject':
                record.reject(request.user, note)
            elif action == 'flag':
                record.flag(request.user, note)
            updated += 1
        except ValueError:
            pass

    return Response({'updated': updated, 'requested': len(record_ids)})


# ---------------------------------------------------------------------------
# Dashboard stats
# ---------------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_stats(request):
    membership = request.user.memberships.select_related('organisation').first()
    if not membership:
        return Response({'error': 'No organisation'}, status=400)

    org = membership.organisation
    qs = EmissionRecord.objects.filter(organisation=org)

    year = request.query_params.get('year')
    if year:
        qs = qs.filter(activity_date__year=year)

    agg = qs.aggregate(
        total=Count('id'),
        pending=Count('id', filter=Q(review_status='pending')),
        flagged=Count('id', filter=Q(review_status='flagged')),
        approved=Count('id', filter=Q(review_status='approved')),
        rejected=Count('id', filter=Q(review_status='rejected')),
        total_co2e=Sum('co2e_kg'),
        approved_co2e=Sum('co2e_kg', filter=Q(review_status='approved')),
    )

    # Scope breakdown
    scope_data = qs.values('scope').annotate(
        co2e=Sum('co2e_kg'), count=Count('id')
    ).order_by('scope')

    scope_breakdown = {}
    for s in scope_data:
        key = f"scope_{s['scope']}"
        scope_breakdown[key] = {
            'co2e_kg': float(s['co2e'] or 0),
            'count': s['count'],
        }

    # Category breakdown (top 10)
    cat_data = qs.values('category').annotate(
        co2e=Sum('co2e_kg'), count=Count('id')
    ).order_by('-co2e')[:10]

    # Monthly trend (last 12 months)
    monthly = (
        qs.annotate(month=TruncMonth('activity_date'))
        .values('month')
        .annotate(co2e=Sum('co2e_kg'), count=Count('id'))
        .order_by('month')
    )

    recent_batches = UploadBatch.objects.filter(organisation=org).order_by('-uploaded_at')[:5]

    return Response({
        'total_records': agg['total'] or 0,
        'pending_count': agg['pending'] or 0,
        'flagged_count': agg['flagged'] or 0,
        'approved_count': agg['approved'] or 0,
        'rejected_count': agg['rejected'] or 0,
        'total_co2e_kg': float(agg['total_co2e'] or 0),
        'approved_co2e_kg': float(agg['approved_co2e'] or 0),
        'scope_breakdown': scope_breakdown,
        'category_breakdown': [
            {'category': c['category'], 'co2e_kg': float(c['co2e'] or 0), 'count': c['count']}
            for c in cat_data
        ],
        'monthly_trend': [
            {
                'month': m['month'].strftime('%Y-%m') if m['month'] else None,
                'co2e_kg': float(m['co2e'] or 0),
                'count': m['count'],
            }
            for m in monthly
        ],
        'recent_batches': UploadBatchSerializer(recent_batches, many=True).data,
    })


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def audit_log(request):
    """Full audit log for the organisation."""
    membership = request.user.memberships.select_related('organisation').first()
    if not membership:
        return Response({'error': 'No organisation'}, status=400)

    logs = AuditLog.objects.filter(
        record__organisation=membership.organisation
    ).select_related('actor', 'record').order_by('-timestamp')[:200]

    return Response(AuditLogSerializer(logs, many=True).data)


# ---------------------------------------------------------------------------
# Facility lookup
# ---------------------------------------------------------------------------

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def facility_lookup(request):
    membership = request.user.memberships.select_related('organisation').first()
    if not membership:
        return Response({'error': 'No organisation'}, status=400)

    if request.method == 'GET':
        facilities = FacilityLookup.objects.filter(organisation=membership.organisation)
        return Response(FacilityLookupSerializer(facilities, many=True).data)

    ser = FacilityLookupSerializer(data={**request.data, 'organisation': str(membership.organisation.id)})
    if ser.is_valid():
        ser.save()
        return Response(ser.data, status=201)
    return Response(ser.errors, status=400)
