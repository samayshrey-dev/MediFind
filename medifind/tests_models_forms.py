from decimal import Decimal
from datetime import time, timedelta
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone

from medifind.models import (
    Medicine, Pharmacy, UserProfile, PharmacyClaim, Inventory, Reservation,
    Notification, SearchHistory, AgentAuditLog, Order, WebhookEvent,
    PasswordResetOTP, Prescription, DailyDemandSnapshot, ForecastModelVersion,
    DemandForecast, OperationalAnomalyAlert, OSMPharmacyLocation
)
from medifind.forms import MedicineForm, PharmacyForm, InventoryForm, RegisterForm


class ModelsAndFormsTestCase(TestCase):
    """Unit tests for all ORM Models and Forms in MediFind."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="testuser@example.com",
            password="Password123!"
        )
        self.medicine = Medicine.objects.create(
            name="Paracetamol 500mg",
            brand="Calpol",
            category="Fever & Cold",
            dosage="500mg",
            description="Used for fever and pain",
            uses="Fever, Headaches",
            side_effects="Nausea in rare cases",
            prescription_required=False
        )
        self.pharmacy = Pharmacy.objects.create(
            name="HealthPlus Pharmacy",
            owner_name="Dr. John Doe",
            phone="9876543210",
            email="healthplus@example.com",
            address="123 Main Street",
            city="Bengaluru",
            state="Karnataka",
            pincode="560001",
            latitude=Decimal("12.9715987"),
            longitude=Decimal("77.5945627"),
            opening_time=time(8, 0),
            closing_time=time(22, 0),
            is_active=True,
            is_open=True
        )
        self.inventory = Inventory.objects.create(
            medicine=self.medicine,
            pharmacy=self.pharmacy,
            quantity=100,
            price=Decimal("15.50"),
            expiry_date=timezone.now().date() + timedelta(days=180)
        )

    def test_medicine_model(self):
        """Test Medicine model creation, string representation, and field defaults."""
        self.assertEqual(str(self.medicine), "Paracetamol 500mg")
        self.assertFalse(self.medicine.prescription_required)
        self.assertEqual(self.medicine.category, "Fever & Cold")

    def test_pharmacy_model(self):
        """Test Pharmacy model fields, string representation, and default values."""
        self.assertEqual(str(self.pharmacy), "HealthPlus Pharmacy")
        self.assertTrue(self.pharmacy.is_active)
        self.assertTrue(self.pharmacy.is_open)
        self.assertEqual(self.pharmacy.verification_status, "Approved")

    def test_inventory_model(self):
        """Test Inventory model relationship and stock attributes."""
        self.assertEqual(self.inventory.medicine, self.medicine)
        self.assertEqual(self.inventory.pharmacy, self.pharmacy)
        self.assertEqual(self.inventory.quantity, 100)
        self.assertEqual(self.inventory.price, Decimal("15.50"))

    def test_user_profile_model(self):
        """Test UserProfile model creation and fields."""
        profile = UserProfile.objects.get(user=self.user)
        profile.role = "Customer"
        profile.verification_status = "Approved"
        profile.save()
        self.assertEqual(str(profile), "testuser - Customer (Approved)")
        self.assertEqual(profile.role, "Customer")

    def test_pharmacy_claim_model(self):
        """Test PharmacyClaim model creation and status defaults."""
        claim = PharmacyClaim.objects.create(
            pharmacy=self.pharmacy,
            user=self.user,
            drug_license_number="DL-123456",
            status="Pending"
        )
        self.assertEqual(claim.status, "Pending")
        self.assertEqual(claim.drug_license_number, "DL-123456")

    def test_reservation_model(self):
        """Test Reservation model creation and state fields."""
        reservation = Reservation.objects.create(
            customer=self.user,
            pharmacy=self.pharmacy,
            medicine=self.medicine,
            quantity=2,
            payment_method="PayOnPickup",
            status="Pending"
        )
        self.assertEqual(reservation.quantity, 2)
        self.assertEqual(reservation.payment_method, "PayOnPickup")
        self.assertEqual(reservation.status, "Pending")

    def test_order_model(self):
        """Test Order model creation and status management."""
        order = Order.objects.create(
            order_reference="ORD-TEST-123",
            user=self.user,
            medicine=self.medicine,
            pharmacy=self.pharmacy,
            inventory=self.inventory,
            quantity=3,
            unit_price=Decimal("15.50"),
            total_amount=Decimal("46.50"),
            status="PAID"
        )
        self.assertEqual(order.total_amount, Decimal("46.50"))
        self.assertEqual(order.status, "PAID")
        self.assertIn("ORD-TEST-123", str(order))

    def test_webhook_event_model(self):
        """Test WebhookEvent idempotency logging model."""
        evt = WebhookEvent.objects.create(
            event_id="evt_test_12345",
            event_type="payment.captured",
            payload={"payment_id": "pay_98765"}
        )
        self.assertEqual(evt.event_id, "evt_test_12345")
        self.assertEqual(evt.event_type, "payment.captured")

    def test_agent_audit_log_model(self):
        """Test AgentAuditLog creation for tracking autonomous agent decisions."""
        log = AgentAuditLog.objects.create(
            user=self.user,
            event_type="CHECKOUT_APPROVED",
            session_id="sess_xyz_789",
            state="APPROVED",
            payload={"approved": True, "amount": 46.50}
        )
        self.assertEqual(log.event_type, "CHECKOUT_APPROVED")
        self.assertEqual(log.session_id, "sess_xyz_789")

    def test_operational_anomaly_alert_model(self):
        """Test OperationalAnomalyAlert model creation and resolution flag."""
        alert = OperationalAnomalyAlert.objects.create(
            alert_type="PRICE_ANOMALY",
            severity="HIGH",
            status="DETECTED"
        )
        self.assertEqual(alert.alert_type, "PRICE_ANOMALY")
        self.assertEqual(alert.severity, "HIGH")
        self.assertEqual(alert.status, "DETECTED")

    def test_osm_pharmacy_location_model(self):
        """Test OSMPharmacyLocation model representation."""
        osm_loc = OSMPharmacyLocation.objects.create(
            osm_id=123456789,
            name="Apollo Pharmacy OSM",
            latitude=Decimal("12.9720000"),
            longitude=Decimal("77.5950000"),
            address="Commercial Street, Bengaluru"
        )
        self.assertEqual(osm_loc.osm_id, 123456789)
        self.assertEqual(osm_loc.name, "Apollo Pharmacy OSM")

    # FORMS TESTING
    def test_medicine_form_valid(self):
        """Test MedicineForm with valid data."""
        form = MedicineForm(data={
            "name": "Ibuprofen 400mg",
            "brand": "Brufen",
            "category": "Pain Relief",
            "dosage": "400mg",
            "description": "Anti-inflammatory drug",
            "uses": "Pain, Inflammation",
            "side_effects": "Stomach upset",
            "prescription_required": False
        })
        self.assertTrue(form.is_valid())

    def test_pharmacy_form_valid(self):
        """Test PharmacyForm with valid inputs and Bootstrap styling applied."""
        form = PharmacyForm(data={
            "name": "Metro Chemist",
            "owner_name": "Jane Smith",
            "phone": "9876500000",
            "email": "metro@chemist.com",
            "address": "MG Road",
            "city": "Bengaluru",
            "state": "Karnataka",
            "pincode": "560002",
            "latitude": "12.9750000",
            "longitude": "77.6000000",
            "opening_time": "09:00",
            "closing_time": "21:00",
            "is_active": True,
            "is_open": True,
            "verification_status": "Approved"
        })
        self.assertTrue(form.is_valid())
        self.assertIn("form-control", form.fields["name"].widget.attrs["class"])

    def test_register_form_password_mismatch(self):
        """Test RegisterForm password validation logic."""
        form = RegisterForm(data={
            "username": "newuser",
            "email": "newuser@example.com",
            "role": "Customer",
            "password": "Password123!",
            "confirm_password": "DifferentPassword!"
        })
        self.assertFalse(form.is_valid())
        self.assertIn("__all__", form.errors)
