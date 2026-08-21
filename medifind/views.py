from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Q
from collections import Counter
from django.utils import timezone
from datetime import timedelta
from datetime import datetime
import json


from django.views.decorators.csrf import csrf_exempt
from .ai_search import parse_query_with_ai, haversine_distance, SYMPTOM_MAP

from .models import (
    Medicine,
    Pharmacy,
    Inventory,
    Reservation,
    SearchHistory,
    Notification,
    UserProfile,
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
            return redirect("login")

        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)

        if request.user.userprofile.role == "Pharmacy":
            return view_func(request, *args, **kwargs)

        return render(
            request,
            "403.html",
            status=403
        )

    return wrapper


# ==========================================================
# Home
# ==========================================================

def home(request):

    medicines = Medicine.objects.all()[:8]

    pharmacies = Pharmacy.objects.filter(is_active=True)[:4]

    medicine_count = Medicine.objects.count()

    pharmacy_count = Pharmacy.objects.count()

    reservation_count = Reservation.objects.count()

    user_count = User.objects.count()

    context = {

        "popular_medicines": medicines,

        "pharmacies": pharmacies,

        "medicine_count": medicine_count,

        "pharmacy_count": pharmacy_count,

        "reservation_count": reservation_count,

        "user_count": user_count,

    }

    return render(

        request,

        "home.html",

        context

    )


# ==========================================================
# AI Natural-Language Query Interpretation API
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

    # Filtering with AI / Natural-Language Search Terms
    if query:
        search_terms = [query]
        if ai_result:
            if ai_result.get("medicine_name"):
                search_terms.append(ai_result["medicine_name"])
            if ai_result.get("generic_name"):
                search_terms.append(ai_result["generic_name"])
            if ai_result.get("search_term"):
                search_terms.append(ai_result["search_term"])

        q_objects = Q()
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

    return render(
        request,
        "search.html",
        {
            "inventory": inventory_items,
            "query": query,
            "category": category,
            "sort": sort,
            "radius": radius_param,
            "ai_result": ai_result,
            "ai_interpreted": ai_interpreted,
            "warning_msg": warning_msg,
            "marker_data": json.dumps(marker_data)
        }
    )
def search_suggestions(request):

    query = request.GET.get("q", "").strip()

    suggestions = []

    if query:

        medicines = (
            Medicine.objects.filter(
                Q(name__icontains=query) |
                Q(brand__icontains=query)
            )
            .order_by("name")
            .distinct()[:8]
        )

        for medicine in medicines:

            suggestions.append({

                "id": medicine.id,

                "name": medicine.name,

                "brand": medicine.brand,

                "category": medicine.category,

            })

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

    if request.user.userprofile.role != "Pharmacy":

        messages.error(
            request,
            "Access denied."
        )

        return redirect("home")

    pharmacy = request.user.userprofile.pharmacy

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

    query = request.GET.get("q")

    medicines = Medicine.objects.all().order_by("name")

    if query:
        medicines = medicines.filter(
            name__icontains=query
        )

    paginator = Paginator(
        medicines,
        8
    )

    page = request.GET.get("page")

    medicines = paginator.get_page(page)

    return render(
        request,
        "medicines.html",
        {
            "medicines": medicines,
            "query": query
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
# Pharmacy Management
# ==========================================================

def pharmacies(request):

    pharmacies = Pharmacy.objects.all().order_by("name")

    active_count = pharmacies.filter(is_active=True).count()

    open_count = pharmacies.filter(is_open=True).count()

    return render(

        request,

        "pharmacies.html",

        {

            "pharmacies": pharmacies,

            "active_count": active_count,

            "open_count": open_count,

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

    query = request.GET.get("q")

    if request.user.is_superuser:

        inventory = Inventory.objects.select_related(
            "medicine",
            "pharmacy"
        ).order_by(
            "medicine__name"
        )

    else:

        inventory = Inventory.objects.select_related(
            "medicine",
            "pharmacy"
        ).filter(
            pharmacy=request.user.userprofile.pharmacy
        ).order_by(
            "medicine__name"
        )

    if query:

        inventory = inventory.filter(
            medicine__name__icontains=query
        )

    paginator = Paginator(
        inventory,
        10
    )

    page = request.GET.get("page")

    inventory = paginator.get_page(page)

    return render(
        request,
        "inventory.html",
        {
            "inventory": inventory,
            "query": query
        }
    )


@pharmacy_required
def add_inventory(request):

    user_pharmacy = getattr(request.user.userprofile, "pharmacy", None)

    if request.method == "POST":

        form = InventoryForm(
            request.POST
        )

        if form.is_valid():

            item = form.save(commit=False)

            if not item.pharmacy_id and user_pharmacy:

                item.pharmacy = user_pharmacy

            item.save()

            messages.success(
                request,
                "Inventory added successfully."
            )

            return redirect("inventory")

    else:

        initial_data = {}

        if user_pharmacy:

            initial_data["pharmacy"] = user_pharmacy.id

        form = InventoryForm(initial=initial_data)

    return render(
        request,
        "add_inventory.html",
        {
            "form": form
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

    if (
        not request.user.is_superuser
        and item.pharmacy != request.user.userprofile.pharmacy
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
                "Inventory updated successfully."
            )

            return redirect("inventory")

    else:

        form = InventoryForm(
            instance=item
        )

    return render(
        request,
        "add_inventory.html",
        {
            "form": form
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

                f"Welcome to MediFind, {user.first_name or user.username}! Account created successfully."

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

    if request.user.is_superuser:
        return redirect("dashboard")

    if request.user.userprofile.role == "Pharmacy":
        return redirect("pharmacy_dashboard")

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

    inventory = get_object_or_404(
        Inventory,
        id=inventory_id
    )

    if request.user.userprofile.role != "Customer":

        messages.error(
            request,
            "Only customers can reserve medicines."
        )

        return redirect("search")

    if inventory.quantity <= 0:

        messages.error(
            request,
            "Medicine is currently out of stock."
        )

        return redirect("search")

    existing = Reservation.objects.filter(
        customer=request.user,
        pharmacy=inventory.pharmacy,
        medicine=inventory.medicine,
        status="Pending"
    ).exists()

    if existing:

        messages.warning(
            request,
            "You already have a pending reservation."
        )

        return redirect("search")

    reservation = Reservation.objects.create(
        customer=request.user,
        pharmacy=inventory.pharmacy,
        medicine=inventory.medicine,
        quantity=1,
        status="Pending"
    )

    # Send Bidirectional Notifications for Both Customer & Pharmacy Owner
    notify_reservation_update(reservation, "NEW_RESERVATION", request.user)

    messages.success(
        request,
        "Reservation request sent successfully."
    )

    return redirect("search")
@login_required
def reservations(request):

    if request.user.is_superuser:

        reservations = Reservation.objects.filter(

            status="Pending"

        )

    else:

        reservations = Reservation.objects.filter(

            pharmacy=request.user.userprofile.pharmacy,

            status="Pending"

        )

    reservations = reservations.order_by("-requested_at")

    return render(

        request,

        "reservations.html",

        {

            "reservations": reservations

        }

    )
@login_required
def reservation_history(request):

    if request.user.is_superuser:

        history = Reservation.objects.exclude(

            status="Pending"

        )

    else:

        history = Reservation.objects.filter(

            pharmacy=request.user.userprofile.pharmacy

        ).exclude(

            status="Pending"

        )

    history = history.order_by("-requested_at")

    return render(

        request,

        "reservation_history.html",

        {

            "history": history

        }

    )
@login_required
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
        "Reservation accepted successfully."
    )

    return redirect("reservations")


@login_required
def reject_reservation(request, id):

    reservation = get_object_or_404(
        Reservation,
        id=id
    )

    reservation.status = "Rejected"
    reservation.save()

    # Send Bidirectional Notifications for Both Customer & Pharmacy Owner
    notify_reservation_update(reservation, "REJECTED", request.user)

    messages.success(
        request,
        "Reservation rejected."
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
    ).order_by("-searched_at")

    return render(
        request,
        "search_history.html",
        {
            "searches": searches
        }
    )

@pharmacy_required
def pharmacy_dashboard(request):

    pharmacy = request.user.userprofile.pharmacy

    inventory = Inventory.objects.filter(
        pharmacy=pharmacy
    ).select_related("medicine")

    reservations = Reservation.objects.filter(
        pharmacy=pharmacy
    ).order_by("-requested_at")[:10]

    low_stock = inventory.filter(
        quantity__lte=10
    )

    context = {

    "pharmacy": pharmacy,

    "inventory": inventory,

    "inventory_count": inventory.count(),

    "reservation_count": Reservation.objects.filter(
        pharmacy=pharmacy
    ).count(),

    "low_stock": low_stock,

    "reservations": reservations,

    "available_stock": inventory.filter(
        quantity__gt=0
    ).count(),

    "out_of_stock": inventory.filter(
        quantity=0
    ).count(),

    "expiring_stock": inventory.filter(
        expiry_date__lte=timezone.now().date() + timedelta(days=30)
    ).count(),

}
    return render(
        request,
        "pharmacy_dashboard.html",
        context,
    )
# ==========================================================
# Notification API
# ==========================================================

@login_required
def notifications_api(request):

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