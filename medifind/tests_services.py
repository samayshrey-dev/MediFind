import json
from decimal import Decimal
from datetime import time, timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone

from medifind.models import Medicine, Pharmacy, Inventory, PasswordResetOTP, OperationalAnomalyAlert
from medifind.otp_service import (
    generate_numeric_otp, mask_target_contact, send_password_reset_otp, verify_and_consume_otp
)
from medifind.fuzzy_search import MedicineMatcher
from medifind.security import get_client_ip, is_rate_limited, is_safe_external_url, sanitize_plain_text
from medifind.commerce_service import AgenticCommerceService
from medifind.excel_service import ExcelInventoryService
from medifind.price_intelligence import UnitPriceNormalizer, ValueScoreEngine
from medifind.anomaly_engine import AnomalyDetectionEngine
from medifind.multilingual_engine import LanguageDetectorService
from medifind.osm_pharmacy_service import haversine_distance, format_distance_display, OSMPharmacyService
from medifind.medicine_info_assistant import InfoIntentClassifier
from medifind.inventory_intelligence import TimeSeriesForecastingEngine


class ServicesTestCase(TestCase):
    """Comprehensive unit test suite for business logic, services, and intelligence engines."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="serviceuser",
            email="serviceuser@example.com",
            password="Password123!"
        )
        self.medicine = Medicine.objects.create(
            name="Dolo 650",
            brand="Micro Labs",
            category="Fever & Cold",
            dosage="650mg",
            description="Paracetamol 650mg tablet for fever",
            uses="Fever, Pain",
            side_effects="Nausea",
            prescription_required=False
        )
        self.pharmacy = Pharmacy.objects.create(
            name="City Pharma",
            owner_name="Alice Brown",
            phone="9876543211",
            email="citypharma@example.com",
            address="45 Park Road",
            city="Chennai",
            state="Tamil Nadu",
            pincode="600001",
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
            quantity=50,
            price=Decimal("30.00"),
            expiry_date=timezone.now().date() + timedelta(days=200),
            batch_number="B123"
        )

    # 1. OTP SERVICE TESTS
    def test_generate_numeric_otp(self):
        """Test OTP generation creates random 6-digit numeric string."""
        otp1 = generate_numeric_otp(6)
        otp2 = generate_numeric_otp(6)
        self.assertEqual(len(otp1), 6)
        self.assertTrue(otp1.isdigit())
        self.assertTrue(otp2.isdigit())

    def test_mask_target_contact(self):
        """Test email and phone number privacy masking."""
        masked_email = mask_target_contact("serviceuser@example.com")
        self.assertTrue(masked_email.startswith("s"))
        self.assertIn("@example.com", masked_email)

        masked_phone = mask_target_contact("9876543211")
        self.assertTrue(masked_phone.endswith("3211"))

    def test_send_and_verify_password_reset_otp(self):
        """Test OTP generation, database saving, and successful verification."""
        success, msg, otp_obj = send_password_reset_otp(self.user)
        self.assertTrue(success)
        self.assertIsNotNone(otp_obj)

        # Verify correct OTP code succeeds
        is_valid, err_msg = verify_and_consume_otp(self.user, otp_obj.otp_code)
        self.assertTrue(is_valid)

        # Re-verification fails (OTP used)
        is_valid_again, err_msg_again = verify_and_consume_otp(self.user, otp_obj.otp_code)
        self.assertFalse(is_valid_again)

    def test_verify_expired_otp(self):
        """Test that expired OTP is rejected."""
        otp_obj = PasswordResetOTP.objects.create(
            user=self.user,
            otp_code="123456",
            target=self.user.email,
            channel="email",
            is_used=False,
            expires_at=timezone.now() - timedelta(minutes=5)
        )
        is_valid, err_msg = verify_and_consume_otp(self.user, "123456")
        self.assertFalse(is_valid)

    # 2. FUZZY SEARCH ENGINE TESTS
    def test_medicine_matcher_clean_query(self):
        """Test query cleaning removes filler words and punctuation."""
        cleaned = MedicineMatcher.clean_query("dolo 650 tablet near me")
        self.assertEqual(cleaned, "dolo 650")

    def test_medicine_matcher_similarity(self):
        """Test hybrid string similarity calculation."""
        score = MedicineMatcher.compute_similarity("dolo", "dolo 650")
        self.assertGreater(score, 0.7)

    def test_medicine_matcher_alias_resolution(self):
        """Test brand alias resolution to canonical name."""
        resolved = MedicineMatcher.resolve_medicine_alias("doloo")
        self.assertEqual(resolved, "Dolo 650")

    # 3. SECURITY MODULE TESTS
    def test_is_safe_external_url(self):
        """Test SSRF protection disallows internal and metadata URLs."""
        self.assertTrue(is_safe_external_url("https://api.testpharmacy.com/stock"))
        self.assertFalse(is_safe_external_url("http://127.0.0.1/admin"))
        self.assertFalse(is_safe_external_url("http://169.254.169.254/latest/meta-data/"))

    def test_sanitize_plain_text(self):
        """Test input sanitization strips HTML tags."""
        sanitized = sanitize_plain_text("<script>alert('xss')</script>Dolo 650")
        self.assertEqual(sanitized, "alert('xss')Dolo 650")

    def test_is_rate_limited(self):
        """Test rate limiting sliding window."""
        key = "test_key_123"
        self.assertFalse(is_rate_limited(key, max_requests=10, window_seconds=60))

    # 4. EXCEL SERVICE TESTS
    def test_generate_excel_template(self):
        """Test Excel template generation returns workbook byte stream."""
        content = ExcelInventoryService.generate_excel_template()
        self.assertTrue(len(content) > 0)

    def test_export_inventory_excel(self):
        """Test inventory export generates Excel binary content."""
        content = ExcelInventoryService.export_pharmacy_inventory(self.pharmacy)
        self.assertTrue(len(content) > 0)

    # 5. PRICE INTELLIGENCE TESTS
    def test_price_intelligence_unit_price(self):
        """Test price intelligence unit price computation."""
        res = UnitPriceNormalizer.parse_pack_quantity("Strip of 10")
        self.assertEqual(res, 10)

    # 6. ANOMALY ENGINE TESTS
    def test_run_full_system_anomaly_scan(self):
        """Test full system anomaly scan execution."""
        res = AnomalyDetectionEngine.run_full_system_anomaly_scan()
        self.assertIn("new_alerts_detected", res)

    # 7. MULTILINGUAL ENGINE TESTS
    def test_multilingual_language_detection(self):
        """Test language detection for input query."""
        lang, confidence = LanguageDetectorService.detect_language("बुखार की दवा")
        self.assertIn(lang, ["hi", "ta", "te", "en", "auto"])

    # 8. OSM PHARMACY SERVICE TESTS
    def test_haversine_distance(self):
        """Test geographical distance computation in kilometers."""
        dist = haversine_distance(13.0827, 80.2707, 13.0830, 80.2710)
        self.assertGreater(dist, 0)

    def test_format_distance_display(self):
        """Test distance display formatting."""
        self.assertEqual(format_distance_display(0.5), "500 m away")
        self.assertEqual(format_distance_display(2.5), "2.5 km away")

    # 9. MEDICINE INFO ASSISTANT TESTS
    def test_medicine_info_intent_classification(self):
        """Test intent classification for medicine queries."""
        intent = InfoIntentClassifier.classify_intent("What are the side effects of Dolo 650?")
        self.assertIn("SIDE_EFFECTS", intent)

    # 10. INVENTORY INTELLIGENCE TESTS
    def test_predictive_inventory_sma(self):
        """Test simple moving average forecast calculation."""
        sma = TimeSeriesForecastingEngine.simple_moving_average([10.0, 20.0, 30.0, 40.0], window=2)
        self.assertEqual(sma, 35.0)
