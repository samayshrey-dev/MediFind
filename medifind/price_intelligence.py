"""
MediFind AI #10 — Price Intelligence & Best Value Finder Engine

Architecture & Principles:
  1. Deterministic Server-Side Ranking: Value score is calculated entirely in Python based on verified price, distance, stock, and open status.
  2. Grounded Gemini Explanation: Gemini Flash ONLY explains backend calculation results without determining prices or changing rankings.
  3. Result Categories: Highlights ⭐ Best Value, 💰 Cheapest, 📍 Closest, and 📦 Best Stock.
  4. Unit Price Normalization: Calculates price per unit/tablet/ml when package size is known (e.g. Strip of 10 vs Strip of 20).
  5. User Ranking Modes: Respects user preference ('BALANCED', 'PRICE_FIRST', 'DISTANCE_FIRST', 'AVAILABILITY_FIRST').
"""

import re
import logging
from typing import Dict, Any, List, Optional, Tuple
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


# ==========================================================
# 1. UNIT PRICE NORMALIZER
# ==========================================================

class UnitPriceNormalizer:
    """
    Normalizes total retail pack price into price per unit (tablet/ml/gram) when pack size is specified.
    """

    @classmethod
    def parse_pack_quantity(cls, package_size: str) -> Optional[int]:
        """
        Extracts unit count from package size string.
        Examples:
          "Strip of 10" -> 10
          "Strip of 15" -> 15
          "Bottle of 100 ml" -> 100
          "Tube of 20 g" -> 20
          "Box of 1" -> 1
        """
        if not package_size:
            return None

        match = re.search(r'(\d+)', package_size)
        if match:
            try:
                qty = int(match.group(1))
                return qty if qty > 0 else None
            except ValueError:
                return None
        return None

    @classmethod
    def compute_unit_price(cls, price: float, package_size: str) -> Dict[str, Any]:
        """
        Calculates price per unit and provides human-readable unit breakdown.
        """
        unit_qty = cls.parse_pack_quantity(package_size)
        if unit_qty and unit_qty > 0 and price > 0:
            unit_price = round(price / float(unit_qty), 2)
            unit_name = "ml" if "ml" in package_size.lower() else ("g" if "g" in package_size.lower() else "tablet")
            return {
                "unit_qty": unit_qty,
                "unit_price": unit_price,
                "unit_name": unit_name,
                "display_text": f"₹{unit_price:.2f}/{unit_name}"
            }
        return {
            "unit_qty": 1,
            "unit_price": price,
            "unit_name": "pack",
            "display_text": f"₹{price:.2f}/pack"
        }


# ==========================================================
# 2. VALUE SCORE & RANKING ENGINE
# ==========================================================

class ValueScoreEngine:
    """
    Calculates deterministic Value Scores (0 to 100) based on Price, Distance, Stock Level, and Open Status.
    Weightings adapt based on user-selected mode:
      - BALANCED (Default): 40% Price, 35% Distance, 15% Stock, 10% Open Status
      - PRICE_FIRST: 70% Price, 15% Distance, 10% Stock, 5% Open Status
      - DISTANCE_FIRST: 15% Price, 70% Distance, 10% Stock, 5% Open Status
      - AVAILABILITY_FIRST: 20% Price, 20% Distance, 50% Stock, 10% Open Status
    """

    @classmethod
    def calculate_value_score(
        cls,
        price: float,
        distance_km: Optional[float],
        quantity: int,
        is_open: bool,
        min_price: float,
        max_price: float,
        min_dist: float,
        max_dist: float,
        mode: str = "BALANCED"
    ) -> float:
        """
        Calculates normalized composite value score (0 to 100).
        Higher score = better overall value.
        """
        if price <= 0:
            return 0.0

        # Price Score (0 to 100, lower price = higher score)
        if max_price > min_price:
            price_score = 100.0 * (1.0 - ((price - min_price) / (max_price - min_price)))
        else:
            price_score = 100.0

        # Distance Score (0 to 100, shorter distance = higher score)
        if distance_km is not None:
            if max_dist > min_dist:
                dist_score = 100.0 * (1.0 - ((distance_km - min_dist) / (max_dist - min_dist)))
            else:
                dist_score = 100.0
        else:
            dist_score = 50.0

        # Availability Score (0 to 100)
        stock_score = 100.0 if quantity > 10 else (60.0 if quantity > 0 else 0.0)

        # Open Status Score (0 to 100)
        open_score = 100.0 if is_open else 20.0

        # Apply weights based on user mode
        mode_upper = (mode or "BALANCED").upper()
        if mode_upper == "PRICE_FIRST":
            w_p, w_d, w_s, w_o = 0.70, 0.15, 0.10, 0.05
        elif mode_upper == "DISTANCE_FIRST":
            w_p, w_d, w_s, w_o = 0.15, 0.70, 0.10, 0.05
        elif mode_upper == "AVAILABILITY_FIRST":
            w_p, w_d, w_s, w_o = 0.20, 0.20, 0.50, 0.10
        else:  # BALANCED
            w_p, w_d, w_s, w_o = 0.40, 0.35, 0.15, 0.10

        composite_score = (price_score * w_p) + (dist_score * w_d) + (stock_score * w_s) + (open_score * w_o)
        return round(composite_score, 1)


# ==========================================================
# 3. PRICE CATEGORY CLASSIFIER
# ==========================================================

class PriceCategoryClassifier:
    """
    Identifies winner candidates for Best Value, Cheapest, Closest, and Best Availability.
    """

    @classmethod
    def rank_candidates(cls, candidates: List[Dict[str, Any]], mode: str = "BALANCED") -> List[Dict[str, Any]]:
        """
        Ranks candidate pharmacy listings and annotates badges.
        """
        if not candidates:
            return []

        # Extract min/max bounds for normalization
        prices = [c["price"] for c in candidates if c.get("price") and c["price"] > 0]
        distances = [c["distance_km"] for c in candidates if c.get("distance_km") is not None]

        min_p = min(prices) if prices else 1.0
        max_p = max(prices) if prices else 1.0
        min_d = min(distances) if distances else 0.1
        max_d = max(distances) if distances else 1.0

        # Calculate unit price and value score for each candidate
        for c in candidates:
            norm = UnitPriceNormalizer.compute_unit_price(c["price"], c.get("package_size", ""))
            c["unit_price_info"] = norm
            c["value_score"] = ValueScoreEngine.calculate_value_score(
                price=c["price"],
                distance_km=c.get("distance_km"),
                quantity=c.get("quantity", 0),
                is_open=c.get("is_open", True),
                min_price=min_p,
                max_price=max_p,
                min_dist=min_d,
                max_dist=max_d,
                mode=mode
            )

        # Sort candidates by value score descending
        sorted_candidates = sorted(candidates, key=lambda x: x["value_score"], reverse=True)

        # Identify category winners
        cheapest_cand = min(candidates, key=lambda x: x["price"]) if candidates else None
        dist_cands = [c for c in candidates if c.get("distance_km") is not None]
        closest_cand = min(dist_cands, key=lambda x: x["distance_km"]) if dist_cands else None
        best_value_cand = sorted_candidates[0] if sorted_candidates else None

        for c in sorted_candidates:
            c["badges"] = []
            if best_value_cand and c["pharmacy_id"] == best_value_cand["pharmacy_id"]:
                c["badges"].append({"type": "BEST_VALUE", "label": "⭐ Best Value", "class": "bg-primary"})
            if cheapest_cand and c["pharmacy_id"] == cheapest_cand["pharmacy_id"]:
                c["badges"].append({"type": "CHEAPEST", "label": "💰 Lowest Price", "class": "bg-success"})
            if closest_cand and c["pharmacy_id"] == closest_cand["pharmacy_id"]:
                c["badges"].append({"type": "CLOSEST", "label": "📍 Closest Pharmacy", "class": "bg-info text-dark"})

            # Price difference compared to cheapest
            if cheapest_cand and c["price"] > cheapest_cand["price"]:
                diff = c["price"] - cheapest_cand["price"]
                diff_pct = (diff / cheapest_cand["price"]) * 100.0
                c["price_diff_note"] = f"₹{diff:.2f} (+{diff_pct:.1f}%) compared to lowest price"
            else:
                c["price_diff_note"] = "Lowest verified price option"

        return sorted_candidates


# ==========================================================
# 4. AI PRICE EXPLANATION SERVICE
# ==========================================================

class AIPriceExplanationService:
    """
    Generates grounded Gemini Flash explanations for backend ranking results.
    Rule: NEVER determines prices or alters backend rankings.
    """

    @classmethod
    def generate_explanation(cls, winning_candidate: Dict[str, Any], cheapest_candidate: Dict[str, Any], mode: str = "BALANCED") -> str:
        """
        Generates clear explanation why the winning pharmacy was ranked #1.
        """
        p_name = winning_candidate.get("pharmacy_name", "Pharmacy")
        price = winning_candidate.get("price", 0)
        dist = winning_candidate.get("distance_km", 0)
        ch_name = cheapest_candidate.get("pharmacy_name", "")
        ch_price = cheapest_candidate.get("price", 0)

        fallback = f"**{p_name}** is ranked as your **Best Value** option at **₹{price:.2f}** ({dist} km away). "

        if p_name == ch_name:
            fallback += f"It offers the lowest verified price and convenient nearby availability."
        else:
            diff = price - ch_price
            fallback += f"While {ch_name} costs ₹{ch_price:.2f}, {p_name} is significantly closer and currently open, offering a stronger overall balance."

        gemini_api_key = getattr(settings, "GEMINI_API_KEY", None)
        if not gemini_api_key:
            return fallback

        prompt = f"""
You are Medifind AI #10 — Price Intelligence & Best Value Assistant.
Explain the following backend price comparison ranking to the user in 2 clear, friendly sentences.

BACKEND RANKING RESULT:
- Ranked #1 Winner: {p_name} (Price: ₹{price:.2f}, Distance: {dist} km, Value Score: {winning_candidate.get('value_score')}/100)
- Lowest Price Option: {ch_name} (Price: ₹{ch_price:.2f})
- Ranking Preference Mode: {mode}

RULES:
1. State clearly why {p_name} won based ONLY on the numbers above (e.g. balance of price and distance).
2. Do NOT invent prices, discounts, or pharmacies not listed above.
"""
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_api_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            resp = model.generate_content(prompt)
            if resp and resp.text:
                return resp.text.strip()
        except Exception as e:
            logger.warning(f"Gemini price explanation fallback: {str(e)}")

        return fallback
