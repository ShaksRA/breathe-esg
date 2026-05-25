from django.urls import path
from . import views

urlpatterns = [
    # Auth
    path('auth/login/', views.login_view, name='login'),
    path('auth/logout/', views.logout_view, name='logout'),
    path('auth/me/', views.me_view, name='me'),

    # Uploads
    path('batches/', views.UploadBatchView.as_view(), name='batch-list'),
    path('batches/<uuid:batch_id>/', views.batch_detail, name='batch-detail'),
    path('upload/', views.upload_file, name='upload'),

    # Emission records — bulk-review MUST come before the uuid param route
    path('records/', views.emission_records, name='records'),
    path('records/bulk-review/', views.bulk_review, name='bulk-review'),
    path('records/<uuid:record_id>/', views.emission_record_detail, name='record-detail'),
    path('records/<uuid:record_id>/review/', views.review_action, name='review-action'),

    # Dashboard
    path('dashboard/', views.dashboard_stats, name='dashboard'),

    # Audit
    path('audit-log/', views.audit_log, name='audit-log'),

    # Facility lookup
    path('facilities/', views.facility_lookup, name='facilities'),
]
