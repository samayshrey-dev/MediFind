import hmac
import hashlib
import json
import uuid
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.conf import settings
from django.utils import timezone

from django.contrib.auth.models import User
from .models import Medicine, Pharmacy, Inventory, Order, WebhookEvent, AgentAuditLog, Reservation, UserProfile
from .commerce_service import AgenticCommerceService, PriceMismatchError, OutOfStockError


class RazorpayAgenticCommerceTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.medicine = Medicine.objects.create(
            name="Dolo 650",
            brand="Micro Labs",
            dosage="650mg",
            category="Pain Relief",
            description="Paracetamol tablet",
            uses="Fever, headache",
            side_effects="None",
            prescription_required=False
        )
        self.pharmacy = Pharmacy.objects.create(
            name="Apollo Pharmacy",
            owner_name="Apollo Chemist",
            phone="9876543210",
            email="apollo@test.com",
            address="10 Anna Salai",
            city="Chennai",
            state="Tamil Nadu",
            pincode="600002",
            latitude=13.0827,
            longitude=80.2707,
            opening_time="08:00",
            closing_time="22:00",
            is_active=True,
            is_open=True
        )
        self.inventory = Inventory.objects.create(
            medicine=self.medicine,
            pharmacy=self.pharmacy,
            quantity=50,
            price=Decimal("22.00"),
            expiry_date=timezone.now().date() + timezone.timedelta(days=300)
        )
        self.session_id = "test_session_abc123"

    def test_01_create_transaction_snapshot(self):
        """User reviews purchase -> server creates immutable snapshot."""
        resp = self.client.post("/api/commerce/snapshot/", data=json.dumps({
            "session_id": self.session_id,
            "inventory_id": self.inventory.id,
            "quantity": 1
        }), content_type="application/json")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["total_amount"], 22.0)
        self.assertEqual(data["status"], "APPROVED")

        order = Order.objects.get(order_reference=data["order_reference"])
        self.assertEqual(order.status, "APPROVED")
        self.assertEqual(order.total_amount, Decimal("22.00"))

    def test_02_create_razorpay_order_amount_in_paise(self):
        """Revalidates inventory and creates Razorpay Order with amount in paise."""
        order = AgenticCommerceService.create_transaction_snapshot(
            session_id=self.session_id,
            inventory_id=self.inventory.id,
            quantity=1
        )

        with patch("medifind.commerce_service.AgenticCommerceService.get_razorpay_client") as mock_client:
            mock_order_api = MagicMock()
            mock_order_api.create.return_value = {"id": "order_mock_12345", "amount": 2200, "status": "created"}
            mock_client.return_value.order = mock_order_api

            resp = self.client.post("/api/payments/create-order/", data=json.dumps({
                "order_reference": order.order_reference
            }), content_type="application/json")

            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue(data["success"])
            self.assertEqual(data["amount"], 2200)
            self.assertEqual(data["razorpay_order_id"], "order_mock_12345")

    def test_03_price_change_guard_rejects_order(self):
        """Bounded Commerce: Price divergence rejects checkout and requests re-approval."""
        order = AgenticCommerceService.create_transaction_snapshot(
            session_id=self.session_id,
            inventory_id=self.inventory.id,
            quantity=1
        )
        # Price changed by pharmacist in DB
        self.inventory.price = Decimal("28.00")
        self.inventory.save()

        resp = self.client.post("/api/payments/create-order/", data=json.dumps({
            "order_reference": order.order_reference
        }), content_type="application/json")

        self.assertEqual(resp.status_code, 409)
        data = resp.json()
        self.assertEqual(data["error_type"], "PRICE_CHANGED")
        self.assertEqual(data["message"], "This option has changed. Please review your order.")
        self.assertEqual(data["old_price"], 22.0)
        self.assertEqual(data["new_price"], 28.0)

    def test_04_out_of_stock_guard_rejects_order(self):
        """Bounded Commerce: Out of stock rejects checkout safely."""
        order = AgenticCommerceService.create_transaction_snapshot(
            session_id=self.session_id,
            inventory_id=self.inventory.id,
            quantity=1
        )
        self.inventory.quantity = 0
        self.inventory.save()

        resp = self.client.post("/api/payments/create-order/", data=json.dumps({
            "order_reference": order.order_reference
        }), content_type="application/json")

        self.assertEqual(resp.status_code, 409)
        data = resp.json()
        self.assertEqual(data["error_type"], "OUT_OF_STOCK")
        self.assertEqual(data["message"], "This option has changed. Please review your order.")

    def test_05_invalid_signature_rejection(self):
        """Tampered or invalid signature is rejected and does NOT reduce stock."""
        order = AgenticCommerceService.create_transaction_snapshot(
            session_id=self.session_id,
            inventory_id=self.inventory.id,
            quantity=1
        )
        order.razorpay_order_id = "order_rzp_test_1"
        order.save()

        resp = self.client.post("/api/payments/verify/", data=json.dumps({
            "order_reference": order.order_reference,
            "razorpay_order_id": "order_rzp_test_1",
            "razorpay_payment_id": "pay_test_1",
            "razorpay_signature": "invalid_fake_signature"
        }), content_type="application/json")

        self.assertEqual(resp.status_code, 400)
        order.refresh_from_db()
        self.assertEqual(order.status, "PAYMENT_FAILED")
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.quantity, 50)

    def test_06_valid_signature_marks_paid_and_decrements_stock(self):
        """Valid HMAC SHA256 signature confirms payment and decrements stock."""
        order = AgenticCommerceService.create_transaction_snapshot(
            session_id=self.session_id,
            inventory_id=self.inventory.id,
            quantity=1
        )
        rzp_order_id = "order_rzp_valid_99"
        rzp_pay_id = "pay_rzp_valid_99"
        order.razorpay_order_id = rzp_order_id
        order.save()

        valid_sig = hmac.new(
            settings.RAZORPAY_KEY_SECRET.encode("utf-8"),
            f"{rzp_order_id}|{rzp_pay_id}".encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        resp = self.client.post("/api/payments/verify/", data=json.dumps({
            "order_reference": order.order_reference,
            "razorpay_order_id": rzp_order_id,
            "razorpay_payment_id": rzp_pay_id,
            "razorpay_signature": valid_sig
        }), content_type="application/json")

        self.assertEqual(resp.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, "PAID")
        self.assertEqual(order.razorpay_payment_id, rzp_pay_id)
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.quantity, 49)

    def test_07_webhook_signature_and_idempotency(self):
        """Webhook verifies RAW body signature and prevents double stock deduction."""
        order = AgenticCommerceService.create_transaction_snapshot(
            session_id=self.session_id,
            inventory_id=self.inventory.id,
            quantity=1
        )
        rzp_order_id = "order_rzp_wh_test"
        order.razorpay_order_id = rzp_order_id
        order.status = "PAYMENT_PENDING"
        order.save()

        wh_event_id = f"evt_test_{uuid.uuid4().hex[:8]}"
        wh_payload = {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_wh_captured_1",
                        "order_id": rzp_order_id,
                        "amount": 2200,
                        "currency": "INR"
                    }
                }
            }
        }
        raw_body = json.dumps(wh_payload).encode("utf-8")
        wh_sig = hmac.new(
            settings.RAZORPAY_WEBHOOK_SECRET.encode("utf-8"),
            raw_body,
            hashlib.sha256
        ).hexdigest()

        # Delivery 1
        resp1 = self.client.post(
            "/api/payments/razorpay/webhook/",
            data=raw_body,
            content_type="application/json",
            headers={"X-Razorpay-Signature": wh_sig, "X-Razorpay-Event-Id": wh_event_id}
        )
        self.assertEqual(resp1.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, "PAID")
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.quantity, 49)

        # Duplicate Delivery 2
        resp2 = self.client.post(
            "/api/payments/razorpay/webhook/",
            data=raw_body,
            content_type="application/json",
            headers={"X-Razorpay-Signature": wh_sig, "X-Razorpay-Event-Id": wh_event_id}
        )
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["status"], "DUPLICATE_IGNORED")
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.quantity, 49)  # Preserved

    def test_08_order_status_and_confirmed_page(self):
        """Order status API and HTML receipt page render correctly."""
        order = AgenticCommerceService.create_transaction_snapshot(
            session_id=self.session_id,
            inventory_id=self.inventory.id,
            quantity=1
        )
        order.status = "PAID"
        order.save()

        resp_api = self.client.get(f"/api/orders/{order.order_reference}/")
        self.assertEqual(resp_api.status_code, 200)
        self.assertEqual(resp_api.json()["status"], "PAID")

        resp_html = self.client.get(f"/orders/confirmed/{order.order_reference}/")
        self.assertEqual(resp_html.status_code, 200)
        self.assertContains(resp_html, "Order Confirmed!")
        self.assertContains(resp_html, order.order_reference)

    def test_09_pay_reservation_via_razorpay(self):
        """Customer can directly pay for a Reservation via Razorpay."""
        from django.contrib.auth.models import User
        from .models import Reservation, UserProfile

        user = User.objects.create_user(username="res_payer_user", password="password123")
        UserProfile.objects.filter(user=user).update(role="Customer")
        self.client.force_login(user)


        res = Reservation.objects.create(
            customer=user,
            pharmacy=self.pharmacy,
            medicine=self.medicine,
            quantity=1,
            status="Pending"
        )

        with patch("medifind.commerce_service.AgenticCommerceService.get_razorpay_client") as mock_client:
            mock_order_api = MagicMock()
            mock_order_api.create.return_value = {"id": "order_res_rzp_123", "amount": 2200, "status": "created"}
            mock_client.return_value.order = mock_order_api

            resp = self.client.post(f"/api/payments/pay-reservation/{res.id}/")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue(data["success"])
            self.assertEqual(data["amount"], 2200)
            self.assertEqual(data["razorpay_order_id"], "order_res_rzp_123")

            # Verify order created with reservation link
            order = Order.objects.get(order_reference=data["order_reference"])
            self.assertEqual(order.reservation, res)

            # Test completing payment signature
            rzp_payment_id = "pay_res_complete_99"
            valid_sig = hmac.new(
                settings.RAZORPAY_KEY_SECRET.encode("utf-8"),
                f"{data['razorpay_order_id']}|{rzp_payment_id}".encode("utf-8"),
                hashlib.sha256
            ).hexdigest()

            verify_resp = self.client.post("/api/payments/verify/", data=json.dumps({
                "order_reference": data["order_reference"],
                "razorpay_order_id": data["razorpay_order_id"],
                "razorpay_payment_id": rzp_payment_id,
                "razorpay_signature": valid_sig
            }), content_type="application/json")

            self.assertEqual(verify_resp.status_code, 200)
            res.refresh_from_db()
            self.assertTrue(res.is_paid)
            self.assertEqual(res.status, "Accepted")

    def test_10_fuzzy_misspelled_medicine_search(self):
        """Typo-tolerant and approximate medicine search returns matching inventory."""
        # Create Cetirizine for full test coverage
        med_cet = Medicine.objects.create(
            name="Cetirizine 10",
            brand="Cipla",
            dosage="10mg",
            category="Allergy",
            description="Antihistamine",
            uses="Cold, allergy"
        )
        Inventory.objects.create(
            medicine=med_cet,
            pharmacy=self.pharmacy,
            quantity=25,
            price=Decimal("18.00"),
            expiry_date=timezone.now().date() + timezone.timedelta(days=300)
        )

        # 1. Test web search with typo 'dollo'
        resp_web = self.client.get("/search/?medicine=dollo")
        self.assertEqual(resp_web.status_code, 200)
        self.assertContains(resp_web, "Dolo")

        # 2. Test AI Agent search with typo 'dollo 650'
        resp_agent = self.client.post("/api/ai/agent/search/", data=json.dumps({
            "query": "dollo 650",
            "lat": 13.0827,
            "lng": 80.2707
        }), content_type="application/json")
        self.assertEqual(resp_agent.status_code, 200)
        data = resp_agent.json()
        self.assertTrue(data["success"])
        self.assertGreater(len(data["all_options"]), 0)
        self.assertEqual(data["best_match"]["medicine_name"], "Dolo 650")

        # 3. Test suggestions with typo 'cetrizin'
        resp_sugg = self.client.get("/search/suggestions/?q=cetrizin")
        self.assertEqual(resp_sugg.status_code, 200)
        suggs = resp_sugg.json()
        self.assertGreater(len(suggs), 0)
        self.assertTrue(any("Cetirizine" in s["name"] for s in suggs))

    def test_11_reserve_medicine_pay_on_pickup(self):
        """Customer reserves medicine with 'Pay at Pharmacy on Pickup' option."""
        user = User.objects.create_user(username="pickup_res_user", password="password123")
        UserProfile.objects.filter(user=user).update(role="Customer")
        self.client.force_login(user)

        # GET reservation page
        resp_get = self.client.get(f"/reserve/{self.inventory.id}/")
        self.assertContains(resp_get, "Reserve Medicine")
        self.assertContains(resp_get, "Pay at Store Counter")


        # POST reservation with PayOnPickup
        resp_post = self.client.post(f"/reserve/{self.inventory.id}/", {
            "quantity": 2,
            "payment_method": "PayOnPickup",
            "notes": "Will pickup around 6 PM"
        }, follow=True)
        self.assertEqual(resp_post.status_code, 200)

        # Verify reservation created with is_paid=False and status=Pending
        res = Reservation.objects.get(customer=user, medicine=self.medicine)
        self.assertEqual(res.quantity, 2)
        self.assertEqual(res.payment_method, "PayOnPickup")
        self.assertFalse(res.is_paid)
        self.assertEqual(res.status, "Pending")

    def test_12_reserve_medicine_pay_online(self):
        """Customer reserves medicine and completes payment via Razorpay."""
        user = User.objects.create_user(username="online_res_user", password="password123")
        UserProfile.objects.filter(user=user).update(role="Customer")
        self.client.force_login(user)

        with patch("medifind.commerce_service.AgenticCommerceService.get_razorpay_client") as mock_client:
            mock_order_api = MagicMock()
            mock_order_api.create.return_value = {"id": "order_res_online_99", "amount": 2200, "status": "created"}
            mock_client.return_value.order = mock_order_api

            # POST online reservation via AJAX
            resp_post = self.client.post(f"/reserve/{self.inventory.id}/", {
                "quantity": 1,
                "payment_method": "Online",
                "notes": "Paid online"
            }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
            self.assertEqual(resp_post.status_code, 200)
            data = resp_post.json()
            self.assertTrue(data["success"])
            self.assertEqual(data["razorpay_order_id"], "order_res_online_99")

            res = Reservation.objects.get(id=data["order_reference"].split("-")[-1] if False else Reservation.objects.filter(customer=user).first().id)
            self.assertEqual(res.payment_method, "Online")
            self.assertFalse(res.is_paid)

            # Complete payment verification
            rzp_payment_id = "pay_res_online_captured_99"
            valid_sig = hmac.new(
                settings.RAZORPAY_KEY_SECRET.encode("utf-8"),
                f"{data['razorpay_order_id']}|{rzp_payment_id}".encode("utf-8"),
                hashlib.sha256
            ).hexdigest()

            verify_resp = self.client.post("/api/payments/verify/", data=json.dumps({
                "order_reference": data["order_reference"],
                "razorpay_order_id": data["razorpay_order_id"],
                "razorpay_payment_id": rzp_payment_id,
                "razorpay_signature": valid_sig
            }), content_type="application/json")

            self.assertEqual(verify_resp.status_code, 200)
            res.refresh_from_db()
            self.assertTrue(res.is_paid)
            self.assertEqual(res.status, "Accepted")

    def test_13_password_reset_flow(self):
        """User requests OTP password reset, receives 6-digit OTP, and sets a new password."""
        from django.core import mail
        from medifind.models import PasswordResetOTP

        user = User.objects.create_user(username="reset_tester", email="reset@example.com", password="old_password_123")

        # 1. GET password reset form
        resp_get = self.client.get("/password-reset/")
        self.assertEqual(resp_get.status_code, 200)
        self.assertContains(resp_get, "Forgot password?")

        # 2. POST identifier to trigger 6-digit OTP dispatch
        resp_post = self.client.post("/password-reset/", {"identifier": "reset@example.com"}, follow=True)
        self.assertEqual(resp_post.status_code, 200)
        self.assertContains(resp_post, "Verify OTP")
        self.assertEqual(len(mail.outbox), 1)

        # 3. Retrieve generated OTP
        otp_record = PasswordResetOTP.objects.filter(user=user, is_used=False).first()
        self.assertIsNotNone(otp_record)
        self.assertEqual(len(otp_record.otp_code), 6)

        # 4. Test invalid OTP rejection
        bad_post = self.client.post("/password-reset/verify/", {
            "otp_code": "000000",
            "new_password1": "NewSecretPass456!",
            "new_password2": "NewSecretPass456!"
        }, follow=True)
        self.assertContains(bad_post, "Invalid OTP code")

        # 5. POST valid OTP and new password
        resp_verify = self.client.post("/password-reset/verify/", {
            "otp_code": otp_record.otp_code,
            "new_password1": "NewSecretPass456!",
            "new_password2": "NewSecretPass456!"
        }, follow=True)
        self.assertEqual(resp_verify.status_code, 200)
        self.assertContains(resp_verify, "Password reset successfully!")

        otp_record.refresh_from_db()
        self.assertTrue(otp_record.is_used)

        # 6. Verify login with new password
        login_success = self.client.login(username="reset_tester", password="NewSecretPass456!")
        self.assertTrue(login_success)

    def test_14_recommendation_cheapest_mode_guarantees_lowest_price(self):
        """Cheapest mode ranking strictly guarantees lowest price first."""
        from medifind.commerce_agent import DeterministicRankingEngine, OptimizationGoal

        pharmacy_expensive = Pharmacy.objects.create(
            name="Expensive Chemist", owner_name="Chemist", phone="9111111111", email="exp@test.com",
            address="Near Road", city="Chennai", state="TN", pincode="600001",
            latitude=13.0800, longitude=80.2700, opening_time="08:00", closing_time="22:00",
            is_active=True, is_open=True
        )
        inv_expensive = Inventory.objects.create(
            medicine=self.medicine, pharmacy=pharmacy_expensive, quantity=30, price=Decimal("38.00"),
            expiry_date=timezone.now().date() + timezone.timedelta(days=200)
        )

        candidates = [
            {"inventory_id": inv_expensive.id, "medicine_name": "Dolo 650", "pharmacy_name": "Expensive Chemist", "price": 38.0, "distance_km": 0.5, "stock": 30, "is_open": True},
            {"inventory_id": self.inventory.id, "medicine_name": "Dolo 650", "pharmacy_name": "Apollo Pharmacy", "price": 22.0, "distance_km": 3.2, "stock": 50, "is_open": True}
        ]

        ranked = DeterministicRankingEngine.rank_candidates(candidates, OptimizationGoal.LOWEST_PRICE)
        self.assertEqual(ranked[0]["inventory_id"], self.inventory.id)
        self.assertEqual(ranked[0]["price"], 22.0)
        self.assertEqual(ranked[0]["rank"], 1)

    def test_15_recommendation_nearest_mode_guarantees_shortest_distance(self):
        """Nearest mode ranking strictly guarantees shortest distance first."""
        from medifind.commerce_agent import DeterministicRankingEngine, OptimizationGoal

        candidates = [
            {"inventory_id": 101, "medicine_name": "Dolo 650", "pharmacy_name": "Far Pharmacy", "price": 18.0, "distance_km": 8.5, "stock": 100, "is_open": True},
            {"inventory_id": 102, "medicine_name": "Dolo 650", "pharmacy_name": "Nearby Pharmacy", "price": 26.0, "distance_km": 0.8, "stock": 25, "is_open": True}
        ]

        ranked = DeterministicRankingEngine.rank_candidates(candidates, OptimizationGoal.CLOSEST)
        self.assertEqual(ranked[0]["inventory_id"], 102)
        self.assertEqual(ranked[0]["distance_km"], 0.8)
        self.assertEqual(ranked[0]["rank"], 1)

    def test_16_recommendation_best_value_mode_deterministic_composite(self):
        """Best value ranking combines normalized price, distance, stock, and open status deterministically."""
        from medifind.commerce_agent import DeterministicRankingEngine, OptimizationGoal

        candidates = [
            {"inventory_id": 201, "medicine_name": "Dolo 650", "pharmacy_name": "Far But Cheap", "price": 20.0, "distance_km": 15.0, "stock": 5, "is_open": False},
            {"inventory_id": 202, "medicine_name": "Dolo 650", "pharmacy_name": "Balanced Value Option", "price": 22.0, "distance_km": 1.2, "stock": 40, "is_open": True},
            {"inventory_id": 203, "medicine_name": "Dolo 650", "pharmacy_name": "Super Close But Overpriced", "price": 50.0, "distance_km": 0.2, "stock": 10, "is_open": True}
        ]

        ranked = DeterministicRankingEngine.rank_candidates(candidates, OptimizationGoal.BEST_VALUE, target_medicine_name="Dolo 650")
        # Balanced option wins best value
        self.assertEqual(ranked[0]["inventory_id"], 202)
        self.assertEqual(ranked[0]["rank"], 1)
        self.assertIn("composite_score", ranked[0])

    def test_17_recommendation_urgent_mode_guarantees_open_stock_proximity(self):
        """Urgent mode strictly requires reasonable stock (>=5) at currently open pharmacy closest to user."""
        from medifind.commerce_agent import DeterministicRankingEngine, OptimizationGoal

        candidates = [
            {"inventory_id": 301, "medicine_name": "Dolo 650", "pharmacy_name": "Closed Pharmacy", "price": 15.0, "distance_km": 0.3, "stock": 50, "is_open": False},
            {"inventory_id": 302, "medicine_name": "Dolo 650", "pharmacy_name": "Open Far Away", "price": 22.0, "distance_km": 7.0, "stock": 30, "is_open": True},
            {"inventory_id": 303, "medicine_name": "Dolo 650", "pharmacy_name": "Open Near With Stock", "price": 25.0, "distance_km": 1.1, "stock": 15, "is_open": True}
        ]

        ranked = DeterministicRankingEngine.rank_candidates(candidates, OptimizationGoal.FASTEST)
        # Open Near with stock wins urgent search
        self.assertEqual(ranked[0]["inventory_id"], 303)
        self.assertTrue(ranked[0]["is_open"])
        self.assertGreaterEqual(ranked[0]["stock"], 5)
        self.assertEqual(ranked[0]["rank"], 1)

    def test_18_no_ai_hallucination_facts_provenance_guard(self):
        """Zero AI hallucination: All returned medicines and pharmacies originate strictly from verified Django DB rows."""
        from medifind.commerce_agent import CommerceSearchService, IntentParser

        # Execute intent parser on natural language
        intent = IntentParser.local_fallback_parser("Find the cheapest Dolo 650 within 10 km")
        candidates = CommerceSearchService.search_candidates(intent, user_lat=13.0827, user_lng=80.2707)

        self.assertTrue(len(candidates) >= 1)
        for cand in candidates:
            # Verify DB fact provenance
            db_item = Inventory.objects.get(id=cand["inventory_id"])
            self.assertEqual(float(db_item.price), cand["price"])
            self.assertEqual(db_item.quantity, cand["stock"])
            self.assertEqual(db_item.pharmacy.name, cand["pharmacy_name"])
            self.assertEqual(db_item.medicine.name, cand["medicine_name"])

    def test_19_full_razorpay_success_flow_confirm_to_order_confirmed(self):
        """Step 8: Confirm & Pay -> Django Validates -> Razorpay Test Order -> Payment -> Verify -> Order Confirmed."""
        # 1. User reviews purchase -> Snapshot created
        snap_resp = self.client.post("/api/commerce/snapshot/", data=json.dumps({
            "session_id": "session_success_demo",
            "inventory_id": self.inventory.id,
            "quantity": 2
        }), content_type="application/json")
        self.assertEqual(snap_resp.status_code, 200)
        order_ref = snap_resp.json()["order_reference"]

        # 2. Confirm & Pay -> Django validates & creates Razorpay Test Order
        with patch("medifind.commerce_service.AgenticCommerceService.get_razorpay_client") as mock_client:
            mock_order_api = MagicMock()
            mock_order_api.create.return_value = {"id": "order_rzp_step8_success", "amount": 4400, "status": "created"}
            mock_client.return_value.order = mock_order_api

            pay_resp = self.client.post("/api/payments/create-order/", data=json.dumps({
                "order_reference": order_ref
            }), content_type="application/json")
            self.assertEqual(pay_resp.status_code, 200)
            self.assertEqual(pay_resp.json()["amount"], 4400)
            self.assertEqual(pay_resp.json()["razorpay_order_id"], "order_rzp_step8_success")

        # 3. Razorpay Checkout -> Payment Completed -> Server Verification
        rzp_pay_id = "pay_rzp_step8_verified_99"
        valid_sig = hmac.new(
            settings.RAZORPAY_KEY_SECRET.encode("utf-8"),
            f"order_rzp_step8_success|{rzp_pay_id}".encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        verify_resp = self.client.post("/api/payments/verify/", data=json.dumps({
            "order_reference": order_ref,
            "razorpay_order_id": "order_rzp_step8_success",
            "razorpay_payment_id": rzp_pay_id,
            "razorpay_signature": valid_sig
        }), content_type="application/json")
        self.assertEqual(verify_resp.status_code, 200)
        self.assertTrue(verify_resp.json()["success"])
        self.assertEqual(verify_resp.json()["status"], "PAID")

        # 4. Verify Stock decremented & Order Confirmed page displays correctly
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.quantity, 48)  # 50 - 2

        confirm_page_resp = self.client.get(f"/orders/confirmed/{order_ref}/")
        self.assertEqual(confirm_page_resp.status_code, 200)
        self.assertContains(confirm_page_resp, "Order Confirmed!")
        self.assertContains(confirm_page_resp, order_ref)
        self.assertContains(confirm_page_resp, "Dolo 650")

    def test_20_full_razorpay_failure_retry_flow(self):
        """Step 8: Payment failed/cancelled -> Order remains unpaid -> Stock NOT decremented -> Retry succeeds."""
        # 1. Create snapshot
        snap_resp = self.client.post("/api/commerce/snapshot/", data=json.dumps({
            "session_id": "session_retry_demo",
            "inventory_id": self.inventory.id,
            "quantity": 1
        }), content_type="application/json")
        order_ref = snap_resp.json()["order_reference"]

        # 2. Payment fails or user dismisses checkout
        fail_resp = self.client.post("/api/payments/fail/", data=json.dumps({
            "order_reference": order_ref,
            "reason": "Payment cancelled by user"
        }), content_type="application/json")
        self.assertEqual(fail_resp.status_code, 200)
        self.assertEqual(fail_resp.json()["status"], "PAYMENT_FAILED")

        # Verify stock is NOT deducted
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.quantity, 50)

        # 3. User clicks "Retry" -> Re-initiates Razorpay Order
        with patch("medifind.commerce_service.AgenticCommerceService.get_razorpay_client") as mock_client:
            mock_order_api = MagicMock()
            mock_order_api.create.return_value = {"id": "order_rzp_step8_retry", "amount": 2200, "status": "created"}
            mock_client.return_value.order = mock_order_api

            retry_pay_resp = self.client.post("/api/payments/create-order/", data=json.dumps({
                "order_reference": order_ref
            }), content_type="application/json")
            self.assertEqual(retry_pay_resp.status_code, 200)
            self.assertEqual(retry_pay_resp.json()["razorpay_order_id"], "order_rzp_step8_retry")

        # 4. User completes payment on retry -> Verification succeeds
        retry_pay_id = "pay_rzp_step8_retry_success"
        valid_sig = hmac.new(
            settings.RAZORPAY_KEY_SECRET.encode("utf-8"),
            f"order_rzp_step8_retry|{retry_pay_id}".encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        verify_resp = self.client.post("/api/payments/verify/", data=json.dumps({
            "order_reference": order_ref,
            "razorpay_order_id": "order_rzp_step8_retry",
            "razorpay_payment_id": retry_pay_id,
            "razorpay_signature": valid_sig
        }), content_type="application/json")
        self.assertEqual(verify_resp.status_code, 200)
        self.assertEqual(verify_resp.json()["status"], "PAID")

        # Stock is decremented now
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.quantity, 49)

    def test_21_failure_story_1_payment_fails_clean_unpaid_state(self):
        """Failure Story 1: Payment fails/dismissed -> Clean unpaid state -> Stock not decremented."""
        snap_resp = self.client.post("/api/commerce/snapshot/", data=json.dumps({
            "session_id": "fail_story_1",
            "inventory_id": self.inventory.id,
            "quantity": 1
        }), content_type="application/json")
        order_ref = snap_resp.json()["order_reference"]

        # Failure recorded
        fail_resp = self.client.post("/api/payments/fail/", data=json.dumps({
            "order_reference": order_ref,
            "reason": "Payment cancelled by user"
        }), content_type="application/json")
        self.assertEqual(fail_resp.status_code, 200)
        self.assertEqual(fail_resp.json()["status"], "PAYMENT_FAILED")

        # Database inventory preserved
        self.inventory.refresh_from_db()
        self.assertEqual(self.inventory.quantity, 50)

    def test_22_failure_story_2_stock_disappears_blocks_payment(self):
        """Failure Story 2: Stock disappears -> Pre-payment recheck blocks checkout with 409."""
        snap_resp = self.client.post("/api/commerce/snapshot/", data=json.dumps({
            "session_id": "fail_story_2",
            "inventory_id": self.inventory.id,
            "quantity": 5
        }), content_type="application/json")
        order_ref = snap_resp.json()["order_reference"]

        # Stock is depleted before user clicks confirm & pay
        self.inventory.quantity = 2
        self.inventory.save()

        resp = self.client.post("/api/payments/create-order/", data=json.dumps({
            "order_reference": order_ref
        }), content_type="application/json")
        self.assertEqual(resp.status_code, 409)
        data = resp.json()
        self.assertEqual(data["error_type"], "OUT_OF_STOCK")
        self.assertEqual(data["message"], "This option has changed. Please review your order.")

    def test_23_failure_story_3_price_changes_blocks_payment(self):
        """Failure Story 3: Price changes -> Pre-payment recheck blocks checkout with 409."""
        snap_resp = self.client.post("/api/commerce/snapshot/", data=json.dumps({
            "session_id": "fail_story_3",
            "inventory_id": self.inventory.id,
            "quantity": 1
        }), content_type="application/json")
        order_ref = snap_resp.json()["order_reference"]

        # Pharmacist changed price from ₹22 to ₹30
        self.inventory.price = Decimal("30.00")
        self.inventory.save()

        resp = self.client.post("/api/payments/create-order/", data=json.dumps({
            "order_reference": order_ref
        }), content_type="application/json")
        self.assertEqual(resp.status_code, 409)
        data = resp.json()
        self.assertEqual(data["error_type"], "PRICE_CHANGED")
        self.assertEqual(data["old_price"], 22.0)
        self.assertEqual(data["new_price"], 30.0)
        self.assertEqual(data["message"], "This option has changed. Please review your order.")

    def test_24_failure_story_4_location_denied_graceful_fallback(self):
        """Failure Story 4: User denies location -> Defaults gracefully to Chennai Central origin."""
        # Query without latitude or longitude
        resp = self.client.get("/api/pharmacies/nearby/?radius=5")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        # Should fallback to Chennai Central (13.0827, 80.2707) and return pharmacies
        self.assertGreaterEqual(data["count"], 1)

    def test_25_failure_story_5_ai_unavailable_normal_search_works(self):
        """Failure Story 5: AI LLM unavailable/throws error -> Deterministic DB search continues with 0 downtime."""
        from medifind.commerce_agent import IntentParser, CommerceSearchService

        # When AI model raises Exception or is unavailable, parse_with_ai falls back to local_fallback_parser
        with patch.object(IntentParser, "parse_with_ai", side_effect=lambda q: IntentParser.local_fallback_parser(q)):
            intent = IntentParser.parse_with_ai("Find the cheapest Dolo 650 within 5 km")
            self.assertEqual(intent["medicine_query"], "Dolo 650")
            self.assertEqual(intent["max_distance_km"], 5.0)

            # Database candidate search executes normally
            candidates = CommerceSearchService.search_candidates(intent, user_lat=13.0827, user_lng=80.2707)
            self.assertGreaterEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["medicine_name"], "Dolo 650")

    def test_26_pharmacy_api_query_and_sync(self):
        """Tests that PharmacyAPIClient queries external pharmacy API and syncs local stock."""
        from medifind.pharmacy_api import PharmacyAPIClient
        self.pharmacy.api_endpoint_url = "https://api.testpharmacy.com/v1/stock"
        self.pharmacy.api_auth_token = "test_token_123"
        self.pharmacy.api_sync_enabled = True
        self.pharmacy.save()

        mock_api_response = MagicMock()
        mock_api_response.status_code = 200
        mock_api_response.json.return_value = [
            {
                "medicine_name": "Azithromycin 500mg",
                "brand": "Zithrocare",
                "category": "Antibiotic",
                "dosage": "500mg",
                "price": 115.00,
                "quantity": 35,
                "batch_number": "AZI-LIVE-01",
                "expiry_date": "2027-05-30",
                "package_size": "Strip of 10",
                "sku_code": "AZI500-S10"
            }
        ]

        with patch("requests.get", return_value=mock_api_response):
            synced = PharmacyAPIClient.query_pharmacy_inventory(self.pharmacy, "Azithromycin")
            self.assertEqual(len(synced), 1)
            self.assertEqual(synced[0].medicine.name, "Azithromycin 500mg")
            self.assertEqual(synced[0].quantity, 35)
            self.assertEqual(synced[0].price, Decimal("115.00"))

            # Verify in DB
            db_inv = Inventory.objects.filter(pharmacy=self.pharmacy, medicine__name="Azithromycin 500mg").first()
            self.assertIsNotNone(db_inv)
            self.assertEqual(db_inv.quantity, 35)

    def test_27_pharmacy_api_timeout_fallback(self):
        """Tests that API timeout falls back gracefully without crashing search."""
        import requests
        from medifind.pharmacy_api import PharmacyAPIClient
        self.pharmacy.api_endpoint_url = "https://slow-api.testpharmacy.com/stock"
        self.pharmacy.api_sync_enabled = True
        self.pharmacy.save()

        with patch("requests.get", side_effect=requests.exceptions.Timeout):
            synced = PharmacyAPIClient.query_pharmacy_inventory(self.pharmacy, "Dolo 650")
            self.assertEqual(synced, [])
            self.pharmacy.refresh_from_db()
            self.assertIn("Timeout", self.pharmacy.api_sync_status)

    def test_28_mock_pharmacy_system_api_endpoint(self):
        """Tests that the built-in mock POS API returns real-time JSON catalog."""
        resp = self.client.get("/api/pharmacy-system/mock-inventory/?q=dolo")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertGreaterEqual(data["count"], 1)
        self.assertIn("Dolo", data["items"][0]["medicine_name"])

    def test_29_excel_template_download(self):
        """Tests Excel (.xlsx) and CSV template generation and download."""
        pharmacy_user = User.objects.create_user(username="pharm_owner_tpl", password="password123", email="apollo_tpl@test.com")
        prof = pharmacy_user.userprofile
        prof.role = "Pharmacy"
        prof.pharmacy = self.pharmacy
        prof.verification_status = "Approved"
        prof.save()
        self.client.force_login(pharmacy_user)

        # Excel template
        resp_xlsx = self.client.get("/inventory/template/download/?format=xlsx")
        self.assertEqual(resp_xlsx.status_code, 200)
        self.assertIn("spreadsheetml.sheet", resp_xlsx["Content-Type"])

        # CSV template
        resp_csv = self.client.get("/inventory/template/download/?format=csv")
        self.assertEqual(resp_csv.status_code, 200)
        self.assertIn("text/csv", resp_csv["Content-Type"])
        self.assertIn("Medicine Name", resp_csv.content.decode("utf-8"))

    def test_30_excel_inventory_import(self):
        """Tests batch Excel/CSV file parsing and inventory ingestion."""
        from medifind.excel_service import ExcelInventoryService
        import io

        csv_data = (
            "Medicine Name,Brand,Category,Dosage,Price (INR),Quantity (Stock),Batch Number,Expiry Date,Package Size,SKU Code\n"
            "Amoxicillin 250mg,Novamox,Antibiotic,250mg,45.00,80,AMX-9988,2027-12-31,Strip of 10,AMX250-S10\n"
            "Dolo 650,Micro Labs,Pain Relief,650mg,32.00,120,DOLO-NEW,2028-01-31,Strip of 15,DOLO650-S15\n"
        )
        file_obj = io.StringIO(csv_data)

        result = ExcelInventoryService.import_inventory_file(self.pharmacy, file_obj, filename="inventory.csv")
        self.assertTrue(result["success"])
        self.assertEqual(result["total_processed"], 2)

        # Check DB updates
        amx_inv = Inventory.objects.filter(pharmacy=self.pharmacy, medicine__name="Amoxicillin 250mg").first()
        self.assertIsNotNone(amx_inv)
        self.assertEqual(amx_inv.quantity, 80)
        self.assertEqual(amx_inv.price, Decimal("45.00"))

    def test_31_excel_inventory_export(self):
        """Tests exporting pharmacy inventory into Excel workbook."""
        pharmacy_user = User.objects.create_user(username="pharm_owner_exp", password="password123", email="apollo_exp@test.com")
        prof = pharmacy_user.userprofile
        prof.role = "Pharmacy"
        prof.pharmacy = self.pharmacy
        prof.verification_status = "Approved"
        prof.save()
        self.client.force_login(pharmacy_user)

        resp = self.client.get("/inventory/export/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spreadsheetml.sheet", resp["Content-Type"])

    def test_32_pharmacy_api_settings_management(self):
        """Tests saving API settings and connection testing via endpoint."""
        pharmacy_user = User.objects.create_user(username="pharm_owner_api", password="password123", email="apollo_api@test.com")
        prof = pharmacy_user.userprofile
        prof.role = "Pharmacy"
        prof.pharmacy = self.pharmacy
        prof.verification_status = "Approved"
        prof.save()
        self.client.force_login(pharmacy_user)

        # Save settings
        resp = self.client.post("/pharmacy/api-settings/", data={
            "action": "save",
            "api_endpoint_url": "https://api.mypharmacy.com/stock",
            "api_auth_token": "secret_key_456",
            "api_sync_enabled": "on"
        })
        self.assertEqual(resp.status_code, 302) # Redirects to inventory with flash message
        self.pharmacy.refresh_from_db()
        self.assertEqual(self.pharmacy.api_endpoint_url, "https://api.mypharmacy.com/stock")
        self.assertTrue(self.pharmacy.api_sync_enabled)

    def test_33_add_inventory_redirects_with_notice(self):
        """Tests that legacy add_inventory route redirects to inventory management with guidance."""
        pharmacy_user = User.objects.create_user(username="pharm_owner_add", password="password123", email="apollo_add@test.com")
        prof = pharmacy_user.userprofile
        prof.role = "Pharmacy"
        prof.pharmacy = self.pharmacy
        prof.verification_status = "Approved"
        prof.save()
        self.client.force_login(pharmacy_user)

        resp = self.client.get("/inventory/add/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, "/inventory/")

    def test_34_seo_and_conversion_features(self):
        """Tests that robots.txt, sitemap.xml, thank-you, 404, and schema render properly."""
        # 1. robots.txt
        resp_robots = self.client.get("/robots.txt")
        self.assertEqual(resp_robots.status_code, 200)
        self.assertIn("User-agent: *", resp_robots.content.decode())
        self.assertIn("Sitemap:", resp_robots.content.decode())

        # 2. sitemap.xml
        resp_sitemap = self.client.get("/sitemap.xml")
        self.assertEqual(resp_sitemap.status_code, 200)
        self.assertEqual(resp_sitemap["Content-Type"], "application/xml")
        self.assertIn("<urlset", resp_sitemap.content.decode())
        self.assertIn("/medicines/", resp_sitemap.content.decode())

        # 3. thank-you page
        resp_thanks = self.client.get(f"/thank-you/?ref=TEST999&pharmacy_id={self.pharmacy.id}")
        self.assertEqual(resp_thanks.status_code, 200)
        self.assertContains(resp_thanks, "TEST999")
        self.assertContains(resp_thanks, self.pharmacy.name)

        # 4. 404 page
        resp_404 = self.client.get("/404/")
        self.assertEqual(resp_404.status_code, 404)
        self.assertContains(resp_404, "Page Not Found", status_code=404)

        # 5. Homepage FAQs & Schema
        resp_home = self.client.get("/")
        self.assertEqual(resp_home.status_code, 200)
        self.assertContains(resp_home, "Frequently Asked Questions")
        self.assertContains(resp_home, "Healthcare Impact &amp; Case Studies")
        self.assertContains(resp_home, "Real Reviews from Real Users")
        self.assertContains(resp_home, "Leadership &amp; Clinical Advisory")
        self.assertContains(resp_home, "application/ld+json")

    def test_35_security_and_access_control(self):
        """
        Validates security checklist implementations:
        - Security Headers & Clickjacking defense
        - SSRF protection & Disallowed IPs
        - IDOR / Horizontal Access Control on reservations
        - File upload security validation
        - In-memory / cache sliding window rate limiting
        """
        from .security import is_safe_external_url, is_rate_limited
        from .excel_service import ExcelInventoryService
        import io

        # 1. Security Headers on HTTP response
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Content-Security-Policy", resp.headers)
        self.assertIn("Permissions-Policy", resp.headers)
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(resp.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(resp.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")

        # 2. SSRF Protection
        self.assertFalse(is_safe_external_url("http://127.0.0.1:8000/api"))
        self.assertFalse(is_safe_external_url("http://localhost:5000"))
        self.assertFalse(is_safe_external_url("http://169.254.169.254/latest/meta-data/"))
        self.assertFalse(is_safe_external_url("http://10.0.0.1/api"))
        self.assertFalse(is_safe_external_url("http://192.168.1.1/admin"))
        self.assertFalse(is_safe_external_url("file:///etc/passwd"))
        self.assertTrue(is_safe_external_url("https://api.verifiedpharmacy.com/stock"))
        self.assertTrue(is_safe_external_url("https://pos.apollohospitals.com/v1/inventory"))

        # 3. IDOR / Horizontal Access Control on Reservations
        # Pharmacy User 2 attempts to accept a reservation placed for Pharmacy 1
        other_pharm = Pharmacy.objects.create(
            name="Secure Test Pharmacy 2",
            owner_name="Test Owner",
            phone="9876543999",
            email="secure2@test.com",
            address="45 Mount Road",
            city="Chennai",
            latitude=13.0827,
            longitude=80.2707,
            opening_time="08:00",
            closing_time="22:00"
        )

        cust = User.objects.create_user(username="test_customer_sec", password="Password123!")
        res_test = Reservation.objects.create(
            customer=cust,
            pharmacy=self.pharmacy,
            medicine=self.medicine,
            quantity=1,
            status="Pending"
        )

        other_user = User.objects.create_user(username="other_pharm_user_sec", password="Password123!")
        UserProfile.objects.filter(user=other_user).delete()
        other_prof = UserProfile.objects.create(
            user=other_user,
            role="Pharmacy",
            pharmacy=other_pharm,
            verification_status="Approved"
        )

        self.client.force_login(other_user)
        resp_idor = self.client.get(f"/reservations/{res_test.id}/accept/", follow=True)
        # Should be redirected with error message and NOT accepted
        res_test.refresh_from_db()
        self.assertNotEqual(res_test.status, "Accepted")
        self.assertContains(resp_idor, "Unauthorized")

        # 4. File Upload Security
        fake_exe = io.BytesIO(b"MZ executable contents")
        res = ExcelInventoryService.import_inventory_file(self.pharmacy, fake_exe, filename="payload.exe")
        self.assertFalse(res["success"])
        self.assertIn("Invalid file format", res["message"])

        # 5. Sliding window rate limiter
        key = "test_rate_limit_user"
        for _ in range(5):
            is_rate_limited(key, max_requests=5, window_seconds=10)
        self.assertTrue(is_rate_limited(key, max_requests=5, window_seconds=10))

        # 6. Global Medicine Catalog Delete Protection (Non-superuser gets 403)
        resp_del = self.client.get(f"/medicines/delete/{self.medicine.id}/")
        self.assertEqual(resp_del.status_code, 403)


        # 7. Input Sanitization
        from .security import sanitize_plain_text
        dirty_input = "<script>alert('xss')</script>Dolo 650<b>test</b>"
        clean = sanitize_plain_text(dirty_input)
        self.assertNotIn("<script>", clean)
        self.assertNotIn("<b>", clean)

    def test_36_medifind_ai_search_pipeline(self):
        """
        Tests the full Medifind AI Natural-Language Medicine Search Pipeline across
        13 critical test cases (intent extraction, DB grounding, emergency triage, safety, rate limits).
        """
        from .ai_search import execute_ai_medicine_search_pipeline, extract_search_intent_with_gemini

        # 1. Basic Query
        res_basic = execute_ai_medicine_search_pipeline("Find paracetamol")
        self.assertTrue(res_basic["success"])
        self.assertIn(res_basic["intent"], ["MEDICINE_SEARCH", "AVAILABILITY_SEARCH"])
        self.assertFalse(res_basic["is_emergency"])

        # 2. Brand Query
        res_brand = execute_ai_medicine_search_pipeline("Find Dolo 650")
        self.assertTrue(res_brand["success"])
        self.assertGreaterEqual(res_brand["total_results"], 1)

        # 3. Misspelling Query
        res_typo = execute_ai_medicine_search_pipeline("Find paracetmol")
        self.assertTrue(res_typo["success"])

        # 4. Location Query
        res_loc = execute_ai_medicine_search_pipeline("Find paracetamol near me", user_lat=13.0827, user_lng=80.2707)
        self.assertTrue(res_loc["success"])

        # 5. Radius Query
        res_rad = execute_ai_medicine_search_pipeline("Find Dolo within 2 km")
        self.assertTrue(res_rad["success"])
        self.assertEqual(res_rad["radius_km"], 2.0)

        # 6. Open Pharmacies Query
        res_open = execute_ai_medicine_search_pipeline("Find paracetamol at pharmacies open now")
        self.assertTrue(res_open["success"])

        # 7. Generic Symptom Request (Non-Prescribing Guardrail)
        res_fever = execute_ai_medicine_search_pipeline("Do you have medicine for fever?")
        self.assertTrue(res_fever["success"])
        self.assertFalse(res_fever["is_emergency"])

        # 8. Pharmacy Query
        res_pharm = execute_ai_medicine_search_pipeline("Find pharmacies near me")
        self.assertTrue(res_pharm["success"])

        # 9. Medicine Information
        res_info = execute_ai_medicine_search_pipeline("What is paracetamol?")
        self.assertTrue(res_info["success"])

        # 10. Ambiguous Query
        res_ambig = execute_ai_medicine_search_pipeline("I need medicine")
        self.assertTrue(res_ambig["success"])

        # 11. No Result Query
        res_none = execute_ai_medicine_search_pipeline("Find NonExistentSuperMed123")
        self.assertTrue(res_none["success"])
        self.assertEqual(res_none["total_results"], 0)

        # 12. Emergency Symptom Triage Safety Check
        res_emerg = execute_ai_medicine_search_pipeline("I am having severe chest pain and difficulty breathing")
        self.assertTrue(res_emerg["is_emergency"])
        self.assertIn("112", res_emerg["ai_response"])

        # 13. API Endpoint Security Test (POST /api/ai/search/)
        resp_api = self.client.post("/api/ai/search/", json.dumps({
            "query": "<script>alert(1)</script>Find Dolo 650",
            "latitude": 13.0827,
            "longitude": 80.2707,
            "radius_km": 5
        }), content_type="application/json")
        self.assertEqual(resp_api.status_code, 200)
        data = resp_api.json()
        self.assertTrue(data["success"])
        self.assertNotIn("<script>", data["query"])

    def test_37_medicine_intelligence_and_semantic_understanding(self):
        """
        Tests Medicine Intelligence (AI #3): Normalization, Exact match, Brand/Generic lookup,
        Controlled Fuzzy matching, Unit variations, Ambiguity detection, Rejection of non-existent drugs,
        and Admin Data Quality audit.
        """
        from .medicine_intelligence import MedicineIntelligenceEngine, NormalizationService, DataQualityService
        from .models import Medicine

        # 1. Unit Normalization Tests
        self.assertEqual(NormalizationService.normalize_units("650mg"), "650 mg")
        self.assertEqual(NormalizationService.normalize_units("1g"), "1000 mg")

        # 2. Dosage Form & Strength Extraction Tests
        self.assertEqual(NormalizationService.extract_dosage_form("Paracetamol syrup 200 ml"), "Syrup")
        self.assertEqual(NormalizationService.extract_strength("Dolo 650mg tablet"), "650 mg")

        # 3. Exact & Brand Search Tests
        res_exact = MedicineIntelligenceEngine.understand_query("Dolo 650")
        self.assertIn(res_exact["match_type"], ["EXACT", "BRAND_GENERIC_ALIAS", "SUBSTRING", "FUZZY"])
        self.assertTrue(len(res_exact["matches"]) >= 1)

        # 4. Misspelling & Typos Tests ("paracetmol", "cetrazine")
        res_typo = MedicineIntelligenceEngine.understand_query("paracetmol 650")
        self.assertTrue(len(res_typo["matches"]) >= 1)
        self.assertEqual(res_typo["matches"][0]["name"], "Dolo 650")

        # 5. Ambiguity Detection Test (Searching generic "Dolo" when both Dolo 650 and Dolo 500 exist)
        Medicine.objects.create(name="Dolo 500", brand="Micro Labs", dosage="500 mg", category="Pain Relief")
        res_ambig = MedicineIntelligenceEngine.understand_query("Dolo")
        self.assertTrue(res_ambig["requires_clarification"])
        self.assertIsNotNone(res_ambig["clarification_message"])

        # 6. Non-Existent Drug Rejection & Hallucination Prevention Test
        initial_count = Medicine.objects.count()
        res_halluc = MedicineIntelligenceEngine.understand_query("SuperPain X999")
        self.assertEqual(res_halluc["match_type"], "UNMATCHED")
        self.assertEqual(len(res_halluc["matches"]), 0)
        self.assertEqual(Medicine.objects.count(), initial_count)  # Verified zero fake records created

        # 7. Understand API Endpoint Test
        resp_api = self.client.post("/api/ai/medicine/understand/", json.dumps({
            "query": "cetrazine 10mg"
        }), content_type="application/json")
        self.assertEqual(resp_api.status_code, 200)
        data = resp_api.json()
        self.assertIn("normalized_query", data)

        # 8. Data Quality Audit Service Test
        audit_res = DataQualityService.analyze_catalog_quality()
        self.assertIn("total_medicines", audit_res)

    def test_38_mandatory_prescription_upload_enforcement(self):
        """
        Verifies that prescription-required medicines force the user to upload a valid doctor prescription
        before allowing online payment or store reservation.
        """
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import Medicine, Inventory, Reservation

        # Create prescription-required medicine & inventory
        rx_med = Medicine.objects.create(
            name="Augmentin 625 Duo",
            brand="GSK",
            dosage="625 mg",
            category="Antibiotic",
            prescription_required=True
        )
        rx_inv = Inventory.objects.create(
            medicine=rx_med,
            pharmacy=self.pharmacy,
            quantity=20,
            price=Decimal("150.00"),
            batch_number="BATCH123",
            expiry_date=timezone.now().date() + timezone.timedelta(days=365)
        )

        user = User.objects.create_user(username="rx_patient", password="password123")
        self.client.force_login(user)

        # 1. Attempt reservation WITHOUT uploading prescription -> Expect HTTP 400 rejection
        resp_reject = self.client.post(f"/reserve/{rx_inv.id}/", {
            "quantity": 1,
            "payment_method": "Online",
            "notes": "Test without prescription"
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp_reject.status_code, 400)
        data_rej = resp_reject.json()
        self.assertFalse(data_rej["success"])
        self.assertIn("prescription", data_rej["message"].lower())

        # 2. Attempt reservation WITH valid prescription image -> Expect HTTP 200 success
        fake_rx_file = SimpleUploadedFile("rx_doctor_note.png", b"\x89PNG\r\n\x1a\nvalid png bytes", content_type="image/png")
        resp_success = self.client.post(f"/reserve/{rx_inv.id}/", {
            "quantity": 1,
            "payment_method": "Online",
            "notes": "Test with prescription",
            "prescription_file": fake_rx_file
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(resp_success.status_code, 200)
        data_succ = resp_success.json()
        self.assertTrue(data_succ["success"])

        # 3. Verify Database state
        rx_obj = Reservation.objects.filter(customer=user, medicine=rx_med).first()
        self.assertIsNotNone(rx_obj)
        self.assertTrue(rx_obj.prescription_uploaded)

    def test_39_predictive_inventory_and_demand_forecasting(self):
        """
        Comprehensive test for Medifind AI #4 — Predictive Inventory & Medicine Demand Intelligence.
        Tests data snapshot sync, deterministic forecasting models (SMA/EWMA), backtesting metrics,
        stock risk classification, days of cover, security data isolation, and API endpoints.
        """
        from .inventory_intelligence import (
            DemandDataService,
            TimeSeriesForecastingEngine,
            StockRiskEngine,
            AIInventoryExplanationService
        )
        from .models import Pharmacy, Medicine, Inventory, Reservation, DailyDemandSnapshot, UserProfile

        # 1. Setup Pharmacy owner & test inventory
        pharm_user = User.objects.create_user(username="pharm_manager", password="password123")
        prof = pharm_user.userprofile
        prof.role = "Pharmacy"
        prof.pharmacy = self.pharmacy
        prof.save()
        self.client.force_login(pharm_user)

        med_dolo = Medicine.objects.create(name="Dolo 650", brand="Micro Labs", category="Fever & Cold", dosage="650 mg")
        inv_dolo = Inventory.objects.create(
            pharmacy=self.pharmacy,
            medicine=med_dolo,
            quantity=15,
            price=Decimal("30.00"),
            minimum_stock=10,
            batch_number="B100",
            expiry_date=timezone.now().date() + timezone.timedelta(days=365)
        )

        # 2. Seed past reservations (actual sales history)
        today = timezone.now().date()
        for d_offset in range(1, 10):
            Reservation.objects.create(
                customer=pharm_user,
                pharmacy=self.pharmacy,
                medicine=med_dolo,
                quantity=4,
                status="Collected",
                payment_method="Online",
                is_paid=True,
                requested_at=timezone.now() - timezone.timedelta(days=d_offset)
            )

        # 3. Test DemandDataService sync
        synced_count = DemandDataService.sync_daily_snapshots(self.pharmacy, days_back=15)
        self.assertGreater(synced_count, 0)
        ts_data = DemandDataService.get_timeseries_data(self.pharmacy, med_dolo, days=15)
        self.assertEqual(len(ts_data), 16)

        # 4. Test TimeSeriesForecastingEngine Evaluation & Confidence Intervals
        forecast = TimeSeriesForecastingEngine.generate_forecast(self.pharmacy, med_dolo, horizon_days=7)
        self.assertEqual(forecast["horizon_days"], 7)
        self.assertGreater(forecast["predicted_demand"], 0.0)
        self.assertGreaterEqual(forecast["upper_bound"], forecast["predicted_demand"])
        self.assertLessEqual(forecast["lower_bound"], forecast["predicted_demand"])

        # 5. Test StockRiskEngine Days of Cover & Reorder Point
        risk_info = StockRiskEngine.analyze_inventory_risk(inv_dolo, forecast)
        self.assertIn(risk_info["risk_level"], ["CRITICAL", "HIGH", "MODERATE", "LOW"])
        self.assertIsNotNone(risk_info["days_of_cover"])
        self.assertIn("reorder_recommended", risk_info)

        # 6. Test Cold Start Handling for New SKU
        new_med = Medicine.objects.create(name="RareDrug 50mg", brand="PharmaCo", category="General Health", dosage="50 mg")
        new_inv = Inventory.objects.create(
            pharmacy=self.pharmacy,
            medicine=new_med,
            quantity=50,
            price=Decimal("500.00"),
            batch_number="B999",
            expiry_date=timezone.now().date() + timezone.timedelta(days=365)
        )
        cold_forecast = TimeSeriesForecastingEngine.generate_forecast(self.pharmacy, new_med, horizon_days=7)
        self.assertTrue(cold_forecast["is_cold_start"])
        self.assertEqual(cold_forecast["model_name"], "ColdStart_Baseline")

        # 7. Test Pharmacy Inventory Insights API Endpoint
        resp_insights = self.client.get("/api/pharmacy/ai/inventory-insights/")
        self.assertEqual(resp_insights.status_code, 200)
        data_ins = resp_insights.json()
        self.assertTrue(data_ins["success"])
        self.assertIn("risk_summary", data_ins)
        self.assertGreaterEqual(data_ins["total_medicines"], 2)

        # 8. Test Single SKU Demand Forecast API Endpoint
        resp_single = self.client.get(f"/api/pharmacy/ai/demand-forecast/{med_dolo.id}/")
        self.assertEqual(resp_single.status_code, 200)
        data_single = resp_single.json()
        self.assertTrue(data_single["success"])
        self.assertIn("explanation", data_single)
        self.assertIn("historical_timeseries", data_single)

        # 9. Test Security & Data Isolation (Other Pharmacy User Rejection)
        other_pharm = Pharmacy.objects.create(
            name="Other Pharmacy",
            owner_name="Other",
            phone="9998887776",
            address="Other St",
            city="Chennai",
            state="TN",
            pincode="600002",
            latitude=Decimal("13.0800"),
            longitude=Decimal("80.2700"),
            opening_time=timezone.now().time(),
            closing_time=timezone.now().time()
        )
        other_user = User.objects.create_user(username="other_mgr", password="password123")
        other_prof = other_user.userprofile
        other_prof.role = "Pharmacy"
        other_prof.pharmacy = other_pharm
        other_prof.save()
        self.client.force_login(other_user)

        resp_sec = self.client.get(f"/api/pharmacy/ai/demand-forecast/{med_dolo.id}/")
        self.assertEqual(resp_sec.status_code, 404)  # SKU not found in other pharmacy inventory

        # 10. Test Retraining Model API Endpoint
        admin_user = User.objects.create_superuser(username="superadmin", password="password123")
        self.client.force_login(admin_user)

        resp_retrain = self.client.post("/api/pharmacy/ai/retrain/", {"pharmacy_id": self.pharmacy.id})
        self.assertEqual(resp_retrain.status_code, 200)
        data_retrain = resp_retrain.json()
        self.assertTrue(data_retrain["success"])
        self.assertIn("model_version", data_retrain)

        # 11. Test Admin Model Performance View
        resp_admin_perf = self.client.get("/admin/ai-model-performance/")
        self.assertEqual(resp_admin_perf.status_code, 200)


















