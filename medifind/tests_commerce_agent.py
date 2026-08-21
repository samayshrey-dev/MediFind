import os
from django.test import TestCase
from django.contrib.auth.models import User
from medifind.models import Medicine, Pharmacy, Inventory, AgentAuditLog
from medifind.commerce_agent import (
    IntentParser,
    CommerceSearchService,
    DeterministicRankingEngine,
    RecommendationExplainer,
    AgentAuditService,
    AICommerceAgent,
    AgentState,
    OptimizationGoal,
    MEDICAL_SAFETY_DISCLAIMER
)


class AICommerceAgentTests(TestCase):
    """
    Test suite verifying all 10 required AI Commerce Agent scenarios.
    """

    def setUp(self):
        # Create test pharmacies with real coordinates
        self.pharmacy_a = Pharmacy.objects.create(
            name="Apollo Pharmacy Anna Nagar",
            owner_name="Apollo Admin",
            phone="9876543210",
            address="12 Main St, Anna Nagar",
            city="Chennai",
            state="Tamil Nadu",
            pincode="600040",
            latitude=13.08784,
            longitude=80.21026,
            opening_time="08:00:00",
            closing_time="23:00:00",
            is_active=True,
            is_open=True
        )

        self.pharmacy_b = Pharmacy.objects.create(
            name="MedPlus Velachery",
            owner_name="MedPlus Admin",
            phone="9876543211",
            address="45 Velachery Bypass",
            city="Chennai",
            state="Tamil Nadu",
            pincode="600042",
            latitude=12.98153,
            longitude=80.21801,
            opening_time="08:00:00",
            closing_time="22:00:00",
            is_active=True,
            is_open=True
        )

        self.pharmacy_c = Pharmacy.objects.create(
            name="Guardian Pharmacy T Nagar",
            owner_name="Guardian Admin",
            phone="9876543212",
            address="78 North Usman Rd",
            city="Chennai",
            state="Tamil Nadu",
            pincode="600017",
            latitude=13.0418,
            longitude=80.2333,
            opening_time="09:00:00",
            closing_time="21:00:00",
            is_active=True,
            is_open=True
        )

        # Create test medicines
        self.dolo_650 = Medicine.objects.create(
            name="Dolo 650",
            brand="Micro Labs",
            category="Pain Relief",
            dosage="650mg Tablet",
            description="Paracetamol 650mg for fever and pain relief",
            uses="Fever, headache, body pain",
            side_effects="Nausea if overdosed",
            prescription_required=False
        )

        self.dolo_generic = Medicine.objects.create(
            name="Dolo",
            brand="Micro Labs",
            category="Pain Relief",
            dosage="500mg Tablet",
            description="Paracetamol generic",
            uses="Fever relief",
            side_effects="None",
            prescription_required=False
        )

        self.paracetamol_500 = Medicine.objects.create(
            name="Paracetamol 500",
            brand="Cipla",
            category="Pain Relief",
            dosage="500mg Tablet",
            description="Paracetamol 500mg",
            uses="Fever and pain",
            side_effects="None",
            prescription_required=False
        )

        # Add Inventory
        # Apollo: Dolo 650 @ Rs 22 (Stock: 12)
        self.inv_a = Inventory.objects.create(
            medicine=self.dolo_650,
            pharmacy=self.pharmacy_a,
            quantity=12,
            price=22.00,
            batch_number="BATCH-001",
            expiry_date="2027-12-31"
        )

        # MedPlus: Dolo 650 @ Rs 28 (Stock: 25)
        self.inv_b = Inventory.objects.create(
            medicine=self.dolo_650,
            pharmacy=self.pharmacy_b,
            quantity=25,
            price=28.00,
            batch_number="BATCH-002",
            expiry_date="2027-12-31"
        )

        # Guardian: Dolo 650 @ Rs 25 (Stock: 8)
        self.inv_c = Inventory.objects.create(
            medicine=self.dolo_650,
            pharmacy=self.pharmacy_c,
            quantity=8,
            price=25.00,
            batch_number="BATCH-003",
            expiry_date="2027-12-31"
        )

        # Test User
        self.user = User.objects.create_user(
            username="testuser",
            password="password123"
        )

    # -------------------------------------------------------------
    # Test 1: "I need Dolo 650 within 5 km."
    # -------------------------------------------------------------
    def test_scenario_1_medicine_and_radius_identified(self):
        query = "I need Dolo 650 within 5 km."
        intent = IntentParser.local_fallback_parser(query)
        self.assertEqual(intent["medicine_query"], "Dolo 650")
        self.assertEqual(intent["max_distance_km"], 5.0)
        self.assertEqual(intent["generic_name"], "Paracetamol")

    # -------------------------------------------------------------
    # Test 2: "Find the cheapest Dolo 650 near me."
    # -------------------------------------------------------------
    def test_scenario_2_lowest_price_optimization(self):
        query = "Find the cheapest Dolo 650 near me."
        intent = IntentParser.local_fallback_parser(query)
        self.assertEqual(intent["optimization_goal"], OptimizationGoal.LOWEST_PRICE)

        # Rank candidates deterministically
        user_lat, user_lng = 13.08784, 80.21026
        candidates = CommerceSearchService.search_candidates(intent, user_lat, user_lng)
        ranked = DeterministicRankingEngine.rank_candidates(candidates, OptimizationGoal.LOWEST_PRICE)

        # Best option should be Apollo Pharmacy (Rs 22.00)
        self.assertEqual(ranked[0]["pharmacy_name"], "Apollo Pharmacy Anna Nagar")
        self.assertEqual(ranked[0]["price"], 22.00)

    # -------------------------------------------------------------
    # Test 3: "Find the closest pharmacy with Dolo 650."
    # -------------------------------------------------------------
    def test_scenario_3_closest_optimization(self):
        query = "Find the closest pharmacy with Dolo 650."
        intent = IntentParser.local_fallback_parser(query)
        self.assertEqual(intent["optimization_goal"], OptimizationGoal.CLOSEST)

        # Near Anna Nagar coordinates
        user_lat, user_lng = 13.08700, 80.21000
        candidates = CommerceSearchService.search_candidates(intent, user_lat, user_lng)
        ranked = DeterministicRankingEngine.rank_candidates(candidates, OptimizationGoal.CLOSEST)

        # Closest to Anna Nagar should be Apollo Pharmacy
        self.assertEqual(ranked[0]["pharmacy_name"], "Apollo Pharmacy Anna Nagar")
        self.assertLess(ranked[0]["distance_km"], 1.0)

    # -------------------------------------------------------------
    # Test 4: "I need it urgently."
    # -------------------------------------------------------------
    def test_scenario_4_fastest_optimization(self):
        query = "I need it urgently."
        intent = IntentParser.local_fallback_parser(query)
        self.assertEqual(intent["optimization_goal"], OptimizationGoal.FASTEST)

    # -------------------------------------------------------------
    # Test 5: "Find Dolo." (Ambiguity detection)
    # -------------------------------------------------------------
    def test_scenario_5_ambiguity_clarification(self):
        query = "Find Dolo."
        intent = IntentParser.local_fallback_parser(query)
        self.assertTrue(intent["needs_clarification"])
        self.assertEqual(intent["confidence"], "low")
        self.assertIn("Did you mean Dolo 650 or another Dolo variant?", intent["clarification_message"])

    # -------------------------------------------------------------
    # Test 6: "Find something for fever." (Medical safety guardrail)
    # -------------------------------------------------------------
    def test_scenario_6_medical_safety_guardrail(self):
        query = "I have fever, what should I take?"
        intent = IntentParser.local_fallback_parser(query)
        self.assertTrue(intent["needs_clarification"])
        self.assertIsNotNone(intent["medical_safety_warning"])
        self.assertIn("can't diagnose or prescribe", intent["clarification_message"])

    # -------------------------------------------------------------
    # Test 7: No pharmacies have stock
    # -------------------------------------------------------------
    def test_scenario_7_out_of_stock_handling(self):
        # Set all inventory quantity to 0
        Inventory.objects.all().update(quantity=0)

        intent = {"medicine_query": "Dolo 650", "generic_name": "Paracetamol"}
        candidates = CommerceSearchService.search_candidates(intent)
        self.assertEqual(len(candidates), 0)

        explanation = RecommendationExplainer.generate_explanation(None, OptimizationGoal.LOWEST_PRICE)
        self.assertEqual(explanation, "No nearby pharmacy currently shows this medicine in stock.")

    # -------------------------------------------------------------
    # Test 8: AI API unavailable (Graceful local fallback)
    # -------------------------------------------------------------
    def test_scenario_8_fallback_parser(self):
        # Ensure fallback executes without errors even with empty API key
        intent = IntentParser.parse_with_ai("Dolo 650 within 3 km cheapest")
        self.assertEqual(intent["medicine_query"], "Dolo 650")
        self.assertEqual(intent["max_distance_km"], 3.0)
        self.assertEqual(intent["optimization_goal"], OptimizationGoal.LOWEST_PRICE)

    # -------------------------------------------------------------
    # Test 9: Location unavailable
    # -------------------------------------------------------------
    def test_scenario_9_location_unavailable_prompt(self):
        res = AICommerceAgent.execute_search_flow(
            query="Find Dolo 650 within 5 km",
            user_lat=None,
            user_lng=None
        )
        self.assertTrue(res["location_needed"])
        self.assertIn("enable location access", res["location_message"])

    # -------------------------------------------------------------
    # Test 10: User asks to buy & Approval gate (No payment charged)
    # -------------------------------------------------------------
    def test_scenario_10_user_approval_gate(self):
        # 1. Execute Search Flow
        res = AICommerceAgent.execute_search_flow(
            query="I need Dolo 650 within 5 km",
            user_lat=13.08784,
            user_lng=80.21026,
            user=self.user
        )
        self.assertEqual(res["state"], AgentState.AWAITING_APPROVAL)
        self.assertIsNotNone(res["best_match"])
        self.assertEqual(res["approval_gate"]["status"], "AWAITING_APPROVAL")

        # 2. Trigger User Approval Gate
        best_inv_id = res["best_match"]["inventory_id"]
        approval_res = AICommerceAgent.handle_user_approval(
            session_id=res["session_id"],
            inventory_id=best_inv_id,
            user=self.user
        )

        self.assertTrue(approval_res["success"])
        self.assertEqual(approval_res["state"], AgentState.APPROVED)
        self.assertEqual(approval_res["next_phase"], "RAZORPAY_PAYMENT_INITIATION")
        self.assertIn("Purchase approved", approval_res["approval_message"])

        # Check Audit Log was recorded
        logs = AgentAuditLog.objects.filter(session_id=res["session_id"])
        self.assertGreaterEqual(logs.count(), 5)
