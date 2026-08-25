"""
Medifind AI #3 — Medicine Intelligence & Semantic Understanding Engine
Provides deterministic normalization, exact database matching, brand/generic alias resolution,
controlled fuzzy similarity, semantic candidate ranking, ambiguity detection, and data-quality analysis.
"""

import os
import re
import json
import logging
import math
from decimal import Decimal
from typing import List, Dict, Any, Optional, Tuple
from django.db.models import Q, Count
from .models import Medicine, Pharmacy, Inventory
from .fuzzy_search import MedicineMatcher, MEDICINE_ALIASES

logger = logging.getLogger(__name__)

# Standard Unit Conversion Mappings
UNIT_CONVERSIONS = [
    (r'\b0\.5\s*g\b', '500 mg'),
    (r'\b1\s*g\b', '1000 mg'),
    (r'\b2\s*g\b', '2000 mg'),
    (r'\b(\d+)\s*mg\b', r'\1 mg'),
    (r'\b(\d+)\s*g\b', r'\1 g'),
    (r'\b(\d+)\s*mcg\b', r'\1 mcg'),
    (r'\b(\d+)\s*ml\b', r'\1 ml'),
]

DOSAGE_FORMS = [
    'tablet', 'tablets', 'tab',
    'capsule', 'capsules', 'cap',
    'syrup', 'suspension', 'liquid',
    'ointment', 'cream', 'gel',
    'drops', 'injection', 'sachet', 'spray'
]


# ==========================================================
# 1. Normalization Service
# ==========================================================
class NormalizationService:
    """
    Normalizes medicine queries, strength units, and dosage forms deterministically.
    Does NOT make medical conversions or invent dosage data.
    """

    @classmethod
    def normalize_units(cls, query: str) -> str:
        """Converts unit variations into standard format (e.g., '650mg' -> '650 mg', '1g' -> '1000 mg')."""
        if not query:
            return ""
        q = query.strip()
        # Separate numbers and units if joined (e.g. 650mg -> 650 mg)
        q = re.sub(r'(\d+)\s*(mg|g|mcg|ml|iu)\b', r'\1 \2', q, flags=re.IGNORECASE)

        for pattern, repl in UNIT_CONVERSIONS:
            q = re.sub(pattern, repl, q, flags=re.IGNORECASE)
        return q

    @classmethod
    def extract_dosage_form(cls, query: str) -> Optional[str]:
        """Extracts recognized dosage form from query."""
        q_lower = query.lower() if query else ""
        for form in DOSAGE_FORMS:
            if re.search(r'\b' + form + r'\b', q_lower):
                if form in ['tab', 'tablets']:
                    return 'Tablet'
                elif form in ['cap', 'capsules']:
                    return 'Capsule'
                elif form in ['liquid', 'suspension']:
                    return 'Syrup'
                return form.capitalize()
        return None

    @classmethod
    def extract_strength(cls, query: str) -> Optional[str]:
        """Extracts strength value and unit from query."""
        q_norm = cls.normalize_units(query)
        match = re.search(r'\b(\d+(?:\.\d+)?\s*(?:mg|g|mcg|ml|iu))\b', q_norm, re.IGNORECASE)
        return match.group(1).strip() if match else None

    @classmethod
    def clean_medicine_name(cls, query: str) -> str:
        """Strips noise phrases, dosage numbers, and strength to isolate medicine candidate name."""
        if not query:
            return ""
        cleaned = MedicineMatcher.clean_query(query)
        # Strip strength numbers
        cleaned = re.sub(r'\b\d+(?:\.\d+)?\s*(?:mg|g|mcg|ml|iu)?\b', '', cleaned, flags=re.IGNORECASE)
        # Strip dosage forms
        for form in DOSAGE_FORMS:
            cleaned = re.sub(r'\b' + form + r'\b', '', cleaned, flags=re.IGNORECASE)
        return ' '.join(cleaned.split()).strip()


# ==========================================================
# 2. Core Medicine Intelligence Engine
# ==========================================================
class MedicineIntelligenceEngine:
    """
    Multi-stage medicine understanding service:
    Exact DB Search -> Alias/Brand Match -> Fuzzy Search -> Semantic Ranking -> Ambiguity Resolution.
    """

    @classmethod
    def understand_query(cls, raw_query: str) -> Dict[str, Any]:
        """
        Main entry point for medicine understanding.
        Returns normalized entities, candidate DB matches, ambiguity state, and confidence scores.
        """
        if not raw_query or not raw_query.strip():
            return {
                "raw_query": "",
                "normalized_query": {},
                "match_type": "NONE",
                "matches": [],
                "requires_clarification": False,
                "clarification_message": None,
                "confidence": 0.0
            }

        q_clean = raw_query.strip()
        norm_units = NormalizationService.normalize_units(q_clean)
        extracted_strength = NormalizationService.extract_strength(q_clean)
        extracted_form = NormalizationService.extract_dosage_form(q_clean)
        clean_name = NormalizationService.clean_medicine_name(q_clean)

        normalized_entities = {
            "medicine_candidate": clean_name or q_clean,
            "strength": extracted_strength,
            "dosage_form": extracted_form,
            "raw_query": q_clean
        }

        # ----------------------------------------------------
        # STAGE 1: Exact Database Match
        # ----------------------------------------------------
        exact_qs = Medicine.objects.filter(
            Q(name__iexact=q_clean) |
            Q(name__iexact=clean_name) |
            Q(brand__iexact=clean_name)
        )

        if extracted_strength:
            exact_qs_strength = exact_qs.filter(dosage__icontains=extracted_strength)
            if exact_qs_strength.exists():
                exact_qs = exact_qs_strength

        if exact_qs.exists():
            matches = [cls._format_medicine_match(m, match_score=1.0) for m in exact_qs]
            is_ambiguous = len(matches) > 1 and not extracted_strength

            return {
                "raw_query": q_clean,
                "normalized_query": normalized_entities,
                "match_type": "EXACT",
                "matches": matches,
                "requires_clarification": is_ambiguous,
                "clarification_message": f"Multiple variations found for '{clean_name}'. Which one are you looking for?" if is_ambiguous else None,
                "confidence": 1.0
            }

        # ----------------------------------------------------
        # STAGE 2: Alias & Brand-to-Generic Resolution
        # ----------------------------------------------------
        alias_target = MedicineMatcher.resolve_medicine_alias(q_clean) or MedicineMatcher.resolve_medicine_alias(clean_name)
        
        # Check root brand/generic query first (e.g., "dolo", "paracetamol", "amox")
        root_qs = Medicine.objects.filter(
            Q(name__icontains=clean_name) | Q(brand__icontains=clean_name)
        )
        
        if root_qs.count() > 1 and not extracted_strength:
            matches = [cls._format_medicine_match(m, match_score=0.95) for m in root_qs]
            return {
                "raw_query": q_clean,
                "normalized_query": normalized_entities,
                "match_type": "BRAND_GENERIC_ALIAS",
                "matches": matches,
                "requires_clarification": True,
                "clarification_message": f"Found multiple matches for '{clean_name}'. Which strength/variation do you need?",
                "confidence": 0.95
            }

        if alias_target:
            alias_qs = Medicine.objects.filter(
                Q(name__icontains=alias_target) | Q(brand__icontains=alias_target)
            )
            if extracted_strength:
                alias_qs_strength = alias_qs.filter(dosage__icontains=extracted_strength)
                if alias_qs_strength.exists():
                    alias_qs = alias_qs_strength

            if alias_qs.exists():
                matches = [cls._format_medicine_match(m, match_score=0.95) for m in alias_qs]
                is_ambiguous = len(matches) > 1 and not extracted_strength

                return {
                    "raw_query": q_clean,
                    "normalized_query": normalized_entities,
                    "match_type": "BRAND_GENERIC_ALIAS",
                    "matches": matches,
                    "requires_clarification": is_ambiguous,
                    "clarification_message": f"Found multiple matches for '{alias_target}'. Please select:" if is_ambiguous else None,
                    "confidence": 0.95
                }

        # ----------------------------------------------------
        # STAGE 3: Substring & Category Database Search
        # ----------------------------------------------------
        search_term = clean_name if len(clean_name) >= 3 else q_clean
        sub_qs = Medicine.objects.filter(
            Q(name__icontains=search_term) |
            Q(brand__icontains=search_term) |
            Q(category__icontains=search_term) |
            Q(uses__icontains=search_term)
        )

        if extracted_form:
            sub_qs_form = sub_qs.filter(dosage__icontains=extracted_form)
            if sub_qs_form.exists():
                sub_qs = sub_qs_form

        if sub_qs.exists():
            matches = [cls._format_medicine_match(m, match_score=0.88) for m in sub_qs[:6]]
            is_ambiguous = len(matches) > 1 and not extracted_strength

            return {
                "raw_query": q_clean,
                "normalized_query": normalized_entities,
                "match_type": "SUBSTRING",
                "matches": matches,
                "requires_clarification": is_ambiguous,
                "clarification_message": f"Found multiple products matching '{search_term}'. Which one do you need?" if is_ambiguous else None,
                "confidence": 0.88
            }

        # ----------------------------------------------------
        # STAGE 4: Controlled Fuzzy Matching Engine
        # ----------------------------------------------------
        fuzzy_candidates = MedicineMatcher.find_matching_medicines(q_clean, threshold=0.48)
        if not fuzzy_candidates and clean_name:
            fuzzy_candidates = MedicineMatcher.find_matching_medicines(clean_name, threshold=0.48)

        if fuzzy_candidates:
            matches = []
            for cand in fuzzy_candidates[:5]:
                med = cand["medicine"]
                score = round(cand.get("score", cand.get("similarity", 0.8)), 2)
                matches.append(cls._format_medicine_match(med, match_score=score))

            top_score = matches[0]["match_score"]
            is_ambiguous = len(matches) > 1 and (top_score < 0.85 or not extracted_strength)

            return {
                "raw_query": q_clean,
                "normalized_query": normalized_entities,
                "match_type": "FUZZY",
                "matches": matches,
                "requires_clarification": is_ambiguous,
                "clarification_message": f"Did you mean one of these medicines?" if is_ambiguous else None,
                "confidence": top_score
            }

        # ----------------------------------------------------
        # STAGE 5: Non-existent / Zero Match Guardrail
        # ----------------------------------------------------
        return {
            "raw_query": q_clean,
            "normalized_query": normalized_entities,
            "match_type": "UNMATCHED",
            "matches": [],
            "requires_clarification": False,
            "clarification_message": f"No medicine matching '{q_clean}' was found in the Medifind database.",
            "confidence": 0.0
        }

    @classmethod
    def _format_medicine_match(cls, med: Medicine, match_score: float) -> Dict[str, Any]:
        """Formats a Medicine model instance into a standardized response dictionary."""
        return {
            "id": med.id,
            "name": med.name,
            "brand": med.brand,
            "category": med.category,
            "dosage": med.dosage,
            "description": med.description,
            "uses": med.uses,
            "side_effects": med.side_effects,
            "prescription_required": med.prescription_required,
            "match_score": match_score
        }


# ==========================================================
# 3. Admin Medicine Data Quality Service
# ==========================================================
class DataQualityService:
    """
    Analyzes the Medifind database catalog to flag potential duplicate records,
    missing strengths, missing dosage forms, and inconsistent capitalization.
    """

    @classmethod
    def analyze_catalog_quality(cls) -> Dict[str, Any]:
        """Runs quality audit checks across all Medicine database entries."""
        medicines = list(Medicine.objects.all())
        issues = {
            "total_medicines": len(medicines),
            "potential_duplicates": [],
            "missing_dosage_form": [],
            "missing_strength": [],
            "inconsistent_capitalization": []
        }

        seen_names = {}
        for m in medicines:
            norm_name = m.name.lower().strip()

            # 1. Capitalization check
            if m.name != m.name.title() and not any(w.isupper() for w in m.name.split()):
                issues["inconsistent_capitalization"].append({
                    "id": m.id,
                    "name": m.name,
                    "issue": "Inconsistent capitalization"
                })

            # 2. Missing dosage form check
            if not NormalizationService.extract_dosage_form(m.dosage or m.name):
                issues["missing_dosage_form"].append({
                    "id": m.id,
                    "name": m.name,
                    "dosage": m.dosage
                })

            # 3. Missing strength check
            if not NormalizationService.extract_strength(m.dosage or m.name):
                issues["missing_strength"].append({
                    "id": m.id,
                    "name": m.name,
                    "dosage": m.dosage
                })

            # 4. Duplicate name check
            if norm_name in seen_names:
                existing = seen_names[norm_name]
                issues["potential_duplicates"].append({
                    "primary_id": existing.id,
                    "primary_name": existing.name,
                    "duplicate_id": m.id,
                    "duplicate_name": m.name
                })
            else:
                seen_names[norm_name] = m

        return issues
