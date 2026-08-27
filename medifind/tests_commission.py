from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from medifind.models import Pharmacy, Medicine, Inventory, Order, Reservation, AgentAuditLog
from medifind.commerce_service import AgenticCommerceService, CommerceError


class MediAICommissionSystemTests(TestCase):
    """
    Test suite for MediAI Pharmacy Transaction Commission System.
    Validates 3% default rate, custom per-pharmacy rates, revenue recognition on payment,
    voiding on payment failure/cancellation, and Pharmacy/Admin Dashboards.
    """

    def setUp(self):
        # Default 3% Commission Pharmacy
        self.pharmacy_default = Pharmacy.objects.create(
            name="Apollo Pharmacy Velachery",
            owner_name="Ramesh",
            phone="9876543210",
            email="apollo@test.com",
            address="100 Feet Rd",
            city="Chennai",
            state="Tamil Nadu",
            pincode="600042",
            latitude=Decimal("12.9780"),
            longitude=Decimal("80.2200"),
            opening_time="08:00:00",
            closing_time="22:00:00",
            is_active=True,
            commission_rate=Decimal("3.00")
        )

        # Custom 5% Commission Pharmacy
        self.pharmacy_custom = Pharmacy.objects.create(
            name="Health & Glow Chemist",
            owner_name="Suresh",
            phone="9876543211",
            email="healthandglow@test.com",
            address="Velachery Main Rd",
            city="Chennai",
            state="Tamil Nadu",
            pincode="600042",
            latitude=Decimal("12.9790"),
            longitude=Decimal("80.2210"),
            opening_time="08:00:00",
            closing_time="22:00:00",
            is_active=True,
            commission_rate=Decimal("5.00")
        )

        self.medicine = Medicine.objects.create(
            name="Crocin 650",
            brand="GSK",
            category="Fever & Cold",
            dosage="650mg",
            description="Pain and fever reliever",
            uses="Fever, Headache",
            side_effects="Nausea",
            prescription_required=False
        )

        self.inv_default = Inventory.objects.create(
            pharmacy=self.pharmacy_default,
            medicine=self.medicine,
            quantity=100,
            price=Decimal("100.00"),
            expiry_date=timezone.now().date() + timedelta(days=180)
        )

        self.inv_custom = Inventory.objects.create(
            pharmacy=self.pharmacy_custom,
            medicine=self.medicine,
            quantity=100,
            price=Decimal("500.00"),
            expiry_date=timezone.now().date() + timedelta(days=180)
        )

        self.customer = User.objects.create_user(
            username="testuser",
            password="testpassword123",
            email="customer@test.com"
        )

        self.merchant = User.objects.create_user(
            username="merchantuser",
            password="merchantpassword123",
            email="merchant@test.com"
        )
        self.merchant.userprofile.role = "Pharmacy"
        self.merchant.userprofile.pharmacy = self.pharmacy_default
        self.merchant.userprofile.save()

        self.admin_user = User.objects.create_superuser(
            username="adminuser",
            password="adminpassword123",
            email="admin@test.com"
        )

    def test_01_default_3_percent_commission_calculation(self):
        """Order of ₹500 at default 3% rate calculates ₹15.00 commission & ₹485.00 net pharmacy payout."""
        # inv_default price is ₹100. Quantity = 5 -> Total ₹500
        order = AgenticCommerceService.create_transaction_snapshot(
            session_id="sess_comm_3pct",
            inventory_id=self.inv_default.id,
            quantity=5,
            user=self.customer
        )

        self.assertEqual(order.total_amount, Decimal("500.00"))
        self.assertEqual(order.commission_rate, Decimal("3.00"))
        self.assertEqual(order.commission_amount, Decimal("15.00"))
        self.assertEqual(order.net_pharmacy_amount, Decimal("485.00"))
        self.assertEqual(order.commission_status, "PENDING")

        # Verify audit trail
        audit = AgentAuditLog.objects.filter(session_id="sess_comm_3pct", event_type="commission_calculated").first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.payload["commission_amount"], 15.00)
        self.assertEqual(audit.payload["net_pharmacy_amount"], 485.00)

    def test_02_custom_pharmacy_commission_rate(self):
        """Order of ₹1000 at custom 5% rate calculates ₹50.00 commission & ₹950.00 net pharmacy payout."""
        # inv_custom price is ₹500. Quantity = 2 -> Total ₹1000
        order = AgenticCommerceService.create_transaction_snapshot(
            session_id="sess_comm_5pct",
            inventory_id=self.inv_custom.id,
            quantity=2,
            user=self.customer
        )

        self.assertEqual(order.total_amount, Decimal("1000.00"))
        self.assertEqual(order.commission_rate, Decimal("5.00"))
        self.assertEqual(order.commission_amount, Decimal("50.00"))
        self.assertEqual(order.net_pharmacy_amount, Decimal("950.00"))
        self.assertEqual(order.commission_status, "PENDING")

    def test_03_successful_payment_finalizes_commission(self):
        """Commission becomes FINALIZED upon successful Razorpay payment verification."""
        order = AgenticCommerceService.create_transaction_snapshot(
            session_id="sess_success_pay",
            inventory_id=self.inv_default.id,
            quantity=5,
            user=self.customer
        )

        rzp_order = AgenticCommerceService.create_razorpay_test_order(order.order_reference, user=self.customer)

        result = AgenticCommerceService.verify_payment_signature(
            order_reference=order.order_reference,
            razorpay_order_id=rzp_order["razorpay_order_id"],
            razorpay_payment_id="pay_test_succ_123",
            razorpay_signature="dummy_sig_valid",
            user=self.customer
        )

        self.assertTrue(result["success"])
        order.refresh_from_db()
        self.assertEqual(order.status, "PAID")
        self.assertEqual(order.commission_status, "FINALIZED")

        # Verify Audit Log
        audit = AgentAuditLog.objects.filter(session_id="sess_success_pay", event_type="commission_finalized").first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.state, "FINALIZED")
        self.assertEqual(audit.payload["commission_amount"], 15.00)

    def test_04_failed_payment_voids_commission(self):
        """Failed payment signature voids the commission revenue (status = VOIDED)."""
        order = AgenticCommerceService.create_transaction_snapshot(
            session_id="sess_failed_pay",
            inventory_id=self.inv_default.id,
            quantity=2,
            user=self.customer
        )

        result = AgenticCommerceService.verify_payment_signature(
            order_reference=order.order_reference,
            razorpay_order_id="order_fake_123",
            razorpay_payment_id="pay_fake_456",
            razorpay_signature="invalid_signature_test",
            user=self.customer
        )

        self.assertFalse(result["success"])
        order.refresh_from_db()
        self.assertEqual(order.status, "PAYMENT_FAILED")
        self.assertEqual(order.commission_status, "VOIDED")

        # Verify Audit Log
        audit = AgentAuditLog.objects.filter(session_id="sess_failed_pay", event_type="commission_voided").first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.state, "VOIDED")

    def test_05_cancelled_order_voids_commission(self):
        """Checkout dismissal or cancellation marks commission as VOIDED."""
        order = AgenticCommerceService.create_transaction_snapshot(
            session_id="sess_cancel",
            inventory_id=self.inv_default.id,
            quantity=1,
            user=self.customer
        )

        res = AgenticCommerceService.record_payment_failure(
            order_reference=order.order_reference,
            reason="User closed payment modal",
            user=self.customer
        )

        self.assertTrue(res["success"])
        order.refresh_from_db()
        self.assertEqual(order.status, "PAYMENT_FAILED")
        self.assertEqual(order.commission_status, "VOIDED")

    def test_06_pharmacy_dashboard_commission_metrics(self):
        """Pharmacy dashboard context accurately reflects Total Sales, MediAI Commission, and Net Revenue."""
        # Create 2 finalized paid orders: ₹500 (comm ₹15, net ₹485) and ₹200 (comm ₹6, net ₹194)
        o1 = AgenticCommerceService.create_transaction_snapshot("sess_dash_1", self.inv_default.id, quantity=5)
        rzp1 = AgenticCommerceService.create_razorpay_test_order(o1.order_reference)
        AgenticCommerceService.verify_payment_signature(o1.order_reference, rzp1["razorpay_order_id"], "pay_d1", "sig_d1")

        o2 = AgenticCommerceService.create_transaction_snapshot("sess_dash_2", self.inv_default.id, quantity=2)
        rzp2 = AgenticCommerceService.create_razorpay_test_order(o2.order_reference)
        AgenticCommerceService.verify_payment_signature(o2.order_reference, rzp2["razorpay_order_id"], "pay_d2", "sig_d2")

        client = Client()
        client.login(username="merchantuser", password="merchantpassword123")
        response = client.get("/pharmacy-dashboard/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_sales_gmv"], Decimal("700.00"))
        self.assertEqual(response.context["mediai_commission_total"], Decimal("21.00"))
        self.assertEqual(response.context["net_pharmacy_revenue_total"], Decimal("679.00"))
        self.assertEqual(response.context["completed_orders_count"], 2)

    def test_07_admin_revenue_dashboard_view(self):
        """Admin revenue dashboard calculates total GMV, platform commission, net payouts, and pharmacy breakdown."""
        # Store 1 (3%): ₹500 -> comm ₹15, net ₹485
        o1 = AgenticCommerceService.create_transaction_snapshot("sess_adm_1", self.inv_default.id, quantity=5)
        rzp1 = AgenticCommerceService.create_razorpay_test_order(o1.order_reference)
        AgenticCommerceService.verify_payment_signature(o1.order_reference, rzp1["razorpay_order_id"], "pay_a1", "sig_a1")

        # Store 2 (5%): ₹1000 -> comm ₹50, net ₹950
        o2 = AgenticCommerceService.create_transaction_snapshot("sess_adm_2", self.inv_custom.id, quantity=2)
        rzp2 = AgenticCommerceService.create_razorpay_test_order(o2.order_reference)
        AgenticCommerceService.verify_payment_signature(o2.order_reference, rzp2["razorpay_order_id"], "pay_a2", "sig_a2")

        client = Client()
        client.login(username="adminuser", password="adminpassword123")
        response = client.get("/admin/revenue-dashboard/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["gross_gmv"], Decimal("1500.00"))
        self.assertEqual(response.context["total_commission"], Decimal("65.00"))
        self.assertEqual(response.context["total_net_payout"], Decimal("1435.00"))
        self.assertEqual(response.context["completed_count"], 2)
