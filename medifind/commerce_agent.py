"""
MedFinder AI Commerce Agent Core
================================
Architecture:
  USER -> AI INTENT PARSER -> STRUCTURED SEARCH REQUEST
       -> BACKEND SEARCH SERVICE (Django DB / Real Inventory)
       -> DETERMINISTIC RANKING ENGINE
       -> EXPLAINABLE RECOMMENDATION GENERATOR
       -> USER APPROVAL GATE (Pre-Razorpay)

Single Source of Truth: Django SQLite Database
Zero LLM Hallucinations: All pharmacy names, stock, prices, and distances are 100% verified.
"""

import os
import re
import json
import math
import uuid
import urllib.request
import urllib.error
from datetime import datetime
from django.utils import timezone
from django.db.models import Q
from .models import Medicine, Pharmacy, Inventory, AgentAuditLog
from .fuzzy_search import MedicineMatcher


# ============================================================================

# 1. AGENT STATES & OPTIMIZATION GOALS
# ============================================================================

class AgentState:
    IDLE = "IDLE"
    UNDERSTANDING_REQUEST = "UNDERSTANDING_REQUEST"
    SEARCHING = "SEARCHING"
    EVALUATING = "EVALUATING"
    RECOMMENDING = "RECOMMENDING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    FAILED = "FAILED"


class OptimizationGoal:
    LOWEST_PRICE = "lowest_price"
    CLOSEST = "closest"
    FASTEST = "fastest"
    BEST_VALUE = "best_value"


# ============================================================================
# 2. MEDICAL SAFETY & SYMPTOM CATALOG
# ============================================================================

MEDICAL_SAFETY_DISCLAIMER = (
    "I can help you search medicines in the MedFinder database, but I can't diagnose "
    "or prescribe medication. If you already have a medicine name, tell me what you're looking for."
)

SYMPTOM_MAP = {
    'fever': {
        'category': 'Pain Relief',
        'generic_name': 'Paracetamol',
        'suggested_medicines': ['Dolo 650', 'Paracetamol 500', 'Crocin', 'Combiflam'],
        'term': 'fever relief (Paracetamol / Dolo)'
    },
    'headache': {
        'category': 'Pain Relief',
        'generic_name': 'Paracetamol',
        'suggested_medicines': ['Dolo 650', 'Paracetamol 500', 'Combiflam', 'Ibuprofen 400'],
        'term': 'headache relief (Paracetamol / Ibuprofen)'
    },
    'pain': {
        'category': 'Pain Relief',
        'generic_name': 'Ibuprofen',
        'suggested_medicines': ['Ibuprofen 400', 'Combiflam', 'Dolo 650'],
        'term': 'pain relief'
    },
    'infection': {
        'category': 'Antibiotic',
        'generic_name': 'Amoxicillin',
        'suggested_medicines': ['Amoxicillin 500', 'Azithromycin 500', 'Augmentin 625', 'Ciprofloxacin 500'],
        'term': 'antibiotics (Amoxicillin / Azithromycin)'
    },
    'antibiotic': {
        'category': 'Antibiotic',
        'generic_name': 'Amoxicillin',
        'suggested_medicines': ['Amoxicillin 500', 'Azithromycin 500', 'Augmentin 625'],
        'term': 'antibiotics'
    },
    'vitamin': {
        'category': 'Vitamin',
        'generic_name': 'Vitamin C',
        'suggested_medicines': ['Limcee Vitamin C', 'Calcirol Vitamin D3', 'Becosules Z', 'Neurobion Forte'],
        'term': 'vitamins'
    },
    'allergy': {
        'category': 'Allergy',
        'generic_name': 'Cetirizine',
        'suggested_medicines': ['Cetirizine 10', 'Allegra 120', 'Levocetirizine 5', 'Montair LC'],
        'term': 'allergy medicine'
    },
    'cold': {
        'category': 'Allergy',
        'generic_name': 'Cetirizine',
        'suggested_medicines': ['Cetirizine 10', 'Allegra 120', 'Levocetirizine 5'],
        'term': 'cold / allergy relief'
    },
    'cough': {
        'category': 'Allergy',
        'generic_name': 'Levocetirizine',
        'suggested_medicines': ['Levocetirizine 5', 'Montair LC', 'Cetirizine 10'],
        'term': 'cough & allergy relief'
    },
    'diabetes': {
        'category': 'Diabetes',
        'generic_name': 'Metformin',
        'suggested_medicines': ['Glycomet Metformin', 'Mixtard 30/70 Insulin', 'Amaryl Glimepiride', 'Januvia Sitagliptin'],
        'term': 'diabetes management'
    },
    'sugar': {
        'category': 'Diabetes',
        'generic_name': 'Metformin',
        'suggested_medicines': ['Glycomet Metformin', 'Mixtard 30/70 Insulin'],
        'term': 'blood sugar care'
    },
    'heart': {
        'category': 'Heart',
        'generic_name': 'Aspirin',
        'suggested_medicines': ['Ecosprin 75', 'Atorva 10', 'Stamlo Amlodipine', 'Telma 40'],
        'term': 'cardiovascular care'
    },
    'bp': {
        'category': 'Heart',
        'generic_name': 'Amlodipine',
        'suggested_medicines': ['Stamlo Amlodipine', 'Telma 40', 'Atorva 10'],
        'term': 'blood pressure care'
    }
}


def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculates great-circle distance between two GPS coordinates in kilometers."""
    try:
        if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
            return None
        R = 6371.0
        dlat = math.radians(float(lat2) - float(lat1))
        dlon = math.radians(float(lon2) - float(lon1))
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(float(lat1))) * math.cos(math.radians(float(lat2))) * math.sin(dlon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c
    except (ValueError, TypeError):
        return None


# ============================================================================
# 3. INTENT PARSER & MEDICAL SAFETY GUARDRAILS
# ============================================================================

class IntentParser:
    """
    Parses natural language requests into strict structured commerce intent schemas.
    Implements medicine normalization, ambiguity detection, optimization goal parsing,
    and strict medical safety guardrails (never diagnose/prescribe).
    """

    @classmethod
    def get_known_medicines(cls):
        """Fetches active medicine names from database for ambiguity & normalization matching."""
        try:
            db_meds = list(Medicine.objects.values_list('name', flat=True))
            if db_meds:
                return db_meds
        except Exception:
            pass
        return [
            "Dolo 650", "Crocin 650", "Combiflam", "Saridon", "Meftal-Spas", "Volini Pain Relief Gel",
            "Sinarest Tablet", "Ascoril LS Syrup", "Benadryl Cough Syrup", "Otrivin Adult Nasal Spray",
            "Cetirizine 10 mg", "Allegra 120 mg", "Montair-LC", "Pan 40", "Omez 20",
            "Digene Gel Mint", "Gelusil MPS Liquid", "Electral ORS Powder", "Eno Fruit Salt Regular",
            "Becosules Z", "Neurobion Forte", "Shelcal 500", "Limcee Vitamin C 500 mg", "Calcirol Vitamin D3 60K",
            "Glycomet 500 mg", "Januvia 100 mg", "Amaryl 1 mg", "Telma 40 mg", "Amlodac 5 mg",
            "Ecosprin 75 mg", "Atorva 10 mg", "Augmentin 625 Duo", "Azithral 500 mg", "Ciplox 500 mg",
            "Betadine 5% Ointment", "Dettol Antiseptic Liquid", "Candid Dusting Powder",
            "Refresh Tears Eye Drops", "Hexidine Mouthwash"
        ]

    @classmethod
    def local_fallback_parser(cls, query: str) -> dict:
        """
        Deterministic, rule-based NLP query normalizer.
        Used as primary engine when offline or when LLM API key is not configured.
        """
        q_raw = query or ""
        q = q_raw.lower().strip()

        if not q:
            return {
                "intent": "medicine_search",
                "medicine_query": None,
                "generic_name": None,
                "strength_mg": None,
                "dosage_form": None,
                "quantity": None,
                "max_distance_km": None,
                "optimization_goal": OptimizationGoal.BEST_VALUE,
                "confidence": "low",
                "needs_clarification": True,
                "clarification_message": "Which medicine would you like me to search for?",
                "suggested_options": [],
                "medical_safety_warning": None,
                "interpretation": "Awaiting medicine query",
                "fallback": True
            }

        # -------------------------------------------------------------
        # 1. MEDICAL SAFETY & PRESCRIPTION / DIAGNOSIS GUARDRAILS
        # -------------------------------------------------------------
        diagnosis_patterns = [
            r'\bi have (?:a )?(?:fever|headache|pain|cough|cold|infection|fever and cough)\b',
            r'\bwhat (?:medicine|tablet|pill|drug)?\s*(?:should|can)\s*i\s*(?:take|use|have)\b',
            r'\bhow to (?:cure|treat|heal)\b',
            r'\bwhat (?:is|are) (?:the best medicine for|good for)\b',
            r'\bdiagnose\b',
            r'\bsuggest (?:a )?medicine for (?:fever|pain|cough|cold|headache|infection)\b',
            r'\bfind something for (?:fever|pain|cough|cold|headache|infection)\b'
        ]

        is_medical_advice_request = any(re.search(pat, q) for pat in diagnosis_patterns)

        # -------------------------------------------------------------
        # 2. OPTIMIZATION GOAL EXTRACTION
        # -------------------------------------------------------------
        optimization_goal = OptimizationGoal.BEST_VALUE

        if re.search(r'\b(cheapest|cheaper|lowest price|least price|low price|minimum price|lowest cost|budget|affordable|inexpensive)\b', q):
            optimization_goal = OptimizationGoal.LOWEST_PRICE
        elif re.search(r'\b(asap|as soon as possible|urgently|urgent|emergency|fastest|quickest|immediate|need it now|right now)\b', q):
            optimization_goal = OptimizationGoal.FASTEST
        elif re.search(r'\b(closest|nearest|near me|nearby|shortest distance|closer|close by)\b', q):
            optimization_goal = OptimizationGoal.CLOSEST

        # -------------------------------------------------------------
        # 3. RADIUS / DISTANCE EXTRACTION
        # -------------------------------------------------------------
        max_distance_km = None
        radius_match = re.search(r'(?:within|in|under|less than|max(?:imum)? of)?\s*(\d+(?:\.\d+)?)\s*(?:km|kms|kilometer|kilometers)\b', q)
        if radius_match:
            try:
                max_distance_km = float(radius_match.group(1))
            except ValueError:
                max_distance_km = None

        # -------------------------------------------------------------
        # 4. QUANTITY EXTRACTION (SAFE: do not invent if missing)
        # -------------------------------------------------------------
        quantity = None
        qty_match = re.search(r'\b(\d+)\s*(?:strips?|packs?|boxes?|bottles?|units?|tablets?|capsules?|tabs?|caps?)\b', q)
        if qty_match:
            try:
                qty_val = int(qty_match.group(1))
                # Only set quantity if reasonable (not a strength like 650)
                if qty_val <= 100:
                    quantity = qty_val
            except ValueError:
                quantity = None

        # -------------------------------------------------------------
        # 5. STRENGTH & DOSAGE FORM NORMALIZATION
        # -------------------------------------------------------------
        strength_mg = None
        strength_raw = None

        # Check for numeric strength like "650 mg", "650mg", "six fifty"
        if "six fifty" in q or "six-fifty" in q:
            strength_mg = 650
            strength_raw = "650 mg"
        elif "five hundred" in q:
            strength_mg = 500
            strength_raw = "500 mg"
        else:
            str_match = re.search(r'\b(\d+)\s*(?:mg|milligram|milligrams)\b', q)
            if str_match:
                strength_mg = int(str_match.group(1))
                strength_raw = f"{strength_mg} mg"
            elif re.search(r'\b650\b', q):
                strength_mg = 650
                strength_raw = "650 mg"
            elif re.search(r'\b500\b', q):
                strength_mg = 500
                strength_raw = "500 mg"
            elif re.search(r'\b400\b', q):
                strength_mg = 400
                strength_raw = "400 mg"
            elif re.search(r'\b120\b', q):
                strength_mg = 120
                strength_raw = "120 mg"

        dosage_form = None
        if re.search(r'\b(tablet|tablets|tab|tabs)\b', q):
            dosage_form = "tablet"
        elif re.search(r'\b(capsule|capsules|cap|caps)\b', q):
            dosage_form = "capsule"
        elif re.search(r'\b(syrup|liquid|suspension)\b', q):
            dosage_form = "syrup"
        elif re.search(r'\b(injection|insulin|vial|pen)\b', q):
            dosage_form = "injection"

        # -------------------------------------------------------------
        # 6. MEDICINE RECOGNITION & AMBIGUITY HANDLING
        # -------------------------------------------------------------
        known_meds = cls.get_known_medicines()
        matched_medicine = None
        generic_name = None

        # Clean search query for normalization
        # e.g. "dolo six fifty" -> "Dolo 650", "dolo650" -> "Dolo 650"
        normalized_q = q
        normalized_q = re.sub(r'\bdolo\s*650\b|\bdolo650\b|\bdolo\s*six\s*fifty\b', 'Dolo 650', normalized_q, flags=re.IGNORECASE)
        normalized_q = re.sub(r'\bparacetamol\s*650\b|\bpara\s*650\b', 'Paracetamol 650', normalized_q, flags=re.IGNORECASE)
        normalized_q = re.sub(r'\bparacetamol\s*500\b|\bpara\s*500\b', 'Paracetamol 500', normalized_q, flags=re.IGNORECASE)
        normalized_q = re.sub(r'\bcrocin\s*650\b', 'Crocin 650', normalized_q, flags=re.IGNORECASE)
        normalized_q = re.sub(r'\bcrocin\b', 'Crocin', normalized_q, flags=re.IGNORECASE)

        # Check for explicit medicine name matches in known_meds
        # Sort by length descending so "Dolo 650" matches before "Dolo"
        sorted_meds = sorted(known_meds, key=lambda m: len(m), reverse=True)
        for med in sorted_meds:
            if re.search(r'\b' + re.escape(med.lower()) + r'\b', normalized_q.lower()):
                matched_medicine = med
                break

        # Check for partial / generic terms or fuzzy typo matches
        if not matched_medicine:
            # Check fuzzy matcher for approximate medicine names and typos (e.g. 'dollo', 'paractamol', 'pan-d')
            fuzzy_results = MedicineMatcher.find_matching_medicines(normalized_q, threshold=0.52)
            if fuzzy_results:
                top_fuzzy = fuzzy_results[0]["medicine"]
                matched_medicine = top_fuzzy.name
                if top_fuzzy.brand and top_fuzzy.brand.lower() != top_fuzzy.name.lower():
                    generic_name = top_fuzzy.brand
            elif "dolo" in normalized_q.lower():
                matched_medicine = "Dolo 650"
            elif "paracetamol" in normalized_q.lower() or "para " in normalized_q.lower():
                matched_medicine = "Dolo 650"
            elif "crocin" in normalized_q.lower():
                matched_medicine = "Crocin 650"
            elif "combiflam" in normalized_q.lower():
                matched_medicine = "Combiflam"
            elif "saridon" in normalized_q.lower():
                matched_medicine = "Saridon"
            elif "meftal" in normalized_q.lower():
                matched_medicine = "Meftal-Spas"
            elif "volini" in normalized_q.lower():
                matched_medicine = "Volini Pain Relief Gel"
            elif "sinarest" in normalized_q.lower() or "cold tablet" in normalized_q.lower():
                matched_medicine = "Sinarest Tablet"
            elif "ascoril" in normalized_q.lower():
                matched_medicine = "Ascoril LS Syrup"
            elif "benadryl" in normalized_q.lower() or "cough syrup" in normalized_q.lower():
                matched_medicine = "Benadryl Cough Syrup"
            elif "otrivin" in normalized_q.lower() or "nasal spray" in normalized_q.lower():
                matched_medicine = "Otrivin Adult Nasal Spray"
            elif "cetirizine" in normalized_q.lower():
                matched_medicine = "Cetirizine 10 mg"
            elif "allegra" in normalized_q.lower() or "fexofenadine" in normalized_q.lower():
                matched_medicine = "Allegra 120 mg"
            elif "montair" in normalized_q.lower() or "montelukast" in normalized_q.lower():
                matched_medicine = "Montair-LC"
            elif "pan 40" in normalized_q.lower() or "pantoprazole" in normalized_q.lower() or "pan40" in normalized_q.lower():
                matched_medicine = "Pan 40"
            elif "omez" in normalized_q.lower() or "omeprazole" in normalized_q.lower():
                matched_medicine = "Omez 20"
            elif "digene" in normalized_q.lower() or "antacid syrup" in normalized_q.lower():
                matched_medicine = "Digene Gel Mint"
            elif "gelusil" in normalized_q.lower():
                matched_medicine = "Gelusil MPS Liquid"
            elif "electral" in normalized_q.lower() or "ors" in normalized_q.lower():
                matched_medicine = "Electral ORS Powder"
            elif "eno" in normalized_q.lower() or "fruit salt" in normalized_q.lower():
                matched_medicine = "Eno Fruit Salt Regular"
            elif "becosules" in normalized_q.lower() or "b-complex" in normalized_q.lower():
                matched_medicine = "Becosules Z"
            elif "neurobion" in normalized_q.lower() or "b12" in normalized_q.lower():
                matched_medicine = "Neurobion Forte"
            elif "shelcal" in normalized_q.lower() or "calcium" in normalized_q.lower():
                matched_medicine = "Shelcal 500"
            elif "limcee" in normalized_q.lower() or "vitamin c" in normalized_q.lower():
                matched_medicine = "Limcee Vitamin C 500 mg"
            elif "calcirol" in normalized_q.lower() or "vitamin d" in normalized_q.lower():
                matched_medicine = "Calcirol Vitamin D3 60K"
            elif "glycomet" in normalized_q.lower() or "metformin" in normalized_q.lower():
                matched_medicine = "Glycomet 500 mg"
            elif "januvia" in normalized_q.lower() or "sitagliptin" in normalized_q.lower():
                matched_medicine = "Januvia 100 mg"
            elif "amaryl" in normalized_q.lower() or "glimepiride" in normalized_q.lower():
                matched_medicine = "Amaryl 1 mg"
            elif "telma" in normalized_q.lower() or "telmisartan" in normalized_q.lower():
                matched_medicine = "Telma 40 mg"
            elif "amlodac" in normalized_q.lower() or "amlodipine" in normalized_q.lower():
                matched_medicine = "Amlodac 5 mg"
            elif "ecosprin" in normalized_q.lower() or "aspirin" in normalized_q.lower():
                matched_medicine = "Ecosprin 75 mg"
            elif "atorva" in normalized_q.lower() or "atorvastatin" in normalized_q.lower() or "cholesterol" in normalized_q.lower():
                matched_medicine = "Atorva 10 mg"
            elif "augmentin" in normalized_q.lower() or "amoxicillin" in normalized_q.lower():
                matched_medicine = "Augmentin 625 Duo"
            elif "azithral" in normalized_q.lower() or "azithromycin" in normalized_q.lower():
                matched_medicine = "Azithral 500 mg"
            elif "ciplox" in normalized_q.lower() or "ciprofloxacin" in normalized_q.lower():
                matched_medicine = "Ciplox 500 mg"
            elif "betadine" in normalized_q.lower() or "povidone" in normalized_q.lower():
                matched_medicine = "Betadine 5% Ointment"
            elif "dettol" in normalized_q.lower() or "antiseptic" in normalized_q.lower():
                matched_medicine = "Dettol Antiseptic Liquid"
            elif "candid" in normalized_q.lower() or "dusting powder" in normalized_q.lower():
                matched_medicine = "Candid Dusting Powder"
            elif "refresh tears" in normalized_q.lower() or "eye drops" in normalized_q.lower():
                matched_medicine = "Refresh Tears Eye Drops"
            elif "hexidine" in normalized_q.lower() or "mouthwash" in normalized_q.lower():
                matched_medicine = "Hexidine Mouthwash"


        # Determine generic name
        if matched_medicine:
            m_lower = matched_medicine.lower()
            if "dolo" in m_lower or "crocin" in m_lower or "paracetamol" in m_lower:
                generic_name = "Paracetamol"
            elif "ibuprofen" in m_lower or "combiflam" in m_lower:
                generic_name = "Ibuprofen"
            elif "amoxicillin" in m_lower or "augmentin" in m_lower:
                generic_name = "Amoxicillin"
            elif "azithromycin" in m_lower:
                generic_name = "Azithromycin"
            elif "cetirizine" in m_lower or "allegra" in m_lower or "levocetirizine" in m_lower:
                generic_name = "Cetirizine / Levocetirizine"
            elif "metformin" in m_lower or "glycomet" in m_lower:
                generic_name = "Metformin"
            elif "insulin" in m_lower or "mixtard" in m_lower:
                generic_name = "Insulin"

        # Check symptom matching if no medicine matched
        matched_symptom = None
        symptom_data = None
        if not matched_medicine:
            for s_key, s_info in SYMPTOM_MAP.items():
                if re.search(r'\b' + s_key + r'\b', q):
                    matched_symptom = s_key
                    symptom_data = s_info
                    break

        # -------------------------------------------------------------
        # 7. AMBIGUITY DETECTION & CLARIFICATION LOGIC
        # -------------------------------------------------------------
        needs_clarification = False
        clarification_message = None
        suggested_options = []
        confidence = "high"

        # Case A: Medical advice request (e.g. "I have fever, what should I take?")
        if is_medical_advice_request or (matched_symptom and not matched_medicine):
            needs_clarification = True
            confidence = "low"
            if matched_symptom and symptom_data:
                suggested_options = symptom_data.get('suggested_medicines', [])
                clarification_message = (
                    f"{MEDICAL_SAFETY_DISCLAIMER}\n"
                    f"If you are looking for {symptom_data.get('term', 'medicine')}, "
                    f"common options in MedFinder include {', '.join(suggested_options[:3])}."
                )
            else:
                clarification_message = (
                    f"{MEDICAL_SAFETY_DISCLAIMER}\n"
                    f"Please tell me the name of the specific medicine or active ingredient you wish to search for."
                )
                suggested_options = ["Dolo 650", "Paracetamol 500", "Cetirizine 10", "Ibuprofen 400"]

        # Case B: Generic query without medicine name (e.g. "Find the cheapest medicine")
        elif not matched_medicine and not matched_symptom:
            cleaned_q = re.sub(
                r'\b(find|i need|get|show me|search|cheapest|closest|fastest|near me|nearby|within \d+\s*(?:km|kms)?|the|a|medicine|tablet|pill)\b',
                '', q, flags=re.IGNORECASE
            ).strip()

            if not cleaned_q or len(cleaned_q) < 2:
                needs_clarification = True
                confidence = "low"
                clarification_message = "Which medicine would you like me to search for?"
                suggested_options = ["Dolo 650", "Paracetamol 500", "Crocin", "Cetirizine 10"]
            else:
                # User typed a specific name not in our pre-indexed list
                matched_medicine = cleaned_q.title()

        # Case C: Ambiguous brand with multiple variants (e.g. user typed exactly "Find Dolo" or "Dolo")
        elif matched_medicine.lower() == "dolo" and strength_mg is None:
            # Check if both Dolo and Dolo 650 exist
            dolo_variants = [m for m in known_meds if "dolo" in m.lower()]
            if len(dolo_variants) > 1:
                needs_clarification = True
                confidence = "low"
                clarification_message = "Did you mean Dolo 650 or another Dolo variant?"
                suggested_options = dolo_variants[:4]

        # -------------------------------------------------------------
        # 8. HUMAN READABLE INTERPRETATION STRING
        # -------------------------------------------------------------
        interp_parts = []
        if optimization_goal == OptimizationGoal.LOWEST_PRICE:
            interp_parts.append("Cheapest")
        elif optimization_goal == OptimizationGoal.CLOSEST:
            interp_parts.append("Nearest")
        elif optimization_goal == OptimizationGoal.FASTEST:
            interp_parts.append("Fastest available")

        if matched_medicine:
            interp_parts.append(matched_medicine)
        elif generic_name:
            interp_parts.append(f"{generic_name} ({matched_symptom.capitalize() if matched_symptom else 'Relief'})")
        else:
            interp_parts.append("Medicine")

        if strength_raw and (not matched_medicine or strength_raw not in matched_medicine):
            interp_parts.append(strength_raw)
        if dosage_form and (not matched_medicine or dosage_form not in matched_medicine):
            interp_parts.append(f"({dosage_form})")

        if max_distance_km:
            interp_parts.append(f"within {int(max_distance_km) if max_distance_km.is_integer() else max_distance_km} km")
        elif "near me" in q or "nearby" in q or optimization_goal == OptimizationGoal.CLOSEST:
            interp_parts.append("near your location")

        interpretation = "Looking for " + " ".join(interp_parts) if interp_parts else f"Searching for '{q_raw}'"

        return {
            "intent": "medicine_search",
            "medicine_query": matched_medicine,
            "generic_name": generic_name,
            "strength_mg": strength_mg,
            "strength_raw": strength_raw,
            "dosage_form": dosage_form,
            "quantity": quantity,
            "max_distance_km": max_distance_km,
            "optimization_goal": optimization_goal,
            "confidence": confidence,
            "needs_clarification": needs_clarification,
            "clarification_message": clarification_message,
            "suggested_options": suggested_options,
            "medical_safety_warning": MEDICAL_SAFETY_DISCLAIMER if (is_medical_advice_request or matched_symptom) else None,
            "interpretation": interpretation,
            "fallback": True
        }

    @classmethod
    def parse_with_ai(cls, query: str) -> dict:
        """
        Extracts structured intent using LLM (Gemini 1.5 Flash), falling back
        instantly to deterministic local rule parser if unavailable or timed out.
        """
        q = (query or "").strip()
        if not q:
            return cls.local_fallback_parser("")

        api_key = os.environ.get('AI_API_KEY', '').strip() or os.environ.get('GEMINI_API_KEY', '').strip()
        if not api_key or api_key == "YOUR_API_KEY_HERE":
            return cls.local_fallback_parser(q)

        prompt = f"""You are the AI Commerce Agent intent extractor for MedFinder.
Strictly convert the user's natural language medicine search request into a JSON structure.

Rules:
1. Optimization goals must be one of: "lowest_price", "closest", "fastest", "best_value".
   - "cheapest", "lowest price" -> "lowest_price"
   - "closest", "near me", "nearest" -> "closest"
   - "urgently", "asap", "fastest" -> "fastest"
   - default -> "best_value"
2. Medical Safety: NEVER diagnose or prescribe. If the user asks for diagnosis or what to take for symptoms (e.g. "I have fever, what should I take?"), set needs_clarification=true and provide a helpful safety disclaimer.
3. Medicine Normalization: Normalize typos and spoken numbers (e.g. "Dolo six fifty" -> "Dolo 650", "paracetamol 650" -> generic: "Paracetamol", strength_mg: 650).
4. Ambiguity: If user searches "Find Dolo" without variant, set confidence="low", needs_clarification=true, clarification_message="Did you mean Dolo 650 or another Dolo variant?".
5. Do NOT hallucinate quantity if not mentioned.

Return ONLY a JSON object matching this schema:
{{
  "intent": "medicine_search",
  "medicine_query": "exact brand or medicine name (e.g. 'Dolo 650' or null)",
  "generic_name": "active ingredient name (e.g. 'Paracetamol' or null)",
  "strength_mg": integer or null (e.g. 650),
  "dosage_form": "tablet" | "capsule" | "syrup" | "injection" | null,
  "quantity": integer or null,
  "max_distance_km": float or null (e.g. 5.0),
  "optimization_goal": "lowest_price" | "closest" | "fastest" | "best_value",
  "confidence": "high" | "low",
  "needs_clarification": boolean,
  "clarification_message": string or null,
  "suggested_options": list of strings,
  "interpretation": string
}}

User query: "{q}"
"""

        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
            payload = json.dumps({
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.0,
                    "responseMimeType": "application/json"
                }
            }).encode('utf-8')

            req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})

            with urllib.request.urlopen(req, timeout=3.5) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                text_content = res_data['candidates'][0]['content']['parts'][0]['text']

                if "```" in text_content:
                    text_content = re.sub(r'```json\s*', '', text_content)
                    text_content = re.sub(r'```\s*$', '', text_content)

                parsed = json.loads(text_content.strip())
                parsed["fallback"] = False

                # Ensure valid optimization goal
                if parsed.get("optimization_goal") not in [
                    OptimizationGoal.LOWEST_PRICE,
                    OptimizationGoal.CLOSEST,
                    OptimizationGoal.FASTEST,
                    OptimizationGoal.BEST_VALUE
                ]:
                    parsed["optimization_goal"] = OptimizationGoal.BEST_VALUE

                return parsed

        except Exception as e:
            fallback = cls.local_fallback_parser(q)
            fallback["fallback_reason"] = str(e)
            return fallback


# ============================================================================
# 4. BACKEND SEARCH SERVICE (REAL INVENTORY LOOKUP)
# ============================================================================

class CommerceSearchService:
    """
    Queries real Django models (Medicine, Pharmacy, Inventory).
    Calculates Haversine distance, checks live stock and operating hours.
    Guarantees that no fake pharmacy or inventory item ever reaches the AI.
    """

    @classmethod
    def search_candidates(cls, structured_intent: dict, user_lat=None, user_lng=None) -> list[dict]:
        """
        Retrieves verified candidate items from Django database.
        """
        medicine_query = structured_intent.get("medicine_query") or ""
        generic_name = structured_intent.get("generic_name") or ""
        max_distance_km = structured_intent.get("max_distance_km")
        dosage_form = structured_intent.get("dosage_form")

        # Base Query: active pharmacies with verified stock > 0
        qs = Inventory.objects.select_related("medicine", "pharmacy").filter(
            pharmacy__is_active=True,
            quantity__gt=0
        )

        # Medicine matching query with fuzzy matching & typo tolerance
        if medicine_query or generic_name:
            search_query_text = medicine_query or generic_name
            fuzzy_matches = MedicineMatcher.find_matching_medicines(search_query_text, threshold=0.50)
            matched_med_ids = [m["medicine"].id for m in fuzzy_matches] if fuzzy_matches else []

            if fuzzy_matches:
                top_match = fuzzy_matches[0]
                if top_match["medicine"].name.lower() != search_query_text.lower():
                    structured_intent["matched_medicine_name"] = top_match["medicine"].name
                    structured_intent["suggested_correction"] = top_match["suggested_correction"]

            terms = []
            if medicine_query:
                terms.append(medicine_query)
            if generic_name and generic_name.lower() not in medicine_query.lower():
                terms.append(generic_name)

            q_filter = Q()
            if matched_med_ids:
                q_filter |= Q(medicine_id__in=matched_med_ids)

            for term in terms:
                q_filter |= Q(medicine__name__icontains=term)
                q_filter |= Q(medicine__brand__icontains=term)
                q_filter |= Q(medicine__description__icontains=term)
                q_filter |= Q(medicine__uses__icontains=term)

            qs = qs.filter(q_filter)


        if dosage_form:
            qs = qs.filter(
                Q(medicine__dosage__icontains=dosage_form) |
                Q(medicine__name__icontains=dosage_form) |
                Q(medicine__description__icontains=dosage_form)
            )

        candidates = []
        current_time = timezone.localtime().time()

        for item in qs:
            pharmacy = item.pharmacy
            medicine = item.medicine

            # Pharmacy operating hours check
            is_open = (
                pharmacy.is_open and
                pharmacy.opening_time <= current_time <= pharmacy.closing_time
            )

            # Compute Haversine distance if coordinates are present
            distance = None
            if user_lat is not None and user_lng is not None:
                distance = haversine_distance(
                    user_lat, user_lng,
                    pharmacy.latitude, pharmacy.longitude
                )

            # Max distance radius filter (if distance is known and max_distance is specified)
            if max_distance_km is not None and distance is not None:
                if distance > max_distance_km:
                    continue

            candidates.append({
                "inventory_id": item.id,
                "medicine_id": medicine.id,
                "medicine_name": medicine.name,
                "brand": medicine.brand,
                "category": medicine.category,
                "dosage": medicine.dosage,
                "prescription_required": medicine.prescription_required,
                "pharmacy_id": pharmacy.id,
                "pharmacy_name": pharmacy.name,
                "pharmacy_phone": pharmacy.phone,
                "pharmacy_address": pharmacy.address,
                "pharmacy_city": pharmacy.city,
                "pharmacy_state": pharmacy.state,
                "pharmacy_pincode": pharmacy.pincode,
                "latitude": float(pharmacy.latitude),
                "longitude": float(pharmacy.longitude),
                "is_open": is_open,
                "opening_time": pharmacy.opening_time.strftime("%I:%M %p"),
                "closing_time": pharmacy.closing_time.strftime("%I:%M %p"),
                "price": float(item.price),
                "stock": item.quantity,
                "batch_number": item.batch_number,
                "expiry_date": str(item.expiry_date),
                "distance_km": round(distance, 1) if distance is not None else None
            })

        return candidates


# ============================================================================
# 5. DETERMINISTIC DECISION & RANKING ENGINE
# ============================================================================

class DeterministicRankingEngine:
    """
    Deterministic candidate ranker implemented entirely in Python.
    The LLM is NOT permitted to invent ranking scores or manipulate results.
    """

    @classmethod
    def rank_candidates(cls, candidates: list[dict], optimization_goal: str, target_medicine_name: str = None) -> list[dict]:
        """
        Ranks verified candidates according to the specified optimization goal.
        Attaches deterministic scores, ranking position, and decision reasons.
        """
        if not candidates:
            return []

        ranked = list(candidates)

        if optimization_goal == OptimizationGoal.LOWEST_PRICE:
            # 1. Price ascending (strictly lowest price first)
            # 2. Distance ascending as secondary factor
            # 3. Open status
            ranked.sort(
                key=lambda x: (
                    x["price"],
                    x["distance_km"] if x["distance_km"] is not None else 9999.0,
                    0 if x["is_open"] else 1
                )
            )

        elif optimization_goal == OptimizationGoal.CLOSEST:
            # 1. Distance ascending (strictly shortest distance first)
            # 2. Price ascending as secondary factor
            # 3. Open status
            ranked.sort(
                key=lambda x: (
                    x["distance_km"] if x["distance_km"] is not None else 9999.0,
                    x["price"],
                    0 if x["is_open"] else 1
                )
            )

        elif optimization_goal == OptimizationGoal.FASTEST:
            # Urgent Mode:
            # 1. Open pharmacies with reasonable availability first (is_open == True and stock >= 5)
            # 2. Open pharmacies with any stock (stock > 0)
            # 3. Distance ascending (shortest distance / proximity)
            # 4. Price ascending
            ranked.sort(
                key=lambda x: (
                    0 if (x["is_open"] and x["stock"] >= 5) else (1 if (x["is_open"] and x["stock"] > 0) else 2),
                    x["distance_km"] if x["distance_km"] is not None else 9999.0,
                    x["price"]
                )
            )

        else:
            # BEST_VALUE: Transparent composite multi-factor scoring (deterministic combination)
            prices = [c["price"] for c in ranked]
            min_price, max_price = min(prices), max(prices)
            price_spread = (max_price - min_price) if max_price > min_price else 1.0

            distances = [c["distance_km"] for c in ranked if c["distance_km"] is not None]
            min_dist = min(distances) if distances else 0.0
            max_dist = max(distances) if distances else 1.0
            dist_spread = (max_dist - min_dist) if max_dist > min_dist else 1.0

            target_word = target_medicine_name.lower().split()[0] if target_medicine_name else ""

            for item in ranked:
                # Normalized price score (0 to 100, lower price is higher score)
                price_score = 100.0 - ((item["price"] - min_price) / price_spread * 60.0)

                # Normalized distance score (0 to 100, closer is higher score)
                if item["distance_km"] is not None:
                    dist_score = 100.0 - ((item["distance_km"] - min_dist) / dist_spread * 50.0)
                else:
                    dist_score = 50.0

                # Stock confidence bonus (reasonable availability)
                stock_bonus = 15.0 if item["stock"] >= 15 else (8.0 if item["stock"] >= 5 else 3.0)

                # Open status bonus
                open_bonus = 15.0 if item["is_open"] else 0.0

                # Direct brand/name match bonus
                match_bonus = 25.0 if (target_word and target_word in item["medicine_name"].lower()) else 0.0

                composite_score = round(
                    (0.40 * price_score) +
                    (0.30 * dist_score) +
                    stock_bonus +
                    open_bonus +
                    match_bonus,
                    1
                )
                item["composite_score"] = composite_score

            ranked.sort(key=lambda x: x.get("composite_score", 0), reverse=True)


        # Annotate rankings and decision reasons
        for idx, item in enumerate(ranked, start=1):
            item["rank"] = idx
            reasons = []
            if idx == 1:
                if optimization_goal == OptimizationGoal.LOWEST_PRICE:
                    reasons.append(f"Lowest price verified at ₹{item['price']:.2f}")
                    if item['distance_km'] is not None:
                        reasons.append(f"{item['distance_km']} km away")
                elif optimization_goal == OptimizationGoal.CLOSEST:
                    if item['distance_km'] is not None:
                        reasons.append(f"Closest pharmacy ({item['distance_km']} km)")
                    reasons.append(f"₹{item['price']:.2f} per unit")
                elif optimization_goal == OptimizationGoal.FASTEST:
                    reasons.append("Currently open for immediate fulfillment" if item['is_open'] else "Fastest route")
                    if item['distance_km'] is not None:
                        reasons.append(f"{item['distance_km']} km distance")
                else:
                    reasons.append(f"Best overall value (₹{item['price']:.2f})")
                    if item['distance_km'] is not None:
                        reasons.append(f"{item['distance_km']} km proximity")

                if item['stock'] > 10:
                    reasons.append(f"High verified stock ({item['stock']} units)")
                else:
                    reasons.append(f"{item['stock']} units left in stock")

            item["decision_reasons"] = reasons

        return ranked


# ============================================================================
# 6. EXPLAINABLE RECOMMENDATIONS GENERATOR
# ============================================================================

class RecommendationExplainer:
    """
    Generates natural language explanations strictly bounded by verified database values.
    Zero fabricated numbers, prices, or store names.
    """

    @classmethod
    def generate_explanation(cls, best_match: dict, optimization_goal: str, max_distance_km=None) -> str:
        """
        Builds explainable recommendation text referencing ONLY verified values.
        """
        if not best_match:
            return "No nearby pharmacy currently shows this medicine in stock."

        pharmacy = best_match["pharmacy_name"]
        medicine = best_match["medicine_name"]
        price = best_match["price"]
        dist = best_match.get("distance_km")
        stock = best_match.get("stock", 0)
        is_open = best_match.get("is_open", True)

        dist_str = f"{dist} km away" if dist is not None else "in your area"
        radius_str = f" within your {int(max_distance_km) if max_distance_km and float(max_distance_km).is_integer() else max_distance_km} km limit" if max_distance_km else ""

        if optimization_goal == OptimizationGoal.LOWEST_PRICE:
            return (
                f"Best match: {medicine} at {pharmacy}. "
                f"It is ₹{price:.2f} and {dist_str}, making it the lowest-priced verified option{radius_str} "
                f"with {stock} units in stock."
            )
        elif optimization_goal == OptimizationGoal.CLOSEST:
            return (
                f"Best match: {medicine} at {pharmacy}. "
                f"It is the nearest verified pharmacy at {dist_str} with {stock} units in stock at ₹{price:.2f}."
            )
        elif optimization_goal == OptimizationGoal.FASTEST:
            open_info = f"currently open (closes at {best_match.get('closing_time', 'closing')})" if is_open else "opening soon"
            return (
                f"Best match: {medicine} at {pharmacy}. "
                f"It is {open_info} and {dist_str} for fast collection ({stock} units available at ₹{price:.2f})."
            )
        else:
            return (
                f"Best match: {medicine} at {pharmacy}. "
                f"It offers the optimal balance of price (₹{price:.2f}), proximity ({dist_str}), "
                f"and verified stock ({stock} units available)."
            )


# ============================================================================
# 7. AGENT AUDIT SERVICE
# ============================================================================

class AgentAuditService:
    """
    Logs internal agent decision events to database and memory.
    Sanitizes sensitive information and provides complete traceability.
    """

    @classmethod
    def log_event(cls, session_id: str, event_type: str, state: str, payload: dict, user=None) -> dict:
        """
        Creates an audit trail entry.
        """
        # Sanitize any accidental sensitive fields
        sanitized_payload = {}
        for k, v in payload.items():
            if k not in ["api_key", "password", "token", "secret", "card", "payment_token"]:
                sanitized_payload[k] = v

        entry = {
            "session_id": session_id,
            "event_type": event_type,
            "state": state,
            "payload": sanitized_payload,
            "timestamp": timezone.now().isoformat()
        }

        try:
            # Avoid logging during unit tests if DB table not populated
            AgentAuditLog.objects.create(
                session_id=session_id,
                user=user if user and getattr(user, 'is_authenticated', False) else None,
                event_type=event_type,
                state=state,
                payload=sanitized_payload
            )
        except Exception:
            pass

        return entry


# ============================================================================
# 8. AI COMMERCE AGENT MASTER ORCHESTRATOR
# ============================================================================

class AICommerceAgent:
    """
    Master orchestrator for the AI Commerce Agent.
    Coordinates State Transitions:
      IDLE -> UNDERSTANDING_REQUEST -> SEARCHING -> EVALUATING -> RECOMMENDING -> AWAITING_APPROVAL
    """

    @classmethod
    def execute_search_flow(cls, query: str, user_lat=None, user_lng=None, user=None, session_id=None) -> dict:
        """
        Executes end-to-end AI commerce discovery and ranking flow.
        """
        session_id = session_id or str(uuid.uuid4())
        audit_trail = []

        # -------------------------------------------------------------
        # STATE 1: IDLE -> UNDERSTANDING_REQUEST
        # -------------------------------------------------------------
        current_state = AgentState.UNDERSTANDING_REQUEST
        event_1 = AgentAuditService.log_event(
            session_id=session_id,
            event_type="search_request",
            state=current_state,
            payload={"query": query, "user_lat": user_lat, "user_lng": user_lng},
            user=user
        )
        audit_trail.append(event_1)

        # Parse Intent using AI (with instant local fallback)
        intent = IntentParser.parse_with_ai(query)

        event_2 = AgentAuditService.log_event(
            session_id=session_id,
            event_type="intent_extracted",
            state=current_state,
            payload={
                "medicine": intent.get("medicine_query"),
                "generic": intent.get("generic_name"),
                "radius": intent.get("max_distance_km"),
                "optimization": intent.get("optimization_goal"),
                "confidence": intent.get("confidence"),
                "needs_clarification": intent.get("needs_clarification")
            },
            user=user
        )
        audit_trail.append(event_2)

        # Handle early clarification / medical safety guardrails
        if intent.get("needs_clarification"):
            current_state = AgentState.AWAITING_APPROVAL
            return {
                "session_id": session_id,
                "state": current_state,
                "intent": intent,
                "candidates_count": 0,
                "best_match": None,
                "other_options": [],
                "explanation": intent.get("clarification_message") or MEDICAL_SAFETY_DISCLAIMER,
                "needs_clarification": True,
                "clarification_message": intent.get("clarification_message"),
                "suggested_options": intent.get("suggested_options", []),
                "medical_safety_warning": intent.get("medical_safety_warning"),
                "audit_trail": audit_trail
            }

        # Check location requirement: if user asked for "within X km" or "near me" but location is absent
        location_needed = False
        location_message = None
        if (intent.get("max_distance_km") or intent.get("optimization_goal") == OptimizationGoal.CLOSEST) and (user_lat is None or user_lng is None):
            location_needed = True
            location_message = "Please enable location access or enter your area so I can find nearby pharmacies."

        # -------------------------------------------------------------
        # STATE 2: SEARCHING
        # -------------------------------------------------------------
        current_state = AgentState.SEARCHING
        raw_candidates = CommerceSearchService.search_candidates(
            structured_intent=intent,
            user_lat=user_lat,
            user_lng=user_lng
        )

        event_3 = AgentAuditService.log_event(
            session_id=session_id,
            event_type="candidate_search",
            state=current_state,
            payload={
                "candidate_count": len(raw_candidates),
                "medicine_query": intent.get("medicine_query"),
                "max_distance_km": intent.get("max_distance_km")
            },
            user=user
        )
        audit_trail.append(event_3)

        # -------------------------------------------------------------
        # STATE 3: EVALUATING
        # -------------------------------------------------------------
        current_state = AgentState.EVALUATING
        target_med = intent.get("matched_medicine_name") or intent.get("medicine_query")
        ranked_candidates = DeterministicRankingEngine.rank_candidates(
            candidates=raw_candidates,
            optimization_goal=intent.get("optimization_goal", OptimizationGoal.BEST_VALUE),
            target_medicine_name=target_med
        )


        event_4 = AgentAuditService.log_event(
            session_id=session_id,
            event_type="ranking_evaluated",
            state=current_state,
            payload={
                "ranked_count": len(ranked_candidates),
                "optimization_goal": intent.get("optimization_goal")
            },
            user=user
        )
        audit_trail.append(event_4)

        # -------------------------------------------------------------
        # STATE 4: RECOMMENDING
        # -------------------------------------------------------------
        current_state = AgentState.RECOMMENDING
        best_match = ranked_candidates[0] if ranked_candidates else None
        other_options = ranked_candidates[1:4] if len(ranked_candidates) > 1 else []

        # Explicitly identify the Cheapest Option and Nearest Option
        cheapest_option = None
        nearest_option = None

        in_stock_candidates = [c for c in ranked_candidates if c.get("stock", 0) > 0]
        if in_stock_candidates:
            cheapest_option = min(
                in_stock_candidates,
                key=lambda c: (c["price"], c["distance_km"] if c["distance_km"] is not None else 99999)
            )
            candidates_with_dist = [c for c in in_stock_candidates if c.get("distance_km") is not None]
            if candidates_with_dist:
                nearest_option = min(
                    candidates_with_dist,
                    key=lambda c: (c["distance_km"], c["price"])
                )
            else:
                nearest_option = in_stock_candidates[0]

        explanation = RecommendationExplainer.generate_explanation(
            best_match=best_match,
            optimization_goal=intent.get("optimization_goal", OptimizationGoal.BEST_VALUE),
            max_distance_km=intent.get("max_distance_km")
        )

        if best_match:
            event_5 = AgentAuditService.log_event(
                session_id=session_id,
                event_type="recommendation",
                state=current_state,
                payload={
                    "pharmacy_id": best_match["pharmacy_id"],
                    "pharmacy_name": best_match["pharmacy_name"],
                    "medicine_id": best_match["medicine_id"],
                    "price": best_match["price"],
                    "distance_km": best_match["distance_km"],
                    "stock": best_match["stock"],
                    "rank": 1
                },
                user=user
            )
            audit_trail.append(event_5)

        # -------------------------------------------------------------
        # STATE 5: AWAITING_APPROVAL (Gate before payment)
        # -------------------------------------------------------------
        current_state = AgentState.AWAITING_APPROVAL

        event_6 = AgentAuditService.log_event(
            session_id=session_id,
            event_type="awaiting_user_approval",
            state=current_state,
            payload={
                "best_match_inventory_id": best_match["inventory_id"] if best_match else None,
                "approval_required": True
            },
            user=user
        )
        audit_trail.append(event_6)

        return {
            "success": True,
            "session_id": session_id,
            "state": current_state,
            "intent": intent,
            "candidates_count": len(ranked_candidates),
            "best_match": best_match,
            "cheapest_option": cheapest_option,
            "nearest_option": nearest_option,
            "other_options": other_options,
            "all_options": ranked_candidates,
            "explanation": explanation,
            "location_needed": location_needed,
            "location_message": location_message,
            "needs_clarification": False,
            "clarification_message": None,
            "medical_safety_warning": None,
            "approval_gate": {
                "status": "AWAITING_APPROVAL",
                "message": "Would you like to purchase this?",
                "ready_for_approval": bool(best_match)
            },
            "audit_trail": audit_trail
        }



    @classmethod
    def handle_user_approval(cls, session_id: str, inventory_id: int, user=None) -> dict:
        """
        Handles explicit user approval gate.
        Transitions state: AWAITING_APPROVAL -> APPROVED.
        Prepares order context for the future Razorpay commerce service.
        """
        try:
            item = Inventory.objects.select_related("medicine", "pharmacy").get(id=inventory_id)
        except Inventory.DoesNotExist:
            return {
                "success": False,
                "state": AgentState.FAILED,
                "message": "Selected inventory item not found."
            }

        # Log User Approval Event
        AgentAuditService.log_event(
            session_id=session_id,
            event_type="user_approval_granted",
            state=AgentState.APPROVED,
            payload={
                "inventory_id": item.id,
                "medicine_name": item.medicine.name,
                "pharmacy_name": item.pharmacy.name,
                "price": float(item.price),
                "approval_timestamp": timezone.now().isoformat()
            },
            user=user
        )

        return {
            "success": True,
            "session_id": session_id,
            "state": AgentState.APPROVED,
            "item": {
                "inventory_id": item.id,
                "medicine_id": item.medicine.id,
                "medicine_name": item.medicine.name,
                "pharmacy_name": item.pharmacy.name,
                "price": float(item.price),
                "quantity": 1
            },
            "approval_message": (
                f"Purchase approved for {item.medicine.name} at {item.pharmacy.name} (₹{item.price:.2f}). "
                f"Payment integration (Razorpay) will execute in the next phase."
            ),
            "next_phase": "RAZORPAY_PAYMENT_INITIATION"
        }
