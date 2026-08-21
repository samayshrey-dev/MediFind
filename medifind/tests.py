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




