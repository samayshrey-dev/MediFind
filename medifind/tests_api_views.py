import json
from decimal import Decimal
from datetime import time, timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone

from medifind.models import Medicine, Pharmacy, Inventory, Order, Reservation, UserProfile, OperationalAnomalyAlert


class APIViewsIntegrationTestCase(TestCase):
    """Integration test suite for HTTP Views, API Endpoints, Commerce & Payment Workflows."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="apiviewuser",
            email="apiviewuser@example.com",
            password="Password123!"
        )
        self.profile, _ = UserProfile.objects.get_or_create(
            user=self.user,
            defaults={
                "role": "Customer",
                "verification_status": "Approved"
            }
        )
        self.medicine = Medicine.objects.create(
            name="Crocin 650",
            brand="GSK",
            category="Fever & Cold",
            dosage="650mg",
            description="Effective fever relief tablet",
            uses="Fever, Pain",
            side_effects="Mild rash in rare cases",
            prescription_required=False
        )
        self.pharmacy = Pharmacy.objects.create(
            name="Apollo Pharmacy ViewTest",
            owner_name="Apollo Admin",
            phone="9876543210",
            email="apolloview@test.com",
            address="100 Mount Road",
            city="Chennai",
            state="Tamil Nadu",
            pincode="600002",
            latitude=Decimal("13.0827"),
            longitude=Decimal("80.2707"),
            opening_time=time(8, 0),
            closing_time=time(22, 0),
            is_active=True,
            is_open=True
        )
        self.inventory = Inventory.objects.create(
            medicine=self.medicine,
            pharmacy=self.pharmacy,
            quantity=40,
            price=Decimal("25.00"),
            expiry_date=timezone.now().date() + timedelta(days=150)
        )

    # 1. CORE SEARCH & DETAIL VIEWS
    def test_home_view(self):
        """Test home page GET request renders correctly."""
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)

    def test_search_view(self):
        """Test search endpoint with medicine query."""
        response = self.client.get(reverse("search"), {"q": "Crocin"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Crocin 650", response.content.decode())

    def test_medicine_detail_view(self):
        """Test medicine detail view for specific medicine."""
        response = self.client.get(reverse("medicine_detail", args=[self.medicine.id]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("Crocin 650", response.content.decode())

    def test_pharmacy_detail_view(self):
        """Test pharmacy detail view."""
        response = self.client.get(reverse("pharmacy_detail", args=[self.pharmacy.id]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("Apollo Pharmacy ViewTest", response.content.decode())

    # 2. COMMERCE & API ENDPOINTS
    def test_commerce_snapshot_api(self):
        """Test transaction snapshot creation via POST API."""
        payload = {
            "session_id": "test_sess_views_001",
            "inventory_id": self.inventory.id,
            "quantity": 2
        }
        response = self.client.post(
            reverse("commerce_create_snapshot"),
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["total_amount"], 50.0)

    def test_ai_multilingual_search_api(self):
        """Test multilingual query translation API endpoint."""
        payload = {"query": "बुखार की दवा", "lat": 13.0827, "lng": 80.2707}
        response = self.client.post(
            reverse("ai_multilingual_search_api"),
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("query", data)

    def test_ai_medicine_info_api(self):
        """Test AI medicine info lookup endpoint."""
        response = self.client.get(reverse("ai_medicine_info_api"), {"q": "Crocin 650"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("medicine", data)

    def test_nearby_pharmacies_api(self):
        """Test geo-distance nearby pharmacies API response."""
        response = self.client.get(reverse("nearby_pharmacies_api"), {
            "lat": "13.0827",
            "lng": "80.2707",
            "radius": "10"
        })
        self.assertEqual(response.status_code, 200)

    # 3. AUTHENTICATION & LOGIN FLOW
    def test_user_login_view(self):
        """Test user login authentication endpoint."""
        login_success = self.client.login(username="apiviewuser", password="Password123!")
        self.assertTrue(login_success)

    def test_unauthorized_dashboard_access_redirects(self):
        """Test protected pharmacy dashboard redirects unauthenticated users."""
        response = self.client.get(reverse("dashboard"))
        self.assertIn(response.status_code, [302, 403])
