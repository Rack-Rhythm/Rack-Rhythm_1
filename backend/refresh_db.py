import os
import sys
from urllib.parse import urlparse, unquote

DB_URL = "postgresql://postgres.ofrezbxbgfgayrdijfko:JanSeva%40123@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"

os.environ["SUPABASE_DB_URL"] = DB_URL
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"

import django
django.setup()

from django.core.management import call_command
from django.db import connection
from janSetu.models import CustomUser, CivicIssue, Comment, NotificationItem, Profile

def run():
    print("1. Running database migrations on Supabase PostgreSQL...")
    call_command('migrate')
    print("[SUCCESS] Migrations applied successfully!")

    print("\n2. Ensuring schema columns are expanded to varchar(100)...")
    with connection.cursor() as cursor:
        try:
            cursor.execute('ALTER TABLE "janSetu_civicissue" ALTER COLUMN "status" TYPE varchar(100);')
            cursor.execute('ALTER TABLE "janSetu_civicissue" ALTER COLUMN "category" TYPE varchar(50);')
            cursor.execute('ALTER TABLE "janSetu_notificationitem" ALTER COLUMN "notification_type" TYPE varchar(50);')
            print("[SUCCESS] PostgreSQL columns altered to varchar(100) / varchar(50) successfully!")
        except Exception as e:
            print("Schema alter note:", e)

    print("\n3. Cleaning the CivicIssue table entirely...")
    # Clean comments and notifications linked to issues
    Comment.objects.all().delete()
    NotificationItem.objects.all().delete()
    CivicIssue.objects.all().delete()
    print("[SUCCESS] CivicIssue, Comment, and Notification tables emptied!")

    print("\n4. Seeding fresh verified sample civic issues...")
    
    # Ensure default users exist
    citizen, _ = CustomUser.objects.get_or_create(
        username="citizen_reporter",
        defaults={
            "email": "citizen@janseva.org",
            "role": "citizen",
            "first_name": "Verified",
            "last_name": "Citizen",
            "civic_citizen_xp": 185,
            "verified_citizen": True,
            "pin_code": "751003",
            "city": "Bhubaneswar",
            "state": "Odisha",
        }
    )
    if not hasattr(citizen, 'profile') or not citizen.profile:
        Profile.objects.get_or_create(
            user=citizen,
            defaults={
                "public_username": "citizen_reporter",
                "full_name": "Verified Citizen",
                "is_email_verified": True,
                "pincode": "751003"
            }
        )

    water_officer, _ = CustomUser.objects.get_or_create(
        username="officer_water",
        defaults={
            "email": "officer.water@bmc.gov.in",
            "role": "officer",
            "first_name": "Er. Water",
            "last_name": "Officer",
            "level_title": "Division Lead Officer - Water",
            "phone_number": "+91 94370 12345",
            "verified_citizen": True,
            "pin_code": "751003",
        }
    )

    roads_officer, _ = CustomUser.objects.get_or_create(
        username="officer_roads",
        defaults={
            "email": "officer.roads@bmc.gov.in",
            "role": "officer",
            "first_name": "Er. Roads",
            "last_name": "Officer",
            "level_title": "Division Lead Officer - Roads",
            "phone_number": "+91 94370 67890",
            "verified_citizen": True,
            "pin_code": "751024",
        }
    )

    # Issue 1: Water issue (JS-111)
    issue_water = CivicIssue.objects.create(
        id="JS-111",
        title="Leaking Pipeline and Water Waste",
        description="High-pressure underground drinking water pipe ruptured near Khandagiri main road intersection. Substantial potable water wastage flooding the pedestrian pavement.",
        category="Water",
        status="AI Verified",
        urgency="High",
        location={
            "address": "Khandagiri (Near Khandagiri Main Road)",
            "ward": "Khandagiri Ward",
            "wardNumber": 42,
            "pincode": "751003",
            "lat": 20.28314146459801,
            "lng": 85.7811959108105,
            "date": "2026-09-04",
            "time": "11:07 AM"
        },
        pin_code="751003",
        reporter=citizen,
        images={
            "reported": "https://images.unsplash.com/photo-1541888946425-d0fbb18086f6?w=800&auto=format&fit=crop&q=80",
            "resolved": ""
        },
        ai_analysis={
            "detectedObject": "Pipeline Rupture & Water Leak",
            "confidence": 94,
            "summary": "AI detected active pressurized water leak from municipal supply line. Urgency elevated to High."
        },
        assigned_department="Water Supply & Drainage Division",
        timeline=[
            {
                "stage": "Reported",
                "timestamp": "2026-09-04T05:37:00Z",
                "note": "Citizen submitted geo-tagged photo report.",
                "actor": "Verified Resident"
            },
            {
                "stage": "AI Verified",
                "timestamp": "2026-09-04T05:37:05Z",
                "note": "Computer vision validated defect authenticity (94% confidence). Categorized as Water Supply.",
                "actor": "JanSeva AI Triage Engine"
            }
        ],
        upvotes=14,
        verification_votes={"yes": 0, "no": 0, "users": {}},
        is_hidden_from_map=False,
        times_reported=1,
        merged_ticket_ids=[]
    )

    # Issue 2: Road issue (JS-101)
    issue_roads = CivicIssue.objects.create(
        id="JS-101",
        title="Deep Asphalt Pothole & Craters on Main Transit Road",
        description="Dangerous double crater pothole on left carriageway causing vehicular bottleneck and high two-wheeler skid hazard during night hours.",
        category="Roads",
        status="AI Verified",
        urgency="Critical",
        location={
            "address": "Patia Square, Near Infocity Road",
            "ward": "Patia Tech Ward",
            "wardNumber": 12,
            "pincode": "751024",
            "lat": 20.3533,
            "lng": 85.8195,
            "date": "2026-09-04",
            "time": "09:30 AM"
        },
        pin_code="751024",
        reporter=citizen,
        images={
            "reported": "https://images.unsplash.com/photo-1515162816999-a0c47dc192f7?w=800&auto=format&fit=crop&q=80",
            "resolved": ""
        },
        ai_analysis={
            "detectedObject": "Road Crater & Asphalt Erosion",
            "confidence": 96,
            "summary": "Severe pavement crater detected with active vehicular hazard risk. Categorized as Roads & PWD."
        },
        assigned_department="Roads & Public Works Department (PWD)",
        timeline=[
            {
                "stage": "Reported",
                "timestamp": "2026-09-04T04:00:00Z",
                "note": "Report logged with verified GPS geotag.",
                "actor": "Verified Resident"
            },
            {
                "stage": "AI Verified",
                "timestamp": "2026-09-04T04:00:04Z",
                "note": "Automated vision analysis confirmed critical depth crater.",
                "actor": "JanSeva AI Triage Engine"
            }
        ],
        upvotes=28,
        verification_votes={"yes": 0, "no": 0, "users": {}},
        is_hidden_from_map=False,
        times_reported=2,
        merged_ticket_ids=[]
    )

    # Issue 3: Sanitation issue (JS-102)
    issue_sanitation = CivicIssue.objects.create(
        id="JS-102",
        title="Overflowing Municipal Garbage Bin and Waste Spillage",
        description="Public community bin overflowing with secondary spillage on pavement. Foul odor and health hazard across residential street.",
        category="Sanitation",
        status="AI Verified",
        urgency="High",
        location={
            "address": "Saheed Nagar Commercial Lane 4",
            "ward": "Saheed Nagar Ward",
            "wardNumber": 34,
            "pincode": "751007",
            "lat": 20.2882,
            "lng": 85.8431,
            "date": "2026-09-04",
            "time": "08:15 AM"
        },
        pin_code="751007",
        reporter=citizen,
        images={
            "reported": "https://images.unsplash.com/photo-1532996122724-e3c354a0b15b?w=800&auto=format&fit=crop&q=80",
            "resolved": ""
        },
        ai_analysis={
            "detectedObject": "Solid Waste & Overflowing Dumpster",
            "confidence": 92,
            "summary": "Uncollected municipal waste cluster detected on pedestrian walkway."
        },
        assigned_department="Solid Waste Management Division",
        timeline=[
            {
                "stage": "Reported",
                "timestamp": "2026-09-04T02:45:00Z",
                "note": "Citizen submitted geo-tagged sanitation complaint.",
                "actor": "Verified Resident"
            },
            {
                "stage": "AI Verified",
                "timestamp": "2026-09-04T02:45:06Z",
                "note": "Computer vision categorized under Solid Waste & Sanitation.",
                "actor": "JanSeva AI Triage Engine"
            }
        ],
        upvotes=19,
        verification_votes={"yes": 0, "no": 0, "users": {}},
        is_hidden_from_map=False,
        times_reported=1,
        merged_ticket_ids=[]
    )

    print("[SUCCESS] Successfully created fresh issues:")
    print(f"  - {issue_water.id}: {issue_water.title} ({issue_water.category})")
    print(f"  - {issue_roads.id}: {issue_roads.title} ({issue_roads.category})")
    print(f"  - {issue_sanitation.id}: {issue_sanitation.title} ({issue_sanitation.category})")
    print("\n[SUCCESS] Supabase PostgreSQL database is completely cleaned, schema-updated, and refreshed!")

if __name__ == "__main__":
    run()
