from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.conf import settings

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Q
from collections import Counter
from django.utils import timezone
from datetime import timedelta
from datetime import datetime
from decimal import Decimal
import json


from django.views.decorators.csrf import csrf_exempt
from .ai_search import parse_query_with_ai, haversine_distance, SYMPTOM_MAP
from .fuzzy_search import MedicineMatcher
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
            profile.role = "Pharmacy"

        if not profile.pharmacy:
            profile.pharmacy = (
                Pharmacy.objects.filter(email__iexact=request.user.email).first()
                or Pharmacy.objects.filter(owner_name__icontains=request.user.username).first()
                or Pharmacy.objects.first()
            )
            profile.save()
        elif profile.role != "Pharmacy":
            profile.save()

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
            user_pharmacy = getattr(request.user.userprofile, "pharmacy", None)
            if not user_pharmacy:
                user_pharmacy = Pharmacy.objects.filter(email__iexact=request.user.email).first()
                if not user_pharmacy:
                    user_pharmacy = Pharmacy.objects.filter(owner_name__icontains=request.user.username).first()
                if not user_pharmacy:
                    user_pharmacy = Pharmacy.objects.first()
                if user_pharmacy:
                    request.user.userprofile.pharmacy = user_pharmacy
                    request.user.userprofile.save(update_fields=["pharmacy"])
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

    intent = IntentParser.parse_with_ai(query)
    return JsonResponse(intent)


@csrf_exempt
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
# Legacy AI Query Interpretation API (Preserved for compatibility)
# ==========================================================

@csrf_exempt
def ai_search_api(request):
    """
    POST /api/ai/search/
    Parses natural language query into structured search parameters.
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

    result = parse_query_with_ai(query)
    return JsonResponse(result)



# ==========================================================
# Search (AI-Powered Natural-Language Medicine Search)
# ==========================================================

def search(request):

    query = request.GET.get("medicine", "").strip()
    category = request.GET.get("category", "").strip()
    sort = request.GET.get("sort", "").strip()
    radius_param = request.GET.get("radius", "").strip()
    user_lat_param = request.GET.get("lat", "").strip()
    user_lng_param = request.GET.get("lng", "").strip()
    ai_interpreted = request.GET.get("ai_interpreted", "").strip()

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

        SearchHistory.objects.create(
            user=request.user,
            medicine=query
        )

    # Base Query
    inventory = Inventory.objects.select_related(
        "medicine",
        "pharmacy"
    )

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
            if term:
                q_objects |= Q(medicine__name__icontains=term)
                q_objects |= Q(medicine__brand__icontains=term)
                q_objects |= Q(medicine__description__icontains=term)
                q_objects |= Q(medicine__uses__icontains=term)

        if ai_result and ai_result.get("symptom_category"):
            q_objects |= Q(medicine__category__iexact=ai_result["symptom_category"])

        inventory = inventory.filter(q_objects)

    # Filter by category if manually specified
    if category and category != "All":
        inventory = inventory.filter(
            medicine__category=category
        )

    # Convert to list for distance, open status, and sorting
    inventory_items = list(inventory.distinct())

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

    # Filter by radius if radius_km is specified and user coordinates are available
    if radius_km is not None and user_lat is not None and user_lng is not None:
        inventory_items = [item for item in inventory_items if getattr(item, 'distance_km', 0) <= radius_km]

    # Sort Results
    if sort == "cheapest":
        inventory_items.sort(key=lambda x: x.price)
    elif user_lat is not None and user_lng is not None:
        inventory_items.sort(key=lambda x: getattr(x, 'distance_km', 9999))

    # Marker Data
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
    best_match_item = inventory_items[0] if inventory_items else None
    other_items = inventory_items[1:] if len(inventory_items) > 1 else []

    explanation = "Lowest verified price within your selected radius with live stock."
    if sort == "nearest" and best_match_item and getattr(best_match_item, 'distance_km', None) is not None:
        explanation = f"Nearest verified pharmacy ({best_match_item.distance_km} km) with active stock."
    elif best_match_item:
        explanation = f"Lowest verified price (₹{best_match_item.price}) among nearby pharmacies."

    return render(
        request,
        "search.html",
        {
            "inventory": inventory_items,
            "best_match_item": best_match_item,
            "other_items": other_items,
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
            "marker_data": json.dumps(marker_data)
        }
    )


def search_suggestions(request):
    """
    GET /search/suggestions/?q=dollo
    Fault-tolerant auto-suggestions returning exact & fuzzy matched medicines.
    """
    query = request.GET.get("q", "").strip()
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



@pharmacy_required
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
@pharmacy_required
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
def nearby_pharmacies_api(request):
    """
    GET /api/pharmacies/nearby/?lat=...&lng=...&radius=5&sort=nearest
    Calculates verified Haversine distance, open status, and real medicine count from DB.
    """
    lat_str = request.GET.get("lat", "").strip()
    lng_str = request.GET.get("lng", "").strip()
    radius_str = request.GET.get("radius", "5").strip()
    sort_by = request.GET.get("sort", "nearest").strip()
    query = request.GET.get("q", "").strip()

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
            "marker_data": json.dumps(marker_data)
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

    pharmacy = getattr(request.user.userprofile, "pharmacy", None) if hasattr(request.user, "userprofile") else None
    if not pharmacy:
        pharmacy = Pharmacy.objects.filter(email__iexact=request.user.email).first() or Pharmacy.objects.first()
        if hasattr(request.user, "userprofile") and pharmacy:
            request.user.userprofile.pharmacy = pharmacy
            request.user.userprofile.save(update_fields=["pharmacy"])

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
        }
    )


@pharmacy_required
def add_inventory(request):
    user_pharmacy = getattr(request.user.userprofile, "pharmacy", None) if hasattr(request.user, "userprofile") else None
    if not user_pharmacy:
        user_pharmacy = Pharmacy.objects.filter(email__iexact=request.user.email).first() or Pharmacy.objects.first()
        if hasattr(request.user, "userprofile") and user_pharmacy:
            request.user.userprofile.pharmacy = user_pharmacy
            request.user.userprofile.save(update_fields=["pharmacy"])

    if request.method == "POST":
        form = InventoryForm(request.POST)
        if form.is_valid():
            medicine = form.cleaned_data.get("medicine")
            quantity = form.cleaned_data.get("quantity", 0)
            price = form.cleaned_data.get("price")
            batch_number = form.cleaned_data.get("batch_number", "")
            expiry_date = form.cleaned_data.get("expiry_date")
            minimum_stock = form.cleaned_data.get("minimum_stock", 10)

            # Smart duplicate check: update existing item instead of crashing
            existing_item = Inventory.objects.filter(pharmacy=user_pharmacy, medicine=medicine).first()
            if existing_item:
                existing_item.quantity += quantity
                if price is not None:
                    existing_item.price = price
                if batch_number:
                    existing_item.batch_number = batch_number
                if expiry_date:
                    existing_item.expiry_date = expiry_date
                if minimum_stock:
                    existing_item.minimum_stock = minimum_stock
                existing_item.save()
                messages.success(
                    request,
                    f"Stock updated for {medicine.name}. New total inventory: {existing_item.quantity} units (₹{existing_item.price})."
                )
            else:
                item = form.save(commit=False)
                item.pharmacy = user_pharmacy
                item.save()
                messages.success(
                    request,
                    f"Successfully added {medicine.name} ({item.quantity} units at ₹{item.price}) to your store inventory."
                )
            return redirect("inventory")
    else:
        initial_data = {}
        if user_pharmacy:
            initial_data["pharmacy"] = user_pharmacy.id
        form = InventoryForm(initial=initial_data)

    medicines = Medicine.objects.all().order_by("name")

    return render(
        request,
        "add_inventory.html",
        {
            "form": form,
            "user_pharmacy": user_pharmacy,
            "medicines": medicines,
        }
    )
# ==========================================================
# Inventory Management
# ==========================================================

@pharmacy_required
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


@pharmacy_required
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


# ==========================================================
# Authentication
# ==========================================================

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

            pharmacy_instance = None

            if role == "Pharmacy":

                option = form.cleaned_data.get("pharmacy_option")

                if option == "existing" and form.cleaned_data.get("existing_pharmacy"):

                    pharmacy_instance = form.cleaned_data.get("existing_pharmacy")

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

                        is_active=True,

                        is_open=True,

                    )

            profile, _ = UserProfile.objects.get_or_create(user=user)

            profile.role = role

            profile.pharmacy = pharmacy_instance

            profile.save()

            user.refresh_from_db()

            login(request, user)

            messages.success(
                request,
                f"Welcome to MediAI, {user.first_name or user.username}! Account created successfully."
            )

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
    except Exception as e:
        print("NOTIFICATION CREATION WARNING:", e)


# ==========================================================
# Reservation System
# ==========================================================

@login_required
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
        return render(request, "reserve_medicine.html", {
            "inventory": inventory,
            "medicine": inventory.medicine,
            "pharmacy": inventory.pharmacy,
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

    reservation.status = "Accepted"
    reservation.save()

    # Send Bidirectional Notifications for Both Customer & Pharmacy Owner
    notify_reservation_update(reservation, "ACCEPTED", request.user)

    inventory = get_object_or_404(
        Inventory,
        pharmacy=reservation.pharmacy,
        medicine=reservation.medicine
    )

    inventory.quantity -= reservation.quantity
    if inventory.quantity < 0:
        inventory.quantity = 0
    inventory.save()

    messages.success(
        request,
        f"Order #MF-{reservation.id:04d} accepted and marked Ready for customer pickup."
    )
    return redirect("reservations")


@pharmacy_required
def complete_reservation(request, id):
    reservation = get_object_or_404(Reservation, id=id)
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
    pharmacy = getattr(request.user.userprofile, "pharmacy", None) if hasattr(request.user, "userprofile") else None
    if not pharmacy:
        pharmacy = Pharmacy.objects.filter(email__iexact=request.user.email).first() or Pharmacy.objects.first()
        if hasattr(request.user, "userprofile") and pharmacy:
            request.user.userprofile.pharmacy = pharmacy
            request.user.userprofile.save(update_fields=["pharmacy"])

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

def forgot_password_request(request):
    """
    Step 1: User enters their email, username, or registered phone number.
    Generates and dispatches a 6-digit OTP code to their Gmail/phone.
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


def forgot_password_verify(request):
    """
    Step 2: User enters the 6-digit OTP received via Gmail/phone along with their new password.
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