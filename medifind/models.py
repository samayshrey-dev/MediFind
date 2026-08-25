from django.db import models
from django.contrib.auth.models import User


class Medicine(models.Model):

    CATEGORY_CHOICES = [
        ('Pain Relief', 'Pain Relief'),
        ('Fever & Cold', 'Fever & Cold'),
        ('Allergy', 'Allergy'),
        ('Digestive Health', 'Digestive Health'),
        ('Vitamins & Supplements', 'Vitamins & Supplements'),
        ('Diabetes Care', 'Diabetes Care'),
        ('Blood Pressure', 'Blood Pressure'),
        ('Skin Care', 'Skin Care'),
        ('First Aid', 'First Aid'),
        ('Respiratory', 'Respiratory'),
        ('Eye Care', 'Eye Care'),
        ('Oral Care', 'Oral Care'),
        ('Women\'s Health', 'Women\'s Health'),
        ('General Health', 'General Health'),
        ('Antibiotic', 'Antibiotic'),
        ('Heart', 'Heart'),
        ('Other', 'Other'),
    ]

    name = models.CharField(max_length=150)

    brand = models.CharField(max_length=100)

    category = models.CharField(
        max_length=50,
        choices=CATEGORY_CHOICES,
        default="General Health"
    )

    dosage = models.CharField(max_length=50)

    description = models.TextField()

    uses = models.TextField()

    side_effects = models.TextField()

    prescription_required = models.BooleanField(default=False)

    image = models.ImageField(
        upload_to="medicines/",
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Pharmacy(models.Model):

    name = models.CharField(max_length=200)

    owner_name = models.CharField(max_length=150)

    phone = models.CharField(max_length=15)

    email = models.EmailField(blank=True)

    address = models.TextField()

    city = models.CharField(max_length=100)

    state = models.CharField(max_length=100)

    pincode = models.CharField(max_length=10)

    latitude = models.DecimalField(
        max_digits=10,
        decimal_places=7
    )

    longitude = models.DecimalField(
        max_digits=10,
        decimal_places=7
    )

    opening_time = models.TimeField()

    closing_time = models.TimeField()

    image = models.ImageField(
        upload_to="pharmacies/",
        blank=True,
        null=True
    )

    is_active = models.BooleanField(default=True)
    is_open = models.BooleanField(
        default=True
    )
    verification_status = models.CharField(
        max_length=20,
        choices=[
            ("Approved", "Approved"),
            ("Pending", "Verification Pending"),
            ("Rejected", "Rejected"),
        ],
        default="Approved"
    )
    license_number = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Form 20/21 Drug License Number"
    )

    # Real-Time Pharmacy System API Integration
    api_endpoint_url = models.URLField(
        max_length=500,
        blank=True,
        null=True,
        help_text="Direct POS/ERP API endpoint URL for real-time inventory lookup"
    )
    api_auth_token = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="API Secret Key or Bearer Token for POS integration"
    )
    api_sync_enabled = models.BooleanField(
        default=False,
        help_text="Enable real-time inventory checks via Pharmacy API"
    )
    api_last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of the most recent real-time API inventory query"
    )
    api_sync_status = models.CharField(
        max_length=100,
        default="No API Configured",
        blank=True,
        help_text="Current health/connectivity status of pharmacy API"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class UserProfile(models.Model):

    ROLE_CHOICES = [
        ("Customer", "Customer"),
        ("Pharmacy", "Pharmacy"),
    ]

    VERIFICATION_CHOICES = [
        ("Approved", "Approved"),
        ("Pending", "Verification Pending"),
        ("Rejected", "Rejected"),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE
    )

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default="Customer"
    )
    pharmacy = models.ForeignKey(
        "Pharmacy",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="user_profiles"
    )
    claimed_pharmacy = models.ForeignKey(
        "Pharmacy",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="claimants",
        help_text="Pharmacy being claimed while verification is pending"
    )
    verification_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_CHOICES,
        default="Approved"
    )

    def __str__(self):
        return f"{self.user.username} - {self.role} ({self.verification_status})"


class PharmacyClaim(models.Model):
    """
    Tracks merchant ownership claims for pharmacies requiring admin review and verification.
    """
    STATUS_CHOICES = [
        ("Pending", "Verification Pending"),
        ("Approved", "Approved"),
        ("Rejected", "Rejected"),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="pharmacy_claims"
    )
    pharmacy = models.ForeignKey(
        Pharmacy,
        on_delete=models.CASCADE,
        related_name="ownership_claims"
    )
    drug_license_number = models.CharField(
        max_length=100,
        default="PENDING-DOCS",
        help_text="Form 20/21 Drug Retail License Number"
    )
    gstin = models.CharField(
        max_length=30,
        blank=True,
        null=True,
        help_text="GST Identification Number"
    )
    owner_proof = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        help_text="Owner contact proof or license name"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Pending"
    )
    admin_notes = models.TextField(
        blank=True,
        default=""
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_pharmacy_claims"
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Claim #{self.id} for {self.pharmacy.name} by {self.user.username} ({self.status})"

    
class Inventory(models.Model):

    medicine = models.ForeignKey(
        Medicine,
        on_delete=models.CASCADE
    )

    pharmacy = models.ForeignKey(
        Pharmacy,
        on_delete=models.CASCADE
    )

    quantity = models.PositiveIntegerField(default=0)

    price = models.DecimalField(
        max_digits=8,
        decimal_places=2
    )

    batch_number = models.CharField(
        max_length=50
    )

    expiry_date = models.DateField()

    PACKAGE_SIZE_CHOICES = [
        ("Strip of 10", "Strip of 10"),
        ("Strip of 15", "Strip of 15"),
        ("Strip of 30", "Strip of 30"),
        ("Bottle of 60", "Bottle of 60"),
        ("Bottle of 100", "Bottle of 100"),
        ("Bottle of 100 ml", "Bottle of 100 ml"),
        ("Bottle of 200 ml", "Bottle of 200 ml"),
        ("Tube of 20 g", "Tube of 20 g"),
        ("Tube of 30 g", "Tube of 30 g"),
        ("Sachet", "Sachet"),
        ("Box of 1", "Box of 1"),
        ("Vial / Ampoule", "Vial / Ampoule"),
        ("Unit", "Unit"),
    ]

    package_size = models.CharField(
        max_length=80,
        default="Strip of 15",
        blank=True,
        choices=PACKAGE_SIZE_CHOICES,
        help_text="Packaging SKU e.g. Strip of 15, Strip of 30, Bottle of 100"
    )

    sku_code = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        help_text="Unique SKU identifier e.g. DOLO650-S15"
    )

    minimum_stock = models.PositiveIntegerField(
        default=10
    )

    expected_restock = models.DateField(
        null=True,
        blank=True
    )

    last_updated = models.DateTimeField(
        auto_now=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        unique_together = ('pharmacy', 'medicine', 'package_size')
        verbose_name_plural = "Inventories"
        indexes = [
            models.Index(fields=['pharmacy', 'medicine']),
            models.Index(fields=['medicine', 'quantity']),
        ]

    def __str__(self):
        return f"{self.medicine.name} ({self.package_size}) - {self.pharmacy.name}"
class Reservation(models.Model):

    STATUS_CHOICES = [
        ("Pending", "Pending"),
        ("Accepted", "Accepted"),
        ("Rejected", "Rejected"),
        ("Collected", "Collected"),
        ("Cancelled", "Cancelled"),
    ]

    customer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="reservations"
    )

    pharmacy = models.ForeignKey(
        Pharmacy,
        on_delete=models.CASCADE
    )

    medicine = models.ForeignKey(
        Medicine,
        on_delete=models.CASCADE
    )

    quantity = models.PositiveIntegerField(default=1)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Pending"
    )

    PAYMENT_METHOD_CHOICES = [
        ("Online", "Paid Online (Razorpay)"),
        ("PayOnPickup", "Pay at Pharmacy on Pickup"),
    ]

    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHOD_CHOICES,
        default="PayOnPickup"
    )

    is_paid = models.BooleanField(default=False)

    prescription_image = models.ImageField(
        upload_to="prescriptions/",
        blank=True,
        null=True,
        help_text="Uploaded doctor prescription file for prescription-required medicines"
    )

    prescription_uploaded = models.BooleanField(
        default=False,
        help_text="True if a valid doctor prescription has been uploaded for this reservation"
    )

    requested_at = models.DateTimeField(auto_now_add=True)

    pickup_before = models.DateTimeField(
        null=True,
        blank=True
    )

    notes = models.TextField(
        blank=True
    )

    def __str__(self):
        return f"{self.customer.username} - {self.medicine.name}"

    @property
    def payment_state(self):
        """
        Derives a canonical 6-state payment lifecycle string from existing fields.
        No migration required — computed from is_paid + payment_method + status.

        States (in order):
          PAYMENT_PENDING   – Online reservation created, payment not yet captured
          PAYMENT_VERIFIED  – Razorpay payment successfully captured & signature verified
          ORDER_CONFIRMED   – Pharmacy has received and acknowledged the paid order (Pending → Accepted transition)
          READY_FOR_PICKUP  – Pharmacy has confirmed stock is held (Accepted)
          COMPLETED         – Customer collected medicine (Collected)
          CANCELLED         – Rejected or Cancelled
          PAY_AT_STORE      – PayOnPickup method, counter payment expected
        """
        if self.status in ("Rejected", "Cancelled"):
            return "CANCELLED"
        if self.status == "Collected":
            return "COMPLETED"
        if self.payment_method == "PayOnPickup":
            if self.status == "Accepted":
                return "READY_FOR_PICKUP"
            return "PAY_AT_STORE"
        # Online payment path
        if not self.is_paid:
            return "PAYMENT_PENDING"
        # is_paid = True
        if self.status == "Accepted":
            return "READY_FOR_PICKUP"
        # Pending + paid = verified and confirmed, waiting pharmacy to accept
        return "ORDER_CONFIRMED"

    @property
    def payment_state_display(self):
        """Human-readable label for the payment_state."""
        return {
            "PAYMENT_PENDING":  "Payment Pending",
            "PAYMENT_VERIFIED": "Payment Verified",
            "ORDER_CONFIRMED":  "Order Confirmed",
            "READY_FOR_PICKUP": "Ready for Pickup",
            "COMPLETED":        "Completed",
            "CANCELLED":        "Cancelled",
            "PAY_AT_STORE":     "Pay at Store",
        }.get(self.payment_state, self.payment_state)
    # ==========================================================

# Notification Model
# ==========================================================

class Notification(models.Model):

    NOTIFICATION_TYPES = [

        ("Reservation", "Reservation"),
        ("Accepted", "Accepted"),
        ("Rejected", "Rejected"),
        ("Inventory", "Inventory"),

    ]

    recipient = models.ForeignKey(

        User,

        on_delete=models.CASCADE,

        related_name="notifications"

    )

    sender = models.ForeignKey(

        User,

        on_delete=models.SET_NULL,

        null=True,

        blank=True,

        related_name="sent_notifications"

    )

    reservation = models.ForeignKey(

        "Reservation",

        on_delete=models.CASCADE,

        null=True,

        blank=True

    )

    title = models.CharField(

        max_length=150

    )

    message = models.TextField()

    notification_type = models.CharField(

        max_length=20,

        choices=NOTIFICATION_TYPES,

        default="Reservation"

    )

    is_read = models.BooleanField(

        default=False

    )

    created_at = models.DateTimeField(

        auto_now_add=True

    )

    class Meta:

        ordering = ["-created_at"]

    def __str__(self):

        return f"{self.recipient.username} - {self.title}"
    
class SearchHistory(models.Model):

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )

    medicine = models.CharField(
        max_length=200
    )

    searched_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f"{self.user.username} - {self.medicine}"


class AgentAuditLog(models.Model):
    """
    Internal audit trail for AI Commerce Agent decisions and events.
    Enables explainability, state tracking, and regulatory audit compliance.
    """
    session_id = models.CharField(max_length=64, db_index=True)
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agent_audit_logs"
    )
    event_type = models.CharField(max_length=60, db_index=True)
    state = models.CharField(max_length=40, default="IDLE")
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"[{self.session_id[:8]}] {self.event_type} ({self.state}) - {self.created_at.strftime('%H:%M:%S')}"


class Order(models.Model):
    """
    Local MedFinder Order Model.
    Tracks state machine from PENDING_APPROVAL -> APPROVED -> PAYMENT_PENDING -> PAID / PAYMENT_FAILED.
    """
    STATUS_CHOICES = [
        ("PENDING_APPROVAL", "Pending Approval"),
        ("APPROVED", "Approved"),
        ("PAYMENT_PENDING", "Payment Pending"),
        ("PAID", "Paid"),
        ("PAYMENT_FAILED", "Payment Failed"),
        ("CANCELLED", "Cancelled"),
    ]

    order_reference = models.CharField(max_length=64, unique=True, db_index=True)
    session_id = models.CharField(max_length=64, db_index=True, blank=True, null=True)
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders"
    )
    medicine = models.ForeignKey(
        Medicine,
        on_delete=models.CASCADE,
        related_name="orders"
    )
    pharmacy = models.ForeignKey(
        Pharmacy,
        on_delete=models.CASCADE,
        related_name="orders"
    )
    inventory = models.ForeignKey(
        Inventory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders"
    )
    reservation = models.ForeignKey(
        "Reservation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders"
    )
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)
    total_amount = models.DecimalField(max_digits=8, decimal_places=2)

    currency = models.CharField(max_length=10, default="INR")
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="PENDING_APPROVAL",
        db_index=True
    )
    razorpay_order_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_signature = models.CharField(max_length=255, blank=True, null=True)
    snapshot_data = models.JSONField(default=dict, blank=True)
    prescription_image = models.ImageField(upload_to="prescriptions/", blank=True, null=True)
    prescription_uploaded = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.order_reference}] {self.medicine.name} - ₹{self.total_amount} ({self.status})"


class WebhookEvent(models.Model):
    """
    Webhook idempotency and delivery logging table.
    Guarantees that duplicate Razorpay webhook deliveries are processed exactly once.
    """
    event_id = models.CharField(max_length=100, unique=True, db_index=True)
    event_type = models.CharField(max_length=100)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=30, default="RECEIVED")
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"Webhook [{self.event_id}] {self.event_type} - {self.status}"


class PasswordResetOTP(models.Model):
    """
    Secure One-Time Password (OTP) model for password resets via Email or SMS.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reset_otps")
    otp_code = models.CharField(max_length=6, db_index=True)
    target = models.CharField(max_length=150)
    channel = models.CharField(max_length=20, default="email")
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ["-created_at"]

    def is_valid(self):
        from django.utils import timezone
        return not self.is_used and timezone.now() <= self.expires_at

    def __str__(self):
        return f"OTP for {self.user.username} ({self.target}) - Valid: {self.is_valid()}"


class Prescription(models.Model):
    """
    Secure User Prescription record.
    Tracks extracted OCR data, confirmed medicine lists, fulfillment state, and private file storage.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="prescriptions",
        null=True,
        blank=True
    )
    image = models.FileField(
        upload_to="prescriptions/",
        blank=True,
        null=True
    )
    document_type = models.CharField(
        max_length=50,
        default="prescription"
    )
    doctor_name = models.CharField(
        max_length=150,
        blank=True,
        null=True
    )
    patient_name = models.CharField(
        max_length=150,
        blank=True,
        null=True
    )
    prescription_date = models.CharField(
        max_length=50,
        blank=True,
        null=True
    )
    extracted_data = models.JSONField(default=dict)
    confirmed_medicines = models.JSONField(default=list)
    overall_confidence = models.FloatField(default=0.0)
    requires_confirmation = models.BooleanField(default=True)
    is_saved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        username = self.user.username if self.user else "Anonymous"
        return f"Prescription #{self.id} by {username} ({self.document_type})"


