"""
MedFinder Fuzzy Matching & Medicine Normalization Engine
Provides fault-tolerant medicine search, typo correction, phonetic/edit-distance matching,
and brand-to-generic alias resolution.
"""

import re
import difflib
from decimal import Decimal
from typing import List, Tuple, Optional, Dict, Any

# Common brand-to-generic & spelling alias lookup
MEDICINE_ALIASES = {
    # Paracetamol / Dolo / Crocin / Calpol
    "dolo": "Dolo 650",
    "dollo": "Dolo 650",
    "doloo": "Dolo 650",
    "dolu": "Dolo 650",
    "dolo650": "Dolo 650",
    "dollo650": "Dolo 650",
    "dolo 650": "Dolo 650",
    "crocin": "Crocin",
    "crocine": "Crocin",
    "crocin650": "Crocin",
    "calpol": "Paracetamol 500",
    "calpol500": "Paracetamol 500",
    "calpol 500": "Paracetamol 500",
    "paracetamol": "Paracetamol 500",
    "paractamol": "Paracetamol 500",
    "paracetmol": "Paracetamol 500",
    "paracitamol": "Paracetamol 500",
    "paracetamol650": "Dolo 650",
    "paracetamol 650": "Dolo 650",
    "paracetamol 500": "Paracetamol 500",
    "pcm": "Paracetamol 500",

    # Pain Relief / Anti-inflammatory
    "combiflam": "Combiflam",
    "combiflem": "Combiflam",
    "combiflame": "Combiflam",
    "ibuprofen": "Ibuprofen 400",
    "ibugesic": "Ibuprofen 400",
    "advil": "Ibuprofen 400",
    "brufen": "Ibuprofen 400",

    # Antibiotics
    "amoxicillin": "Amoxicillin 500",
    "amoxilin": "Amoxicillin 500",
    "amoxycillin": "Amoxicillin 500",
    "amoxicilin": "Amoxicillin 500",
    "mox": "Amoxicillin 500",
    "mox500": "Amoxicillin 500",
    "novamox": "Amoxicillin 500",
    "augmentin": "Augmentin 625",
    "augmentn": "Augmentin 625",
    "augmetin": "Augmentin 625",
    "amoxyclav": "Augmentin 625",
    "amoxiclav": "Augmentin 625",
    "azithromycin": "Azithromycin 500",
    "azithromicin": "Azithromycin 500",
    "azithral": "Azithromycin 500",
    "azithral500": "Azithromycin 500",
    "azithro": "Azithromycin 500",
    "aziwok": "Azithromycin 500",
    "zithromax": "Azithromycin 500",
    "ciprofloxacin": "Ciprofloxacin 500",
    "cipro": "Ciprofloxacin 500",
    "ciplox": "Ciprofloxacin 500",
    "ciprobid": "Ciprofloxacin 500",

    # Allergy / Antihistamine
    "cetirizine": "Cetirizine 10",
    "cetrizin": "Cetirizine 10",
    "cetrizine": "Cetirizine 10",
    "citrizine": "Cetirizine 10",
    "cetirizne": "Cetirizine 10",
    "cetcip": "Cetirizine 10",
    "alerid": "Cetirizine 10",
    "zyrtec": "Cetirizine 10",
    "levocetirizine": "Levocetirizine 5",
    "levocet": "Levocetirizine 5",
    "levorid": "Levocetirizine 5",
    "allegra": "Allegra 120",
    "allegra120": "Allegra 120",
    "fexofenadine": "Allegra 120",
    "fexova": "Allegra 120",
    "montair": "Montair LC",
    "montair lc": "Montair LC",
    "montairlc": "Montair LC",
    "montelukast": "Montair LC",
    "montek lc": "Montair LC",

    # Antacids / Gastrointestinal
    "pantoprazole": "Pantocid 40",
    "pantop": "Pantocid 40",
    "pantocid": "Pantocid 40",
    "pan 40": "Pantocid 40",
    "pan40": "Pantocid 40",
    "pan d": "Pantocid 40",
    "pan-d": "Pantocid 40",
    "pantodac": "Pantocid 40",
    "pantosec": "Pantocid 40",
    "omeprazole": "Omez 20",
    "omez": "Omez 20",
    "rabeprazole": "Rablet 20",
    "rablet": "Rablet 20",
    "gelusil": "Gelusil Antacid",
    "digene": "Digene Gel",

    # Diabetes
    "metformin": "Glycomet Metformin",
    "metformn": "Glycomet Metformin",
    "glycomet": "Glycomet Metformin",
    "glycomet500": "Glycomet Metformin",
    "glimet": "Glycomet Metformin",
    "insulin": "Mixtard 30/70 Insulin",
    "inslin": "Mixtard 30/70 Insulin",
    "mixtard": "Mixtard 30/70 Insulin",
    "humalog": "Mixtard 30/70 Insulin",
    "novorapid": "Mixtard 30/70 Insulin",
    "glimepiride": "Amaryl Glimepiride",
    "amaryl": "Amaryl Glimepiride",
    "sitagliptin": "Januvia Sitagliptin",
    "januvia": "Januvia Sitagliptin",

    # Heart & Blood Pressure
    "aspirin": "Ecosprin 75",
    "asprin": "Ecosprin 75",
    "ecosprin": "Ecosprin 75",
    "ecosprin75": "Ecosprin 75",
    "disprin": "Ecosprin 75",
    "atorvastatin": "Atorva 10",
    "atorva": "Atorva 10",
    "atorva10": "Atorva 10",
    "lipitor": "Atorva 10",
    "amlodipine": "Stamlo Amlodipine",
    "stamlo": "Stamlo Amlodipine",
    "norvasc": "Stamlo Amlodipine",
    "telmisartan": "Telma 40",
    "telma": "Telma 40",
    "telma40": "Telma 40",
    "telmikind": "Telma 40",

    # Vitamins & Supplements
    "limcee": "Limcee Vitamin C",
    "limce": "Limcee Vitamin C",
    "vitamin c": "Limcee Vitamin C",
    "vit c": "Limcee Vitamin C",
    "calcirol": "Calcirol Vitamin D3",
    "vitamin d3": "Calcirol Vitamin D3",
    "vit d3": "Calcirol Vitamin D3",
    "becosules": "Becosules Z",
    "becosule": "Becosules Z",
    "becosules z": "Becosules Z",
    "b complex": "Becosules Z",
    "neurobion": "Neurobion Forte",
    "neurobian": "Neurobion Forte",
    "neurobion forte": "Neurobion Forte",
    "vitamin b12": "Neurobion Forte",
    "vit b12": "Neurobion Forte",
}


class MedicineMatcher:
    """
    High-performance fuzzy matching & query correction service for MedFinder.
    """

    @classmethod
    def clean_query(cls, query: str) -> str:
        """Strips noise words, dosage numbers, and punctuation for pure name matching."""
        if not query:
            return ""
        q = query.lower().strip()
        # Remove common filler phrases
        q = re.sub(
            r'\b(i need|find|search|buy|do you have|give me|medicine for|tablet|tablets|capsule|capsules|syrup|mg|g|mcg|ml|iu|within \d+.*|nearby|near me|urgent|urgently)\b',
            ' ',
            q,
            flags=re.IGNORECASE
        )
        # Strip special punctuation but preserve alphanumeric
        q = re.sub(r'[^a-zA-Z0-9\s]', ' ', q)
        return ' '.join(q.split()).strip()

    @classmethod
    def compute_similarity(cls, str1: str, str2: str) -> float:
        """
        Computes hybrid similarity ratio taking full string, token matching,
        and character prefixes into account.
        """
        s1 = str1.lower().strip()
        s2 = str2.lower().strip()

        if not s1 or not s2:
            return 0.0

        if s1 == s2:
            return 1.0

        # Exact substring match gives high base score
        if s1 in s2 or s2 in s1:
            len_ratio = min(len(s1), len(s2)) / max(len(s1), len(s2))
            return 0.80 + (0.20 * len_ratio)

        # Full SequenceMatcher ratio
        full_ratio = difflib.SequenceMatcher(None, s1, s2).ratio()

        # Token-level best match
        tokens1 = s1.split()
        tokens2 = s2.split()
        token_scores = []
        for t1 in tokens1:
            if len(t1) < 2:
                continue
            best_t_score = 0.0
            for t2 in tokens2:
                if len(t2) < 2:
                    continue
                ratio = difflib.SequenceMatcher(None, t1, t2).ratio()
                if ratio > best_t_score:
                    best_t_score = ratio
            token_scores.append(best_t_score)

        avg_token_score = (sum(token_scores) / len(token_scores)) if token_scores else 0.0

        # Prefix bonus (if first 3 characters match, e.g. 'dol' in 'dollo' and 'dolo')
        prefix_bonus = 0.0
        if len(s1) >= 3 and len(s2) >= 3 and s1[:3] == s2[:3]:
            prefix_bonus = 0.08

        return min(1.0, max(full_ratio, avg_token_score) + prefix_bonus)

    @classmethod
    def resolve_medicine_alias(cls, query: str) -> Optional[str]:
        """
        Checks if query matches or is near any known medicine alias.
        """
        cleaned = cls.clean_query(query)
        if not cleaned:
            return None

        # 1. Direct dictionary match
        if cleaned in MEDICINE_ALIASES:
            return MEDICINE_ALIASES[cleaned]

        # 2. Token match against dictionary keys
        for key, target in MEDICINE_ALIASES.items():
            if key in cleaned or cleaned in key:
                return target

        # 3. Fuzzy match against dictionary keys (e.g. 'dollo' -> 'dolo' -> 'Dolo 650')
        best_key = None
        best_ratio = 0.0
        for key in MEDICINE_ALIASES.keys():
            ratio = difflib.SequenceMatcher(None, cleaned, key).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_key = key

        if best_ratio >= 0.70 and best_key:
            return MEDICINE_ALIASES[best_key]

        return None

    @classmethod
    def find_matching_medicines(cls, query: str, threshold: float = 0.52, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Finds matching Medicine model records from Django DB using alias resolution
        and fuzzy multi-field similarity.
        """
        from .models import Medicine

        cleaned_q = cls.clean_query(query)
        if not cleaned_q and not query:
            return []

        alias_target = cls.resolve_medicine_alias(query)

        # Load candidate medicines from DB
        all_meds = Medicine.objects.all()
        scored_medicines = []

        for med in all_meds:
            # Fields to compare
            med_name = med.name or ""
            med_brand = med.brand or ""
            med_category = med.category or ""
            med_desc = med.description or ""
            med_uses = med.uses or ""

            # Score against alias target if resolved
            alias_score = 0.0
            if alias_target:
                alias_score = cls.compute_similarity(alias_target, med_name)

            # Score against raw query and cleaned query
            score_name = max(
                cls.compute_similarity(query, med_name),
                cls.compute_similarity(cleaned_q, med_name)
            )
            score_brand = max(
                cls.compute_similarity(query, med_brand),
                cls.compute_similarity(cleaned_q, med_brand)
            )
            score_cat = cls.compute_similarity(cleaned_q, med_category) * 0.75
            score_desc = 0.70 if (cleaned_q and cleaned_q in med_desc.lower()) else 0.0
            score_uses = 0.70 if (cleaned_q and cleaned_q in med_uses.lower()) else 0.0

            final_score = max(alias_score, score_name, score_brand, score_cat, score_desc, score_uses)

            # Check if query matches distinct word tokens (ignoring pure numbers/dosage tokens)
            q_words = [w for w in cleaned_q.split() if len(w) > 2 and not re.match(r'^\d+(?:mg|ml|g)?$', w)]
            name_words = [w.lower() for w in med_name.split() if not re.match(r'^\d+(?:mg|ml|g)?$', w.lower())]
            for qw in q_words:
                for nw in name_words:
                    if difflib.SequenceMatcher(None, qw, nw).ratio() >= 0.82:
                        final_score = max(final_score, 0.80)

            if final_score >= threshold:
                scored_medicines.append({
                    "medicine": med,
                    "score": final_score,
                    "matched_field": "name" if score_name >= score_brand else "brand",
                    "suggested_correction": alias_target or med.name
                })

        # Sort by similarity score descending
        scored_medicines.sort(key=lambda x: x["score"], reverse=True)

        if scored_medicines:
            top_score = scored_medicines[0]["score"]
            # If we have an exact or high match (>= 0.85), only include close matches
            if top_score >= 0.85:
                scored_medicines = [m for m in scored_medicines if m["score"] >= max(threshold, top_score - 0.18)]

        return scored_medicines[:limit]

    @classmethod
    def get_suggested_correction(cls, query: str) -> Optional[str]:
        """
        Returns a friendly 'Did you mean X?' correction string if query is misspelled.
        """
        matches = cls.find_matching_medicines(query, threshold=0.55, limit=1)
        if matches:
            top_match = matches[0]
            top_med = top_match["medicine"]
            # If the query is not an exact substring of the medicine name, suggest the correction
            if query.lower().strip() not in top_med.name.lower():
                return top_med.name
        return None
