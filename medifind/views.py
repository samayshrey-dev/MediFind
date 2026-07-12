from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.core.paginator import Paginator

from .models import Medicine, Pharmacy, Inventory
from .forms import MedicineForm, PharmacyForm, InventoryForm
from django.db.models import Q
from collections import Counter
from django.utils import timezone
from datetime import timedelta
import json

from django.contrib.auth.models import User
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import render, redirect
from .forms import RegisterForm
from django.http import HttpResponseForbidden

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
def home(request):
    return render(request, "home.html")

def search(request):

    query = request.GET.get("medicine", "")

    inventory = Inventory.objects.select_related(
        "medicine",
        "pharmacy"
    )

    if query:

        inventory = inventory.filter(

            Q(medicine__name__icontains=query) |

            Q(medicine__brand__icontains=query)

        )

    marker_data = []

    for item in inventory:

        marker_data.append({

            "medicine": item.medicine.name,

            "brand": item.medicine.brand,

            "pharmacy": item.pharmacy.name,

            "address": item.pharmacy.address,

            "city": item.pharmacy.city,

            "phone": item.pharmacy.phone,

            "price": float(item.price),

            "quantity": item.quantity,

            "latitude": float(item.pharmacy.latitude),

            "longitude": float(item.pharmacy.longitude),

        })

    return render(

        request,

        "search.html",

        {

            "inventory": inventory,

            "query": query,

            "marker_data": json.dumps(marker_data)

        }

    )
def medicine_detail(request):
    return render(request, "medicine_detail.html")

def pharmacy_detail(request):
    return render(request, "pharmacy_detail.html")

@pharmacy_required
def dashboard(request):
    medicine_count = Medicine.objects.count()
    pharmacy_count = Pharmacy.objects.count()
    inventory_count = Inventory.objects.count()
    active_pharmacies = Pharmacy.objects.filter(
        is_active=True
    ).count()

    medicines = Medicine.objects.all()

    inventory = Inventory.objects.select_related(
        "medicine",
        "pharmacy"
    )

    category_counter = Counter()

    for medicine in medicines:
        category_counter[medicine.category] += 1

    category_labels = list(category_counter.keys())
    category_values = list(category_counter.values())

    stock_labels = []
    stock_values = []

    for item in inventory:
        stock_labels.append(item.medicine.name)
        stock_values.append(item.quantity)

    low_stock = inventory.filter(quantity__lte=20)

    expiring = inventory.filter(
        expiry_date__lte=timezone.now().date() + timedelta(days=90)
    )

    recent_inventory = inventory.order_by("-created_at")[:5]

    top_pharmacy = (
        Pharmacy.objects
        .order_by("name")
        .first()
    )

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
        context,
    )

def medicines(request):

    query = request.GET.get("q")

    medicines = Medicine.objects.all().order_by("name")

    if query:
        medicines = medicines.filter(name__icontains=query)

    paginator = Paginator(medicines, 8)

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

                "Medicine updated."

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


def delete_medicine(request, pk):

    medicine = get_object_or_404(

        Medicine,

        pk=pk

    )

    medicine.delete()

    messages.success(

        request,

        "Medicine deleted."

    )

    return redirect("medicines")

def pharmacies(request):

    pharmacies = Pharmacy.objects.all().order_by("name")

    return render(
        request,
        "pharmacies.html",
        {
            "pharmacies": pharmacies
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


def edit_pharmacy(request, pk):

    pharmacy = get_object_or_404(
        Pharmacy,
        pk=pk
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


def delete_pharmacy(request, pk):

    pharmacy = get_object_or_404(
        Pharmacy,
        pk=pk
    )

    pharmacy.delete()

    messages.success(
        request,
        "Pharmacy deleted successfully."
    )

    return redirect("pharmacies")

def inventory(request):

    query = request.GET.get("q")

    inventory = Inventory.objects.select_related(
        "medicine",
        "pharmacy"
    ).order_by("medicine__name")

    if query:

        inventory = inventory.filter(
            medicine__name__icontains=query
        )

    paginator = Paginator(inventory, 10)

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

    if request.method == "POST":

        form = InventoryForm(request.POST)

        if form.is_valid():

            form.save()

            messages.success(
                request,
                "Inventory added successfully."
            )

            return redirect("inventory")

    else:

        form = InventoryForm()

    return render(
        request,
        "add_inventory.html",
        {
            "form": form
        }
    )


def edit_inventory(request, pk):

    item = get_object_or_404(
        Inventory,
        pk=pk
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
                "Inventory updated."
            )

            return redirect("inventory")

    else:

        form = InventoryForm(instance=item)

    return render(
        request,
        "add_inventory.html",
        {
            "form": form
        }
    )


def delete_inventory(request, pk):

    item = get_object_or_404(
        Inventory,
        pk=pk
    )

    item.delete()

    messages.success(
        request,
        "Inventory deleted."
    )

    return redirect("inventory")

def register(request):

    if request.method == "POST":

        form = RegisterForm(request.POST)

        if form.is_valid():

            user = User.objects.create_user(

                username=form.cleaned_data["username"],

                password=form.cleaned_data["password"],

                first_name=form.cleaned_data["first_name"],

                email=form.cleaned_data["email"]

            )

            user.userprofile.role = form.cleaned_data["role"]

            user.userprofile.save()

            login(request, user)

            return redirect("home")

    else:

        form = RegisterForm()

    return render(

        request,

        "register.html",

        {

            "form": form

        }

    )
from django.contrib.auth.decorators import login_required

@login_required
def dashboard_redirect(request):

    if request.user.is_superuser:
        return redirect("dashboard")

    if request.user.userprofile.role == "Pharmacy":
        return redirect("dashboard")

    return redirect("home")