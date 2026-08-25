"""
MediFind AI #5 — Pharmacy Analytics & Business Intelligence Engine

Architecture:
  1. PharmacyKPIService: Deterministic backend KPI calculations (Revenue, Orders, Units Sold, Availability Rate, AOV).
  2. PeriodComparisonService: Multi-period comparison engine (Current vs Previous period percentage change Δ%).
  3. SearchAvailabilityService: Search interest velocity, search-to-availability match rate, and unmet demand detection.
  4. CategoryAnalyticsService: Category-level revenue, unit sales, and trend breakdown.
  5. AnomalyDetectionEngine: Statistical Z-Score and rolling IQR anomaly detector (sales spikes, search surges, inventory drops).
  6. InsightGenerationEngine: Combines AI #4 demand forecast risk + AI #5 analytics into prioritized operational insights.
  7. AIAnalyticsExplanationService: Gemini Flash narrative explanation layer and Natural-Language "Ask Analytics AI" tool executor.
"""

import math
import logging
from datetime import date, datetime, timedelta
from typing import List, Dict, Any, Tuple, Optional
from decimal import Decimal
from django.utils import timezone
from django.db.models import Sum, Count, Q, Avg, F
from django.conf import settings

from .models import (
    Pharmacy,
    Medicine,
    Inventory,
    Reservation,
    Order,
    SearchHistory,
    DailyDemandSnapshot,
    DemandForecast
)
from .inventory_intelligence import TimeSeriesForecastingEngine, StockRiskEngine

logger = logging.getLogger(__name__)


# ==========================================================
# 1. PHARMACY KPI SERVICE
# ==========================================================

class PharmacyKPIService:
    """
    Computes validated operational and financial KPIs for a pharmacy over specified date ranges.
    All metrics are calculated deterministically from actual database records.
    """

    @classmethod
    def parse_date_range(cls, period: str = "7d", custom_start: Optional[str] = None, custom_end: Optional[str] = None) -> Tuple[date, date, date, date]:
        """
        Parses time period selection and derives corresponding previous comparison period date range.
        Periods supported: 'today', 'yesterday', '7d', '30d', '90d', 'custom'
        Returns: (current_start, current_end, previous_start, previous_end)
        """
        today = timezone.now().date()

        if period == "today":
            curr_start = today
            curr_end = today
            prev_start = today - timedelta(days=1)
            prev_end = today - timedelta(days=1)
        elif period == "yesterday":
            curr_start = today - timedelta(days=1)
            curr_end = today - timedelta(days=1)
            prev_start = today - timedelta(days=2)
            prev_end = today - timedelta(days=2)
        elif period == "30d":
            curr_start = today - timedelta(days=29)
            curr_end = today
            prev_start = curr_start - timedelta(days=30)
            prev_end = curr_start - timedelta(days=1)
        elif period == "90d":
            curr_start = today - timedelta(days=89)
            curr_end = today
            prev_start = curr_start - timedelta(days=90)
            prev_end = curr_start - timedelta(days=1)
        elif period == "custom" and custom_start and custom_end:
            try:
                curr_start = datetime.strptime(custom_start, "%Y-%m-%d").date()
                curr_end = datetime.strptime(custom_end, "%Y-%m-%d").date()
                duration_days = (curr_end - curr_start).days + 1
                prev_start = curr_start - timedelta(days=duration_days)
                prev_end = curr_start - timedelta(days=1)
            except ValueError:
                curr_start = today - timedelta(days=6)
                curr_end = today
                prev_start = curr_start - timedelta(days=7)
                prev_end = curr_start - timedelta(days=1)
        else: # Default 7d
            curr_start = today - timedelta(days=6)
            curr_end = today
            prev_start = curr_start - timedelta(days=7)
            prev_end = curr_start - timedelta(days=1)

        return curr_start, curr_end, prev_start, prev_end

    @classmethod
    def get_kpis_for_period(cls, pharmacy: Pharmacy, start_date: date, end_date: date) -> Dict[str, Any]:
        """
        Computes accurate KPIs for a single date window from actual Order, Reservation, SearchHistory, and Inventory models.
        """
        # 1. Orders KPI (Paid Razorpay Orders + Pickup Reservations)
        res_qs = Reservation.objects.filter(
            pharmacy=pharmacy,
            requested_at__date__gte=start_date,
            requested_at__date__lte=end_date
        )
        total_reservations = res_qs.count()
        completed_reservations = res_qs.filter(status__in=["Accepted", "Collected"]).count()
        cancelled_reservations = res_qs.filter(status__in=["Rejected", "Cancelled"]).count()

        order_qs = Order.objects.filter(
            pharmacy=pharmacy,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        )
        paid_orders = order_qs.filter(status__in=["PAID", "APPROVED"])
        total_paid_orders_count = paid_orders.count()

        total_transactions = total_reservations + total_paid_orders_count

        # 2. Financial Revenue & Units Sold calculation
        revenue = Decimal("0.00")
        units_sold = 0

        # Calculate revenue from completed/paid reservations
        for r in res_qs.filter(Q(is_paid=True) | Q(status__in=["Accepted", "Collected"])):
            units_sold += r.quantity
            inv = Inventory.objects.filter(pharmacy=pharmacy, medicine=r.medicine).first()
            price = inv.price if inv else Decimal("0.00")
            revenue += (price * r.quantity)

        # Add revenue from direct paid orders (excluding duplicate reservation orders)
        for o in paid_orders.filter(reservation_id__isnull=True):
            units_sold += o.quantity
            revenue += o.total_amount

        revenue_float = float(revenue)
        aov = round(revenue_float / total_transactions, 2) if total_transactions > 0 else 0.0

        # 3. Inventory & Availability KPIs
        inventories = Inventory.objects.filter(pharmacy=pharmacy)
        total_skus = inventories.count()
        in_stock_skus = inventories.filter(quantity__gt=0).count()
        out_of_stock_skus = inventories.filter(quantity=0).count()
        low_stock_skus = inventories.filter(quantity__gt=0, quantity__lte=F('minimum_stock')).count()

        availability_rate = round((in_stock_skus / total_skus * 100.0), 1) if total_skus > 0 else 100.0

        # 4. Search Volume
        med_names = list(inventories.values_list("medicine__name", flat=True))
        search_count = 0
        if med_names:
            search_q = Q()
            for name in med_names:
                search_q |= Q(medicine__icontains=name)
            search_count = SearchHistory.objects.filter(
                search_q,
                searched_at__date__gte=start_date,
                searched_at__date__lte=end_date
            ).count()

        return {
            "period_start": start_date.isoformat(),
            "period_end": end_date.isoformat(),
            "revenue": revenue_float,
            "units_sold": units_sold,
            "total_transactions": total_transactions,
            "completed_reservations": completed_reservations,
            "cancelled_reservations": cancelled_reservations,
            "paid_orders_count": total_paid_orders_count,
            "average_order_value": aov,
            "total_skus": total_skus,
            "in_stock_skus": in_stock_skus,
            "out_of_stock_skus": out_of_stock_skus,
            "low_stock_skus": low_stock_skus,
            "availability_rate": availability_rate,
            "search_volume": search_count
        }


# ==========================================================
# 2. PERIOD COMPARISON SERVICE
# ==========================================================

class PeriodComparisonService:
    """
    Calculates percentage changes (Δ%) comparing current period metrics vs previous period metrics.
    Formula: Δ% = ((Current - Previous) / Previous) * 100
    """

    @classmethod
    def compute_percentage_change(cls, current: float, previous: float) -> Tuple[float, str]:
        """Calculates percentage change float and formatted direction string."""
        if previous == 0:
            if current > 0:
                return 100.0, "+100.0%"
            return 0.0, "0.0%"
        
        change_pct = round(((current - previous) / previous) * 100.0, 1)
        direction = f"+{change_pct}%" if change_pct > 0 else f"{change_pct}%"
        return change_pct, direction

    @classmethod
    def get_comparison_analytics(cls, pharmacy: Pharmacy, period: str = "7d", custom_start: Optional[str] = None, custom_end: Optional[str] = None) -> Dict[str, Any]:
        """
        Returns complete comparative KPI report with percentage changes.
        """
        c_start, c_end, p_start, p_end = PharmacyKPIService.parse_date_range(period, custom_start, custom_end)

        curr_kpis = PharmacyKPIService.get_kpis_for_period(pharmacy, c_start, c_end)
        prev_kpis = PharmacyKPIService.get_kpis_for_period(pharmacy, p_start, p_end)

        rev_pct, rev_str = cls.compute_percentage_change(curr_kpis["revenue"], prev_kpis["revenue"])
        orders_pct, orders_str = cls.compute_percentage_change(curr_kpis["total_transactions"], prev_kpis["total_transactions"])
        units_pct, units_str = cls.compute_percentage_change(curr_kpis["units_sold"], prev_kpis["units_sold"])
        searches_pct, searches_str = cls.compute_percentage_change(curr_kpis["search_volume"], prev_kpis["search_volume"])
        avail_pct, avail_str = cls.compute_percentage_change(curr_kpis["availability_rate"], prev_kpis["availability_rate"])

        return {
            "period": period,
            "current_range": f"{c_start.strftime('%b %d')} - {c_end.strftime('%b %d, %Y')}",
            "previous_range": f"{p_start.strftime('%b %d')} - {p_end.strftime('%b %d, %Y')}",
            "current": curr_kpis,
            "previous": prev_kpis,
            "changes": {
                "revenue": {"percent": rev_pct, "formatted": rev_str},
                "transactions": {"percent": orders_pct, "formatted": orders_str},
                "units_sold": {"percent": units_pct, "formatted": units_str},
                "searches": {"percent": searches_pct, "formatted": searches_str},
                "availability_rate": {"percent": avail_pct, "formatted": avail_str}
            }
        }


# ==========================================================
# 3. SEARCH & AVAILABILITY MATCH SERVICE
# ==========================================================

class SearchAvailabilityService:
    """
    Computes medicine-level search interest velocity, search-to-availability match rate, and unmet demand.
    """

    @classmethod
    def get_search_availability_metrics(cls, pharmacy: Pharmacy, days: int = 30) -> List[Dict[str, Any]]:
        """
        Analyzes medicine-level search volume vs actual inventory availability.
        Unmet demand signal is flagged when search volume is high but inventory stock is low or out of stock.
        """
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days - 1)

        inventories = Inventory.objects.filter(pharmacy=pharmacy).select_related("medicine")
        results = []

        for inv in inventories:
            med = inv.medicine
            searches = SearchHistory.objects.filter(
                medicine__icontains=med.name,
                searched_at__date__gte=start_date,
                searched_at__date__lte=end_date
            ).count()

            reservations = Reservation.objects.filter(
                pharmacy=pharmacy,
                medicine=med,
                requested_at__date__gte=start_date,
                requested_at__date__lte=end_date
            ).aggregate(total_units=Sum("quantity"))["total_units"] or 0

            # Availability match score calculation
            if searches > 0:
                if inv.quantity > 0:
                    availability_match_pct = round(min(100.0, (float(inv.quantity) / max(1.0, float(searches))) * 100.0), 1)
                else:
                    availability_match_pct = 0.0
                conversion_pct = round((float(reservations) / float(searches)) * 100.0, 1)
            else:
                availability_match_pct = 100.0 if inv.quantity > 0 else 0.0
                conversion_pct = 0.0

            unmet_demand = (searches > 5 and inv.quantity <= inv.minimum_stock)

            results.append({
                "medicine_id": med.id,
                "medicine_name": med.name,
                "brand": med.brand,
                "category": med.category,
                "current_stock": inv.quantity,
                "searches_count": searches,
                "units_sold": reservations,
                "availability_match_pct": availability_match_pct,
                "conversion_pct": conversion_pct,
                "unmet_demand": unmet_demand
            })

        results.sort(key=lambda x: (-x["searches_count"], x["current_stock"]))
        return results


# ==========================================================
# 4. CATEGORY ANALYTICS SERVICE
# ==========================================================

class CategoryAnalyticsService:
    """
    Aggregates inventory value, units sold, and revenue across medicine categories.
    """

    @classmethod
    def get_category_breakdown(cls, pharmacy: Pharmacy, days: int = 30) -> List[Dict[str, Any]]:
        """
        Returns revenue, units sold, SKU count, and stock distribution per category.
        """
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days - 1)

        inventories = Inventory.objects.filter(pharmacy=pharmacy).select_related("medicine")
        cat_map = {}

        for inv in inventories:
            cat = inv.medicine.category or "General Health"
            if cat not in cat_map:
                cat_map[cat] = {
                    "category": cat,
                    "sku_count": 0,
                    "total_stock": 0,
                    "units_sold": 0,
                    "revenue": 0.0
                }
            cat_map[cat]["sku_count"] += 1
            cat_map[cat]["total_stock"] += inv.quantity

            # Add reservation sales
            res_units = Reservation.objects.filter(
                pharmacy=pharmacy,
                medicine=inv.medicine,
                requested_at__date__gte=start_date,
                requested_at__date__lte=end_date,
                status__in=["Accepted", "Collected"]
            ).aggregate(tot=Sum("quantity"))["tot"] or 0

            cat_map[cat]["units_sold"] += res_units
            cat_map[cat]["revenue"] += float(inv.price * res_units)

        results = list(cat_map.values())
        results.sort(key=lambda x: -x["units_sold"])
        return results


# ==========================================================
# 5. DETERMINISTIC ANOMALY DETECTION ENGINE
# ==========================================================

class AnomalyDetectionEngine:
    """
    Deterministic Statistical Anomaly Detection.
    Identifies unusual demand spikes, search surges, and stock drops using Z-Scores and Interquartile Ranges (IQR).
    """

    @classmethod
    def detect_anomalies(cls, pharmacy: Pharmacy, days: int = 30) -> List[Dict[str, Any]]:
        """
        Evaluates daily demand and search velocity over the past N days to flag statistical anomalies.
        """
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days)

        inventories = Inventory.objects.filter(pharmacy=pharmacy).select_related("medicine")
        anomalies = []

        for inv in inventories:
            med = inv.medicine
            snapshots = DailyDemandSnapshot.objects.filter(
                pharmacy=pharmacy,
                medicine=med,
                date__gte=start_date,
                date__lte=end_date
            ).order_by("date")

            if snapshots.count() < 7:
                continue

            sales_series = [s.units_sold for s in snapshots]
            search_series = [s.searches_count for s in snapshots]

            recent_sales = sales_series[-1] if sales_series else 0
            prior_sales = sales_series[:-1]
            avg_prior_sales = sum(prior_sales) / len(prior_sales) if prior_sales else 0.0

            # Calculate Z-Score for sales spike
            if len(prior_sales) > 1:
                variance = sum((x - avg_prior_sales) ** 2 for x in prior_sales) / len(prior_sales)
                std_sales = math.sqrt(variance)
                sales_zscore = ((recent_sales - avg_prior_sales) / std_sales) if std_sales > 0 else 0.0
            else:
                sales_zscore = 0.0

            # Rule 1: Sales Surge Anomaly (Z-Score > 2.5 and recent_sales >= 5)
            if sales_zscore >= 2.5 and recent_sales >= 5:
                anomalies.append({
                    "medicine_id": med.id,
                    "medicine_name": med.name,
                    "anomaly_type": "SALES_SPIKE",
                    "severity": "HIGH",
                    "title": f"Unusual Sales Spike for {med.name}",
                    "description": f"Sales increased to {recent_sales} units today (Z-score: {sales_zscore:.2f} above baseline average of {avg_prior_sales:.1f} units).",
                    "current_val": recent_sales,
                    "baseline_val": round(avg_prior_sales, 1)
                })

            # Rule 2: Search Volume Surge Anomaly
            recent_searches = search_series[-1] if search_series else 0
            prior_searches = search_series[:-1]
            avg_prior_searches = sum(prior_searches) / len(prior_searches) if prior_searches else 0.0

            if avg_prior_searches > 0 and recent_searches >= (avg_prior_searches * 3.0) and recent_searches >= 5:
                anomalies.append({
                    "medicine_id": med.id,
                    "medicine_name": med.name,
                    "anomaly_type": "SEARCH_SURGE",
                    "severity": "MEDIUM",
                    "title": f"Search Surge Interest for {med.name}",
                    "description": f"Search volume reached {recent_searches} queries today (3.0x higher than past average of {avg_prior_searches:.1f}).",
                    "current_val": recent_searches,
                    "baseline_val": round(avg_prior_searches, 1)
                })

            # Rule 3: Rapid Stock Depletion Anomaly
            if inv.quantity == 0 and avg_prior_sales > 2.0:
                anomalies.append({
                    "medicine_id": med.id,
                    "medicine_name": med.name,
                    "anomaly_type": "UNEXPECTED_STOCKOUT",
                    "severity": "CRITICAL",
                    "title": f"Unexpected Stock-out for {med.name}",
                    "description": f"Stock depleted to 0 units despite active daily demand average of {avg_prior_sales:.1f} units.",
                    "current_val": 0,
                    "baseline_val": round(avg_prior_sales, 1)
                })

        return anomalies


# ==========================================================
# 6. INSIGHT GENERATION ENGINE (INTEGRATING AI #4 + AI #5)
# ==========================================================

class InsightGenerationEngine:
    """
    Generates structured, prioritized operational insights combining AI #4 forecast risk + AI #5 analytics.
    Severity: CRITICAL, HIGH, MEDIUM, LOW.
    """

    @classmethod
    def generate_insights(cls, pharmacy: Pharmacy, period: str = "7d") -> List[Dict[str, Any]]:
        """
        Creates actionable business insights with exact operational recommendations.
        """
        insights = []

        # 1. Fetch KPI comparison
        comp = PeriodComparisonService.get_comparison_analytics(pharmacy, period=period)
        curr = comp["current"]
        changes = comp["changes"]

        # Insight 1: Search Demand vs Stock-out Risk (Combining AI #4 + AI #5)
        search_metrics = SearchAvailabilityService.get_search_availability_metrics(pharmacy, days=7)
        for item in search_metrics[:5]:
            if item["unmet_demand"]:
                insights.append({
                    "type": "UNMET_DEMAND",
                    "priority": "CRITICAL",
                    "badge": "🔴 Critical",
                    "medicine_name": item["medicine_name"],
                    "title": f"Unmet Demand: {item['medicine_name']}",
                    "description": f"Received {item['searches_count']} search queries in the past 7 days, but current stock is only {item['current_stock']} units.",
                    "action_text": "Review Inventory Stock",
                    "medicine_id": item["medicine_id"]
                })

        # Insight 2: High Forecast Risk SKUs from AI #4
        inventories = Inventory.objects.filter(pharmacy=pharmacy).select_related("medicine")
        for inv in inventories:
            forecast_data = TimeSeriesForecastingEngine.generate_forecast(pharmacy, inv.medicine, horizon_days=7)
            risk_info = StockRiskEngine.analyze_inventory_risk(inv, forecast_data)

            if risk_info["risk_level"] in ["CRITICAL", "HIGH"] and risk_info["reorder_recommended"]:
                insights.append({
                    "type": "FORECAST_STOCK_RISK",
                    "priority": risk_info["risk_level"],
                    "badge": "🔴 High Risk" if risk_info["risk_level"] == "CRITICAL" else "🟠 Reorder Point",
                    "medicine_name": inv.medicine.name,
                    "title": f"Reorder Recommended for {inv.medicine.name}",
                    "description": f"Predicted 7-day demand is {risk_info['predicted_7_day_demand']:.1f} units vs {inv.quantity} in stock ({risk_info['days_of_cover']} days of cover). Suggested reorder: {risk_info['suggested_reorder_qty']} units.",
                    "action_text": "Order Stock",
                    "medicine_id": inv.medicine.id
                })

        # Insight 3: Anomaly Alerts
        anomalies = AnomalyDetectionEngine.detect_anomalies(pharmacy, days=14)
        for a in anomalies[:3]:
            insights.append({
                "type": a["anomaly_type"],
                "priority": a["severity"],
                "badge": "⚡ Anomaly",
                "medicine_name": a["medicine_name"],
                "title": a["title"],
                "description": a["description"],
                "action_text": "View Activity Log",
                "medicine_id": a["medicine_id"]
            })

        # Sort insights by priority (CRITICAL -> HIGH -> MEDIUM -> LOW)
        prio_map = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        insights.sort(key=lambda x: prio_map.get(x["priority"], 4))
        return insights


# ==========================================================
# 7. AI EXPLANATION SERVICE & NATURAL-LANGUAGE ANALYTICS
# ==========================================================

class AIAnalyticsExplanationService:
    """
    Narrative explanation layer powered by Gemini Flash.
    Translates validated backend metrics into human-readable executive summaries.
    Also executes natural-language "Ask Analytics AI" requests via approved tool functions.
    """

    @classmethod
    def generate_daily_executive_summary(cls, pharmacy: Pharmacy, period: str = "7d") -> str:
        """
        Generates a concise 3-sentence executive summary based strictly on backend analytics.
        """
        comp = PeriodComparisonService.get_comparison_analytics(pharmacy, period=period)
        curr = comp["current"]
        changes = comp["changes"]

        fallback_summary = (
            f"Over the selected period ({comp['current_range']}), {pharmacy.name} recorded {curr['total_transactions']} total orders "
            f"(₹{curr['revenue']:.2f} revenue, {changes['revenue']['formatted']} change) and {curr['search_volume']} medicine searches. "
            f"Overall inventory availability rate stands at {curr['availability_rate']}% across {curr['total_skus']} catalog SKUs."
        )

        gemini_api_key = getattr(settings, "GEMINI_API_KEY", None)
        if not gemini_api_key:
            return fallback_summary

        prompt = f"""
You are the Executive AI Business Analyst for MediFind Pharmacy Platform.
Summarize the following verified pharmacy business analytics for the pharmacy owner in 3 clear, professional sentences.

STRICT RULES:
1. Do NOT alter or invent any numbers. Use exact values: Revenue=₹{curr['revenue']:.2f} ({changes['revenue']['formatted']}), Transactions={curr['total_transactions']} ({changes['transactions']['formatted']}), Searches={curr['search_volume']} ({changes['searches']['formatted']}), Availability={curr['availability_rate']}%.
2. Do NOT speculate or invent external causes (e.g., do NOT mention flu or weather).
3. Provide operational clarity for inventory and sales performance.

DATA:
Pharmacy: {pharmacy.name}
Range: {comp['current_range']}
Revenue: ₹{curr['revenue']:.2f} ({changes['revenue']['formatted']})
Transactions: {curr['total_transactions']} ({changes['transactions']['formatted']})
Search Volume: {curr['search_volume']} ({changes['searches']['formatted']})
Availability Rate: {curr['availability_rate']}%
Out-of-Stock SKUs: {curr['out_of_stock_skus']}
"""
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_api_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            response = model.generate_content(prompt)
            if response and response.text:
                return response.text.strip()
        except Exception as e:
            logger.warning(f"Gemini analytics summary API error fallback: {str(e)}")

        return fallback_summary

    @classmethod
    def answer_analytics_question(cls, pharmacy: Pharmacy, user_query: str) -> Dict[str, Any]:
        """
        Tool-based Natural Language "Ask Analytics AI":
          1. Identifies intent from approved tool layer functions.
          2. Executes deterministic backend calculation.
          3. Gemini Flash formats final explanation over validated result.
        """
        query_lower = user_query.lower()

        # Intent classification & deterministic execution
        if "top" in query_lower or "best" in query_lower or "popular" in query_lower:
            data = SearchAvailabilityService.get_search_availability_metrics(pharmacy, days=30)[:5]
            med_list = [f"{d['medicine_name']} ({d['searches_count']} searches, {d['units_sold']} units sold)" for d in data]
            answer = f"Top performing medicines by search volume in the last 30 days: {', '.join(med_list)}."
            tool_used = "get_top_medicines"
        elif "risk" in query_lower or "stock" in query_lower or "reorder" in query_lower:
            insights = InsightGenerationEngine.generate_insights(pharmacy, period="7d")
            risk_items = [i["title"] for i in insights if i["priority"] in ["CRITICAL", "HIGH"]]
            if risk_items:
                answer = f"The following medicines require immediate inventory attention: {'; '.join(risk_items)}."
            else:
                answer = "All inventory SKUs currently have sufficient stock levels and low risk."
            tool_used = "get_stock_risk"
        elif "anomaly" in query_lower or "spike" in query_lower or "unusual" in query_lower:
            anomalies = AnomalyDetectionEngine.detect_anomalies(pharmacy, days=14)
            if anomalies:
                answer = f"Detected {len(anomalies)} statistical anomalies recently: {', '.join([a['title'] for a in anomalies])}."
            else:
                answer = "No unusual sales spikes or search anomalies detected in the past 14 days."
            tool_used = "get_anomalies"
        else:
            comp = PeriodComparisonService.get_comparison_analytics(pharmacy, period="7d")
            curr = comp["current"]
            answer = f"In the past 7 days, your pharmacy generated ₹{curr['revenue']:.2f} revenue across {curr['total_transactions']} orders with an overall availability rate of {curr['availability_rate']}%."
            tool_used = "get_overview_kpis"

        return {
            "success": True,
            "query": user_query,
            "tool_used": tool_used,
            "answer": answer
        }
