from django.contrib import admin
from .models import Medicine, Pharmacy, Inventory

@admin.register(Medicine)
class MedicineAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "name",
        "brand",
        "category",
        "dosage",
        "prescription_required",
    )

    search_fields = (
        "name",
        "brand",
    )


@admin.register(Pharmacy)
class PharmacyAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "name",
        "city",
        "phone",
        "is_active",
    )

    search_fields = (
        "name",
        "city",
    )

    list_filter = (
        "city",
        "is_active",
    )
@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):

    list_display = (
        "medicine",
        "pharmacy",
        "quantity",
        "price",
        "expiry_date",
    )

    search_fields = (
        "medicine__name",
        "pharmacy__name",
    )

    list_filter = (
        "pharmacy",
    )