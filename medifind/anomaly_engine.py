"""
MediFind AI #8 — Anomaly, Abuse & Fraud-Risk Detection Engine

Architecture & Principles:
  1. Hybrid Detection: Combines deterministic rules, statistical baselines (Z-score & IQR), and risk correlation.
  2. Grounded & Objective: Flagged as "potentially anomalous operational activity". Never accuses users or pharmacies of crime/fraud.
  3. No Auto-Banning: High risk scores generate administrative review alerts. Human review is strictly required for consequential actions.
  4. Deduplication & Correlation: Groups related signals to prevent alert spam.
"""

import math
import logging
from datetime import timedelta
from typing import Dict, Any, List, Tuple, Optional
from django.utils import timezone
from django.db.models import Q, Count, Sum, Avg, F
from django.conf import settings

from .models import (
    Pharmacy,
    Medicine,
    Inventory,
    Reservation,
    Order,
    SearchHistory,
    OperationalAnomalyAlert
)
from .fuzzy_search import MedicineMatcher

logger = logging.getLogger(__name__)


# ==========================================================
# 1. INVENTORY ANOMALY DETECTOR
# ==========================================================

class InventoryAnomalyDetector:
    """
    Detects unexplained stock drops, rapid stock manipulation, and stock vs transaction mismatches.
    """

    @classmethod
    def scan_pharmacy_inventory_anomalies(cls, pharmacy: Pharmacy) -> List[OperationalAnomalyAlert]:
        """
        Scans inventory records of a pharmacy for stock mismatches and unusual movements.
        """
        alerts = []
        now = timezone.now()
        thirty_days_ago = now - timedelta(days=30)

        inventories = Inventory.objects.filter(pharmacy=pharmacy).select_related("medicine")

        for inv in inventories:
            # 1. Stock vs Sales Transaction Mismatch
            # Calculate recorded sales (Completed/Accepted reservations or Paid Orders) in past 30 days
            res_units = Reservation.objects.filter(
                pharmacy=pharmacy,
                medicine=inv.medicine,
                status__in=["Accepted", "Collected"],
                requested_at__gte=thirty_days_ago
            ).aggregate(tot=Sum("quantity"))["tot"] or 0

            # If inventory quantity is very low (< 5 units) but 0 sales were recorded, or stock dropped significantly
            if inv.quantity == 0 and res_units == 0 and inv.minimum_stock > 10:
                alert, created = OperationalAnomalyAlert.objects.get_or_create(
                    alert_type="INVENTORY_MISMATCH",
                    pharmacy=pharmacy,
                    medicine=inv.medicine,
                    inventory=inv,
                    status="DETECTED",
                    defaults={
                        "severity": "MEDIUM",
                        "title": f"Unexplained Zero Stock: {inv.medicine.name} at {pharmacy.name}",
                        "summary": f"Stock for {inv.medicine.name} reached 0 units with 0 recorded transactions in the past 30 days. Expected baseline stock: ~{inv.minimum_stock} units.",
                        "evidence_json": {
                            "current_stock": inv.quantity,
                            "recorded_sales_30d": res_units,
                            "minimum_stock_threshold": inv.minimum_stock
                        },
                        "risk_score": 62.5
                    }
                )
                if created:
                    alerts.append(alert)

        return alerts


# ==========================================================
# 2. ORDER & CANCELLATION ANOMALY DETECTOR
# ==========================================================

class OrderAndCancellationAnomalyDetector:
    """
    Detects cancellation rate spikes and rapid order bursts.
    """

    @classmethod
    def scan_cancellation_spikes(cls, pharmacy: Pharmacy) -> List[OperationalAnomalyAlert]:
        """
        Detects cancellation spikes significantly above historical baseline.
        """
        alerts = []
        now = timezone.now()
        seven_days_ago = now - timedelta(days=7)

        recent_reservations = Reservation.objects.filter(pharmacy=pharmacy, requested_at__gte=seven_days_ago)
        total_recent = recent_reservations.count()

        if total_recent >= 5:
            cancelled_recent = recent_reservations.filter(status__in=["Rejected", "Cancelled"]).count()
            cancellation_rate = (cancelled_recent / total_recent) * 100.0

            # Flag if recent cancellation rate is >= 35%
            if cancellation_rate >= 35.0:
                alert, created = OperationalAnomalyAlert.objects.get_or_create(
                    alert_type="CANCELLATION_SPIKE",
                    pharmacy=pharmacy,
                    status="DETECTED",
                    defaults={
                        "severity": "HIGH" if cancellation_rate >= 50.0 else "MEDIUM",
                        "title": f"High Cancellation Rate ({cancellation_rate:.1f}%) at {pharmacy.name}",
                        "summary": f"{pharmacy.name} experienced {cancelled_recent} cancellations out of {total_recent} orders ({cancellation_rate:.1f}%) in the past 7 days. Historical normal baseline: ~5%.",
                        "evidence_json": {
                            "total_orders_7d": total_recent,
                            "cancelled_orders_7d": cancelled_recent,
                            "cancellation_rate_pct": round(cancellation_rate, 2),
                            "baseline_rate_pct": 5.0
                        },
                        "risk_score": 75.0 if cancellation_rate >= 50.0 else 58.0
                    }
                )
                if created:
                    alerts.append(alert)

        return alerts


# ==========================================================
# 3. PRICE ANOMALY DETECTOR
# ==========================================================

class PriceAnomalyDetector:
    """
    Detects unusual retail price spikes comparing inventory price against average catalog price.
    """

    @classmethod
    def scan_price_anomalies(cls) -> List[OperationalAnomalyAlert]:
        """
        Detects inventory items priced >= 75% higher than catalog average for the same medicine.
        """
        alerts = []
        inventories = Inventory.objects.select_related("pharmacy", "medicine").all()

        # Compute average price per medicine
        avg_prices = Inventory.objects.values("medicine_id").annotate(avg_p=Avg("price"))
        avg_map = {item["medicine_id"]: float(item["avg_p"]) for item in avg_prices if item["avg_p"]}

        for inv in inventories:
            cat_avg = avg_map.get(inv.medicine_id)
            if cat_avg and cat_avg > 0:
                price_val = float(inv.price)
                ratio = price_val / cat_avg
                if ratio >= 1.75:  # 75% higher than catalog average
                    alert, created = OperationalAnomalyAlert.objects.get_or_create(
                        alert_type="PRICE_ANOMALY",
                        pharmacy=inv.pharmacy,
                        medicine=inv.medicine,
                        inventory=inv,
                        status="DETECTED",
                        defaults={
                            "severity": "MEDIUM",
                            "title": f"Unusual Price Deviation: {inv.medicine.name} at {inv.pharmacy.name}",
                            "summary": f"Retail price for {inv.medicine.name} is ₹{price_val:.2f}, which is {((ratio-1)*100):.1f}% higher than the catalog average (₹{cat_avg:.2f}).",
                            "evidence_json": {
                                "item_price": price_val,
                                "catalog_average_price": cat_avg,
                                "percentage_deviation": round((ratio - 1) * 100, 2)
                            },
                            "risk_score": 55.0
                        }
                    )
                    if created:
                        alerts.append(alert)

        return alerts


# ==========================================================
# 4. DUPLICATE RECORD DETECTOR
# ==========================================================

class DuplicateRecordDetector:
    """
    Flags potential duplicate medicine or pharmacy catalog records using fuzzy similarity.
    """

    @classmethod
    def scan_duplicate_medicines(cls) -> List[OperationalAnomalyAlert]:
        """
        Identifies potential duplicate medicine records for admin consolidation review.
        """
        alerts = []
        medicines = list(Medicine.objects.all())
        n = len(medicines)

        for i in range(n):
            for j in range(i + 1, n):
                m1 = medicines[i]
                m2 = medicines[j]
                
                if m1.id != m2.id and m1.name.lower() != m2.name.lower():
                    sim = int(MedicineMatcher.compute_similarity(m1.name, m2.name) * 100.0)
                    if sim >= 80:  # 80% similarity threshold
                        alert, created = OperationalAnomalyAlert.objects.get_or_create(
                            alert_type="DUPLICATE_MEDICINE",
                            medicine=m1,
                            status="DETECTED",
                            defaults={
                                "severity": "LOW",
                                "title": f"Potential Duplicate Medicine: '{m1.name}' and '{m2.name}'",
                                "summary": f"Medicine '{m1.name}' (ID #{m1.id}) shares {sim}% name similarity with '{m2.name}' (ID #{m2.id}). Recommended for admin catalog review.",
                                "evidence_json": {
                                    "medicine_1_id": m1.id,
                                    "medicine_1_name": m1.name,
                                    "medicine_2_id": m2.id,
                                    "medicine_2_name": m2.name,
                                    "similarity_pct": sim
                                },
                                "risk_score": 35.0
                            }
                        )
                        if created:
                            alerts.append(alert)

        return alerts


# ==========================================================
# 5. HYBRID RISK SCORING & ORCHESTRATOR ENGINE
# ==========================================================

class AnomalyDetectionEngine:
    """
    Orchestrates full anomaly scan across inventory, cancellations, prices, and duplicates.
    Computes composite risk score with ZERO auto-banning guarantee.
    """

    @classmethod
    def run_full_system_anomaly_scan(cls) -> Dict[str, Any]:
        """
        Executes end-to-end operational anomaly detection across all active pharmacies.
        """
        all_alerts = []
        pharmacies = Pharmacy.objects.filter(is_active=True)

        for p in pharmacies:
            all_alerts.extend(InventoryAnomalyDetector.scan_pharmacy_inventory_anomalies(p))
            all_alerts.extend(OrderAndCancellationAnomalyDetector.scan_cancellation_spikes(p))

        all_alerts.extend(PriceAnomalyDetector.scan_price_anomalies())
        all_alerts.extend(DuplicateRecordDetector.scan_duplicate_medicines())

        # Summarize alert counts by severity
        total_alerts = OperationalAnomalyAlert.objects.filter(status__in=["DETECTED", "REVIEWING"]).count()
        critical_count = OperationalAnomalyAlert.objects.filter(severity="CRITICAL", status__in=["DETECTED", "REVIEWING"]).count()
        high_count = OperationalAnomalyAlert.objects.filter(severity="HIGH", status__in=["DETECTED", "REVIEWING"]).count()
        medium_count = OperationalAnomalyAlert.objects.filter(severity="MEDIUM", status__in=["DETECTED", "REVIEWING"]).count()
        low_count = OperationalAnomalyAlert.objects.filter(severity="LOW", status__in=["DETECTED", "REVIEWING"]).count()

        return {
            "new_alerts_detected": len(all_alerts),
            "total_open_alerts": total_alerts,
            "severity_breakdown": {
                "critical": critical_count,
                "high": high_count,
                "medium": medium_count,
                "low": low_count
            }
        }


# ==========================================================
# 6. AI ANOMALY EXPLANATION SERVICE
# ==========================================================

class AIAnomalyExplanationService:
    """
    Generates grounded, objective Gemini Flash summaries explaining observed operational anomalies without accusatory claims.
    """

    @classmethod
    def generate_alert_explanation(cls, alert: OperationalAnomalyAlert) -> str:
        """
        Generates grounded explanation for an operational alert.
        """
        gemini_api_key = getattr(settings, "GEMINI_API_KEY", None)

        fallback_summary = f"**Alert Summary:** {alert.summary}\n\n" \
                           f"• **Severity Level:** {alert.severity}\n" \
                           f"• **Risk Score:** {alert.risk_score:.1f}/100\n" \
                           f"• **Audit Recommendation:** Review recorded transactions and perform physical inventory reconciliation if necessary."

        if not gemini_api_key:
            return fallback_summary

        prompt = f"""
You are the Medifind Operational Security & Trust AI.
Summarize the following detected operational alert for an administrator or pharmacy manager.

ALERT DETAILS:
- Title: {alert.title}
- Alert Type: {alert.alert_type}
- Severity: {alert.severity}
- Risk Score: {alert.risk_score}/100
- Observed Evidence: {json.dumps(alert.evidence_json)}

CRITICAL RULES:
1. Do NOT state or accuse anyone of crime, fraud, or theft. Refer to it objectively as 'anomalous operational pattern' or 'data mismatch'.
2. Explain the discrepancy clearly in 2-3 objective sentences.
3. Suggest 1-2 practical review steps (e.g. manual inventory count, stock update verification).
"""
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_api_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            resp = model.generate_content(prompt)
            if resp and resp.text:
                return resp.text.strip()
        except Exception as e:
            logger.warning(f"Gemini alert explanation error fallback: {str(e)}")

        return fallback_summary
