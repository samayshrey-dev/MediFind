from django.contrib import admin
from django.utils import timezone
from .models import (
    Medicine,
    Pharmacy,
    Inventory,
    UserProfile,
    Reservation,
    Notification,
    PharmacyClaim,
)


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
        "verification_status",
        "is_active",
        "is_open"
    )

    search_fields = (
        "name",
        "city",
        "license_number",
    )

    list_filter = (
        "verification_status",
        "city",
        "is_active",
    )


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):

    list_display = (
        "medicine",
        "pharmacy",
        "package_size",
        "quantity",
        "price",
        "expiry_date",
    )

    search_fields = (
        "medicine__name",
        "pharmacy__name",
        "package_size",
    )

    list_filter = (
        "pharmacy",
        "package_size",
    )


@admin.register(PharmacyClaim)
class PharmacyClaimAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "pharmacy",
        "user",
        "drug_license_number",
        "status",
        "created_at",
        "reviewed_at"
    )
    list_filter = ("status", "created_at")
    search_fields = ("pharmacy__name", "user__username", "drug_license_number")
    actions = ["approve_claims", "reject_claims"]

    @admin.action(description="Approve selected pharmacy claims (grant inventory access)")
    def approve_claims(self, request, queryset):
        for claim in queryset:
            claim.status = "Approved"
            claim.reviewed_at = timezone.now()
            claim.reviewed_by = request.user
            claim.save()

            # Update UserProfile
            if hasattr(claim.user, "userprofile"):
                prof = claim.user.userprofile
                prof.verification_status = "Approved"
                prof.pharmacy = claim.pharmacy
                prof.save()

            # Activate Pharmacy
            claim.pharmacy.verification_status = "Approved"
            claim.pharmacy.is_active = True
            claim.pharmacy.save()

            # Send Notification
            Notification.objects.create(
                recipient=claim.user,
                title="Pharmacy Claim Approved",
                message=f"Congratulations! Your ownership claim for {claim.pharmacy.name} has been verified and approved. You now have full inventory access.",
                notification_type="System"
            )
        self.message_user(request, f"{queryset.count()} pharmacy claim(s) successfully approved.")

    @admin.action(description="Reject selected pharmacy claims")
    def reject_claims(self, request, queryset):
        for claim in queryset:
            claim.status = "Rejected"
            claim.reviewed_at = timezone.now()
            claim.reviewed_by = request.user
            claim.save()

            if hasattr(claim.user, "userprofile"):
                prof = claim.user.userprofile
                prof.verification_status = "Rejected"
                prof.save()

            Notification.objects.create(
                recipient=claim.user,
                title="Pharmacy Claim Update",
                message=f"Your ownership claim for {claim.pharmacy.name} could not be verified. Please contact support or upload valid Form 20/21 license documents.",
                notification_type="System"
            )
        self.message_user(request, f"{queryset.count()} pharmacy claim(s) marked as Rejected.")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "verification_status", "pharmacy", "claimed_pharmacy")
    list_filter = ("role", "verification_status")
    search_fields = ("user__username", "user__email", "pharmacy__name")


admin.site.register(Reservation)
admin.site.register(Notification)