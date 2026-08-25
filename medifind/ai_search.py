import os
import re
import json
import logging
import urllib.request
import urllib.error
import math
from decimal import Decimal
from django.utils import timezone
from django.db.models import Q
from .models import Medicine, Pharmacy, Inventory
from .fuzzy_search import MedicineMatcher

logger = logging.getLogger(__name__)

# ==========================================================
# 1. Emergency Safety & Triage Patterns
# ==========================================================
EMERGENCY_SYMPTOM_PATTERNS = [
    (r'\b(?:chest\s*pain|heart\s*attack|cardiac\s*arrest|crushing\s*chest)\b', "Potential cardiac emergency"),
    (r'\b(?:difficulty\s*breathing|cannot\s*breathe|shortness\s*of\s*breath|suffocating|choking|gasping)\b', "Severe respiratory distress"),
    (r'\b(?:unconscious|passed\s*out|fainted|unresponsive|collapsed|loss\s*of\s*consciousness)\b', "Loss of consciousness"),
    (r'\b(?:severe\s*bleeding|hemorrhage|uncontrolled\s*bleeding|spurting\s*blood)\b', "Severe hemorrhage / bleeding"),
    (r'\b(?:stroke|facial\s*droop|slurred\s*speech|paralysis|one\s*sided\s*weakness)\b', "Potential stroke symptoms"),
    (r'\b(?:seizure|convulsions|epileptic\s*fit)\b', "Active seizure / convulsions"),
    (r'\b(?:anaphylaxis|throat\s*swelling|tongue\s*swelling|severe\s*allergic\s*reaction)\b', "Severe allergic reaction / anaphylaxis"),
    (r'\b(?:poison|swallowed\s*bleach|overdose|drank\s*chemical|toxic\s*ingestion)\b', "Suspected poisoning / overdose"),
]

# ==========================================================
# 2. Symptom & Generic Category Mappings
# ==========================================================
SYMPTOM_MAP = {
    'fever': {
        'category': 'Pain Relief',
        'generic_name': 'Paracetamol',
        'suggested_medicines': ['Dolo 650', 'Paracetamol 500', 'Crocin', 'Combiflam'],
        'term': 'fever medicine (Paracetamol / Dolo)'
    },
    'headache': {
        'category': 'Pain Relief',
        'generic_name': 'Paracetamol',
        'suggested_medicines': ['Dolo 650', 'Paracetamol 500', 'Combiflam', 'Ibuprofen 400'],
        'term': 'headache medicine (Paracetamol / Ibuprofen)'
    },
    'pain': {
        'category': 'Pain Relief',
        'generic_name': 'Ibuprofen',
        'suggested_medicines': ['Ibuprofen 400', 'Combiflam', 'Dolo 650'],
        'term': 'pain relief medicine'
    },
    'infection': {
        'category': 'Antibiotic',
        'generic_name': 'Amoxicillin',
        'suggested_medicines': ['Amoxicillin 500', 'Azithromycin 500', 'Augmentin 625', 'Ciprofloxacin 500'],
        'term': 'antibiotic medicine (Amoxicillin / Azithromycin)'
    },
    'antibiotic': {
        'category': 'Antibiotic',
        'generic_name': 'Amoxicillin',
        'suggested_medicines': ['Amoxicillin 500', 'Azithromycin 500', 'Augmentin 625'],
        'term': 'antibiotic medicine'
    },
    'vitamin': {
        'category': 'Vitamin',
        'generic_name': 'Vitamin C',
        'suggested_medicines': ['Limcee Vitamin C', 'Calcirol Vitamin D3', 'Becosules Z', 'Neurobion Forte'],
        'term': 'vitamin supplement'
    },
    'allergy': {
        'category': 'Allergy',
        'generic_name': 'Cetirizine',
        'suggested_medicines': ['Cetirizine 10', 'Allegra 120', 'Levocetirizine 5', 'Montair LC'],
        'term': 'allergy medicine (Cetirizine / Allegra)'
    },
    'cold': {
        'category': 'Allergy',
        'generic_name': 'Cetirizine',
        'suggested_medicines': ['Cetirizine 10', 'Allegra 120', 'Levocetirizine 5'],
        'term': 'cold / allergy medicine'
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
        'term': 'diabetes care (Metformin / Insulin)'
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
        'term': 'heart care (Ecosprin / Atorva)'
    },
    'bp': {
        'category': 'Heart',
        'generic_name': 'Amlodipine',
        'suggested_medicines': ['Stamlo Amlodipine', 'Telma 40', 'Atorva 10'],
        'term': 'blood pressure care'
    }
}

KNOWN_MEDICINES = [
    "Dolo 650", "Dolo", "Crocin", "Paracetamol 500", "Paracetamol", "Ibuprofen 400", "Ibuprofen",
    "Combiflam", "Amoxicillin 500", "Amoxicillin", "Azithromycin 500", "Azithromycin",
    "Augmentin 625", "Augmentin", "Ciprofloxacin 500", "Ciprofloxacin", "Limcee Vitamin C",
    "Limcee", "Calcirol Vitamin D3", "Calcirol", "Becosules Z", "Becosules", "Neurobion Forte",
    "Neurobion", "Cetirizine 10", "Cetirizine", "Allegra 120", "Allegra", "Levocetirizine 5",
    "Levocetirizine", "Montair LC", "Montair", "Glycomet Metformin", "Glycomet", "Metformin",
    "Mixtard 30/70 Insulin", "Mixtard", "Insulin", "Amaryl Glimepiride", "Amaryl", "Glimepiride",
    "Januvia Sitagliptin", "Januvia", "Sitagliptin", "Ecosprin 75", "Ecosprin", "Atorva 10",
    "Atorva", "Stamlo Amlodipine", "Stamlo", "Amlodipine", "Telma 40", "Telma"
]


def haversine_distance(lat1, lon1, lat2, lon2) -> float:
    """Calculates distance between two coordinates in kilometers using Haversine formula."""
    try:
        if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
            return 0.0
        R = 6371.0
        dlat = math.radians(float(lat2) - float(lat1))
        dlon = math.radians(float(lon2) - float(lon1))
        a = math.sin(dlat / 2)**2 + math.cos(math.radians(float(lat1))) * math.cos(math.radians(float(lat2))) * math.sin(dlon / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return round(R * c, 2)
    except (ValueError, TypeError):
        return 0.0


# ==========================================================
# 3. Emergency & Safety Detection
# ==========================================================
def detect_emergency_intent(query: str) -> dict:
    """
    Scans the query for acute life-threatening medical emergency symptoms.
    Returns emergency metadata and guidance without diagnosing or prescribing.
    """
    if not query:
        return {"is_emergency": False}

    q_lower = query.lower().strip()
    for pattern, description in EMERGENCY_SYMPTOM_PATTERNS:
        if re.search(pattern, q_lower, re.IGNORECASE):
            return {
                "is_emergency": True,
                "intent": "EMERGENCY_ALERT",
                "condition": description,
                "emergency_message": (
                    "⚠️ Urgent Medical Notice: The symptoms described may indicate an acute medical emergency. "
                    "MediFind AI is an inventory discovery platform and cannot provide emergency care or triage. "
                    "Please immediately call local emergency services (112 / 108 in India, or your local emergency hotline) "
                    "or visit the nearest hospital emergency department."
                ),
                "action": "SEEK_IMMEDIATE_EMERGENCY_CARE"
            }

    return {"is_emergency": False}


# ==========================================================
# 4. Local Rule-Based NLP Intent Extractor (Fallback Engine)
# ==========================================================
def local_rule_based_intent_extractor(query: str, user_lat=None, user_lng=None, default_radius_km=5.0) -> dict:
    """
    Deterministic rule-based intent and entity extractor.
    Guarantees reliable operation when offline or when external AI API keys are unavailable.
    """
    q_lower = query.lower().strip() if query else ""

    # Emergency check
    emergency = detect_emergency_intent(query)
    if emergency.get("is_emergency"):
        return {
            "intent": "EMERGENCY_ALERT",
            "medicine_name": None,
            "brand_name": None,
            "generic_name": None,
            "strength": None,
            "dosage_form": None,
            "location_requested": True,
            "radius_km": default_radius_km,
            "open_now": False,
            "prescription_required": None,
            "quantity": None,
            "ambiguity": False,
            "confidence": 0.99,
            "is_emergency": True,
            "emergency_message": emergency["emergency_message"],
            "search_term": "",
            "interpretation": "Emergency assistance guidance required",
            "fallback": True
        }

    # Intent Classification
    intent = "MEDICINE_SEARCH"
    if re.search(r'\b(?:what is|tell me about|information on|side effects of|uses of|composition of)\b', q_lower):
        intent = "MEDICINE_INFORMATION"
    elif re.search(r'\b(?:available|in stock|stock|do you have|availability)\b', q_lower) and not re.search(r'\b(?:find|nearest|nearby)\s+pharmacy\b', q_lower):
        intent = "AVAILABILITY_SEARCH"
    elif re.search(r'\b(?:pharmacy|pharmacies|chemist|medical store|drugstore)\b', q_lower) and not any(m.lower() in q_lower for m in KNOWN_MEDICINES):
        intent = "PHARMACY_SEARCH"
    elif re.search(r'\b(?:near me|nearby|around here|closest|within \d+)\b', q_lower) and not any(m.lower() in q_lower for m in KNOWN_MEDICINES):
        intent = "NEARBY_SEARCH"
    elif not q_lower or q_lower in ["medicine", "i need medicine", "help", "hello", "hi", "find"]:
        intent = "UNKNOWN"

    # Location Requested Flag
    location_requested = bool(
        "near me" in q_lower or "nearby" in q_lower or "closest" in q_lower or
        "around" in q_lower or "within" in q_lower or user_lat is not None
    )

    # Open Now Flag
    open_now = bool(
        "open now" in q_lower or "open today" in q_lower or "currently open" in q_lower or
        "24/7" in q_lower or "24 hours" in q_lower
    )

    # Radius Extraction
    radius_km = None
    radius_match = re.search(r'(?:within|in|under|less than)?\s*(\d+(?:\.\d+)?)\s*(?:km|kms|kilometer|kilometers)\b', q_lower)
    if radius_match:
        try:
            radius_km = float(radius_match.group(1))
        except ValueError:
            radius_km = default_radius_km
    elif location_requested:
        radius_km = default_radius_km

    # Strength Extraction (e.g., "650 mg", "500mg", "10 mg")
    strength = None
    strength_match = re.search(r'\b(\d+\s*(?:mg|g|mcg|ml|iu|units))\b', q_lower, re.IGNORECASE)
    if strength_match:
        strength = strength_match.group(1).strip()

    # Dosage Form Extraction
    dosage_form = None
    if re.search(r'\b(?:tablet|tablets|tab|tabs)\b', q_lower):
        dosage_form = "tablet"
    elif re.search(r'\b(?:capsule|capsules|cap|caps)\b', q_lower):
        dosage_form = "capsule"
    elif re.search(r'\b(?:syrup|liquid|tonic|suspension)\b', q_lower):
        dosage_form = "syrup"
    elif re.search(r'\b(?:injection|vial|pen|insulin)\b', q_lower):
        dosage_form = "injection"
    elif re.search(r'\b(?:ointment|gel|cream)\b', q_lower):
        dosage_form = "ointment"

    # Quantity Extraction
    quantity = None
    qty_match = re.search(r'\b(\d+)\s*(?:strips?|boxes?|bottles?|packs?|tablets?|units?)\b', q_lower)
    if qty_match:
        try:
            quantity = int(qty_match.group(1))
        except ValueError:
            quantity = None

    # Medicine Name & Brand Matching
    matched_med = None
    brand_name = None
    generic_name = None

    for med in KNOWN_MEDICINES:
        if med.lower() in q_lower:
            matched_med = med
            break

    if not matched_med:
        fuzzy = MedicineMatcher.find_matching_medicines(query, threshold=0.52)
        if fuzzy:
            matched_med = fuzzy[0]["medicine"].name

    # Symptom Mapping
    matched_symptom = None
    symptom_info = None
    for sym_key, info in SYMPTOM_MAP.items():
        if re.search(r'\b' + sym_key + r'\b', q_lower):
            matched_symptom = sym_key
            symptom_info = info
            break

    if matched_med:
        search_term = matched_med
        brand_name = matched_med.split()[0]
        if "dolo" in matched_med.lower() or "crocin" in matched_med.lower() or "paracetamol" in matched_med.lower():
            generic_name = "Paracetamol"
        elif "ibuprofen" in matched_med.lower() or "combiflam" in matched_med.lower():
            generic_name = "Ibuprofen"
        elif "amoxicillin" in matched_med.lower() or "augmentin" in matched_med.lower():
            generic_name = "Amoxicillin"
        elif "azithromycin" in matched_med.lower():
            generic_name = "Azithromycin"
        elif "cetirizine" in matched_med.lower() or "allegra" in matched_med.lower():
            generic_name = "Cetirizine"
        elif "metformin" in matched_med.lower() or "glycomet" in matched_med.lower():
            generic_name = "Metformin"
    elif symptom_info:
        generic_name = symptom_info['generic_name']
        search_term = symptom_info['generic_name']
    else:
        cleaned = re.sub(
            r'\b(?:i need|find|do you have|near me|nearby|something for|where can i get|show me|is|available|pharmacies|pharmacy|within \d+\s*(?:km|kms|kilometer|kilometers)?|open now)\b',
            '', q_lower, flags=re.IGNORECASE
        ).strip()
        search_term = cleaned.title() if cleaned else query.title()

    ambiguity = bool(intent == "UNKNOWN" or (not matched_med and not symptom_info and len(search_term) < 3))

    # Interpretation
    parts = []
    if matched_med:
        parts.append(matched_med)
    elif generic_name:
        parts.append(f"{generic_name} ({matched_symptom.capitalize() if matched_symptom else 'Medicine'})")
    elif search_term:
        parts.append(search_term)

    if strength and (not parts or strength.lower() not in parts[0].lower()):
        parts.append(strength)
    if dosage_form and (not parts or dosage_form not in parts[0].lower()):
        parts.append(f"{dosage_form}s")
    if open_now:
        parts.append("(Open Stores Only)")
    if radius_km:
        parts.append(f"within {int(radius_km) if isinstance(radius_km, float) and radius_km.is_integer() else radius_km} km")
    elif location_requested:
        parts.append("near you")

    interpretation = "Looking for " + " ".join(parts) if parts else f"Searching for '{query}'"

    return {
        "intent": intent,
        "medicine_name": matched_med or (search_term if not symptom_info and not ambiguity else None),
        "brand_name": brand_name,
        "generic_name": generic_name,
        "strength": strength,
        "dosage_form": dosage_form,
        "location_requested": location_requested,
        "radius_km": radius_km or default_radius_km,
        "open_now": open_now,
        "prescription_required": None,
        "quantity": quantity,
        "ambiguity": ambiguity,
        "confidence": 0.95 if matched_med else (0.80 if symptom_info else 0.50),
        "is_emergency": False,
        "emergency_message": None,
        "search_term": search_term,
        "interpretation": interpretation,
        "fallback": True
    }


# ==========================================================
# 5. Gemini Flash Intent Extraction (Operation A)
# ==========================================================
def extract_search_intent_with_gemini(query: str, user_lat=None, user_lng=None, default_radius_km=5.0) -> dict:
    """
    Calls Google Gemini Flash to convert natural language queries into strict structured JSON.
    Never prescribes, diagnoses, or queries databases directly.
    """
    query = (query or "").strip()
    if not query:
        return local_rule_based_intent_extractor("", user_lat, user_lng, default_radius_km)

    # 1. Emergency Safety Filter First
    emergency = detect_emergency_intent(query)
    if emergency.get("is_emergency"):
        return local_rule_based_intent_extractor(query, user_lat, user_lng, default_radius_km)

    api_key = os.environ.get('GEMINI_API_KEY', '').strip() or os.environ.get('AI_API_KEY', '').strip()
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        result = local_rule_based_intent_extractor(query, user_lat, user_lng, default_radius_km)
        result["fallback"] = True
        return result

    system_prompt = """You are the Medifind Intent Extraction Engine for a verified medicine & pharmacy discovery platform.
Convert the user's natural-language request into a STRICT JSON object matching the exact schema below.
You do NOT diagnose diseases, prescribe medication, or give medical advice.
Never invent medicine information.
If the query is ambiguous or unclear, set ambiguity to true and intent to UNKNOWN.

Allowed Intent types:
- MEDICINE_SEARCH: Searching for a specific medicine or brand name
- PHARMACY_SEARCH: Searching for pharmacies or chemists
- AVAILABILITY_SEARCH: Checking if a medicine is currently in stock
- NEARBY_SEARCH: Finding nearby pharmacies within radius
- MEDICINE_INFORMATION: Asking what a medicine is, its generic name, or general uses
- UNKNOWN: Ambiguous, nonsensical, or unrecognized query

JSON Schema:
{
  "intent": "MEDICINE_SEARCH | PHARMACY_SEARCH | AVAILABILITY_SEARCH | NEARBY_SEARCH | MEDICINE_INFORMATION | UNKNOWN",
  "medicine_name": string or null,
  "brand_name": string or null,
  "generic_name": string or null,
  "strength": string or null (e.g. "650 mg", "500 mg"),
  "dosage_form": string or null (e.g. "tablet", "capsule", "syrup", "injection"),
  "location_requested": boolean,
  "radius_km": float or null,
  "open_now": boolean,
  "prescription_required": boolean or null,
  "quantity": integer or null,
  "ambiguity": boolean,
  "confidence": float (between 0.0 and 1.0),
  "search_term": string (clean normalized keyword for database lookup),
  "interpretation": string (e.g. "Looking for Dolo 650 within 5 km")
}
"""

    prompt = f"{system_prompt}\nUser Query: \"{query}\"\nJSON Output:"

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.05,
                "responseMimeType": "application/json"
            }
        }).encode('utf-8')

        req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=4.0) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            text_content = res_data['candidates'][0]['content']['parts'][0]['text']

            if "```" in text_content:
                text_content = re.sub(r'```json\s*', '', text_content)
                text_content = re.sub(r'```\s*$', '', text_content)

            parsed = json.loads(text_content.strip())
            parsed["fallback"] = False
            parsed["is_emergency"] = False
            parsed["emergency_message"] = None
            if not parsed.get("radius_km"):
                parsed["radius_km"] = default_radius_km
            if not parsed.get("interpretation"):
                parsed["interpretation"] = f"Searching for {parsed.get('search_term') or query}"
            return parsed

    except Exception as e:
        logger.warning(f"Gemini intent extraction fallback triggered: {e}")
        result = local_rule_based_intent_extractor(query, user_lat, user_lng, default_radius_km)
        result["fallback_reason"] = str(e)
        return result


# ==========================================================
# 6. Database Search & Deterministic Multi-Factor Ranking
# ==========================================================
def search_database_with_intent(intent_data: dict, user_lat=None, user_lng=None, default_radius_km=5.0) -> dict:
    """
    Step 2: Searches Medifind PostgreSQL/SQLite DB using extracted structured parameters.
    The database is the absolute source of truth.
    Ranks pharmacies deterministically by:
      - Availability & in-stock quantity
      - SKU match exactness
      - Road/Haversine distance
      - Operating status (Open Now)
      - Verification status (Approved)
      - Price competitiveness
    """
    if intent_data.get("is_emergency"):
        return {
            "medicines": [],
            "pharmacies": [],
            "total_stock_count": 0,
            "is_emergency": True,
            "emergency_message": intent_data.get("emergency_message")
        }

    search_term = intent_data.get("search_term") or intent_data.get("medicine_name") or intent_data.get("generic_name") or ""
    strength = intent_data.get("strength")
    dosage_form = intent_data.get("dosage_form")
    open_now_only = intent_data.get("open_now", False)
    radius_km = intent_data.get("radius_km") or default_radius_km

    calc_lat = user_lat if user_lat is not None else 13.0827
    calc_lng = user_lng if user_lng is not None else 80.2707
    current_time = timezone.localtime().time()

    # 1. Match Medicines in Catalog
    medicine_qs = Medicine.objects.none()
    if search_term:
        # Exact / Substring / Brand Match
        medicine_qs = Medicine.objects.filter(
            Q(name__icontains=search_term) |
            Q(brand__icontains=search_term) |
            Q(category__icontains=search_term) |
            Q(uses__icontains=search_term) |
            Q(description__icontains=search_term)
        )

        if not medicine_qs.exists():
            fuzzy = MedicineMatcher.find_matching_medicines(search_term, threshold=0.45)
            if fuzzy:
                matched_ids = [f["medicine"].id for f in fuzzy]
                medicine_qs = Medicine.objects.filter(id__in=matched_ids)

    matched_medicines_data = []
    for med in medicine_qs[:5]:
        matched_medicines_data.append({
            "id": med.id,
            "name": med.name,
            "brand": med.brand,
            "category": med.category,
            "dosage": med.dosage,
            "prescription_required": med.prescription_required,
            "uses": med.uses,
            "side_effects": med.side_effects
        })

    # 2. Query Inventories from Active Pharmacies
    inv_qs = Inventory.objects.select_related("medicine", "pharmacy").filter(
        pharmacy__is_active=True
    )

    if medicine_qs.exists():
        inv_qs = inv_qs.filter(medicine__in=medicine_qs)
    elif search_term:
        inv_qs = inv_qs.filter(
            Q(medicine__name__icontains=search_term) |
            Q(medicine__brand__icontains=search_term) |
            Q(pharmacy__name__icontains=search_term)
        )

    # 3. Deterministic Server-Side Ranking Engine
    pharmacies_map = {}
    for inv in inv_qs:
        pharm = inv.pharmacy
        dist_km = haversine_distance(calc_lat, calc_lng, float(pharm.latitude), float(pharm.longitude))

        # Radius boundary check
        if radius_km and dist_km > radius_km:
            continue

        is_store_open = pharm.is_open and (pharm.opening_time <= current_time <= pharm.closing_time)
        if open_now_only and not is_store_open:
            continue

        # Compute Transparent Deterministic Ranking Score
        # 1. Availability Score (0 to 40 pts)
        avail_score = 40 if inv.quantity > 10 else (25 if inv.quantity > 0 else 0)

        # 2. Distance Score (0 to 30 pts: closer = higher)
        dist_score = max(0, 30 - (dist_km * 3))

        # 3. Open Now Score (0 to 15 pts)
        open_score = 15 if is_store_open else 0

        # 4. Verified Store Score (0 to 10 pts)
        verif_score = 10 if pharm.verification_status == "Approved" else 0

        # 5. Price Competitiveness (0 to 5 pts)
        price_score = max(0, 5 - float(inv.price) * 0.02) if inv.price else 0

        total_score = round(avail_score + dist_score + open_score + verif_score + price_score, 2)

        pharm_entry = {
            "id": pharm.id,
            "name": pharm.name,
            "phone": pharm.phone,
            "address": pharm.address,
            "city": pharm.city,
            "latitude": float(pharm.latitude),
            "longitude": float(pharm.longitude),
            "distance_km": dist_km,
            "is_open_now": is_store_open,
            "closing_time": pharm.closing_time.strftime("%I:%M %p") if pharm.closing_time else "",
            "verified": pharm.verification_status == "Approved",
            "medicine_id": inv.medicine.id,
            "medicine_name": inv.medicine.name,
            "medicine_brand": inv.medicine.brand,
            "dosage": inv.medicine.dosage,
            "prescription_required": inv.medicine.prescription_required,
            "inventory_id": inv.id,
            "stock_quantity": inv.quantity,
            "in_stock": inv.quantity > 0,
            "price": float(inv.price),
            "price_formatted": f"₹{inv.price:.2f}",
            "rank_score": total_score,
            "scoring_breakdown": {
                "availability": avail_score,
                "distance": round(dist_score, 1),
                "open_now": open_score,
                "verified": verif_score,
                "price": round(price_score, 1)
            }
        }

        if pharm.id not in pharmacies_map or total_score > pharmacies_map[pharm.id]["rank_score"]:
            pharmacies_map[pharm.id] = pharm_entry

    ranked_pharmacies = sorted(pharmacies_map.values(), key=lambda p: p["rank_score"], reverse=True)

    return {
        "medicines": matched_medicines_data,
        "pharmacies": ranked_pharmacies,
        "total_matches": len(ranked_pharmacies),
        "total_stock_count": sum(p["stock_quantity"] for p in ranked_pharmacies),
        "is_emergency": False,
        "emergency_message": None
    }


# ==========================================================
# 7. Grounded Response Generation (Operation B)
# ==========================================================
def generate_grounded_ai_response(query: str, intent_data: dict, db_results: dict) -> str:
    """
    Synthesizes a natural language response grounded strictly in actual database records.
    Gemini is given ONLY the verified records returned from Medifind DB.
    Never hallucinates stock or pharmacies.
    """
    if db_results.get("is_emergency"):
        return db_results.get("emergency_message")

    pharmacies = db_results.get("pharmacies", [])
    medicines = db_results.get("medicines", [])
    intent = intent_data.get("intent", "MEDICINE_SEARCH")

    # If no results found in DB
    if not pharmacies and not medicines:
        med_name = intent_data.get("medicine_name") or intent_data.get("search_term") or query
        return (
            f"I couldn't find '{med_name}' in the verified pharmacies within your selected area. "
            f"You can try expanding your search radius, checking for alternative brand names, "
            f"or subscribing to a stock restock alert."
        )

    # Medicine Information Intent
    if intent == "MEDICINE_INFORMATION" and medicines:
        med = medicines[0]
        resp = f"**{med['name']}** ({med['brand']}) is categorized under {med['category']}. "
        if med.get("uses"):
            resp += f"Common uses include {med['uses']}. "
        if med.get("prescription_required"):
            resp += "⚠️ Prescription required. "
        if pharmacies:
            resp += f"Currently available at {len(pharmacies)} nearby partner pharmacies starting from {pharmacies[0]['price_formatted']}."
        return resp

    # Standard Grounded Synthesis Prompt for Gemini
    api_key = os.environ.get('GEMINI_API_KEY', '').strip() or os.environ.get('AI_API_KEY', '').strip()
    if api_key and api_key != "YOUR_API_KEY_HERE" and pharmacies:
        prompt = f"""You are Medifind AI, an intelligent pharmacy assistant.
Generate a concise, friendly, 2-to-3 sentence summary explaining the search results to the user.

STRICT GROUNDING RULES:
1. ONLY use the verified database results provided below.
2. NEVER mention any pharmacy, medicine, price, or stock not present in the verified data.
3. Highlight the closest store and best price.
4. Do NOT prescribe, diagnose, or give medical advice.
5. If prescription is required, remind the user to carry a valid doctor prescription.

User Query: "{query}"
Verified Pharmacy Results:
{json.dumps([{
    "pharmacy": p["name"],
    "distance_km": p["distance_km"],
    "medicine": p["medicine_name"],
    "price": p["price_formatted"],
    "stock": p["stock_quantity"],
    "is_open": p["is_open_now"],
    "rx_required": p["prescription_required"]
} for p in pharmacies[:4]], indent=2)}

Explanation:"""

        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
            payload = json.dumps({
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.1}
            }).encode('utf-8')

            req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=3.5) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                grounded_text = res_data['candidates'][0]['content']['parts'][0]['text'].strip()
                if grounded_text:
                    return grounded_text
        except Exception as e:
            logger.warning(f"Grounded response generation fallback: {e}")

    # Deterministic Clean Template Fallback
    if not pharmacies:
        med_name = intent_data.get("medicine_name") or intent_data.get("search_term") or query
        return f"I couldn't find active pharmacies stocking '{med_name}' matching your filters in the selected radius."

    top_store = pharmacies[0]
    available_stores = [p for p in pharmacies if p.get("in_stock")]
    count = len(available_stores)
    med_name = top_store.get("medicine_name") or query

    if count == 1:
        text = f"I found **{med_name}** in stock at **{top_store['name']}** ({top_store['distance_km']} km away) for **{top_store['price_formatted']}**."
    elif count > 1:
        text = f"I found **{med_name}** available at **{count} nearby pharmacies**. **{top_store['name']}** is the closest match at **{top_store['distance_km']} km** ({top_store['price_formatted']})."
    else:
        text = f"I found {len(pharmacies)} pharmacies listing **{med_name}**, but units are currently reserved or awaiting restock."

    if top_store.get("prescription_required"):
        text += " ⚠️ Please ensure you bring a valid prescription."

    return text


# ==========================================================
# 8. Master AI Search Pipeline Orchestrator
# ==========================================================
def execute_ai_medicine_search_pipeline(query: str, user_lat=None, user_lng=None, radius_km=None) -> dict:
    """
    Executes the full end-to-end Medifind AI pipeline:
    Query -> Intent Extraction -> DB Retrieval -> Ranking -> Grounded Response.
    """
    t_start = timezone.now()
    clean_query = (query or "").strip()

    # 1. Intent Extraction
    intent_data = extract_search_intent_with_gemini(
        query=clean_query,
        user_lat=user_lat,
        user_lng=user_lng,
        default_radius_km=radius_km or 5.0
    )

    # 2. Database Retrieval & Ranking
    db_results = search_database_with_intent(
        intent_data=intent_data,
        user_lat=user_lat,
        user_lng=user_lng,
        default_radius_km=radius_km or intent_data.get("radius_km", 5.0)
    )

    # 3. Grounded Response Generation
    ai_response = generate_grounded_ai_response(
        query=clean_query,
        intent_data=intent_data,
        db_results=db_results
    )

    duration_ms = int((timezone.now() - t_start).total_seconds() * 1000)

    return {
        "success": True,
        "query": clean_query,
        "intent": intent_data.get("intent", "MEDICINE_SEARCH"),
        "interpretation": intent_data.get("interpretation"),
        "is_emergency": db_results.get("is_emergency", False),
        "ai_response": ai_response,
        "medicines": db_results.get("medicines", []),
        "pharmacies": db_results.get("pharmacies", []),
        "total_results": len(db_results.get("pharmacies", [])),
        "total_stock": db_results.get("total_stock_count", 0),
        "radius_km": intent_data.get("radius_km"),
        "confidence": intent_data.get("confidence", 0.9),
        "ambiguity": intent_data.get("ambiguity", False),
        "duration_ms": duration_ms
    }

# Backward compatibility alias
parse_query_with_ai = extract_search_intent_with_gemini


