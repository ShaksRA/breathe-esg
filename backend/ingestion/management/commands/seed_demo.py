"""
Management command: seed_demo

Creates a demo organisation, analyst user, and loads sample data for all three sources.
Run: python manage.py seed_demo
"""

import json
import csv
import io
from datetime import date, timedelta
import random

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.db import transaction

from ingestion.models import Organisation, OrganisationMembership, FacilityLookup, UploadBatch
from ingestion.services import run_ingestion


SAP_CSV_DATA = """Belegdatum\tWERKS\tKOSTL\tLIFNR\tMATNR\tTXZ01\tMATKL\tMENGE\tMEINS\tNETPR\tWAERS\tEBELN
15.01.2024\tDE01\t1000\tVENDOR_BP\tFUEL-001\tDiesel EN590\tFUEL01\t12500\tL\t1.42\tEUR\t4500001234
22.01.2024\tDE01\t1000\tVENDOR_BP\tFUEL-001\tDiesel EN590\tFUEL01\t9800\tL\t1.44\tEUR\t4500001235
10.02.2024\tDE02\t1100\tVENDOR_SHELL\tFUEL-002\tPetrol Unleaded\tFUEL02\t3200\tL\t1.61\tEUR\t4500001240
14.02.2024\tDE01\t1000\tVENDOR_BP\tFUEL-001\tDiesel EN590\tFUEL01\t11200\tL\t1.43\tEUR\t4500001241
01.03.2024\tUK01\t2000\tVENDOR_TOTAL\tGAS-001\tNatural Gas\tFUEL03\t48500\tKWH\t0.08\tGBP\t4500001260
15.03.2024\tDE01\t1000\tVENDOR_BP\tFUEL-001\tDiesel EN590\tFUEL01\t13100\tL\t1.45\tEUR\t4500001265
20.03.2024\tDE03\t1200\tVENDOR_ESSO\tFUEL-001\tDiesel EN590\tFUEL01\t8900\tL\t1.46\tEUR\t4500001270
05.04.2024\tDE02\t1100\tVENDOR_SHELL\tFUEL-004\tLPG Automotiv\tFUEL04\t2100\tL\t0.89\tEUR\t4500001280
12.04.2024\tDE01\t1000\tVENDOR_BP\tFUEL-001\tDiesel EN590\tFUEL01\t14200\tL\t1.48\tEUR\t4500001285
18.04.2024\tUK01\t2000\tVENDOR_TOTAL\tGAS-001\tNatural Gas\tFUEL03\t52000\tKWH\t0.079\tGBP\t4500001290
25.04.2024\tDE01\t1000\tVENDOR_BP\tFUEL-001\tDiesel EN590\tFUEL01\t99999\tL\t1.48\tEUR\t4500001291
02.05.2024\tDE01\t1000\tVENDOR_BP\tFUEL-001\tDiesel EN590\tFUEL01\t11800\tL\t1.47\tEUR\t4500001295
10.05.2024\tDE03\t1200\tVENDOR_ESSO\tFUEL-001\tDiesel EN590\tFUEL01\t7600\tL\t1.47\tEUR\t4500001300
20.05.2024\tDE02\t1100\tVENDOR_SHELL\tFUEL-002\tPetrol Unleaded\tFUEL02\t2900\tL\t1.63\tEUR\t4500001305
01.06.2024\tDE01\t1000\tVENDOR_BP\tFUEL-001\tDiesel EN590\tFUEL01\t12900\tL\t1.46\tEUR\t4500001310
15.06.2024\tUK01\t2000\tVENDOR_TOTAL\tGAS-001\tNatural Gas\tFUEL03\t49800\tKWH\t0.078\tGBP\t4500001315
"""

UTILITY_CSV_DATA = """account_number,meter_id,site_name,period_start,period_end,read_type,consumption_kwh,demand_kw,unit_rate_gbp,total_cost_gbp,currency
ACC-001,MTR-DE01-A,DE01 Plant - Dusseldorf North Hall,2024-01-01,2024-01-31,Actual,184200,320,0.28,51576,GBP
ACC-001,MTR-DE01-B,DE01 Plant - Dusseldorf South Hall,2024-01-01,2024-02-01,Actual,96400,185,0.28,26992,GBP
ACC-002,MTR-DE02-A,DE02 Plant - Munich Facility,2024-01-03,2024-02-02,Estimated,142800,260,0.31,44268,EUR
ACC-003,MTR-UK01-A,UK01 - London Office,2024-01-01,2024-01-31,Actual,38400,82,0.32,12288,GBP
ACC-001,MTR-DE01-A,DE01 Plant - Dusseldorf North Hall,2024-02-01,2024-02-29,Actual,178600,315,0.29,51794,GBP
ACC-001,MTR-DE01-B,DE01 Plant - Dusseldorf South Hall,2024-02-02,2024-03-04,Actual,91200,178,0.29,26448,GBP
ACC-002,MTR-DE02-A,DE02 Plant - Munich Facility,2024-02-03,2024-03-05,Actual,138400,252,0.31,42904,EUR
ACC-003,MTR-UK01-A,UK01 - London Office,2024-02-01,2024-02-29,Actual,35800,78,0.32,11456,GBP
ACC-001,MTR-DE01-A,DE01 Plant - Dusseldorf North Hall,2024-03-01,2024-03-31,Actual,192400,328,0.28,53872,GBP
ACC-002,MTR-DE02-A,DE02 Plant - Munich Facility,2024-03-05,2024-04-04,Estimated,145200,264,0.32,46464,EUR
ACC-003,MTR-UK01-A,UK01 - London Office,2024-03-01,2024-03-31,Actual,36900,80,0.33,12177,GBP
ACC-004,MTR-DE03-A,DE03 Plant - Hamburg Warehouse,2024-01-01,2024-01-31,Actual,62400,115,0.30,18720,EUR
ACC-004,MTR-DE03-A,DE03 Plant - Hamburg Warehouse,2024-02-01,2024-02-29,Actual,58800,108,0.30,17640,EUR
ACC-004,MTR-DE03-A,DE03 Plant - Hamburg Warehouse,2024-03-01,2024-03-31,Actual,63600,118,0.30,19080,EUR
"""

TRAVEL_JSON_DATA = [
    {
        "ID": "RPRT-001-001", "ReportID": "RPRT-001",
        "ExpenseTypeName": "Airfare",
        "TransactionDate": "2024-01-10",
        "TransactionAmount": 342.50, "TransactionCurrencyCode": "GBP",
        "VendorDescription": "British Airways",
        "origin_iata": "LHR", "destination_iata": "FRA",
        "cabin_class": "economy",
        "Custom1": "CC-1000", "Comment": "Sales trip Frankfurt",
        "EmployeeID": "EMP-101"
    },
    {
        "ID": "RPRT-001-002", "ReportID": "RPRT-001",
        "ExpenseTypeName": "Hotel",
        "TransactionDate": "2024-01-10",
        "TransactionAmount": 189.00, "TransactionCurrencyCode": "EUR",
        "VendorDescription": "Marriott Frankfurt",
        "nights": 2,
        "Custom1": "CC-1000", "Comment": "Frankfurt hotel",
        "EmployeeID": "EMP-101"
    },
    {
        "ID": "RPRT-001-003", "ReportID": "RPRT-001",
        "ExpenseTypeName": "Taxi",
        "TransactionDate": "2024-01-12",
        "TransactionAmount": 38.50, "TransactionCurrencyCode": "EUR",
        "VendorDescription": "Uber",
        "distance_km": 22,
        "Custom1": "CC-1000", "Comment": "Airport transfer",
        "EmployeeID": "EMP-101"
    },
    {
        "ID": "RPRT-002-001", "ReportID": "RPRT-002",
        "ExpenseTypeName": "Airfare",
        "TransactionDate": "2024-01-22",
        "TransactionAmount": 1850.00, "TransactionCurrencyCode": "GBP",
        "VendorDescription": "Singapore Airlines",
        "origin_iata": "LHR", "destination_iata": "SIN",
        "cabin_class": "business",
        "Custom1": "CC-2000", "Comment": "Asia Pacific Q1 review",
        "EmployeeID": "EMP-205"
    },
    {
        "ID": "RPRT-002-002", "ReportID": "RPRT-002",
        "ExpenseTypeName": "Hotel",
        "TransactionDate": "2024-01-22",
        "TransactionAmount": 450.00, "TransactionCurrencyCode": "SGD",
        "VendorDescription": "Raffles Hotel Singapore",
        "nights": 3,
        "Custom1": "CC-2000", "Comment": "Singapore hotel",
        "EmployeeID": "EMP-205"
    },
    {
        "ID": "RPRT-003-001", "ReportID": "RPRT-003",
        "ExpenseTypeName": "Train",
        "TransactionDate": "2024-02-05",
        "TransactionAmount": 68.00, "TransactionCurrencyCode": "GBP",
        "VendorDescription": "Eurostar",
        "distance_km": 494,
        "Custom1": "CC-1000", "Comment": "LHR to Paris St Pancras",
        "EmployeeID": "EMP-102"
    },
    {
        "ID": "RPRT-004-001", "ReportID": "RPRT-004",
        "ExpenseTypeName": "Airfare",
        "TransactionDate": "2024-02-14",
        "TransactionAmount": 520.00, "TransactionCurrencyCode": "USD",
        "VendorDescription": "United Airlines",
        "origin_iata": "LHR", "destination_iata": "JFK",
        "cabin_class": "economy",
        "is_return": True,
        "Custom1": "CC-1000", "Comment": "NYC client visit return",
        "EmployeeID": "EMP-101"
    },
    {
        "ID": "RPRT-004-002", "ReportID": "RPRT-004",
        "ExpenseTypeName": "Hotel",
        "TransactionDate": "2024-02-14",
        "TransactionAmount": 380.00, "TransactionCurrencyCode": "USD",
        "VendorDescription": "Marriott Times Square",
        "nights": 3,
        "Custom1": "CC-1000",
        "EmployeeID": "EMP-101"
    },
    {
        "ID": "RPRT-005-001", "ReportID": "RPRT-005",
        "ExpenseTypeName": "Car Rental",
        "TransactionDate": "2024-03-01",
        "TransactionAmount": 145.00, "TransactionCurrencyCode": "EUR",
        "VendorDescription": "Hertz",
        "distance_km": 380,
        "Custom1": "CC-1200", "Comment": "Munich client visits",
        "EmployeeID": "EMP-310"
    },
    {
        "ID": "RPRT-006-001", "ReportID": "RPRT-006",
        "ExpenseTypeName": "Airfare",
        "TransactionDate": "2024-03-10",
        "TransactionAmount": 890.00, "TransactionCurrencyCode": "GBP",
        "VendorDescription": "Emirates",
        "origin_iata": "LHR", "destination_iata": "DXB",
        "cabin_class": "economy",
        "Custom1": "CC-2000", "Comment": "Dubai partner meeting",
        "EmployeeID": "EMP-205"
    },
    {
        "ID": "RPRT-006-002", "ReportID": "RPRT-006",
        "ExpenseTypeName": "Hotel",
        "TransactionDate": "2024-03-10",
        "TransactionAmount": 280.00, "TransactionCurrencyCode": "AED",
        "VendorDescription": "DIFC hotel",
        "nights": 2,
        "Custom1": "CC-2000",
        "EmployeeID": "EMP-205"
    },
    {
        "ID": "RPRT-007-001", "ReportID": "RPRT-007",
        "ExpenseTypeName": "Airfare",
        "TransactionDate": "2024-03-20",
        "TransactionAmount": 245.00, "TransactionCurrencyCode": "EUR",
        "VendorDescription": "Lufthansa",
        "origin_iata": "FRA", "destination_iata": "CDG",
        "cabin_class": "economy",
        "Custom1": "CC-1100",
        "EmployeeID": "EMP-412"
    },
    {
        "ID": "RPRT-008-001", "ReportID": "RPRT-008",
        "ExpenseTypeName": "Taxi",
        "TransactionDate": "2024-04-02",
        "TransactionAmount": 52.00, "TransactionCurrencyCode": "GBP",
        "VendorDescription": "Addison Lee",
        "distance_km": 35,
        "Custom1": "CC-2000",
        "EmployeeID": "EMP-205"
    },
    # An entry without IATA codes to trigger the warning flag
    {
        "ID": "RPRT-009-001", "ReportID": "RPRT-009",
        "ExpenseTypeName": "Airfare",
        "TransactionDate": "2024-04-15",
        "TransactionAmount": 410.00, "TransactionCurrencyCode": "GBP",
        "VendorDescription": "easyJet",
        "Custom1": "CC-1000",
        "Comment": "Conference travel",
        "EmployeeID": "EMP-102"
    },
]


class Command(BaseCommand):
    help = 'Seed the database with demo organisation, users, and sample data.'

    def handle(self, *args, **options):
        with transaction.atomic():
            # Create organisation
            org, _ = Organisation.objects.get_or_create(
                slug='acme-corp',
                defaults={'name': 'Acme Manufacturing Corp'}
            )
            self.stdout.write(f'Organisation: {org.name}')

            # Create facility lookups
            facilities = [
                ('DE01', 'Düsseldorf North Plant', 'DE'),
                ('DE02', 'Munich Facility', 'DE'),
                ('DE03', 'Hamburg Warehouse', 'DE'),
                ('UK01', 'London Office', 'GB'),
            ]
            for code, name, country in facilities:
                FacilityLookup.objects.get_or_create(
                    organisation=org, sap_plant_code=code,
                    defaults={'name': name, 'country_code': country}
                )

            # Create users
            analyst, created = User.objects.get_or_create(
                username='analyst',
                defaults={
                    'email': 'analyst@acme.com',
                    'first_name': 'Alex',
                    'last_name': 'Analyst',
                    'is_staff': False,
                }
            )
            if created:
                analyst.set_password('demo1234')
                analyst.save()
            OrganisationMembership.objects.get_or_create(
                user=analyst, organisation=org,
                defaults={'role': 'analyst'}
            )
            self.stdout.write(f'  User: analyst / demo1234')

            admin_user, created = User.objects.get_or_create(
                username='admin',
                defaults={
                    'email': 'admin@acme.com',
                    'first_name': 'Admin',
                    'last_name': 'User',
                    'is_staff': True,
                    'is_superuser': True,
                }
            )
            if created:
                admin_user.set_password('admin1234')
                admin_user.save()
            OrganisationMembership.objects.get_or_create(
                user=admin_user, organisation=org,
                defaults={'role': 'admin'}
            )
            self.stdout.write(f'  User: admin / admin1234')

            # --- SAP batch ---
            if not UploadBatch.objects.filter(organisation=org, source_type='sap_fuel').exists():
                sap_content = SAP_CSV_DATA.encode('utf-8')
                batch_sap = UploadBatch.objects.create(
                    organisation=org,
                    uploaded_by=admin_user,
                    source_type='sap_fuel',
                    original_filename='ME2N_fuel_procurement_Q1-2024.txt',
                )
                batch_sap.raw_file.save(
                    'sap_fuel_demo.txt',
                    ContentFile(sap_content),
                    save=True
                )
                run_ingestion(batch_sap)
                self.stdout.write(f'  SAP batch: {batch_sap.row_count_ok} records OK, '
                                  f'{batch_sap.row_count_failed} failed')

            # --- Utility batch ---
            if not UploadBatch.objects.filter(organisation=org, source_type='utility_elec').exists():
                util_content = UTILITY_CSV_DATA.encode('utf-8')
                batch_util = UploadBatch.objects.create(
                    organisation=org,
                    uploaded_by=admin_user,
                    source_type='utility_elec',
                    original_filename='edf_business_portal_export_Q1-2024.csv',
                )
                batch_util.raw_file.save(
                    'utility_demo.csv',
                    ContentFile(util_content),
                    save=True
                )
                run_ingestion(batch_util)
                self.stdout.write(f'  Utility batch: {batch_util.row_count_ok} records OK')

            # --- Travel batch ---
            if not UploadBatch.objects.filter(organisation=org, source_type='travel_concur').exists():
                travel_content = json.dumps(TRAVEL_JSON_DATA).encode('utf-8')
                batch_travel = UploadBatch.objects.create(
                    organisation=org,
                    uploaded_by=admin_user,
                    source_type='travel_concur',
                    original_filename='concur_expense_export_Q1-2024.json',
                )
                batch_travel.raw_file.save(
                    'travel_demo.json',
                    ContentFile(travel_content),
                    save=True
                )
                run_ingestion(batch_travel)
                self.stdout.write(f'  Travel batch: {batch_travel.row_count_ok} records OK')

            self.stdout.write(self.style.SUCCESS('\nDemo data seeded. Login at /api/auth/login/'))
            self.stdout.write('  analyst / demo1234')
            self.stdout.write('  admin / admin1234')
