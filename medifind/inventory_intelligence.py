"""
MediFind AI #4 — Predictive Inventory & Medicine Demand Intelligence Engine

Architecture:
  1. DemandDataService: Normalizes database transactions (Reservations, Orders, SearchHistory) into DailyDemandSnapshots.
  2. TimeSeriesForecastingEngine: Deterministic SMA & EWMA forecasting models with backtested evaluation (MAE, RMSE, WAPE).
  3. StockRiskEngine: Computes Days of Cover, Safety Stock, Reorder Point, Demand Trends, and Risk Levels (CRITICAL, HIGH, MODERATE, LOW).
  4. AIInventoryExplanationService: Gemini Flash human-readable explanation layer over strict deterministic metrics.
"""

import math
import logging
from datetime import date, timedelta
from typing import List, Dict, Any, Tuple, Optional
from decimal import Decimal
from django.utils import timezone
from django.db.models import Sum, Count, Q, Avg
from django.conf import settings

from .models import (
    Pharmacy,
    Medicine,
    Inventory,
    Reservation,
    Order,
    SearchHistory,
    DailyDemandSnapshot,
    DemandForecast,
    ForecastModelVersion
)

logger = logging.getLogger(__name__)


# ==========================================================
# 1. DEMAND DATA NORMALIZATION SERVICE
# ==========================================================

class DemandDataService:
    """
    Ingests and normalizes actual historical transaction data from Medifind database.
    Calculates daily sales, search velocity, and out-of-stock events per pharmacy SKU.
    """

    @classmethod
    def sync_daily_snapshots(cls, pharmacy: Optional[Pharmacy] = None, days_back: int = 30) -> int:
        """
        Populates or updates DailyDemandSnapshot records using actual Reservation, Order, and SearchHistory data.
        """
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days_back)

        pharmacies = [pharmacy] if pharmacy else Pharmacy.objects.filter(is_active=True)
        created_count = 0

        for pharm in pharmacies:
            inventories = Inventory.objects.filter(pharmacy=pharm).select_related("medicine")
            for inv in inventories:
                med = inv.medicine
                
                # Fetch search queries for this medicine name
                search_logs = SearchHistory.objects.filter(
                    medicine__icontains=med.name,
                    searched_at__date__gte=start_date,
                    searched_at__date__lte=end_date
                )
                search_counts_by_date = {}
                for log in search_logs:
                    d = log.searched_at.date()
                    search_counts_by_date[d] = search_counts_by_date.get(d, 0) + 1

                # Fetch reservations
                res_logs = Reservation.objects.filter(
                    pharmacy=pharm,
                    medicine=med,
                    requested_at__date__gte=start_date,
                    requested_at__date__lte=end_date
                ).exclude(status__in=["Rejected", "Cancelled"])

                res_counts_by_date = {}
                units_by_date = {}
                for res in res_logs:
                    d = res.requested_at.date()
                    res_counts_by_date[d] = res_counts_by_date.get(d, 0) + 1
                    units_by_date[d] = units_by_date.get(d, 0) + res.quantity

                # Fetch paid orders
                order_logs = Order.objects.filter(
                    pharmacy=pharm,
                    medicine=med,
                    created_at__date__gte=start_date,
                    created_at__date__lte=end_date
                ).filter(status__in=["PAID", "APPROVED"])

                for order in order_logs:
                    d = order.created_at.date()
                    # Only add if not already counted via reservation
                    if not order.reservation_id:
                        units_by_date[d] = units_by_date.get(d, 0) + order.quantity

                # Iterate through daily range and persist snapshot
                current_d = start_date
                while current_d <= end_date:
                    u_sold = units_by_date.get(current_d, 0)
                    r_count = res_counts_by_date.get(current_d, 0)
                    s_count = search_counts_by_date.get(current_d, 0)
                    out_of_stock = (inv.quantity == 0)

                    snapshot, created = DailyDemandSnapshot.objects.update_or_create(
                        pharmacy=pharm,
                        medicine=med,
                        date=current_d,
                        defaults={
                            "units_sold": u_sold,
                            "reservations_count": r_count,
                            "searches_count": s_count,
                            "stock_at_end": inv.quantity,
                            "was_out_of_stock": out_of_stock
                        }
                    )
                    if created:
                        created_count += 1
                    current_d += timedelta(days=1)

        return created_count

    @classmethod
    def get_timeseries_data(cls, pharmacy: Pharmacy, medicine: Medicine, days: int = 30) -> List[Dict[str, Any]]:
        """
        Retrieves continuous daily timeseries demand data for a specific pharmacy medicine.
        """
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days)

        snapshots = DailyDemandSnapshot.objects.filter(
            pharmacy=pharmacy,
            medicine=medicine,
            date__gte=start_date,
            date__lte=end_date
        ).order_by("date")

        snapshot_map = {s.date: s for s in snapshots}
        data_points = []
        curr = start_date

        while curr <= end_date:
            if curr in snapshot_map:
                s = snapshot_map[curr]
                # Unconstrained demand estimation: if out-of-stock, use searches as demand signal proxy
                effective_demand = float(s.units_sold)
                if s.was_out_of_stock and s.searches_count > 0:
                    effective_demand = max(effective_demand, float(s.searches_count) * 0.5)

                data_points.append({
                    "date": curr.isoformat(),
                    "units_sold": s.units_sold,
                    "searches": s.searches_count,
                    "effective_demand": effective_demand,
                    "stock_at_end": s.stock_at_end,
                    "was_out_of_stock": s.was_out_of_stock
                })
            else:
                data_points.append({
                    "date": curr.isoformat(),
                    "units_sold": 0,
                    "searches": 0,
                    "effective_demand": 0.0,
                    "stock_at_end": 0,
                    "was_out_of_stock": False
                })
            curr += timedelta(days=1)

        return data_points


# ==========================================================
# 2. DETERMINISTIC TIME-SERIES FORECASTING ENGINE
# ==========================================================

class TimeSeriesForecastingEngine:
    """
    Deterministic Statistical & Time-Series Forecasting Models.
    Compares Baseline Moving Average (SMA) vs Candidate EWMA using sequential validation (MAE, RMSE, WAPE).
    """

    @classmethod
    def simple_moving_average(cls, series: List[float], window: int = 7) -> float:
        """Baseline Model 1: N-day Simple Moving Average."""
        if not series:
            return 0.0
        sub = series[-window:] if len(series) >= window else series
        return sum(sub) / len(sub)

    @classmethod
    def exponential_weighted_moving_average(cls, series: List[float], alpha: float = 0.3) -> float:
        """Candidate Model: Exponentially Weighted Moving Average (EWMA)."""
        if not series:
            return 0.0
        ewma = series[0]
        for val in series[1:]:
            ewma = alpha * val + (1 - alpha) * ewma
        return ewma

    @classmethod
    def calculate_metrics(cls, actuals: List[float], forecasts: List[float]) -> Tuple[float, float, float]:
        """Calculates MAE, RMSE, and WAPE error metrics."""
        if not actuals or len(actuals) != len(forecasts):
            return 0.0, 0.0, 0.0

        n = len(actuals)
        errors = [abs(a - f) for a, f in zip(actuals, forecasts)]
        mae = sum(errors) / n
        rmse = math.sqrt(sum((a - f) ** 2 for a, f in zip(actuals, forecasts)) / n)
        
        sum_actuals = sum(actuals)
        wape = (sum(errors) / sum_actuals * 100.0) if sum_actuals > 0 else 0.0
        return round(mae, 2), round(rmse, 2), round(wape, 2)

    @classmethod
    def evaluate_models(cls, series: List[float]) -> Tuple[str, float, float, float, str]:
        """
        Time-series validation pipeline: Evaluates Baseline SMA vs Candidate EWMA.
        Selects candidate model ONLY IF validation MAE/RMSE demonstrates improvement.
        """
        if len(series) < 5:
            # Cold Start / Insufficient Data -> Return SMA Baseline
            sma_val = cls.simple_moving_average(series)
            return "SMA_Baseline", sma_val, 0.0, 0.0, "v1.0-baseline"

        # Split data for sequential time-series backtesting (80% train, 20% test)
        split_idx = int(len(series) * 0.8)
        train_series = series[:split_idx]
        test_series = series[split_idx:]

        sma_preds = []
        ewma_preds = []

        for i in range(len(test_series)):
            curr_window = train_series + test_series[:i]
            sma_preds.append(cls.simple_moving_average(curr_window, window=7))
            ewma_preds.append(cls.exponential_weighted_moving_average(curr_window, alpha=0.3))

        sma_mae, sma_rmse, _ = cls.calculate_metrics(test_series, sma_preds)
        ewma_mae, ewma_rmse, ewma_wape = cls.calculate_metrics(test_series, ewma_preds)

        # Selection Gate: Candidate model MUST outperform baseline MAE
        if ewma_mae < sma_mae:
            best_model_name = "EWMA_Exponential"
            final_daily_forecast = cls.exponential_weighted_moving_average(series, alpha=0.3)
            return best_model_name, final_daily_forecast, ewma_mae, ewma_rmse, "v1.2-candidate"
        else:
            best_model_name = "SMA_Baseline"
            final_daily_forecast = cls.simple_moving_average(series, window=7)
            return best_model_name, final_daily_forecast, sma_mae, sma_rmse, "v1.0-baseline"

    @classmethod
    def generate_forecast(cls, pharmacy: Pharmacy, medicine: Medicine, horizon_days: int = 7) -> Dict[str, Any]:
        """
        Generates deterministic predicted demand, confidence bounds, and metrics for horizon_days.
        """
        timeseries = DemandDataService.get_timeseries_data(pharmacy, medicine, days=30)
        demand_values = [d["effective_demand"] for d in timeseries]
        non_zero_values = [v for v in demand_values if v > 0]

        is_cold_start = len(non_zero_values) < 3

        if is_cold_start:
            # Cold start fallback using baseline simple average
            daily_demand = cls.simple_moving_average(demand_values, window=7)
            model_name = "ColdStart_Baseline"
            model_ver = "v1.0-coldstart"
            mae, rmse = 0.0, 0.0
        else:
            model_name, daily_demand, mae, rmse, model_ver = cls.evaluate_models(demand_values)

        total_predicted = daily_demand * horizon_days

        # Calculate standard deviation of historical residuals for confidence bounds
        if len(demand_values) > 1:
            variance = sum((x - daily_demand) ** 2 for x in demand_values) / (len(demand_values) - 1)
            std_dev = math.sqrt(variance)
        else:
            std_dev = daily_demand * 0.25

        # 95% Confidence Interval Calculation
        margin_of_error = 1.96 * std_dev * math.sqrt(horizon_days)
        lower_bound = max(0.0, round(total_predicted - margin_of_error, 1))
        upper_bound = round(total_predicted + margin_of_error, 1)

        daily_breakdown = []
        curr_date = timezone.now().date() + timedelta(days=1)
        for d in range(1, horizon_days + 1):
            daily_breakdown.append({
                "day": d,
                "date": curr_date.isoformat(),
                "predicted": round(daily_demand, 1)
            })
            curr_date += timedelta(days=1)

        return {
            "pharmacy_id": pharmacy.id,
            "medicine_id": medicine.id,
            "medicine_name": medicine.name,
            "horizon_days": horizon_days,
            "daily_demand": round(daily_demand, 2),
            "predicted_demand": round(total_predicted, 1),
            "lower_bound": lower_bound,
            "upper_bound": upper_bound,
            "std_dev": round(std_dev, 2),
            "mae": mae,
            "rmse": rmse,
            "model_name": model_name,
            "model_version": model_ver,
            "is_cold_start": is_cold_start,
            "raw_data_points": len(demand_values),
            "daily_breakdown": daily_breakdown
        }


# ==========================================================
# 3. DETERMINISTIC STOCK RISK & REORDER ENGINE
# ==========================================================

class StockRiskEngine:
    """
    Deterministic Inventory Risk Classification, Days of Cover, Safety Stock, and Reorder Point Engine.
    """

    LEAD_TIME_DAYS = 3       # Configurable supplier replenishment lead time
    SERVICE_LEVEL_Z = 1.645  # 95% Service Level multiplier

    @classmethod
    def analyze_inventory_risk(cls, inventory: Inventory, forecast_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Computes deterministic stock-out risk, days of cover, and suggested reorder thresholds.
        """
        current_stock = inventory.quantity
        min_stock = inventory.minimum_stock
        daily_demand = forecast_data["daily_demand"]
        std_dev = forecast_data["std_dev"]
        predicted_7d_demand = forecast_data["predicted_demand"]

        # Days of Cover Calculation
        if daily_demand > 0:
            days_of_cover = round(current_stock / daily_demand, 1)
        else:
            days_of_cover = 999.0  # Infinite cover if zero demand

        # Safety Stock = Z * std_dev * sqrt(lead_time)
        safety_stock = int(round(cls.SERVICE_LEVEL_Z * std_dev * math.sqrt(cls.LEAD_TIME_DAYS)))
        safety_stock = max(safety_stock, 5)

        # Reorder Point = (daily_demand * lead_time) + safety_stock
        reorder_point = int(round(daily_demand * cls.LEAD_TIME_DAYS + safety_stock))
        reorder_point = max(reorder_point, min_stock)

        # Risk Level Classification Gate
        if current_stock == 0 or days_of_cover < 1.0:
            risk_level = "CRITICAL"
        elif days_of_cover < 3.0 or current_stock <= min_stock:
            risk_level = "HIGH"
        elif days_of_cover < 7.0 or current_stock <= reorder_point:
            risk_level = "MODERATE"
        else:
            risk_level = "LOW"

        # Reorder Intelligence
        reorder_recommended = (current_stock <= reorder_point)
        if reorder_recommended:
            suggested_reorder_qty = max(min_stock * 2, int(reorder_point * 2 - current_stock))
        else:
            suggested_reorder_qty = 0

        # Demand Trend Detection
        trend = cls.detect_demand_trend(inventory.pharmacy, inventory.medicine, daily_demand)

        return {
            "inventory_id": inventory.id,
            "medicine_name": inventory.medicine.name,
            "brand": inventory.medicine.brand,
            "package_size": inventory.package_size,
            "current_stock": current_stock,
            "minimum_stock": min_stock,
            "days_of_cover": days_of_cover if days_of_cover != 999.0 else "30+",
            "days_of_cover_numeric": days_of_cover,
            "risk_level": risk_level,
            "safety_stock": safety_stock,
            "reorder_point": reorder_point,
            "reorder_recommended": reorder_recommended,
            "suggested_reorder_qty": suggested_reorder_qty,
            "trend": trend,
            "predicted_7_day_demand": predicted_7d_demand
        }

    @classmethod
    def detect_demand_trend(cls, pharmacy: Pharmacy, medicine: Medicine, current_daily_demand: float) -> str:
        """
        Detects trend direction: INCREASING, DECREASING, SPIKE, or STABLE by comparing recent 7d vs prior 30d averages.
        """
        timeseries = DemandDataService.get_timeseries_data(pharmacy, medicine, days=30)
        if len(timeseries) < 7:
            return "STABLE"

        recent_7d = [d["effective_demand"] for d in timeseries[-7:]]
        recent_avg = sum(recent_7d) / len(recent_7d)

        prior_30d = [d["effective_demand"] for d in timeseries[:-7]] if len(timeseries) > 7 else recent_7d
        prior_avg = (sum(prior_30d) / len(prior_30d)) if prior_30d else recent_avg

        search_spike = any(d["searches"] >= 10 for d in timeseries[-3:])

        if search_spike and recent_avg > prior_avg * 1.4:
            return "SPIKE"
        elif prior_avg > 0 and (recent_avg - prior_avg) / prior_avg >= 0.20:
            return "INCREASING"
        elif prior_avg > 0 and (prior_avg - recent_avg) / prior_avg >= 0.20:
            return "DECREASING"
        else:
            return "STABLE"


# ==========================================================
# 4. AI EXPLANATION SERVICE (GEMINI FLASH INTEGRATION)
# ==========================================================

class AIInventoryExplanationService:
    """
    Human-readable explanation layer powered by Gemini Flash.
    Converts deterministic prediction data into natural language WITHOUT altering numerical values or inferring unverified causation.
    """

    @classmethod
    def explain_inventory_insight(cls, insight_data: Dict[str, Any]) -> str:
        """
        Generates a concise, professional explanation for pharmacy managers based strictly on ML predictions.
        """
        med_name = insight_data.get("medicine_name", "Medicine")
        stock = insight_data.get("current_stock", 0)
        pred_7d = insight_data.get("predicted_7_day_demand", 0.0)
        risk = insight_data.get("risk_level", "LOW")
        doc = insight_data.get("days_of_cover", "N/A")
        trend = insight_data.get("trend", "STABLE")

        # Deterministic Structured Fallback
        fallback_msg = (
            f"{med_name} currently has {stock} units in stock with an estimated 7-day demand of {pred_7d:.1f} units "
            f"({doc} days of cover). Stock risk is classified as {risk} with a {trend.lower()} demand trend."
        )

        gemini_api_key = getattr(settings, "GEMINI_API_KEY", None)
        if not gemini_api_key:
            return fallback_msg

        prompt = f"""
You are an AI Inventory Intelligence Assistant for MediFind Pharmacy Platform.
Explain the following deterministic inventory forecasting result in 2 concise, professional sentences for a pharmacy owner.

STRICT RULES:
1. Do NOT alter any numbers provided. Use the exact values: stock={stock}, 7-day predicted demand={pred_7d:.1f}, days of cover={doc}, risk={risk}, trend={trend}.
2. Do NOT speculate or invent external causes (e.g. do NOT mention flu outbreaks or weather unless provided).
3. Focus purely on inventory management advice (e.g., review reordering, maintain current stock level).

DATA:
Medicine: {med_name}
Current Stock: {stock} units
Predicted 7-Day Demand: {pred_7d:.1f} units
Days of Cover: {doc} days
Risk Classification: {risk}
Demand Trend: {trend}
"""
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_api_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            response = model.generate_content(prompt)
            if response and response.text:
                return response.text.strip()
        except Exception as e:
            logger.warning(f"Gemini inventory explanation API error fallback: {str(e)}")

        return fallback_msg
