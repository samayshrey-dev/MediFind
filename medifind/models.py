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

    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


    

class UserProfile(models.Model):

    ROLE_CHOICES = [
        ("Customer", "Customer"),
        ("Pharmacy", "Pharmacy"),
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
    pharmacy = models.OneToOneField(
    "Pharmacy",
    on_delete=models.SET_NULL,
    null=True,
    blank=True
    )

    def __str__(self):
        return f"{self.user.username} - {self.role}"
    
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

    def __str__(self):

        return f"{self.medicine.name} - {self.pharmacy.name}"
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
