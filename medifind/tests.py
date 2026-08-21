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
        self.assertContains(resp_get, "Pay on the Pharmacy There")


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
        from unittest.mock import patch

        # Mock Gemini API throwing exception
        with patch("google.generativeai.GenerativeModel") as mock_model:
            mock_instance = MagicMock()
            mock_instance.generate_content.side_effect = Exception("Google AI API rate limit / 503 service unavailable")
            mock_model.return_value = mock_instance

            # Intent parsing falls back to deterministic rule-based NLP
            intent = IntentParser.parse_with_ai("Find the cheapest Dolo 650 within 5 km")
            self.assertEqual(intent["medicine_query"], "Dolo 650")
            self.assertEqual(intent["max_distance_km"], 5.0)

            # Database candidate search executes normally
            candidates = CommerceSearchService.search_candidates(intent, user_lat=13.0827, user_lng=80.2707)
            self.assertGreaterEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["medicine_name"], "Dolo 650")







