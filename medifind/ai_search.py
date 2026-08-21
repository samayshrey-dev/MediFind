import os
import re
import json
import urllib.request
import urllib.error
import math

# ==========================================================
# Symptom & Category Mapping for Medical Safety & Search Normalization
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

# Known brand names & medicines in MedFinder DB
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

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculates distance between two coordinates in kilometers using Haversine formula."""
    try:
        R = 6371.0
        dlat = math.radians(float(lat2) - float(lat1))
        dlon = math.radians(float(lon2) - float(lon1))
        a = math.sin(dlat / 2)**2 + math.cos(math.radians(float(lat1))) * math.cos(math.radians(float(lat2))) * math.sin(dlon / 2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c
    except (ValueError, TypeError):
        return 0.0

def local_fallback_parser(query: str) -> dict:
    """Intelligent local query normalizer used when AI API key is missing or offline."""
    q_lower = query.lower().strip() if query else ""
    
    if not q_lower:
        return {
            "intent": "medicine_search",
            "medicine_name": None,
            "generic_name": None,
            "strength": None,
            "dosage_form": None,
            "quantity": None,
            "radius_km": None,
            "symptom_category": None,
            "search_term": "",
            "interpretation": None,
            "warning": None,
            "fallback": True
        }

    # Extract radius if specified (e.g. "within 3 km", "3km", "in 5 kilometers")
    radius_km = None
    radius_match = re.search(r'(?:within|in|under|less than)?\s*(\d+(?:\.\d+)?)\s*(?:km|kms|kilometer|kilometers)', q_lower)
    if radius_match:
        try:
            radius_km = float(radius_match.group(1))
        except ValueError:
            radius_km = None

    # Extract strength (e.g. "650 mg", "500mg", "120 mg", "650mg")
    strength = None
    strength_match = re.search(r'\b(\d+\s*(?:mg|g|mcg|ml|iu|units))\b', q_lower, re.IGNORECASE)
    if strength_match:
        strength = strength_match.group(1)

    # Extract dosage form (e.g. tablet, capsule, syrup, injection)
    dosage_form = None
    if re.search(r'\b(tablet|tablets|tab|tabs)\b', q_lower):
        dosage_form = "tablet"
    elif re.search(r'\b(capsule|capsules|cap)\b', q_lower):
        dosage_form = "capsule"
    elif re.search(r'\b(syrup|liquid)\b', q_lower):
        dosage_form = "syrup"
    elif re.search(r'\b(insulin|injection|vial|pen)\b', q_lower):
        dosage_form = "injection"

    # Check for known medicine name match
    matched_med = None
    for med in KNOWN_MEDICINES:
        if med.lower() in q_lower:
            matched_med = med
            break

    # Check for symptom match
    matched_symptom = None
    symptom_info = None
    for sym_key, info in SYMPTOM_MAP.items():
        if re.search(r'\b' + sym_key + r'\b', q_lower):
            matched_symptom = sym_key
            symptom_info = info
            break

    generic_name = None
    symptom_category = None
    search_term = ""

    if matched_med:
        search_term = matched_med
        if "dolo" in matched_med.lower() or "crocin" in matched_med.lower() or "paracetamol" in matched_med.lower():
            generic_name = "Paracetamol"
        elif "ibuprofen" in matched_med.lower() or "combiflam" in matched_med.lower():
            generic_name = "Ibuprofen"
        elif "amoxicillin" in matched_med.lower() or "augmentin" in matched_med.lower():
            generic_name = "Amoxicillin"
        elif "azithromycin" in matched_med.lower():
            generic_name = "Azithromycin"
        elif "cetirizine" in matched_med.lower() or "allegra" in matched_med.lower():
            generic_name = "Cetirizine / Fexofenadine"
        elif "metformin" in matched_med.lower() or "glycomet" in matched_med.lower():
            generic_name = "Metformin"
    elif symptom_info:
        symptom_category = symptom_info['category']
        generic_name = symptom_info['generic_name']
        search_term = symptom_info['generic_name']
    else:
        cleaned = re.sub(r'\b(i need|find|do you have|near me|nearby|something for|within \d+\s*(?:km|kms|kilometer|kilometers)?|tablets|tablet|capsule|capsules)\b', '', q_lower, flags=re.IGNORECASE).strip()
        search_term = cleaned.title() if cleaned else query.title()

    # Build human-readable interpretation
    parts = []
    if matched_med:
        parts.append(matched_med)
    elif generic_name:
        parts.append(f"{generic_name} ({matched_symptom.capitalize() if matched_symptom else 'Medicine'})")
    elif search_term:
        parts.append(search_term)

    if strength and (not parts or strength not in parts[0]):
        parts.append(strength)
    if dosage_form and (not parts or dosage_form not in parts[0]):
        parts.append(f"{dosage_form}s")

    if radius_km:
        parts.append(f"within {int(radius_km) if radius_km.is_integer() else radius_km} km")
    elif "near me" in q_lower or "nearby" in q_lower:
        parts.append("near you")

    interpretation = "Looking for " + " ".join(parts) if parts else f"Searching for '{query}'"

    return {
        "intent": "medicine_search",
        "medicine_name": matched_med or (search_term if not symptom_info else None),
        "generic_name": generic_name,
        "strength": strength,
        "dosage_form": dosage_form,
        "quantity": None,
        "radius_km": radius_km,
        "symptom_category": symptom_category,
        "search_term": search_term,
        "interpretation": interpretation,
        "warning": None,
        "fallback": True
    }

def parse_query_with_ai(query: str) -> dict:
    """Analyzes a natural language query using AI / NLP query normalizer."""
    query = (query or "").strip()
    if not query:
        return local_fallback_parser("")

    api_key = os.environ.get('AI_API_KEY', '').strip() or os.environ.get('GEMINI_API_KEY', '').strip()
    
    # Check if API key is missing or default placeholder
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        result = local_fallback_parser(query)
        result["warning"] = None
        return result

    # Construct System & User Prompt for Structured JSON Extraction
    prompt = f"""You are an AI search query normalizer for MedFinder (a medicine locator app).
Analyze the user's natural language search query and extract structured search parameters.

Return ONLY a JSON object strictly matching this schema:
{{
  "intent": "medicine_search",
  "medicine_name": "exact brand or product name if specified (e.g. 'Dolo 650', 'Crocin', or null)",
  "generic_name": "chemical / active ingredient name (e.g. 'Paracetamol', 'Amoxicillin', or null)",
  "strength": "dosage strength if mentioned (e.g. '650 mg', '500 mg', or null)",
  "dosage_form": "dosage form if mentioned (e.g. 'tablet', 'capsule', 'syrup', or null)",
  "quantity": null,
  "radius_km": float or null (extract number if query specifies e.g. 'within 3 km' -> 3),
  "symptom_category": "symptom/category if mentioned (e.g. 'Pain Relief', 'Antibiotic', 'Vitamin', 'Allergy', 'Diabetes', 'Heart', or null)",
  "search_term": "clean normalized search term for database lookup",
  "interpretation": "clear user-facing summary string starting with 'Looking for ...'"
}}

User query: "{query}"
"""

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
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
            parsed["warning"] = None
            parsed["fallback"] = False
            
            if not parsed.get("interpretation"):
                parsed["interpretation"] = f"Looking for {parsed.get('search_term') or query} near you"
                
            return parsed

    except Exception as e:
        result = local_fallback_parser(query)
        result["warning"] = None
        result["fallback_reason"] = str(e)
        return result
