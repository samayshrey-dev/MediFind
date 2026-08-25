from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.conf import settings
from django.contrib.auth.decorators import login_required

from django.http import JsonResponse, HttpResponse
from django.db.models import Q
from collections import Counter
from django.utils import timezone
from datetime import timedelta
from datetime import datetime
from decimal import Decimal
import json
import re
import logging

logger = logging.getLogger(__name__)

from django.views.decorators.csrf import csrf_exempt
from .security import rate_limit, sanitize_plain_text, is_safe_external_url
from .ai_search import parse_query_with_ai, haversine_distance, SYMPTOM_MAP

from .fuzzy_search import MedicineMatcher
from .pharmacy_api import PharmacyAPIClient, MockPharmacyAPIService
from .excel_service import ExcelInventoryService
from .commerce_agent import (

    AICommerceAgent,
    IntentParser,
    AgentAuditService,
    AgentAuditLog,
    AgentState,
    OptimizationGoal
)

from .models import (
    Medicine,
    Pharmacy,
    Inventory,
    Reservation,
    SearchHistory,
    Notification,
    UserProfile,
    AgentAuditLog as AgentAuditLogModel,
    Order,
    WebhookEvent,
    PharmacyClaim,
)

from .commerce_service import (
    AgenticCommerceService,
    PriceMismatchError,
    OutOfStockError,
    CommerceError,
)


from .forms import (
    MedicineForm,
    PharmacyForm,
    InventoryForm,
    RegisterForm,
)


# ==========================================================
# Permissions
# ==========================================================

def pharmacy_required(view_func):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/login/?next={request.path}")

        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)

        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        if profile.role != "Pharmacy":
            messages.error(request, "Access denied. Pharmacy merchant account required.")
            return redirect("home")

        # Link fallback only if user has no assigned pharmacy AND no pending claimed pharmacy
        if not profile.pharmacy and not profile.claimed_pharmacy:
            email_match = Pharmacy.objects.filter(email__iexact=request.user.email).first()
            if email_match:
                profile.pharmacy = email_match
                profile.verification_status = "Approved"
                profile.save()

        return view_func(request, *args, **kwargs)

    return wrapper



def verified_pharmacy_required(view_func):
    """
    Guarantees that a pharmacy merchant has an Approved verification status before
    granting inventory publishing/modification access (adding, editing, deleting stock).
    """
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/login/?next={request.path}")

        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)

        profile = getattr(request.user, "userprofile", None)
        if not profile or profile.role != "Pharmacy":
            messages.error(request, "Access denied. Pharmacy merchant account required.")
            return redirect("home")

        if profile.verification_status != "Approved" or not profile.pharmacy:
            messages.warning(
                request,
                "VERIFICATION PENDING: Your pharmacy is being reviewed. You cannot publish inventory until verification is complete."
            )
            return redirect("pharmacy_dashboard")

        return view_func(request, *args, **kwargs)

    return wrapper


# ==========================================================
# Home
# ==========================================================

def home(request):
    user_pharmacy = None
    pharmacy_inventory_count = 0
    pharmacy_pending_count = 0
    today_orders_count = 0
    low_stock_count = 0
    out_of_stock_count = 0
    in_stock_count = 0
    inventory_health_pct = 100
    today_sales = Decimal("0.00")
    today_activities = []

    if request.user.is_authenticated:
        if hasattr(request.user, "userprofile") and request.user.userprofile.role == "Pharmacy":
            prof = request.user.userprofile
            user_pharmacy = prof.pharmacy or prof.claimed_pharmacy
            if not user_pharmacy and not prof.claimed_pharmacy:
                email_match = Pharmacy.objects.filter(email__iexact=request.user.email).first()
                if email_match:
                    user_pharmacy = email_match
                    prof.pharmacy = email_match
                    prof.verification_status = "Approved"
                    prof.save()
        elif request.user.is_superuser:
            user_pharmacy = Pharmacy.objects.first()

        if user_pharmacy:
            inv_qs = Inventory.objects.filter(pharmacy=user_pharmacy)
            pharmacy_inventory_count = inv_qs.count()
            pharmacy_pending_count = Reservation.objects.filter(pharmacy=user_pharmacy, status="Pending").count()
            low_stock_count = inv_qs.filter(quantity__gt=0, quantity__lte=10).count()
            out_of_stock_count = inv_qs.filter(quantity=0).count()
            in_stock_count = inv_qs.filter(quantity__gt=10).count()

            if pharmacy_inventory_count > 0:
                inventory_health_pct = int((in_stock_count / pharmacy_inventory_count) * 100)

            today_date = timezone.now().date()
            today_orders_qs = Reservation.objects.filter(pharmacy=user_pharmacy, requested_at__date=today_date)
            today_orders_count = today_orders_qs.count()

            # Compute real sales from completed/paid orders today
            paid_or_collected = today_orders_qs.filter(Q(is_paid=True) | Q(status__in=["Accepted", "Collected"]))
            for r in paid_or_collected:
                inv = inv_qs.filter(medicine=r.medicine).first()
                if inv and inv.price:
                    today_sales += (inv.price * r.quantity)

            # Build real recent activity list for Today's Activity section
            recent_res = Reservation.objects.filter(pharmacy=user_pharmacy).select_related("medicine", "customer").order_by("-requested_at")[:5]
            for r in recent_res:
                inv = inv_qs.filter(medicine=r.medicine).first()
                p = inv.price if inv and inv.price else Decimal("22.00")
                tot = p * r.quantity
                if r.status == "Collected":
                    today_activities.append({
                        "time": r.requested_at.strftime("%H:%M"),
                        "title": f"Order #{r.id:04d} Completed",
                        "desc": f"{r.medicine.name} ({r.quantity} units) · ₹{tot:.2f} collected",
                        "badge": "Completed",
                        "badge_class": "bg-success-subtle text-success border border-success-subtle",
                        "icon": "fa-circle-check",
                        "timestamp": r.requested_at,
                    })
                elif r.status == "Accepted":
                    today_activities.append({
                        "time": r.requested_at.strftime("%H:%M"),
                        "title": f"Order #{r.id:04d} Ready for Pickup",
                        "desc": f"{r.medicine.name} reserved for {r.customer.username}",
                        "badge": "Ready",
                        "badge_class": "bg-primary-subtle text-primary border border-primary-subtle",
                        "icon": "fa-clock",
                        "timestamp": r.requested_at,
                    })
                else:
                    today_activities.append({
                        "time": r.requested_at.strftime("%H:%M"),
                        "title": f"Order #{r.id:04d} Received",
                        "desc": f"{r.medicine.name} ({r.quantity} units) from {r.customer.username}",
                        "badge": "Pending",
                        "badge_class": "bg-warning-subtle text-warning-emphasis border border-warning-subtle",
                        "icon": "fa-clipboard-list",
                        "timestamp": r.requested_at,
                    })

            recent_inv = inv_qs.select_related("medicine").order_by("-updated_at")[:3]
            for itm in recent_inv:
                today_activities.append({
                    "time": itm.updated_at.strftime("%H:%M"),
                    "title": f"Stock Synced: {itm.medicine.name}",
                    "desc": f"{itm.quantity} units available · ₹{itm.price} retail",
                    "badge": "Inventory",
                    "badge_class": "bg-info-subtle text-info-emphasis border border-info-subtle",
                    "icon": "fa-boxes-stacked",
                    "timestamp": itm.updated_at,
                })

            today_activities.sort(key=lambda x: x["timestamp"], reverse=True)

    medicines = Medicine.objects.all()[:8]
    pharmacies = Pharmacy.objects.filter(is_active=True)[:4]
    all_pharmacies = Pharmacy.objects.filter(is_active=True)[:8]
    medicine_count = Medicine.objects.count()
    pharmacy_count = Pharmacy.objects.count()
    reservation_count = Reservation.objects.count()
    user_count = User.objects.count()

    context = {
        "popular_medicines": medicines,
        "pharmacies": pharmacies,
        "all_pharmacies": all_pharmacies,
        "medicine_count": medicine_count,
        "pharmacy_count": pharmacy_count,
        "reservation_count": reservation_count,
        "user_count": user_count,
        "user_pharmacy": user_pharmacy,
        "pharmacy_inventory_count": pharmacy_inventory_count,
        "pharmacy_pending_count": pharmacy_pending_count,
        "today_orders_count": today_orders_count,
        "low_stock_count": low_stock_count,
        "out_of_stock_count": out_of_stock_count,
        "in_stock_count": in_stock_count,
        "inventory_health_pct": inventory_health_pct,
        "today_sales": today_sales,
        "today_activities": today_activities,
    }

    return render(
        request,
        "home.html",
        context
    )



# ==========================================================
# AI Commerce Agent API Endpoints
# ==========================================================

@csrf_exempt
@rate_limit(max_requests=40, window_seconds=60, key_prefix="ai_agent_interpret", is_json=True)
def ai_commerce_agent_interpret(request):
    """
    POST /api/ai/interpret/
    Parses natural language query into structured commerce intent.
    """
    query = ""
    if request.method == "POST":
        try:
            body = json.loads(request.body.decode("utf-8")) if request.body else {}
            query = body.get("query", "")
        except Exception:
            query = request.POST.get("query", "")
    else:
        query = request.GET.get("query", "")

    query = sanitize_plain_text(query, max_length=150)
    intent = IntentParser.parse_with_ai(query)
    return JsonResponse(intent)


@csrf_exempt
@rate_limit(max_requests=40, window_seconds=60, key_prefix="ai_agent_search", is_json=True)
def ai_commerce_agent_search(request):
    """
    POST /api/ai/agent/search/
    Full AI Commerce Agent execution: Intent -> Search -> Rank -> Recommend -> Await Approval.
    """
    query = ""
    user_lat = None
    user_lng = None
    session_id = None

    if request.method == "POST":
        try:
            body = json.loads(request.body.decode("utf-8")) if request.body else {}
            query = body.get("query", "")
            user_lat = body.get("lat")
            user_lng = body.get("lng")
            session_id = body.get("session_id")
        except Exception:
            query = request.POST.get("query", "")
            user_lat = request.POST.get("lat")
            user_lng = request.POST.get("lng")
            session_id = request.POST.get("session_id")
    else:
        query = request.GET.get("query", "")
        user_lat = request.GET.get("lat")
        user_lng = request.GET.get("lng")
        session_id = request.GET.get("session_id")

    query = sanitize_plain_text(query, max_length=150)
    if session_id:
        session_id = sanitize_plain_text(str(session_id), max_length=64)

    try:
        if user_lat is not None:
            user_lat = float(user_lat)
        if user_lng is not None:
            user_lng = float(user_lng)
    except (ValueError, TypeError):
        user_lat = None
        user_lng = None

    user = request.user if request.user.is_authenticated else None

    # Track search in history if authenticated
    if user and query and hasattr(user, "userprofile") and user.userprofile.role == "Customer":
        try:
            SearchHistory.objects.create(user=user, medicine=query)
        except Exception:
            pass

    agent_result = AICommerceAgent.execute_search_flow(
        query=query,
        user_lat=user_lat,
        user_lng=user_lng,
        user=user,
        session_id=session_id
    )

    return JsonResponse(agent_result)


@csrf_exempt
@rate_limit(max_requests=30, window_seconds=60, key_prefix="ai_agent_approve", is_json=True)
def ai_commerce_agent_approve(request):
    """
    POST /api/ai/agent/approve/
    User approval gate: confirms purchase intent without charging payment.
    Transitions state: AWAITING_APPROVAL -> APPROVED.
    """
    session_id = None
    inventory_id = None

    if request.method == "POST":
        try:
            body = json.loads(request.body.decode("utf-8")) if request.body else {}
            session_id = body.get("session_id")
            inventory_id = body.get("inventory_id")
        except Exception:
            session_id = request.POST.get("session_id")
            inventory_id = request.POST.get("inventory_id")

    if not session_id or not inventory_id:
        return JsonResponse({
            "success": False,
            "message": "session_id and inventory_id are required."
        }, status=400)

    session_id = sanitize_plain_text(str(session_id), max_length=64)

    try:
        inventory_id = int(inventory_id)
    except (ValueError, TypeError):
        return JsonResponse({
            "success": False,
            "message": "Invalid inventory_id."
        }, status=400)

    user = request.user if request.user.is_authenticated else None
    approval_result = AICommerceAgent.handle_user_approval(
        session_id=session_id,
        inventory_id=inventory_id,
        user=user
    )

    return JsonResponse(approval_result)


@csrf_exempt
@rate_limit(max_requests=60, window_seconds=60, key_prefix="ai_agent_audit", is_json=True)
def ai_commerce_agent_audit(request, session_id):

    """
    GET /api/ai/agent/audit/<session_id>/
    Returns internal audit trail logs for an agent session.
    """
    logs = AgentAuditLogModel.objects.filter(session_id=session_id).order_by("created_at")
    trail = []
    for log in logs:
        trail.append({
            "id": log.id,
            "session_id": log.session_id,
            "event_type": log.event_type,
            "state": log.state,
            "payload": log.payload,
            "created_at": log.created_at.strftime("%Y-%m-%d %H:%M:%S")
        })

    return JsonResponse({
        "session_id": session_id,
        "count": len(trail),
        "audit_trail": trail
    })


# ==========================================================
# Phase 2: Razorpay Agentic Commerce API Endpoints
# ==========================================================

@csrf_exempt
def commerce_create_snapshot(request):
    """
    POST /api/commerce/snapshot/
    Creates a server-side immutable transaction snapshot when user reviews recommendation.
    """
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST method required."}, status=405)

    try:
        body = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        body = request.POST

    session_id = body.get("session_id")
    inventory_id = body.get("inventory_id")
    quantity = int(body.get("quantity", 1))

    if not session_id or not inventory_id:
        return JsonResponse({"success": False, "message": "session_id and inventory_id are required."}, status=400)

    try:
        user = request.user if request.user.is_authenticated else None
        order = AgenticCommerceService.create_transaction_snapshot(
            session_id=session_id,
            inventory_id=int(inventory_id),
            quantity=quantity,
            user=user
        )
        return JsonResponse({
            "success": True,
            "order_reference": order.order_reference,
            "session_id": order.session_id,
            "medicine_name": order.medicine.name,
            "medicine_brand": order.medicine.brand,
            "pharmacy_name": order.pharmacy.name,
            "quantity": order.quantity,
            "unit_price": float(order.unit_price),
            "total_amount": float(order.total_amount),
            "currency": order.currency,
            "status": order.status,
            "snapshot_data": order.snapshot_data
        })
    except CommerceError as e:
        return JsonResponse({"success": False, "message": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"success": False, "message": f"Server error: {str(e)}"}, status=500)


@csrf_exempt
def commerce_create_razorpay_order(request):
    """
    POST /api/payments/create-order/
    Explicit user confirmation -> Revalidates inventory & creates Razorpay Test Order.
    """
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST method required."}, status=405)

    try:
        body = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        body = request.POST

    order_reference = body.get("order_reference")
    if not order_reference:
        return JsonResponse({"success": False, "message": "order_reference is required."}, status=400)

    try:
        user = request.user if request.user.is_authenticated else None
        result = AgenticCommerceService.create_razorpay_test_order(
            order_reference=order_reference,
            user=user
        )
        return JsonResponse(result)
    except PriceMismatchError as e:
        return JsonResponse({
            "success": False,
            "error_type": "PRICE_CHANGED",
            "message": str(e),
            "old_price": e.old_price,
            "new_price": e.new_price
        }, status=409)
    except OutOfStockError as e:
        return JsonResponse({
            "success": False,
            "error_type": "OUT_OF_STOCK",
            "message": str(e)
        }, status=409)
    except CommerceError as e:
        return JsonResponse({"success": False, "message": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"success": False, "message": f"Payment initialization failed: {str(e)}"}, status=500)


@csrf_exempt
@login_required
def commerce_pay_reservation(request, reservation_id):
    """
    POST /api/payments/pay-reservation/<int:reservation_id>/
    Allows customer to directly pay merchant via Razorpay Test Mode for an existing reservation.
    """
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST method required."}, status=405)

    try:
        result = AgenticCommerceService.create_reservation_payment_order(
            reservation_id=reservation_id,
            user=request.user
        )
        return JsonResponse(result)
    except PriceMismatchError as e:
        return JsonResponse({
            "success": False,
            "error_type": "PRICE_CHANGED",
            "message": str(e),
            "old_price": e.old_price,
            "new_price": e.new_price
        }, status=409)
    except OutOfStockError as e:
        return JsonResponse({
            "success": False,
            "error_type": "OUT_OF_STOCK",
            "message": str(e)
        }, status=409)
    except CommerceError as e:
        return JsonResponse({"success": False, "message": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"success": False, "message": f"Payment initialization failed: {str(e)}"}, status=500)



@csrf_exempt
def commerce_verify_payment(request):
    """
    POST /api/payments/verify/
    Verifies Razorpay HMAC SHA256 payment signature server-side.
    """
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST method required."}, status=405)

    try:
        body = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        body = request.POST

    order_reference = body.get("order_reference")
    razorpay_order_id = body.get("razorpay_order_id")
    razorpay_payment_id = body.get("razorpay_payment_id")
    razorpay_signature = body.get("razorpay_signature")

    if not all([order_reference, razorpay_order_id, razorpay_payment_id, razorpay_signature]):
        return JsonResponse({
            "success": False,
            "message": "Missing required verification parameters."
        }, status=400)

    user = request.user if request.user.is_authenticated else None
    result = AgenticCommerceService.verify_payment_signature(
        order_reference=order_reference,
        razorpay_order_id=razorpay_order_id,
        razorpay_payment_id=razorpay_payment_id,
        razorpay_signature=razorpay_signature,
        user=user
    )

    status_code = 200 if result.get("success") else 400
    return JsonResponse(result, status=status_code)


@csrf_exempt
def commerce_fail_payment(request):
    """
    POST /api/payments/fail/
    Handles payment cancellation, decline, or checkout abandonment.
    """
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST method required."}, status=405)

    try:
        body = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        body = request.POST

    order_reference = body.get("order_reference")
    reason = body.get("reason", "Payment failed or cancelled by user.")

    if not order_reference:
        return JsonResponse({"success": False, "message": "order_reference is required."}, status=400)

    user = request.user if request.user.is_authenticated else None
    result = AgenticCommerceService.record_payment_failure(
        order_reference=order_reference,
        reason=reason,
        user=user
    )
    return JsonResponse(result)


@csrf_exempt
def commerce_razorpay_webhook(request):
    """
    POST /api/payments/razorpay/webhook/
    Public webhook receiver with raw-body HMAC SHA256 signature verification and idempotency.
    """
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST method required."}, status=405)

    raw_body = request.body
    signature_header = request.headers.get("X-Razorpay-Signature", "")
    event_id_header = request.headers.get("X-Razorpay-Event-Id", "")

    try:
        result = AgenticCommerceService.process_webhook(
            raw_body=raw_body,
            signature_header=signature_header,
            event_id=event_id_header
        )
        status_code = 200 if result.get("success") else 400
        return JsonResponse(result, status=status_code)
    except CommerceError as e:
        return JsonResponse({"success": False, "message": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"success": False, "message": f"Webhook processing error: {str(e)}"}, status=500)


@csrf_exempt
def commerce_order_status(request, order_reference):
    """
    GET /api/orders/<order_reference>/
    Returns order details and transaction status.
    """
    try:
        order = Order.objects.select_related("medicine", "pharmacy", "inventory").get(order_reference=order_reference)
        return JsonResponse({
            "success": True,
            "order_reference": order.order_reference,
            "medicine_name": order.medicine.name,
            "pharmacy_name": order.pharmacy.name,
            "quantity": order.quantity,
            "unit_price": float(order.unit_price),
            "total_amount": float(order.total_amount),
            "currency": order.currency,
            "status": order.status,
            "razorpay_order_id": order.razorpay_order_id,
            "razorpay_payment_id": order.razorpay_payment_id,
            "created_at": order.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "paid_at": order.paid_at.strftime("%Y-%m-%d %H:%M:%S") if order.paid_at else None
        })
    except Order.DoesNotExist:
        return JsonResponse({"success": False, "message": "Order not found."}, status=404)


def order_confirmed_view(request, order_reference):
    """
    GET /orders/confirmed/<order_reference>/
    Full order confirmation page with verified receipt and delivery timeline.
    """
    order = get_object_or_404(Order.objects.select_related("medicine", "pharmacy", "inventory"), order_reference=order_reference)
    return render(request, "order_confirmed.html", {
        "order": order
    })



# ==========================================================
# Medifind AI Natural-Language Medicine Search API
# ==========================================================
from .ai_search import execute_ai_medicine_search_pipeline, extract_search_intent_with_gemini

@csrf_exempt
@rate_limit(max_requests=40, window_seconds=60, key_prefix="ai_search_api", is_json=True)
def ai_search_api(request):
    """
    POST /api/ai/search/
    Full Natural-Language Medicine Search Pipeline:
    Input Validation -> Gemini Flash Intent Extraction -> Database Retrieval ->
    Deterministic Multi-Factor Ranking -> Grounded AI Explanation.
    """
    query = ""
    user_lat = None
    user_lng = None
    radius_km = None

    if request.method == "POST":
        try:
            body = json.loads(request.body.decode("utf-8")) if request.body else {}
            query = body.get("query", "")
            user_lat = body.get("latitude") or body.get("lat")
            user_lng = body.get("longitude") or body.get("lng")
            radius_km = body.get("radius_km") or body.get("radius")
        except Exception:
            query = request.POST.get("query", "")
            user_lat = request.POST.get("latitude") or request.POST.get("lat")
            user_lng = request.POST.get("longitude") or request.POST.get("lng")
            radius_km = request.POST.get("radius_km") or request.POST.get("radius")
    else:
        query = request.GET.get("query", "")
        user_lat = request.GET.get("latitude") or request.GET.get("lat")
        user_lng = request.GET.get("longitude") or request.GET.get("lng")
        radius_km = request.GET.get("radius_km") or request.GET.get("radius")

    query = sanitize_plain_text(query, max_length=200)

    # Validate Coordinates if provided
    try:
        if user_lat is not None and user_lat != "":
            user_lat = float(user_lat)
            if not (-90.0 <= user_lat <= 90.0):
                user_lat = None
        else:
            user_lat = None

        if user_lng is not None and user_lng != "":
            user_lng = float(user_lng)
            if not (-180.0 <= user_lng <= 180.0):
                user_lng = None
        else:
            user_lng = None
    except (ValueError, TypeError):
        user_lat = None
        user_lng = None

    # Validate Radius bounds (0.5 km to 50 km)
    try:
        if radius_km is not None and radius_km != "":
            radius_km = float(radius_km)
            radius_km = max(0.5, min(50.0, radius_km))
        else:
            radius_km = None
    except (ValueError, TypeError):
        radius_km = None

    if not query:
        return JsonResponse({
            "success": False,
            "message": "Please enter a medicine or symptom to search."
        }, status=400)

    # Execute end-to-end Medifind AI pipeline
    result = execute_ai_medicine_search_pipeline(
        query=query,
        user_lat=user_lat,
        user_lng=user_lng,
        radius_km=radius_km
    )

    return JsonResponse(result)




# ==========================================================
# 5-Tier Medicine Search Ranking Engine
# ==========================================================

def compute_sku_exactness_score(medicine, query_text):
    """
    Computes deterministic medicine/SKU exactness score (lower is higher priority/better match):
    0 = Exact full name or brand match (case-insensitive) e.g. "Dolo 650" == "dolo 650"
    1 = Exact prefix match (e.g. "Dolo 650 Tablet" starts with "Dolo 650")
    2 = All query tokens present in medicine name or brand
    3 = Substring in name, brand, uses, or description
    4 = Generic / Fuzzy / Symptom category match
    """
    if not query_text or not medicine:
        return 4

    q = str(query_text).strip().lower()
    m_name = str(medicine.name or "").strip().lower()
    m_brand = str(medicine.brand or "").strip().lower()
    m_uses = str(medicine.uses or "").strip().lower()
    m_desc = str(medicine.description or "").strip().lower()

    if m_name == q or m_brand == q:
        return 0

    clean_q = re.sub(r'[^a-z0-9\s]', ' ', q).strip()
    clean_name = re.sub(r'[^a-z0-9\s]', ' ', m_name).strip()

    if clean_name == clean_q:
        return 0

    if m_name.startswith(q) or clean_name.startswith(clean_q):
        return 1

    q_tokens = [tok for tok in clean_q.split() if len(tok) > 1]
    if q_tokens and all(tok in clean_name or tok in m_brand for tok in q_tokens):
        return 2

    if q in m_name or q in m_brand or q in m_uses or q in m_desc:
        return 3

    return 4


# ==========================================================
# Search (AI-Powered Natural-Language Medicine Search)
# ==========================================================

def search(request):
    query = sanitize_plain_text(request.GET.get("medicine", "").strip(), max_length=150)
    category = sanitize_plain_text(request.GET.get("category", "").strip(), max_length=100)
    sort = sanitize_plain_text(request.GET.get("sort", "").strip(), max_length=20)
    radius_param = sanitize_plain_text(request.GET.get("radius", "").strip(), max_length=10)
    user_lat_param = request.GET.get("lat", "").strip()
    user_lng_param = request.GET.get("lng", "").strip()
    ai_interpreted = sanitize_plain_text(request.GET.get("ai_interpreted", "").strip(), max_length=200)

    ai_result = None
    warning_msg = None


    if query:
        ai_result = parse_query_with_ai(query)
        if ai_result.get("warning"):
            warning_msg = ai_result.get("warning")
        
        if not ai_interpreted and ai_result.get("interpretation"):
            ai_interpreted = ai_result.get("interpretation")
            
        if not radius_param and ai_result.get("radius_km"):
            radius_param = str(ai_result.get("radius_km"))

    current_time = timezone.localtime().time()

    # Save search history
    if (
        request.user.is_authenticated
        and hasattr(request.user, "userprofile")
        and request.user.userprofile.role == "Customer"
        and query
    ):
        try:
            SearchHistory.objects.create(
                user=request.user,
                medicine=query
            )
        except Exception:
            pass

    # Direct Real-Time API Query to connected Pharmacy Systems
    if query:
        try:
            PharmacyAPIClient.query_all_enabled_pharmacies(query)
        except Exception as e:
            logger.warning(f"Live Pharmacy API sync warning: {e}")

    # Base Query: Active pharmacies only
    inventory = Inventory.objects.select_related(
        "medicine",
        "pharmacy"
    ).filter(pharmacy__is_active=True)

    did_you_mean = None

    # Filtering with AI / Natural-Language Search Terms & Fuzzy Matcher
    if query:
        # 1. Fuzzy matching & typo resolution
        fuzzy_matches = MedicineMatcher.find_matching_medicines(query, threshold=0.50)
        matched_med_ids = [m["medicine"].id for m in fuzzy_matches] if fuzzy_matches else []
        did_you_mean = MedicineMatcher.get_suggested_correction(query)

        search_terms = [query]
        if ai_result:
            if ai_result.get("medicine_name"):
                search_terms.append(ai_result["medicine_name"])
            if ai_result.get("generic_name"):
                search_terms.append(ai_result["generic_name"])
            if ai_result.get("search_term"):
                search_terms.append(ai_result["search_term"])

        q_objects = Q()
        if matched_med_ids:
            q_objects |= Q(medicine_id__in=matched_med_ids)

        for term in set(search_terms):
            if term and len(term) >= 2:
                q_objects |= Q(medicine__name__icontains=term)
                q_objects |= Q(medicine__brand__icontains=term)
                q_objects |= Q(medicine__description__icontains=term)
                q_objects |= Q(medicine__uses__icontains=term)

        # Only expand to symptom category if query is an explicit symptom search (e.g. "fever", "cough")
        is_symptom = any(sym in query.lower() for sym in SYMPTOM_MAP)
        if is_symptom and ai_result and ai_result.get("symptom_category"):
            q_objects |= Q(medicine__category__iexact=ai_result["symptom_category"])

        inventory = inventory.filter(q_objects)

    # Filter by category if manually specified
    if category and category != "All":
        inventory = inventory.filter(
            medicine__category=category
        )

    # Convert to list for distance, open status, and ranking
    inventory_items = list(inventory.distinct())

    # If user searched a specific query, prune unrelated items (sku_score > 3 unless matched via fuzzy)
    if query:
        filtered_items = []
        for item in inventory_items:
            sku = compute_sku_exactness_score(item.medicine, query)
            if sku <= 3 or (matched_med_ids and item.medicine.id in matched_med_ids):
                filtered_items.append(item)
        inventory_items = filtered_items

    user_lat = None
    user_lng = None
    if user_lat_param and user_lng_param:
        try:
            user_lat = float(user_lat_param)
            user_lng = float(user_lng_param)
        except ValueError:
            pass

    radius_km = None
    if radius_param:
        try:
            radius_km = float(radius_param)
        except ValueError:
            pass

    # Pharmacy Open / Closed Status & Distance Calculation
    for item in inventory_items:
        opening = item.pharmacy.opening_time
        closing = item.pharmacy.closing_time

        business_hours = (
            opening <= current_time <= closing
        )

        item.is_open = (
            item.pharmacy.is_open
            and business_hours
        )

        if item.is_open:
            item.status_text = f"Closes at {closing.strftime('%I:%M %p')}"
        else:
            item.status_text = f"Opens at {opening.strftime('%I:%M %p')}"

        if user_lat is not None and user_lng is not None:
            dist = haversine_distance(user_lat, user_lng, item.pharmacy.latitude, item.pharmacy.longitude)
            item.distance_km = round(dist, 1)
        else:
            item.distance_km = None

        item.is_live_api = getattr(item, 'is_live_api', False) or bool(item.pharmacy.api_sync_enabled and item.pharmacy.api_endpoint_url)

    # Filter by radius if radius_km is specified and user coordinates are available
    if radius_km is not None and user_lat is not None and user_lng is not None:
        inventory_items = [item for item in inventory_items if (getattr(item, 'distance_km', None) is not None and item.distance_km <= radius_km)]

    # ==========================================================
    # 5-Tier Deterministic Search Ranking
    # Tier 1: In stock (quantity > 0 before quantity == 0) -> ALWAYS Priority #1
    # Tier 2: Medicine/SKU exactness (Exact match > Prefix > Tokens > Substring > Fuzzy)
    # Tier 3: Distance (Closer before further)
    # Tier 4: Price (Lower price before higher)
    # Tier 5: Pharmacy open status (Open now before closed)
    # ==========================================================
    for item in inventory_items:
        item.sku_score = compute_sku_exactness_score(item.medicine, query)
        item.in_stock_tier = 0 if item.quantity > 0 else 1
        item.open_tier = 0 if getattr(item, 'is_open', False) else 1
        item.dist_sort = float(item.distance_km) if getattr(item, 'distance_km', None) is not None else 9999.0
        item.price_sort = float(item.price) if item.price is not None else 999999.0

    # Query-level deduplication & SKU packaging grouping per pharmacy
    # Prevents the same pharmacy from appearing multiple times while presenting genuine SKU variants
    pharmacy_grouped = {}
    for item in inventory_items:
        group_key = (item.pharmacy.id, item.medicine.id)
        if group_key not in pharmacy_grouped:
            item.available_skus = [
                {
                    "id": item.id,
                    "package_size": item.package_size or "Standard Pack",
                    "sku_code": item.sku_code or "",
                    "price": item.price,
                    "quantity": item.quantity,
                    "in_stock": item.quantity > 0,
                }
            ]
            pharmacy_grouped[group_key] = item
        else:
            primary = pharmacy_grouped[group_key]
            if not any(sku["package_size"] == (item.package_size or "Standard Pack") for sku in primary.available_skus):
                primary.available_skus.append({
                    "id": item.id,
                    "package_size": item.package_size or "Standard Pack",
                    "sku_code": item.sku_code or "",
                    "price": item.price,
                    "quantity": item.quantity,
                    "in_stock": item.quantity > 0,
                })
            # If primary was out of stock but this SKU is in stock, promote this SKU as primary
            if primary.quantity == 0 and item.quantity > 0:
                primary.price = item.price
                primary.quantity = item.quantity
                primary.package_size = item.package_size
                primary.id = item.id
                primary.in_stock_tier = 0
                primary.price_sort = item.price_sort

    for item in pharmacy_grouped.values():
        item.available_skus.sort(key=lambda s: float(s["price"]))

    inventory_items = list(pharmacy_grouped.values())

    if sort == "cheapest":
        inventory_items.sort(key=lambda x: (x.in_stock_tier, x.sku_score, x.price_sort, x.dist_sort, x.open_tier))
    elif sort == "nearest":
        inventory_items.sort(key=lambda x: (x.in_stock_tier, x.sku_score, x.dist_sort, x.price_sort, x.open_tier))
    elif sort == "open":
        inventory_items.sort(key=lambda x: (x.in_stock_tier, x.open_tier, x.sku_score, x.dist_sort, x.price_sort))
    else:
        # Default Ranking: 1. In-Stock -> 2. SKU Exactness -> 3. Distance -> 4. Price -> 5. Open Status
        inventory_items.sort(key=lambda x: (x.in_stock_tier, x.sku_score, x.dist_sort, x.price_sort, x.open_tier))

    # Partition available in-stock items and out-of-stock items
    # Guarantee: Top match is NEVER out of stock if any in-stock store exists
    in_stock_items = [item for item in inventory_items if item.quantity > 0]
    out_of_stock_items = [item for item in inventory_items if item.quantity <= 0]

    best_match_item = in_stock_items[0] if in_stock_items else None
    other_items = in_stock_items[1:] if len(in_stock_items) > 1 else []
    has_in_stock = len(in_stock_items) > 0
    zero_stock_message = f"No pharmacies currently have {query} in stock." if (query and not has_in_stock) else None

    # Marker Data for Interactive Map
    marker_data = []
    for item in inventory_items:
        marker_data.append({
            "medicine": item.medicine.name,
            "brand": item.medicine.brand,
            "pharmacy": item.pharmacy.name,
            "address": item.pharmacy.address,
            "city": item.pharmacy.city,
            "phone": item.pharmacy.phone,
            "price": float(item.price),
            "quantity": item.quantity,
            "is_open": item.is_open,
            "latitude": float(item.pharmacy.latitude),
            "longitude": float(item.pharmacy.longitude),
            "distance_km": getattr(item, 'distance_km', None)
        })

    categories = list(
        Medicine.objects.values_list("category", flat=True)
        .distinct()
        .exclude(category__isnull=True)
        .exclude(category="")
        .order_by("category")
    )

    explanation = "In stock at verified pharmacy with guaranteed live availability."
    if sort == "nearest" and best_match_item and getattr(best_match_item, 'distance_km', None) is not None:
        explanation = f"Nearest verified pharmacy ({best_match_item.distance_km} km) with active in-stock inventory."
    elif sort == "cheapest" and best_match_item:
        explanation = f"Lowest verified price (₹{best_match_item.price}) with available stock."
    elif best_match_item:
        if getattr(best_match_item, 'distance_km', None) is not None:
            explanation = f"Available in stock at nearest verified pharmacy ({best_match_item.distance_km} km) for ₹{best_match_item.price}."
        else:
            explanation = f"Lowest verified price (₹{best_match_item.price}) with active stock."

    distinct_pharmacies_count = len(set(item.pharmacy.id for item in in_stock_items))
    other_pharmacies_count = len(set(item.pharmacy.id for item in other_items))
    other_listings_count = sum(len(getattr(item, 'available_skus', [item])) for item in other_items)
    total_listings_count = sum(len(getattr(item, 'available_skus', [item])) for item in in_stock_items)
    out_of_stock_pharmacies_count = len(set(item.pharmacy.id for item in out_of_stock_items))

    return render(
        request,
        "search.html",
        {
            "inventory": inventory_items,
            "in_stock_items": in_stock_items,
            "out_of_stock_items": out_of_stock_items,
            "best_match_item": best_match_item,
            "other_items": other_items,
            "has_in_stock": has_in_stock,
            "zero_stock_message": zero_stock_message,
            "distinct_pharmacies_count": distinct_pharmacies_count,
            "other_pharmacies_count": other_pharmacies_count,
            "other_listings_count": other_listings_count,
            "total_listings_count": total_listings_count,
            "out_of_stock_pharmacies_count": out_of_stock_pharmacies_count,
            "explanation": explanation,
            "categories": categories,
            "query": query,
            "category": category,
            "sort": sort,
            "radius": radius_param,
            "ai_result": ai_result,
            "ai_interpreted": ai_interpreted,
            "did_you_mean": did_you_mean,
            "warning_msg": warning_msg,
            "marker_data": json.dumps(marker_data).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        }
    )



@csrf_exempt
def subscribe_stock_alert(request):
    """
    POST /api/notifications/stock-alert/
    Subscribes a customer to receive an alert when an out-of-stock medicine is restocked.
    """
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST method required."}, status=405)

    try:
        body = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        body = request.POST

    medicine_name = sanitize_plain_text(body.get("medicine_name") or body.get("medicine") or body.get("query", "").strip(), max_length=150)
    email = sanitize_plain_text(body.get("email", "").strip(), max_length=150)
    phone = sanitize_plain_text(body.get("phone", "").strip(), max_length=30)

    if not medicine_name:
        return JsonResponse({"success": False, "message": "Medicine name is required."}, status=400)

    user = request.user if request.user.is_authenticated else None
    
    # Create notification record if user is authenticated
    if user:
        try:
            Notification.objects.create(
                recipient=user,
                title=f"Stock Alert: {medicine_name}",
                message=f"You will be notified immediately when {medicine_name} is restocked at nearby verified pharmacies.",
                notification_type="Inventory"
            )
        except Exception:
            pass

    return JsonResponse({
        "success": True,
        "medicine_name": medicine_name,
        "message": f"You will be notified as soon as {medicine_name} is back in stock at nearby pharmacies."
    })


@rate_limit(max_requests=60, window_seconds=60, key_prefix="suggestions_api", is_json=True)
def search_suggestions(request):
    """
    GET /search/suggestions/?q=dollo
    Fault-tolerant auto-suggestions returning exact & fuzzy matched medicines.
    """
    query = sanitize_plain_text(request.GET.get("q", "").strip(), max_length=100)
    suggestions = []


    if query:
        seen_ids = set()

        # 1. Exact & Substring matches
        exact_meds = (
            Medicine.objects.filter(
                Q(name__icontains=query) |
                Q(brand__icontains=query)
            )
            .order_by("name")
            .distinct()[:8]
        )

        for medicine in exact_meds:
            seen_ids.add(medicine.id)
            suggestions.append({
                "id": medicine.id,
                "name": medicine.name,
                "brand": medicine.brand,
                "category": medicine.category
            })

        # 2. Fuzzy matches for typos & spelling mistakes
        if len(suggestions) < 6:
            fuzzy_matches = MedicineMatcher.find_matching_medicines(query, threshold=0.50, limit=8)
            for fm in fuzzy_matches:
                med = fm["medicine"]
                if med.id not in seen_ids:
                    seen_ids.add(med.id)
                    suggestions.append({
                        "id": med.id,
                        "name": med.name,
                        "brand": med.brand,
                        "category": med.category
                    })
                    if len(suggestions) >= 8:
                        break

    return JsonResponse(suggestions, safe=False)


# ==========================================================

# Details
# ==========================================================

def medicine_detail(request, id):

    medicine = get_object_or_404(Medicine, id=id)

    inventory_items = Inventory.objects.filter(medicine=medicine).select_related("pharmacy")

    current_time = timezone.localtime().time()

    for item in inventory_items:

        business_hours = (item.pharmacy.opening_time <= current_time <= item.pharmacy.closing_time)

        item.is_open = item.pharmacy.is_open and business_hours

    prices = [item.price for item in inventory_items if item.price]

    min_price = min(prices) if prices else 0

    return render(

        request,

        "medicine_detail.html",

        {

            "medicine": medicine,

            "inventory_items": inventory_items,

            "min_price": min_price,

        }

    )


def pharmacy_detail(request, id):

    pharmacy = get_object_or_404(Pharmacy, id=id)

    inventory_items = Inventory.objects.filter(pharmacy=pharmacy).select_related("medicine")

    current_time = timezone.localtime().time()

    is_open = pharmacy.is_open and (pharmacy.opening_time <= current_time <= pharmacy.closing_time)

    return render(

        request,

        "pharmacy_detail.html",

        {

            "pharmacy": pharmacy,

            "inventory_items": inventory_items,

            "is_open": is_open,

        }

    )


# ==========================================================
# Dashboard
# ==========================================================

@pharmacy_required
def dashboard(request):

    current_time = timezone.localtime().time()

    medicine_count = Medicine.objects.count()

    pharmacy_count = Pharmacy.objects.count()

    if request.user.is_superuser:

        inventory = Inventory.objects.select_related(
            "medicine",
            "pharmacy"
        )

        inventory_count = inventory.count()

        top_pharmacy = (
            Pharmacy.objects
            .order_by("name")
            .first()
        )

    else:

        inventory = Inventory.objects.select_related(
            "medicine",
            "pharmacy"
        ).filter(
            pharmacy=request.user.userprofile.pharmacy
        )

        inventory_count = inventory.count()

        top_pharmacy = request.user.userprofile.pharmacy

    active_pharmacies = Pharmacy.objects.filter(
        is_active=True
    ).count()

    medicines = Medicine.objects.all()

    category_counter = Counter()

    for medicine in medicines:
        category_counter[medicine.category] += 1

    category_labels = list(category_counter.keys())

    category_values = list(category_counter.values())

    stock_labels = []

    stock_values = []

    for item in inventory:

        is_open = (
        item.pharmacy.opening_time <= current_time <= item.pharmacy.closing_time
    )

        stock_labels.append(item.medicine.name)

        stock_values.append(item.quantity)

    low_stock = inventory.filter(quantity__lte=20)

    expiring = inventory.filter(
        expiry_date__lte=timezone.now().date() + timedelta(days=90)
    )

    recent_inventory = inventory.order_by("-created_at")[:5]

    context = {

        "medicine_count": medicine_count,

        "pharmacy_count": pharmacy_count,

        "inventory_count": inventory_count,

        "active_pharmacies": active_pharmacies,

        "category_labels": category_labels,

        "category_values": category_values,

        "stock_labels": stock_labels,

        "stock_values": stock_values,

        "low_stock": low_stock,

        "expiring": expiring,

        "recent_inventory": recent_inventory,

        "top_pharmacy": top_pharmacy,

    }

    return render(
        request,
        "dashboard.html",
        context
    )
@login_required
def toggle_pharmacy_status(request):
    if not hasattr(request.user, "userprofile") or request.user.userprofile.role != "Pharmacy":
        messages.error(
            request,
            "Access denied."
        )
        return redirect("home")

    pharmacy = getattr(request.user.userprofile, "pharmacy", None)
    if not pharmacy:
        messages.error(
            request,
            "No pharmacy associated with your account."
        )
        return redirect("home")


    pharmacy.is_open = not pharmacy.is_open

    pharmacy.save()

    if pharmacy.is_open:

        messages.success(
            request,
            "Pharmacy is now OPEN."
        )

    else:

        messages.warning(
            request,
            "Pharmacy is now CLOSED."
        )

    return redirect("pharmacy_dashboard")


# ==========================================================
# Medicines
# ==========================================================

def medicines(request):
    query = request.GET.get("q", "").strip()
    category = request.GET.get("category", "").strip()

    medicines_qs = Medicine.objects.all().order_by("name")

    if query:
        medicines_qs = medicines_qs.filter(
            Q(name__icontains=query) |
            Q(brand__icontains=query) |
            Q(description__icontains=query) |
            Q(uses__icontains=query)
        )

    if category and category != "All":
        medicines_qs = medicines_qs.filter(category__iexact=category)

    categories = [
        "Pain Relief",
        "Fever & Cold",
        "Allergy",
        "Digestive Health",
        "Vitamins & Supplements",
        "Diabetes Care",
        "Blood Pressure",
        "Skin Care",
        "First Aid",
        "Respiratory",
        "Eye Care",
        "Oral Care",
        "Antibiotic",
        "Heart",
    ]

    paginator = Paginator(medicines_qs, 12)
    page = request.GET.get("page")
    page_obj = paginator.get_page(page)

    return render(
        request,
        "medicines.html",
        {
            "medicines": page_obj,
            "query": query,
            "selected_category": category,
            "categories": categories,
            "total_count": medicines_qs.count(),
        }
    )



@verified_pharmacy_required
def add_medicine(request):

    if request.method == "POST":

        form = MedicineForm(
            request.POST,
            request.FILES
        )

        if form.is_valid():

            form.save()

            messages.success(
                request,
                "Medicine added successfully."
            )

            return redirect("medicines")

    else:

        form = MedicineForm()

    return render(
        request,
        "add_medicine.html",
        {
            "form": form
        }
    )


@verified_pharmacy_required
def edit_medicine(request, pk):

    medicine = get_object_or_404(
        Medicine,
        pk=pk
    )

    if request.method == "POST":

        form = MedicineForm(
            request.POST,
            request.FILES,
            instance=medicine
        )

        if form.is_valid():

            form.save()

            messages.success(
                request,
                "Medicine updated successfully."
            )

            return redirect("medicines")

    else:

        form = MedicineForm(
            instance=medicine
        )

    return render(
        request,
        "add_medicine.html",
        {
            "form": form
        }
    )


@pharmacy_required
def delete_medicine(request, pk):
    if not request.user.is_superuser:
        return render(request, "403.html", status=403)

    medicine = get_object_or_404(
        Medicine,
        pk=pk
    )

    medicine.delete()

    messages.success(
        request,
        "Medicine deleted successfully."
    )

    return redirect("medicines")



# ==========================================================
# Nearby Pharmacies API (Real Browser Geolocation & Inventory Discovery)
# ==========================================================

@csrf_exempt
@rate_limit(max_requests=60, window_seconds=60, key_prefix="nearby_api", is_json=True)
def nearby_pharmacies_api(request):
    """
    GET /api/pharmacies/nearby/?lat=...&lng=...&radius=5&sort=nearest
    Calculates verified Haversine distance, open status, and real medicine count from DB.
    """
    lat_str = request.GET.get("lat", "").strip()
    lng_str = request.GET.get("lng", "").strip()
    radius_str = request.GET.get("radius", "5").strip()
    sort_by = sanitize_plain_text(request.GET.get("sort", "nearest").strip(), max_length=20)
    query = sanitize_plain_text(request.GET.get("q", "").strip(), max_length=150)


    user_lat = None
    user_lng = None
    if lat_str and lng_str:
        try:
            user_lat = float(lat_str)
            user_lng = float(lng_str)
        except ValueError:
            pass

    radius_km = None
    if radius_str.lower() != "all" and radius_str:
        try:
            radius_km = float(radius_str)
        except ValueError:
            radius_km = None

    # Default to Chennai Central coordinates if no GPS provided
    calc_lat = user_lat if user_lat is not None else 13.0827
    calc_lng = user_lng if user_lng is not None else 80.2707

    current_time = timezone.localtime().time()
    all_pharmacies = Pharmacy.objects.filter(is_active=True)
    if query:
        all_pharmacies = all_pharmacies.filter(
            Q(name__icontains=query) | Q(address__icontains=query) | Q(city__icontains=query)
        )

    results = []
    for pharm in all_pharmacies:
        is_open = pharm.is_open and (pharm.opening_time <= current_time <= pharm.closing_time)
        dist_km = round(haversine_distance(calc_lat, calc_lng, float(pharm.latitude), float(pharm.longitude)), 1)
        
        if radius_km is not None and dist_km > radius_km:
            continue

        meds_count = Inventory.objects.filter(pharmacy=pharm, quantity__gt=0).count()
        has_connected_inventory = (meds_count > 0)

        results.append({
            "id": pharm.id,
            "name": pharm.name,
            "owner_name": pharm.owner_name,
            "phone": pharm.phone,
            "email": pharm.email,
            "address": pharm.address,
            "city": pharm.city,
            "state": pharm.state,
            "pincode": pharm.pincode,
            "latitude": float(pharm.latitude),
            "longitude": float(pharm.longitude),
            "is_open": is_open,
            "opening_time": pharm.opening_time.strftime("%I:%M %p"),
            "closing_time": pharm.closing_time.strftime("%I:%M %p"),
            "distance_km": dist_km,
            "medicines_available_count": meds_count,
            "has_connected_inventory": has_connected_inventory,
        })

    if sort_by == "open":
        results.sort(key=lambda x: (not x["is_open"], x["distance_km"]))
    elif sort_by == "medicines":
        results.sort(key=lambda x: (-x["medicines_available_count"], x["distance_km"]))
    else:
        results.sort(key=lambda x: x["distance_km"])

    return JsonResponse({
        "success": True,
        "user_location": {"lat": calc_lat, "lng": calc_lng},
        "radius_km": radius_km,
        "count": len(results),
        "pharmacies": results
    })


# ==========================================================
# Pharmacy Management & Discovery List
# ==========================================================

def pharmacies(request):
    user_lat_param = request.GET.get("lat", "").strip()
    user_lng_param = request.GET.get("lng", "").strip()
    radius_param = request.GET.get("radius", "all").strip()
    sort = request.GET.get("sort", "nearest").strip()
    query = request.GET.get("q", "").strip()

    user_lat = None
    user_lng = None
    if user_lat_param and user_lng_param:
        try:
            user_lat = float(user_lat_param)
            user_lng = float(user_lng_param)
        except ValueError:
            pass

    calc_lat = user_lat if user_lat is not None else 13.0827
    calc_lng = user_lng if user_lng is not None else 80.2707

    radius_km = None
    if radius_param.lower() != "all" and radius_param:
        try:
            radius_km = float(radius_param)
        except ValueError:
            radius_km = None

    current_time = timezone.localtime().time()
    pharmacy_qs = Pharmacy.objects.filter(is_active=True)
    if query:
        pharmacy_qs = pharmacy_qs.filter(
            Q(name__icontains=query) | Q(address__icontains=query) | Q(city__icontains=query)
        )

    pharmacies_list = list(pharmacy_qs)
    marker_data = []

    for pharm in pharmacies_list:
        pharm.is_open_now = pharm.is_open and (pharm.opening_time <= current_time <= pharm.closing_time)
        pharm.meds_count = Inventory.objects.filter(pharmacy=pharm, quantity__gt=0).count()
        pharm.has_connected_inventory = (pharm.meds_count > 0)
        dist = haversine_distance(calc_lat, calc_lng, float(pharm.latitude), float(pharm.longitude))
        pharm.distance_km = round(dist, 1)

    if radius_km is not None:
        pharmacies_list = [p for p in pharmacies_list if p.distance_km <= radius_km]

    if sort == "open":
        pharmacies_list.sort(key=lambda x: (not getattr(x, 'is_open_now', False), getattr(x, 'distance_km', 9999)))
    elif sort == "medicines":
        pharmacies_list.sort(key=lambda x: (-getattr(x, 'meds_count', 0), getattr(x, 'distance_km', 9999)))
    else:
        pharmacies_list.sort(key=lambda x: getattr(x, 'distance_km', 9999))

    for pharm in pharmacies_list:
        marker_data.append({
            "id": pharm.id,
            "name": pharm.name,
            "address": pharm.address,
            "city": pharm.city,
            "phone": pharm.phone,
            "is_open": getattr(pharm, 'is_open_now', True),
            "opening_time": pharm.opening_time.strftime("%I:%M %p"),
            "closing_time": pharm.closing_time.strftime("%I:%M %p"),
            "latitude": float(pharm.latitude),
            "longitude": float(pharm.longitude),
            "distance_km": getattr(pharm, 'distance_km', None),
            "medicines_available_count": getattr(pharm, 'meds_count', 0),
            "has_connected_inventory": getattr(pharm, 'has_connected_inventory', False),
        })


    return render(
        request,
        "pharmacies.html",
        {
            "pharmacies": pharmacies_list,
            "active_count": Pharmacy.objects.filter(is_active=True).count(),
            "open_count": sum(1 for p in pharmacies_list if getattr(p, 'is_open_now', False)),
            "user_lat": user_lat,
            "user_lng": user_lng,
            "radius": radius_param,
            "sort": sort,
            "query": query,
            "marker_data": json.dumps(marker_data).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        }
    )



@pharmacy_required
def add_pharmacy(request):

    if request.method == "POST":

        form = PharmacyForm(
            request.POST,
            request.FILES
        )

        if form.is_valid():

            form.save()

            messages.success(
                request,
                "Pharmacy added successfully."
            )

            return redirect("pharmacies")

    else:

        form = PharmacyForm()

    return render(
        request,
        "add_pharmacy.html",
        {
            "form": form
        }
    )
@pharmacy_required
def edit_pharmacy(request, pk):

    pharmacy = get_object_or_404(
        Pharmacy,
        pk=pk
    )

    if (
        not request.user.is_superuser
        and pharmacy != request.user.userprofile.pharmacy
    ):
        return render(
            request,
            "403.html",
            status=403
        )

    if request.method == "POST":

        form = PharmacyForm(
            request.POST,
            request.FILES,
            instance=pharmacy
        )

        if form.is_valid():

            form.save()

            messages.success(
                request,
                "Pharmacy updated successfully."
            )

            return redirect("pharmacies")

    else:

        form = PharmacyForm(
            instance=pharmacy
        )

    return render(
        request,
        "add_pharmacy.html",
        {
            "form": form
        }
    )


@pharmacy_required
def delete_pharmacy(request, pk):

    pharmacy = get_object_or_404(
        Pharmacy,
        pk=pk
    )

    if (
        not request.user.is_superuser
        and pharmacy != request.user.userprofile.pharmacy
    ):
        return render(
            request,
            "403.html",
            status=403
        )

    pharmacy.delete()

    messages.success(
        request,
        "Pharmacy deleted successfully."
    )

    return redirect("pharmacies")


# ==========================================================
# Inventory Management
# ==========================================================

@pharmacy_required
def inventory(request):
    query = request.GET.get("q", "").strip()
    category = request.GET.get("category", "").strip()
    stock_status = request.GET.get("stock_status", "all").strip().lower()
    sort = request.GET.get("sort", "name").strip()

    profile = getattr(request.user, "userprofile", None) if hasattr(request.user, "userprofile") else None
    verification_status = profile.verification_status if profile else "Approved"
    claimed_pharmacy = profile.claimed_pharmacy if profile else None
    pharmacy = profile.pharmacy if (profile and profile.pharmacy) else claimed_pharmacy

    active_claim = None
    if request.user.is_authenticated:
        active_claim = PharmacyClaim.objects.filter(user=request.user).order_by("-created_at").first()

    if not pharmacy and not claimed_pharmacy:
        email_match = Pharmacy.objects.filter(email__iexact=request.user.email).first()
        if email_match:
            pharmacy = email_match
            if hasattr(request.user, "userprofile"):
                request.user.userprofile.pharmacy = email_match
                request.user.userprofile.verification_status = "Approved"
                request.user.userprofile.save(update_fields=["pharmacy", "verification_status"])

    if request.user.is_superuser and not pharmacy:
        base_qs = Inventory.objects.select_related("medicine", "pharmacy")
    else:
        base_qs = Inventory.objects.select_related("medicine", "pharmacy").filter(pharmacy=pharmacy)

    # Compute overall metric counts before filtering
    total_count = base_qs.count()
    in_stock_count = base_qs.filter(quantity__gt=10).count()
    low_stock_count = base_qs.filter(quantity__gt=0, quantity__lte=10).count()
    out_of_stock_count = base_qs.filter(quantity=0).count()

    # Search filter
    filtered_qs = base_qs
    if query:
        filtered_qs = filtered_qs.filter(
            Q(medicine__name__icontains=query) |
            Q(medicine__brand__icontains=query) |
            Q(batch_number__icontains=query)
        )

    # Category filter
    if category and category != "All":
        filtered_qs = filtered_qs.filter(medicine__category__iexact=category)

    # Stock status filter
    if stock_status == "in_stock":
        filtered_qs = filtered_qs.filter(quantity__gt=10)
    elif stock_status == "low_stock":
        filtered_qs = filtered_qs.filter(quantity__gt=0, quantity__lte=10)
    elif stock_status == "out_of_stock":
        filtered_qs = filtered_qs.filter(quantity=0)

    # Sorting
    if sort == "price_asc":
        filtered_qs = filtered_qs.order_by("price")
    elif sort == "price_desc":
        filtered_qs = filtered_qs.order_by("-price")
    elif sort == "stock_asc":
        filtered_qs = filtered_qs.order_by("quantity")
    elif sort == "stock_desc":
        filtered_qs = filtered_qs.order_by("-quantity")
    elif sort == "updated":
        filtered_qs = filtered_qs.order_by("-updated_at")
    else:
        filtered_qs = filtered_qs.order_by("medicine__name")

    # Categories list
    categories = [
        "Pain Relief", "Fever & Cold", "Allergy", "Digestive Health",
        "Vitamins & Supplements", "Diabetes Care", "Blood Pressure",
        "Skin Care", "First Aid", "Respiratory", "Antibiotic", "Heart"
    ]

    paginator = Paginator(filtered_qs, 12)
    page = request.GET.get("page")
    page_obj = paginator.get_page(page)

    return render(
        request,
        "inventory.html",
        {
            "inventory": page_obj,
            "query": query,
            "category": category,
            "stock_status": stock_status,
            "sort": sort,
            "pharmacy": pharmacy,
            "total_count": total_count,
            "in_stock_count": in_stock_count,
            "low_stock_count": low_stock_count,
            "out_of_stock_count": out_of_stock_count,
            "categories": categories,
            "verification_status": verification_status,
            "is_verified": (verification_status == "Approved"),
            "claimed_pharmacy": claimed_pharmacy,
            "active_claim": active_claim,
            # Pre-built tab data for the template (avoids logic in HTML)
            "stock_tabs": [
                ("all",          "All",          total_count,         "secondary"),
                ("in_stock",     "Healthy",       in_stock_count,      "success"),
                ("low_stock",    "Low Stock",     low_stock_count,     "warning"),
                ("out_of_stock", "Out of Stock",  out_of_stock_count,  "danger"),
            ],
            "has_api_configured": bool(pharmacy and pharmacy.api_endpoint_url),
            "api_endpoint_url": pharmacy.api_endpoint_url if pharmacy else "",
            "api_auth_token": pharmacy.api_auth_token if pharmacy else "",
            "api_sync_enabled": pharmacy.api_sync_enabled if pharmacy else False,
            "api_sync_status": pharmacy.api_sync_status if pharmacy else "No API Configured",
            "api_last_synced_at": pharmacy.api_last_synced_at if pharmacy else None,
        }
    )


# ==========================================================
# Excel Bulk Inventory & Real-Time API Management
# ==========================================================

@pharmacy_required
def download_inventory_template(request):
    """
    GET /inventory/template/download/?format=xlsx|csv
    Generates and downloads the standardized MediAI Excel or CSV inventory template.
    """
    file_format = request.GET.get("format", "xlsx").lower()
    if file_format == "csv":
        csv_content = ExcelInventoryService.generate_csv_template()
        response = HttpResponse(csv_content, content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="MediAI_Inventory_Template.csv"'
        return response
    else:
        excel_bytes = ExcelInventoryService.generate_excel_template()
        response = HttpResponse(
            excel_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = 'attachment; filename="MediAI_Inventory_Template.xlsx"'
        return response


@verified_pharmacy_required
def upload_inventory_excel(request):
    """
    POST /inventory/upload/
    Handles pharmacy Excel (.xlsx, .xls) and CSV inventory uploads.
    Batch-validates rows, creates missing medicines, and syncs store inventory.
    """
    if request.method != "POST":
        return redirect("inventory")

    user_pharmacy = getattr(request.user.userprofile, "pharmacy", None) if hasattr(request.user, "userprofile") else None
    if not user_pharmacy:
        user_pharmacy = Pharmacy.objects.filter(email__iexact=request.user.email).first() or Pharmacy.objects.first()
        if hasattr(request.user, "userprofile") and user_pharmacy:
            request.user.userprofile.pharmacy = user_pharmacy
            request.user.userprofile.save(update_fields=["pharmacy"])

    if not user_pharmacy:
        messages.error(request, "No pharmacy associated with your account.")
        return redirect("inventory")

    uploaded_file = request.FILES.get("excel_file") or request.FILES.get("file")
    if not uploaded_file:
        messages.error(request, "Please select an Excel (.xlsx, .xls) or CSV file to upload.")
        return redirect("inventory")

    # Process uploaded inventory spreadsheet
    result = ExcelInventoryService.import_inventory_file(
        pharmacy=user_pharmacy,
        file_obj=uploaded_file,
        filename=uploaded_file.name
    )

    if result.get("success"):
        created = result.get("created_count", 0)
        updated = result.get("updated_count", 0)
        total = result.get("total_processed", 0)
        err_count = result.get("error_count", 0)

        msg = f"Excel Inventory Synced: {total} items successfully processed ({created} newly created, {updated} updated)."
        if err_count > 0:
            msg += f" Note: {err_count} row(s) had formatting errors."
            messages.warning(request, msg)
        else:
            messages.success(request, msg)
    else:
        messages.error(request, result.get("message", "Failed to process inventory upload."))

    return redirect("inventory")


@pharmacy_required
def export_inventory_excel(request):
    """
    GET /inventory/export/
    Exports the logged-in pharmacy's active inventory into an Excel spreadsheet.
    """
    user_pharmacy = getattr(request.user.userprofile, "pharmacy", None) if hasattr(request.user, "userprofile") else None
    if not user_pharmacy:
        user_pharmacy = Pharmacy.objects.filter(email__iexact=request.user.email).first() or Pharmacy.objects.first()

    if not user_pharmacy:
        messages.error(request, "No pharmacy associated with your account.")
        return redirect("inventory")

    excel_bytes = ExcelInventoryService.export_pharmacy_inventory(user_pharmacy)
    clean_name = re.sub(r'[^a-zA-Z0-9_]', '_', user_pharmacy.name)
    response = HttpResponse(
        excel_bytes,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="{clean_name}_Inventory_{timezone.now().strftime("%Y%m%d")}.xlsx"'
    return response


@pharmacy_required
def pharmacy_api_settings(request):
    """
    GET / POST /pharmacy/api-settings/
    Allows pharmacy owners to configure, test, and toggle real-time POS/ERP API integration.
    """
    user_pharmacy = getattr(request.user.userprofile, "pharmacy", None) if hasattr(request.user, "userprofile") else None
    if not user_pharmacy:
        user_pharmacy = Pharmacy.objects.filter(email__iexact=request.user.email).first() or Pharmacy.objects.first()

    if not user_pharmacy:
        return JsonResponse({"success": False, "message": "No pharmacy found."}, status=404)

    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.content_type == "application/json"

    if request.method == "POST":
        action = request.POST.get("action", "save")

        if action == "test":
            # Test connectivity to pharmacy endpoint
            test_query = request.POST.get("test_query", "Dolo 650").strip() or "Dolo 650"
            endpoint_override = request.POST.get("api_endpoint_url", "").strip()
            token_override = request.POST.get("api_auth_token", "").strip()

            if endpoint_override:
                user_pharmacy.api_endpoint_url = endpoint_override
            if token_override:
                user_pharmacy.api_auth_token = token_override

            test_result = PharmacyAPIClient.test_connection(user_pharmacy, test_query=test_query)
            return JsonResponse(test_result)

        elif action == "use_mock":
            # Set the built-in mock POS endpoint for testing
            mock_url = request.build_absolute_uri("/api/pharmacy-system/mock-inventory/")
            user_pharmacy.api_endpoint_url = mock_url
            user_pharmacy.api_sync_enabled = True
            user_pharmacy.api_sync_status = "Connected (MediAI Mock POS)"
            user_pharmacy.save(update_fields=["api_endpoint_url", "api_sync_enabled", "api_sync_status"])

            if is_ajax:
                return JsonResponse({
                    "success": True,
                    "message": "Connected to MediAI Mock Pharmacy System API.",
                    "api_endpoint_url": mock_url,
                    "api_sync_enabled": True,
                    "api_sync_status": user_pharmacy.api_sync_status
                })
            messages.success(request, "Connected to MediAI Mock Pharmacy System API for real-time inventory queries.")
            return redirect("inventory")

        else:
            # Save API settings
            endpoint = request.POST.get("api_endpoint_url", "").strip()
            token = request.POST.get("api_auth_token", "").strip()
            enabled = request.POST.get("api_sync_enabled") in ("on", "true", "1", "True")

            user_pharmacy.api_endpoint_url = endpoint if endpoint else None
            user_pharmacy.api_auth_token = token if token else None
            user_pharmacy.api_sync_enabled = bool(enabled and endpoint)
            user_pharmacy.api_sync_status = "Active" if user_pharmacy.api_sync_enabled else ("No API Configured" if not endpoint else "Disabled")
            user_pharmacy.save(update_fields=["api_endpoint_url", "api_auth_token", "api_sync_enabled", "api_sync_status"])

            if is_ajax:
                return JsonResponse({
                    "success": True,
                    "message": "Pharmacy API integration settings saved successfully.",
                    "api_endpoint_url": user_pharmacy.api_endpoint_url or "",
                    "api_sync_enabled": user_pharmacy.api_sync_enabled,
                    "api_sync_status": user_pharmacy.api_sync_status
                })
            messages.success(request, "Pharmacy API integration settings saved successfully.")
            return redirect("inventory")

    return JsonResponse({
        "success": True,
        "pharmacy_name": user_pharmacy.name,
        "api_endpoint_url": user_pharmacy.api_endpoint_url or "",
        "api_auth_token": user_pharmacy.api_auth_token or "",
        "api_sync_enabled": user_pharmacy.api_sync_enabled,
        "api_sync_status": user_pharmacy.api_sync_status,
        "api_last_synced_at": user_pharmacy.api_last_synced_at.strftime("%Y-%m-%d %H:%M:%S") if user_pharmacy.api_last_synced_at else None
    })


@csrf_exempt
def mock_pharmacy_system_api(request):
    """
    GET /api/pharmacy-system/mock-inventory/?q=dolo&pharmacy_id=1
    Simulates a 3rd-party pharmacy POS/ERP REST API.
    Returns real-time inventory quantities and prices in JSON format.
    """
    query = request.GET.get("q") or request.GET.get("medicine") or ""
    results = MockPharmacyAPIService.search_mock_inventory(query)
    return JsonResponse({
        "status": "success",
        "system": "MediAI POS Simulator v2.4",
        "timestamp": timezone.now().isoformat(),
        "query": query,
        "count": len(results),
        "items": results
    })


@verified_pharmacy_required
def add_inventory(request):
    """
    Redirects legacy 'add inventory' calls to the Excel/API bulk inventory management flow.
    """
    messages.info(
        request,
        "Manual item-by-item stock addition has been replaced. Please upload your inventory using the Excel Template or connect your Pharmacy POS API."
    )
    return redirect("inventory")
# ==========================================================
# Inventory Management
# ==========================================================

@verified_pharmacy_required
def edit_inventory(request, pk):
    item = get_object_or_404(
        Inventory,
        pk=pk
    )
    user_pharmacy = getattr(request.user.userprofile, "pharmacy", None) if hasattr(request.user, "userprofile") else None

    if (
        not request.user.is_superuser
        and item.pharmacy != user_pharmacy
    ):
        return render(
            request,
            "403.html",
            status=403
        )

    if request.method == "POST":
        form = InventoryForm(
            request.POST,
            instance=item
        )
        if form.is_valid():
            form.save()
            messages.success(
                request,
                f"Updated stock details for {item.medicine.name}."
            )
            return redirect("inventory")
    else:
        form = InventoryForm(
            instance=item
        )

    medicines = Medicine.objects.all().order_by("name")
    return render(
        request,
        "add_inventory.html",
        {
            "form": form,
            "item": item,
            "medicines": medicines,
            "user_pharmacy": user_pharmacy,
            "is_edit": True,
        }
    )


@verified_pharmacy_required
def delete_inventory(request, pk):

    item = get_object_or_404(
        Inventory,
        pk=pk
    )

    if (
        not request.user.is_superuser
        and item.pharmacy != request.user.userprofile.pharmacy
    ):
        return render(
            request,
            "403.html",
            status=403
        )

    item.delete()

    messages.success(
        request,
        "Inventory deleted successfully."
    )

    return redirect("inventory")


@login_required
@verified_pharmacy_required
def update_stock(request, pk):
    """
    AJAX endpoint: update inventory quantity inline.
    POST body (JSON or form): { "action": "set"|"add"|"subtract", "value": N }
    Returns JSON { success, quantity, status_label, status_class }
    """
    item = get_object_or_404(Inventory, pk=pk)
    user_pharmacy = getattr(request.user.userprofile, "pharmacy", None) if hasattr(request.user, "userprofile") else None

    if not request.user.is_superuser and item.pharmacy != user_pharmacy:
        return JsonResponse({"success": False, "message": "Permission denied."}, status=403)

    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST required."}, status=405)

    try:
        import json as _json
        body = _json.loads(request.body)
    except Exception:
        body = request.POST

    action = body.get("action", "set")
    try:
        value = int(body.get("value", 0))
    except (ValueError, TypeError):
        return JsonResponse({"success": False, "message": "Invalid value."}, status=400)

    if action == "add":
        item.quantity = max(0, item.quantity + value)
    elif action == "subtract":
        item.quantity = max(0, item.quantity - value)
    else:  # "set"
        item.quantity = max(0, value)

    item.save(update_fields=["quantity", "updated_at"])

    # Compute human-readable status
    if item.quantity > 10:
        status_label, status_class = "Healthy", "success"
    elif item.quantity > 0:
        status_label, status_class = "Low Stock", "warning"
    else:
        status_label, status_class = "Out of Stock", "danger"

    return JsonResponse({
        "success": True,
        "quantity": item.quantity,
        "status_label": status_label,
        "status_class": status_class,
        "medicine_name": item.medicine.name,
    })


@login_required
def inventory_history(request, pk):
    """
    Shows all reservations and orders for a specific inventory item.
    Accessible by the owning pharmacy user.
    """
    item = get_object_or_404(Inventory.objects.select_related("medicine", "pharmacy"), pk=pk)
    user_pharmacy = getattr(request.user.userprofile, "pharmacy", None) if hasattr(request.user, "userprofile") else None

    if not request.user.is_superuser and item.pharmacy != user_pharmacy:
        return render(request, "403.html", status=403)

    reservations = (
        Reservation.objects
        .filter(medicine=item.medicine, pharmacy=item.pharmacy)
        .select_related("customer")
        .order_by("-requested_at")[:50]
    )

    return render(request, "inventory_history.html", {
        "item": item,
        "reservations": reservations,
        "pharmacy": item.pharmacy,
    })


# ==========================================================
# Authentication
# ==========================================================

@rate_limit(max_requests=10, window_seconds=60, key_prefix="register")
def register(request):


    if request.method == "POST":

        form = RegisterForm(request.POST)

        if form.is_valid():

            username = form.cleaned_data["username"]

            if User.objects.filter(username=username).exists():

                messages.error(

                    request,

                    "Username already exists. Please choose another username."

                )

                return render(

                    request,

                    "register.html",

                    {

                        "form": form

                    }

                )

            user = User.objects.create_user(

                username=username,

                password=form.cleaned_data["password"],

                first_name=form.cleaned_data["first_name"],

                email=form.cleaned_data["email"]

            )

            role = form.cleaned_data["role"]

            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = role

            if role == "Pharmacy":
                option = form.cleaned_data.get("pharmacy_option")
                drug_license = form.cleaned_data.get("drug_license_number") or "PENDING-DOCS"
                gstin = form.cleaned_data.get("gstin", "")
                owner_proof = form.cleaned_data.get("owner_proof", "")

                if option == "existing" and form.cleaned_data.get("existing_pharmacy"):
                    claimed = form.cleaned_data.get("existing_pharmacy")
                    profile.claimed_pharmacy = claimed
                    profile.pharmacy = None  # No immediate publishing access until admin approval
                    profile.verification_status = "Pending"

                    PharmacyClaim.objects.create(
                        user=user,
                        pharmacy=claimed,
                        drug_license_number=drug_license,
                        gstin=gstin,
                        owner_proof=owner_proof,
                        status="Pending"
                    )

                    messages.warning(
                        request,
                        f"VERIFICATION PENDING: Your ownership claim for {claimed.name} is currently under admin review. You cannot publish inventory until verification is complete."
                    )

                elif option == "new" and form.cleaned_data.get("new_pharmacy_name"):
                    from datetime import time

                    pharmacy_instance = Pharmacy.objects.create(
                        name=form.cleaned_data.get("new_pharmacy_name"),
                        owner_name=form.cleaned_data["first_name"] or username,
                        phone=form.cleaned_data.get("new_pharmacy_phone") or "9876543210",
                        email=form.cleaned_data["email"],
                        address=form.cleaned_data.get("new_pharmacy_address") or "City Center, Main Road",
                        city=form.cleaned_data.get("new_pharmacy_city") or "Chennai",
                        state="Tamil Nadu",
                        pincode="600001",
                        latitude=13.0827,
                        longitude=80.2707,
                        opening_time=time(8, 0),
                        closing_time=time(22, 0),
                        license_number=drug_license,
                        verification_status="Pending",
                        is_active=False,  # Hidden from public search until verified
                        is_open=True,
                    )

                    profile.claimed_pharmacy = pharmacy_instance
                    profile.pharmacy = pharmacy_instance
                    profile.verification_status = "Pending"

                    PharmacyClaim.objects.create(
                        user=user,
                        pharmacy=pharmacy_instance,
                        drug_license_number=drug_license,
                        gstin=gstin,
                        owner_proof=owner_proof,
                        status="Pending"
                    )

                    messages.warning(
                        request,
                        f"VERIFICATION PENDING: Your new pharmacy registration for {pharmacy_instance.name} has been submitted for review. You cannot publish inventory until verification is complete."
                    )
            else:
                profile.verification_status = "Approved"
                messages.success(
                    request,
                    f"Welcome to MediAI, {user.first_name or user.username}! Account created successfully."
                )

            profile.save()
            user.refresh_from_db()
            login(request, user)
            return redirect("dashboard_redirect")

    else:

        form = RegisterForm()

    return render(

        request,

        "register.html",

        {

            "form": form

        }

    )
# ==========================================================
# Profile
# ==========================================================

@login_required
def profile(request):

    searches = SearchHistory.objects.filter(
        user=request.user
    ).order_by("-searched_at")

    reservations = Reservation.objects.filter(
        customer=request.user
    ).order_by("-requested_at")

    context = {

        "search_count": searches.count(),

        "reservation_count": reservations.count(),

        "recent_searches": searches[:5],

        "recent_reservations": reservations[:5],

    }

    return render(
        request,
        "profile.html",
        context
    )
# ==========================================================
# Dashboard Redirect
# ==========================================================

@login_required
def dashboard_redirect(request):
    next_url = request.GET.get("next") or request.POST.get("next")
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)

    if request.user.is_superuser:
        return redirect("dashboard")

    if hasattr(request.user, "userprofile") and request.user.userprofile.role == "Pharmacy":
        return redirect("home")

    return redirect("home")


def notify_reservation_update(reservation, action, actor_user):
    """
    Creates bidirectional real-time notifications for both Customer and Pharmacy Owner(s).
    """
    try:
        pharmacy = reservation.pharmacy
        medicine = reservation.medicine
        customer = reservation.customer

        # Find pharmacy owner profiles
        pharmacy_profiles = UserProfile.objects.filter(pharmacy=pharmacy)
        pharmacy_users = [p.user for p in pharmacy_profiles if p.user]

        # ACTION 1: New Reservation Created
        if action == "NEW_RESERVATION":
            # 1. Notify Customer (Confirmation)
            Notification.objects.create(
                recipient=customer,
                sender=actor_user,
                reservation=reservation,
                title="Reservation Sent",
                message=f"Your reservation request for {medicine.name} at {pharmacy.name} was successfully submitted.",
                notification_type="Reservation"
            )
            # 2. Notify Pharmacy Owner(s)
            for owner in pharmacy_users:
                Notification.objects.create(
                    recipient=owner,
                    sender=actor_user,
                    reservation=reservation,
                    title="New Reservation Request",
                    message=f"Customer {customer.first_name or customer.username} requested {reservation.quantity} unit(s) of {medicine.name}.",
                    notification_type="Reservation"
                )

        # ACTION 2: Reservation Accepted
        elif action == "ACCEPTED":
            # 1. Notify Customer
            Notification.objects.create(
                recipient=customer,
                sender=actor_user,
                reservation=reservation,
                title="Reservation Accepted",
                message=f"Good news! {pharmacy.name} accepted your reservation for {medicine.name}.",
                notification_type="Accepted"
            )
            # 2. Notify Pharmacy Owner(s)
            for owner in pharmacy_users:
                Notification.objects.create(
                    recipient=owner,
                    sender=actor_user,
                    reservation=reservation,
                    title="Reservation Accepted",
                    message=f"Reservation #{reservation.id} for {medicine.name} was marked as Accepted.",
                    notification_type="Accepted"
                )

        # ACTION 3: Reservation Rejected
        elif action == "REJECTED":
            # 1. Notify Customer
            Notification.objects.create(
                recipient=customer,
                sender=actor_user,
                reservation=reservation,
                title="Reservation Rejected",
                message=f"{pharmacy.name} was unable to fulfill your reservation for {medicine.name}.",
                notification_type="Rejected"
            )
            # 2. Notify Pharmacy Owner(s)
            for owner in pharmacy_users:
                Notification.objects.create(
                    recipient=owner,
                    sender=actor_user,
                    reservation=reservation,
                    title="Reservation Rejected",
                    message=f"Reservation #{reservation.id} for {medicine.name} was marked as Rejected.",
                    notification_type="Rejected"
                )

        # ACTION 4: Payment Verified (Razorpay)
        elif action == "PAID":
            # 1. Notify Customer
            Notification.objects.create(
                recipient=customer,
                sender=actor_user,
                reservation=reservation,
                title="Payment Verified",
                message=f"Your Razorpay payment for {medicine.name} at {pharmacy.name} was successfully verified.",
                notification_type="Accepted"
            )
            # 2. Notify Pharmacy Owner(s)
            for owner in pharmacy_users:
                Notification.objects.create(
                    recipient=owner,
                    sender=actor_user,
                    reservation=reservation,
                    title="Payment Received (Verified)",
                    message=f"Customer {customer.first_name or customer.username} completed online payment for order #{reservation.id} ({medicine.name}).",
                    notification_type="Reservation"
                )
    except Exception as e:
        print("NOTIFICATION CREATION WARNING:", e)


# ==========================================================
# Reservation System
# ==========================================================

@login_required
@rate_limit(max_requests=20, window_seconds=60, key_prefix="reserve")
def reserve_medicine(request, inventory_id):

    """
    Renders reservation checkout page and processes medicine reservations
    with choice of Pay Online (Razorpay) or Pay at Pharmacy on Pickup.
    """
    inventory = get_object_or_404(
        Inventory.objects.select_related("medicine", "pharmacy"),
        id=inventory_id
    )

    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.content_type == "application/json"

    if request.user.userprofile.role != "Customer":
        if is_ajax:
            return JsonResponse({"success": False, "message": "Only customers can reserve medicines."}, status=403)
        messages.error(
            request,
            "Only customers can reserve medicines."
        )
        return redirect("search")

    if inventory.quantity <= 0:
        if is_ajax:
            return JsonResponse({"success": False, "message": f"{inventory.medicine.name} is currently out of stock."}, status=400)
        messages.error(
            request,
            f"{inventory.medicine.name} is currently out of stock."
        )
        return redirect("search")

    # If GET request: render the interactive reservation and payment selection page
    if request.method == "GET":
        available_skus = Inventory.objects.filter(
            pharmacy=inventory.pharmacy,
            medicine=inventory.medicine
        ).order_by("price")

        return render(request, "reserve_medicine.html", {
            "inventory": inventory,
            "medicine": inventory.medicine,
            "pharmacy": inventory.pharmacy,
            "package_size": inventory.package_size or "Strip of 15",
            "available_skus": available_skus,
            "razorpay_key_id": getattr(settings, "RAZORPAY_KEY_ID", "rzp_test_TSJYKlbEfXc5n1"),
            "unit_price": inventory.price,
            "max_quantity": min(inventory.quantity, 10),
        })

    # POST Handling
    try:
        quantity = int(request.POST.get("quantity", 1))
    except (ValueError, TypeError):
        quantity = 1
    quantity = max(1, min(quantity, inventory.quantity))
    payment_choice = request.POST.get("payment_method", "PayOnPickup")
    notes = request.POST.get("notes", "").strip()

    # Check for existing pending reservation
    existing = Reservation.objects.filter(
        customer=request.user,
        pharmacy=inventory.pharmacy,
        medicine=inventory.medicine,
        status="Pending"
    ).first()

    if payment_choice == "Online":
        if existing:
            reservation = existing
            reservation.quantity = quantity
            reservation.notes = notes
            reservation.payment_method = "Online"
            reservation.save(update_fields=["quantity", "notes", "payment_method"])
        else:
            reservation = Reservation.objects.create(
                customer=request.user,
                pharmacy=inventory.pharmacy,
                medicine=inventory.medicine,
                quantity=quantity,
                status="Pending",
                payment_method="Online",
                is_paid=False,
                notes=notes
            )
            notify_reservation_update(reservation, "NEW_RESERVATION", request.user)

        try:
            order_data = AgenticCommerceService.create_reservation_payment_order(
                reservation_id=reservation.id,
                user=request.user
            )
            return JsonResponse(order_data)
        except PriceMismatchError as e:
            return JsonResponse({
                "success": False,
                "error_type": "PRICE_CHANGED",
                "message": str(e),
                "old_price": e.old_price,
                "new_price": e.new_price
            }, status=409)
        except OutOfStockError as e:
            return JsonResponse({
                "success": False,
                "error_type": "OUT_OF_STOCK",
                "message": str(e)
            }, status=409)
        except CommerceError as e:
            return JsonResponse({"success": False, "message": str(e)}, status=400)
        except Exception as e:
            return JsonResponse({"success": False, "message": f"Online reservation initialization failed: {str(e)}"}, status=500)

    elif payment_choice == "PayOnPickup":
        if existing:
            if is_ajax:
                return JsonResponse({
                    "success": False,
                    "message": "You already have a pending reservation for this medicine. You can view or manage it in My Reservations."
                }, status=400)
            messages.warning(
                request,
                "You already have a pending reservation for this medicine. You can pay or manage it below."
            )
            return redirect("my_reservations")

        reservation = Reservation.objects.create(
            customer=request.user,
            pharmacy=inventory.pharmacy,
            medicine=inventory.medicine,
            quantity=quantity,
            status="Pending",
            payment_method="PayOnPickup",
            is_paid=False,
            notes=notes
        )

        # Send notifications
        notify_reservation_update(reservation, "NEW_RESERVATION", request.user)

        total_amount = inventory.price * quantity
        if is_ajax:
            return JsonResponse({
                "success": True,
                "message": f"Reservation confirmed! Your order for {inventory.medicine.name} is reserved. Please pay ₹{total_amount:.2f} at {inventory.pharmacy.name} upon collection."
            })

        messages.success(
            request,
            f"Reservation confirmed! Your order for {inventory.medicine.name} is reserved. Please pay ₹{total_amount:.2f} at {inventory.pharmacy.name} upon collection."
        )
        return redirect("my_reservations")

    return redirect("my_reservations")

@pharmacy_required
def reservations(request):
    tab = request.GET.get("tab", "all").strip().lower()
    query = request.GET.get("q", "").strip()

    pharmacy = getattr(request.user.userprofile, "pharmacy", None) if hasattr(request.user, "userprofile") else None
    if not pharmacy:
        pharmacy = Pharmacy.objects.filter(email__iexact=request.user.email).first() or Pharmacy.objects.first()
        if hasattr(request.user, "userprofile") and pharmacy:
            request.user.userprofile.pharmacy = pharmacy
            request.user.userprofile.save(update_fields=["pharmacy"])

    if request.user.is_superuser and not pharmacy:
        base_qs = Reservation.objects.select_related("customer", "medicine", "pharmacy")
    else:
        base_qs = Reservation.objects.select_related("customer", "medicine", "pharmacy").filter(pharmacy=pharmacy)

    # Tab counts
    total_count = base_qs.count()
    pending_count = base_qs.filter(status="Pending").count()
    accepted_count = base_qs.filter(status="Accepted").count()
    collected_count = base_qs.filter(status="Collected").count()
    cancelled_count = base_qs.filter(status__in=["Rejected", "Cancelled"]).count()

    filtered_qs = base_qs
    if tab == "pending":
        filtered_qs = filtered_qs.filter(status="Pending")
    elif tab in ("processing", "ready", "accepted"):
        filtered_qs = filtered_qs.filter(status="Accepted")
    elif tab in ("completed", "collected"):
        filtered_qs = filtered_qs.filter(status="Collected")
    elif tab in ("cancelled", "rejected"):
        filtered_qs = filtered_qs.filter(status__in=["Rejected", "Cancelled"])

    if query:
        filtered_qs = filtered_qs.filter(
            Q(medicine__name__icontains=query) |
            Q(customer__username__icontains=query) |
            Q(customer__first_name__icontains=query)
        )

    # Attach unit price, formatted total and human-readable order code
    reservations_list = list(filtered_qs.order_by("-requested_at"))
    for r in reservations_list:
        inv = Inventory.objects.filter(pharmacy=r.pharmacy, medicine=r.medicine).first()
        unit_price = inv.price if inv and inv.price else Decimal("22.00")
        r.unit_price = unit_price
        r.calculated_total = unit_price * r.quantity
        r.order_code = f"MF-{r.id:04d}"

    paginator = Paginator(reservations_list, 15)
    page = request.GET.get("page")
    page_obj = paginator.get_page(page)

    return render(
        request,
        "reservations.html",
        {
            "reservations": page_obj,
            "pharmacy": pharmacy,
            "tab": tab,
            "query": query,
            "total_count": total_count,
            "pending_count": pending_count,
            "accepted_count": accepted_count,
            "collected_count": collected_count,
            "cancelled_count": cancelled_count,
        }
    )


@pharmacy_required
def reservation_history(request):
    pharmacy = getattr(request.user.userprofile, "pharmacy", None) if hasattr(request.user, "userprofile") else None
    if not pharmacy:
        pharmacy = Pharmacy.objects.filter(email__iexact=request.user.email).first() or Pharmacy.objects.first()
        if hasattr(request.user, "userprofile") and pharmacy:
            request.user.userprofile.pharmacy = pharmacy
            request.user.userprofile.save(update_fields=["pharmacy"])

    reservations_qs = Reservation.objects.filter(pharmacy=pharmacy).select_related("medicine", "customer").order_by("-requested_at")
    inventory_updates = Inventory.objects.filter(pharmacy=pharmacy).select_related("medicine").order_by("-updated_at")[:20]

    timeline_items = []
    today = timezone.now().date()
    yesterday = today - timedelta(days=1)

    for r in reservations_qs[:40]:
        inv = Inventory.objects.filter(pharmacy=r.pharmacy, medicine=r.medicine).first()
        price = inv.price if inv and inv.price else Decimal("22.00")
        total = price * r.quantity

        if r.status == "Collected":
            badge_type = "completed"
            title = f"Order #{r.id:04d} Completed"
            desc = f"{r.medicine.name} · {r.quantity} unit(s) · ₹{total} collected by {r.customer.username}"
            icon = "fa-circle-check"
            color_class = "success"
        elif r.status == "Accepted":
            badge_type = "ready"
            title = f"Order #{r.id:04d} Ready for Pickup"
            desc = f"{r.medicine.name} · {r.quantity} unit(s) reserved for {r.customer.username}"
            icon = "fa-clock"
            color_class = "primary"
        elif r.status == "Rejected":
            badge_type = "cancelled"
            title = f"Order #{r.id:04d} Rejected"
            desc = f"Reservation for {r.medicine.name} declined"
            icon = "fa-circle-xmark"
            color_class = "danger"
        else:
            badge_type = "pending"
            title = f"New Order #{r.id:04d} Received"
            desc = f"{r.medicine.name} · {r.quantity} unit(s) from {r.customer.username}"
            icon = "fa-clipboard-list"
            color_class = "warning"

        timeline_items.append({
            "title": title,
            "description": desc,
            "timestamp": r.requested_at,
            "badge_type": badge_type,
            "icon": icon,
            "color_class": color_class,
        })

    for item in inventory_updates:
        timeline_items.append({
            "title": f"Stock Updated: {item.medicine.name}",
            "description": f"Current inventory: {item.quantity} units · ₹{item.price} (Batch: {item.batch_number or 'N/A'})",
            "timestamp": item.updated_at,
            "badge_type": "inventory",
            "icon": "fa-boxes-stacked",
            "color_class": "info",
        })

    timeline_items.sort(key=lambda x: x["timestamp"], reverse=True)

    grouped_timeline = {"Today": [], "Yesterday": [], "Earlier": []}
    for item in timeline_items:
        item_date = item["timestamp"].date()
        if item_date == today:
            grouped_timeline["Today"].append(item)
        elif item_date == yesterday:
            grouped_timeline["Yesterday"].append(item)
        else:
            grouped_timeline["Earlier"].append(item)

    return render(
        request,
        "reservation_history.html",
        {
            "pharmacy": pharmacy,
            "grouped_timeline": grouped_timeline,
            "total_activities": len(timeline_items),
        }
    )


@pharmacy_required
def accept_reservation(request, id):
    reservation = get_object_or_404(
        Reservation,
        id=id
    )

    # Horizontal Access Control: Only store owner or superuser can accept
    if not request.user.is_superuser:
        user_pharmacy = getattr(request.user.userprofile, "pharmacy", None)
        if not user_pharmacy or reservation.pharmacy != user_pharmacy:
            messages.error(request, "Unauthorized. You cannot modify reservations for other pharmacies.")
            return redirect("reservations")

    reservation.status = "Accepted"
    reservation.save()

    # Send Bidirectional Notifications for Both Customer & Pharmacy Owner
    notify_reservation_update(reservation, "ACCEPTED", request.user)

    # Safely deduct inventory if exists
    inv = Inventory.objects.filter(
        pharmacy=reservation.pharmacy,
        medicine=reservation.medicine
    ).first()

    if inv:
        inv.quantity -= reservation.quantity
        if inv.quantity < 0:
            inv.quantity = 0
        inv.save()

    messages.success(
        request,
        f"Order #MF-{reservation.id:04d} accepted and marked Ready for customer pickup."
    )
    return redirect("reservations")


@pharmacy_required
def complete_reservation(request, id):
    reservation = get_object_or_404(Reservation, id=id)

    # Horizontal Access Control: Only store owner or superuser can complete
    if not request.user.is_superuser:
        user_pharmacy = getattr(request.user.userprofile, "pharmacy", None)
        if not user_pharmacy or reservation.pharmacy != user_pharmacy:
            messages.error(request, "Unauthorized. You cannot modify reservations for other pharmacies.")
            return redirect("reservations")

    reservation.status = "Collected"
    reservation.save()
    notify_reservation_update(reservation, "COLLECTED", request.user)
    messages.success(request, f"Order #MF-{reservation.id:04d} for {reservation.medicine.name} marked as Collected / Completed.")
    return redirect("reservations")


@pharmacy_required
def reject_reservation(request, id):
    reservation = get_object_or_404(
        Reservation,
        id=id
    )

    # Horizontal Access Control: Only store owner or superuser can reject
    if not request.user.is_superuser:
        user_pharmacy = getattr(request.user.userprofile, "pharmacy", None)
        if not user_pharmacy or reservation.pharmacy != user_pharmacy:
            messages.error(request, "Unauthorized. You cannot modify reservations for other pharmacies.")
            return redirect("reservations")

    reservation.status = "Rejected"
    reservation.save()

    notify_reservation_update(reservation, "REJECTED", request.user)

    messages.success(
        request,
        f"Order #MF-{reservation.id:04d} rejected."
    )
    return redirect("reservations")



@login_required
def my_reservations(request):
    reservations = Reservation.objects.filter(
        customer=request.user
    ).order_by("-requested_at")

    return render(
        request,
        "my_reservations.html",
        {
            "reservations": reservations
        }
    )


@login_required
def search_history(request):
    searches = SearchHistory.objects.filter(
        user=request.user
    ).order_by("-searched_at")[:50]

    audit_logs = AgentAuditLog.objects.filter(
        user=request.user
    ).order_by("-created_at")[:50]

    activities = []

    for s in searches:
        activities.append({
            "type": "search",
            "title": "Medicine searched",
            "description": f'Searched for "{s.medicine}"',
            "timestamp": s.searched_at,
            "badge_class": "bg-primary-subtle text-primary border border-primary-subtle",
            "icon": "fa-magnifying-glass",
            "raw_details": {"query": s.medicine, "user": request.user.username}
        })

    for log in audit_logs:
        etype = log.event_type
        payload = log.payload or {}
        if etype in ("CANDIDATES_EVALUATED", "RECOMMENDATION_GENERATED", "AGENT_SEARCH"):
            best = payload.get("best_match", {})
            if best:
                med_name = best.get("medicine_name", "Medicine")
                pharm_name = best.get("pharmacy_name", "Nearby Pharmacy")
                price = best.get("price", "N/A")
                activities.append({
                    "type": "recommendation",
                    "title": "Best option found",
                    "description": f'{med_name} at {pharm_name} · ₹{price}',
                    "timestamp": log.created_at,
                    "badge_class": "bg-info-subtle text-info-emphasis border border-info-subtle",
                    "icon": "fa-circle-check",
                    "raw_details": payload
                })
        elif etype == "PURCHASE_APPROVED":
            med_name = payload.get("medicine_name", "Medicine")
            qty = payload.get("quantity", 1)
            total = payload.get("total_amount", "N/A")
            activities.append({
                "type": "approval",
                "title": "Purchase approved",
                "description": f'{med_name} ({qty} unit) · ₹{total}',
                "timestamp": log.created_at,
                "badge_class": "bg-warning-subtle text-warning-emphasis border border-warning-subtle",
                "icon": "fa-user-check",
                "raw_details": payload
            })
        elif etype in ("PAYMENT_VERIFIED", "PAYMENT_SUCCESS", "ORDER_CREATED"):
            total = payload.get("amount", payload.get("total_amount", "N/A"))
            ref = payload.get("order_reference", payload.get("razorpay_payment_id", ""))
            activities.append({
                "type": "payment",
                "title": "Payment confirmed",
                "description": f'Razorpay verified · ₹{total} {f"(Ref: {ref})" if ref else ""}',
                "timestamp": log.created_at,
                "badge_class": "bg-success-subtle text-success border border-success-subtle",
                "icon": "fa-receipt",
                "raw_details": payload
            })
        elif etype == "PAYMENT_FAILED":
            reason = payload.get("reason", "Payment incomplete or cancelled")
            activities.append({
                "type": "failure",
                "title": "Payment unsuccessful",
                "description": f'{reason}',
                "timestamp": log.created_at,
                "badge_class": "bg-danger-subtle text-danger border border-danger-subtle",
                "icon": "fa-circle-xmark",
                "raw_details": payload
            })

    activities.sort(key=lambda x: x["timestamp"], reverse=True)

    return render(
        request,
        "search_history.html",
        {
            "searches": searches,
            "activities": activities
        }
    )


@pharmacy_required
def pharmacy_dashboard(request):
    profile = getattr(request.user, "userprofile", None) if hasattr(request.user, "userprofile") else None
    verification_status = profile.verification_status if profile else "Approved"
    claimed_pharmacy = profile.claimed_pharmacy if profile else None
    pharmacy = profile.pharmacy if (profile and profile.pharmacy) else claimed_pharmacy

    active_claim = None
    if request.user.is_authenticated:
        active_claim = PharmacyClaim.objects.filter(user=request.user).order_by("-created_at").first()

    if not pharmacy and not claimed_pharmacy:
        email_match = Pharmacy.objects.filter(email__iexact=request.user.email).first()
        if email_match:
            pharmacy = email_match
            if hasattr(request.user, "userprofile"):
                request.user.userprofile.pharmacy = email_match
                request.user.userprofile.verification_status = "Approved"
                request.user.userprofile.save(update_fields=["pharmacy", "verification_status"])

    current_hour = timezone.localtime().hour
    if current_hour < 12:
        greeting = "Good morning"
    elif current_hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    inventory_qs = Inventory.objects.filter(pharmacy=pharmacy).select_related("medicine")
    reservations_qs = Reservation.objects.filter(pharmacy=pharmacy).select_related("medicine", "customer").order_by("-requested_at")

    today_date = timezone.now().date()
    today_orders_qs = reservations_qs.filter(requested_at__date=today_date)
    today_orders_count = today_orders_qs.count()
    pending_orders_count = reservations_qs.filter(status="Pending").count()
    total_medicines_count = inventory_qs.count()
    
    in_stock_count = inventory_qs.filter(quantity__gt=10).count()
    low_stock_count = inventory_qs.filter(quantity__gt=0, quantity__lte=10).count()
    out_of_stock_count = inventory_qs.filter(quantity=0).count()
    
    inventory_health_pct = 100
    if total_medicines_count > 0:
        inventory_health_pct = int((in_stock_count / total_medicines_count) * 100)

    low_stock_items = inventory_qs.filter(quantity__lte=10).order_by("quantity")[:6]

    recent_orders = []
    for r in reservations_qs[:5]:
        inv = inventory_qs.filter(medicine=r.medicine).first()
        price = inv.price if inv and inv.price else Decimal("22.00")
        r.unit_price = price
        r.calculated_total = price * r.quantity
        r.order_code = f"MF-{r.id:04d}"
        recent_orders.append(r)

    # Real Activity Timeline items
    recent_activities = []
    for r in reservations_qs[:5]:
        inv = inventory_qs.filter(medicine=r.medicine).first()
        p = inv.price if inv and inv.price else Decimal("22.00")
        tot = p * r.quantity
        if r.status == "Collected":
            recent_activities.append({
                "time": r.requested_at.strftime("%H:%M"),
                "title": f"Order #MF-{r.id:04d} completed",
                "desc": f"{r.medicine.name} · ₹{tot:.2f}",
                "badge": "Completed",
                "badge_class": "text-success",
                "icon": "fa-circle-check",
                "timestamp": r.requested_at,
            })
        elif r.status == "Accepted":
            recent_activities.append({
                "time": r.requested_at.strftime("%H:%M"),
                "title": f"Order #MF-{r.id:04d} ready",
                "desc": f"{r.medicine.name} reserved for {r.customer.username}",
                "badge": "Ready",
                "badge_class": "text-primary",
                "icon": "fa-clock",
                "timestamp": r.requested_at,
            })
        else:
            recent_activities.append({
                "time": r.requested_at.strftime("%H:%M"),
                "title": f"Order #MF-{r.id:04d} received",
                "desc": f"{r.medicine.name} ({r.quantity} units)",
                "badge": "Received",
                "badge_class": "text-warning-emphasis",
                "icon": "fa-clipboard-list",
                "timestamp": r.requested_at,
            })

    for itm in inventory_qs.order_by("-updated_at")[:3]:
        recent_activities.append({
            "time": itm.updated_at.strftime("%H:%M"),
            "title": f"{itm.medicine.name} stock updated",
            "desc": f"{itm.quantity} units available · ₹{itm.price}",
            "badge": "Stock",
            "badge_class": "text-info-emphasis",
            "icon": "fa-boxes-stacked",
            "timestamp": itm.updated_at,
        })

    recent_activities.sort(key=lambda x: x["timestamp"], reverse=True)

    context = {
        "pharmacy": pharmacy,
        "greeting": greeting,
        "today_orders_count": today_orders_count,
        "pending_orders_count": pending_orders_count,
        "total_medicines_count": total_medicines_count,
        "low_stock_count": low_stock_count,
        "out_of_stock_count": out_of_stock_count,
        "in_stock_count": in_stock_count,
        "inventory_health_pct": inventory_health_pct,
        "low_stock_items": low_stock_items,
        "recent_orders": recent_orders,
        "recent_activities": recent_activities[:6],
        "verification_status": verification_status,
        "is_verified": (verification_status == "Approved"),
        "claimed_pharmacy": claimed_pharmacy,
        "active_claim": active_claim,
    }
    return render(
        request,
        "pharmacy_dashboard.html",
        context,
    )
# ==========================================================
# Notification API
# ==========================================================

def notifications_api(request):
    if not request.user.is_authenticated:
        return JsonResponse([], safe=False)

    notifications = Notification.objects.filter(
        recipient=request.user
    ).order_by("-created_at")[:20]

    data = []

    now = timezone.now()

    for notification in notifications:

        diff = now - notification.created_at

        if diff.total_seconds() < 60:

            time = "Just now"

        elif diff.total_seconds() < 3600:

            mins = int(diff.total_seconds() / 60)
            time = f"{mins} min ago"

        elif diff.total_seconds() < 86400:

            hrs = int(diff.total_seconds() / 3600)
            time = f"{hrs} hour ago"

        elif diff.days == 1:

            time = "Yesterday"

        else:

            time = f"{diff.days} days ago"

        data.append({
            "id": notification.id,
            "title": notification.title,
            "message": notification.message,
            "type": notification.notification_type,
            "is_read": notification.is_read,
            "time": time
        })

    return JsonResponse(data, safe=False)


# ==========================================================
# OTP-based Password Reset Views
# ==========================================================
from .otp_service import send_password_reset_otp, verify_and_consume_otp, mask_target_contact

@rate_limit(max_requests=5, window_seconds=60, key_prefix="pwd_reset_req")
def forgot_password_request(request):
    """
    Step 1: User enters their email, username, or registered phone number.
    Generates and dispatches a 6-digit OTP code to their email/phone.
    """
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        identifier = request.POST.get("identifier", "").strip()
        if not identifier:
            messages.error(request, "Please enter your registered email address, username, or phone number.")
            return render(request, "password_reset.html")

        # Find matching user by email, username, or profile phone
        user = None
        if "@" in identifier:
            user = User.objects.filter(email__iexact=identifier).first()
        else:
            user = User.objects.filter(username__iexact=identifier).first()
            if not user:
                pharmacy = Pharmacy.objects.filter(phone=identifier).first()
                if pharmacy and hasattr(pharmacy, "userprofile"):
                    user = pharmacy.userprofile.user

        if user:
            success, msg, otp_obj = send_password_reset_otp(user, target_input=identifier)
            request.session["pwd_reset_user_id"] = user.id
            request.session["pwd_reset_target"] = user.email or identifier
            request.session["pwd_reset_masked"] = mask_target_contact(user.email or identifier)
            messages.success(request, f"A 6-digit OTP has been sent to {request.session['pwd_reset_masked']}.")
            return redirect("password_reset_verify")
        else:
            messages.info(request, "If an account matches that contact, a 6-digit verification code has been sent.")
            return redirect("password_reset_verify")

    return render(request, "password_reset.html")


@rate_limit(max_requests=8, window_seconds=60, key_prefix="pwd_reset_verify")
def forgot_password_verify(request):
    """
    Step 2: User enters the 6-digit OTP received via email/phone along with their new password.
    """
    user_id = request.session.get("pwd_reset_user_id")
    masked_target = request.session.get("pwd_reset_masked", "your registered contact")

    if not user_id:
        messages.warning(request, "Please enter your email or username first to receive an OTP.")
        return redirect("password_reset")

    user = get_object_or_404(User, id=user_id)

    if request.method == "POST":
        otp_code = request.POST.get("otp_code", "").strip()
        new_password1 = request.POST.get("new_password1", "").strip()
        new_password2 = request.POST.get("new_password2", "").strip()

        if not otp_code or len(otp_code) != 6:
            messages.error(request, "Please enter the complete 6-digit OTP code.")
            return render(request, "password_reset_verify.html", {"masked_target": masked_target})

        if not new_password1 or not new_password2:
            messages.error(request, "Please provide and confirm your new password.")
            return render(request, "password_reset_verify.html", {"masked_target": masked_target})

        if new_password1 != new_password2:
            messages.error(request, "The passwords do not match. Please re-enter them carefully.")
            return render(request, "password_reset_verify.html", {"masked_target": masked_target})

        if len(new_password1) < 6:
            messages.error(request, "Password must be at least 6 characters long.")
            return render(request, "password_reset_verify.html", {"masked_target": masked_target})

        # Verify OTP
        is_valid, error_msg = verify_and_consume_otp(user, otp_code)
        if not is_valid:
            messages.error(request, error_msg)
            return render(request, "password_reset_verify.html", {"masked_target": masked_target})

        # Update Password
        user.set_password(new_password1)
        user.save()

        # Clean up session
        request.session.pop("pwd_reset_user_id", None)
        request.session.pop("pwd_reset_target", None)
        request.session.pop("pwd_reset_masked", None)

        messages.success(request, "Password reset successfully! You can now log in with your new password.")
        return redirect("login")

    return render(request, "password_reset_verify.html", {
        "masked_target": masked_target
    })


@rate_limit(max_requests=5, window_seconds=60, key_prefix="pwd_reset_resend", is_json=True)
def forgot_password_resend_api(request):

    """
    API endpoint to resend a fresh 6-digit OTP code with rate-limiting.
    """
    if request.method != "POST":
        return JsonResponse({"success": False, "message": "POST method required."}, status=405)

    user_id = request.session.get("pwd_reset_user_id")
    target = request.session.get("pwd_reset_target")

    if not user_id:
        return JsonResponse({"success": False, "message": "No active reset session found."}, status=400)

    user = User.objects.filter(id=user_id).first()
    if not user:
        return JsonResponse({"success": False, "message": "User not found."}, status=404)

    last_otp = PasswordResetOTP.objects.filter(user=user).order_by("-created_at").first()
    if last_otp and (timezone.now() - last_otp.created_at).total_seconds() < 30:
        remaining = int(30 - (timezone.now() - last_otp.created_at).total_seconds())
        return JsonResponse({
            "success": False,
            "message": f"Please wait {remaining} seconds before requesting another OTP."
        }, status=429)

    success, msg, _ = send_password_reset_otp(user, target_input=target)
    return JsonResponse({
        "success": True,
        "message": f"A fresh 6-digit OTP code has been sent to {request.session.get('pwd_reset_masked')}."
    })


def privacy_policy(request):
    """
    Renders the comprehensive, transparent MediAI Privacy Policy.
    Covers: Information collected, account data, pharmacy data, location usage,
    search history, payment processing, cookies, third-party services, data retention,
    deletion requests, and contact info.
    """
    return render(request, "privacy.html")


def terms_of_service(request):
    """
    Renders the MediAI Terms of Service.
    """
    return render(request, "terms.html")


def thank_you_view(request):
    """
    Renders the dedicated reservation / order thank you confirmation page.
    """
    ref_code = request.GET.get("ref", "849204")
    pharmacy_id = request.GET.get("pharmacy_id")
    pharmacy = None
    if pharmacy_id and pharmacy_id.isdigit():
        pharmacy = Pharmacy.objects.filter(id=int(pharmacy_id)).first()

    context = {
        "ref_code": ref_code,
        "pharmacy_name": pharmacy.name if pharmacy else "Apollo Pharmacy Anna Nagar",
        "pharmacy_address": pharmacy.address if pharmacy else "14/2 2nd Avenue, Anna Nagar, Chennai, Tamil Nadu",
        "pharmacy_phone": pharmacy.phone if pharmacy else "+91 98765 43210",
        "pharmacy_lat": pharmacy.latitude if pharmacy and pharmacy.latitude else 13.0827,
        "pharmacy_lng": pharmacy.longitude if pharmacy and pharmacy.longitude else 80.2707,
    }
    return render(request, "thank_you.html", context)


def custom_404_view(request, exception=None):
    """
    Custom 404 handler returning rich search-enabled error template with HTTP 404 status.
    """
    return render(request, "404.html", status=404)


def custom_500_view(request):
    """
    Custom 500 handler returning user-friendly error template with HTTP 500 status.
    """
    return render(request, "500.html", status=500)


def custom_403_view(request, exception=None):
    """
    Custom 403 handler returning permission denied template with HTTP 403 status.
    """
    return render(request, "403.html", status=403)


def robots_txt(request):
    """
    Generates SEO-optimized robots.txt for search engine crawlers.
    """
    host = request.get_host()
    scheme = "https" if request.is_secure() else "http"
    content = f"""User-agent: *
Allow: /
Allow: /search/
Allow: /medicines/
Allow: /pharmacies/
Allow: /privacy/
Allow: /terms/

# Protect Private & Transactional Endpoints
Disallow: /admin/
Disallow: /api/payments/
Disallow: /api/notifications/
Disallow: /dashboard/
Disallow: /pharmacy-dashboard/
Disallow: /inventory/
Disallow: /reservations/
Disallow: /my-reservations/
Disallow: /profile/
Disallow: /password-reset/

Sitemap: {scheme}://{host}/sitemap.xml
"""
    return HttpResponse(content.strip(), content_type="text/plain")


def sitemap_xml(request):
    """
    Generates dynamic XML sitemap indexing all public pages, medicines, and pharmacies.
    """
    host = request.get_host()
    scheme = "https" if request.is_secure() else "http"
    base_url = f"{scheme}://{host}"

    today = timezone.now().strftime("%Y-%m-%d")
    urls = [
        {"loc": f"{base_url}/", "lastmod": today, "changefreq": "daily", "priority": "1.0"},
        {"loc": f"{base_url}/search/", "lastmod": today, "changefreq": "daily", "priority": "0.9"},
        {"loc": f"{base_url}/medicines/", "lastmod": today, "changefreq": "daily", "priority": "0.8"},
        {"loc": f"{base_url}/pharmacies/", "lastmod": today, "changefreq": "daily", "priority": "0.8"},
        {"loc": f"{base_url}/privacy/", "lastmod": today, "changefreq": "monthly", "priority": "0.5"},
        {"loc": f"{base_url}/terms/", "lastmod": today, "changefreq": "monthly", "priority": "0.5"},
    ]

    for med in Medicine.objects.all()[:500]:
        urls.append({
            "loc": f"{base_url}/medicine/{med.id}/",
            "lastmod": today,
            "changefreq": "weekly",
            "priority": "0.7",
        })

    for pharm in Pharmacy.objects.filter(is_active=True)[:200]:
        urls.append({
            "loc": f"{base_url}/pharmacy/{pharm.id}/",
            "lastmod": today,
            "changefreq": "daily",
            "priority": "0.7",
        })

    xml_lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml_lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for u in urls:
        xml_lines.append("  <url>")
        xml_lines.append(f"    <loc>{u['loc']}</loc>")
        xml_lines.append(f"    <lastmod>{u['lastmod']}</lastmod>")
        xml_lines.append(f"    <changefreq>{u['changefreq']}</changefreq>")
        xml_lines.append(f"    <priority>{u['priority']}</priority>")
        xml_lines.append("  </url>")
    xml_lines.append("</urlset>")

    return HttpResponse("\n".join(xml_lines), content_type="application/xml")
