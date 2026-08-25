import hmac
import hashlib
import json
import uuid
from decimal import Decimal
from django.conf import settings
from django.utils import timezone
from django.db import transaction
import razorpay

from .models import (
    Medicine,
    Pharmacy,
    Inventory,
    Order,
    WebhookEvent,
    AgentAuditLog
)

class CommerceError(Exception):
    """Base exception for agentic commerce operations."""
    pass

class PriceMismatchError(CommerceError):
    """Raised when live inventory price diverges from recommendation snapshot."""
    def __init__(self, old_price, new_price, message=None):
        self.old_price = old_price
        self.new_price = new_price
        super().__init__(message or f"Price changed from ₹{old_price} to ₹{new_price}.")

class OutOfStockError(CommerceError):
    """Raised when medicine is out of stock during checkout."""
    pass


class AgenticCommerceService:
    """
    Dedicated server-side orchestrator for Bounded Agentic Commerce & Razorpay Test Mode transactions.
    Strictly enforces separation between AI reasoning and financial execution.
    """

    @classmethod
    def get_razorpay_client(cls):
        """Initializes server-side Razorpay client with test mode credentials."""
        key_id = getattr(settings, "RAZORPAY_KEY_ID", "")
        key_secret = getattr(settings, "RAZORPAY_KEY_SECRET", "")
        if not key_id or not key_secret:
            raise CommerceError("Razorpay credentials are not configured in settings/environment.")
        return razorpay.Client(auth=(key_id, key_secret))

    @classmethod
    def create_transaction_snapshot(cls, session_id: str, inventory_id: int, quantity: int = 1, user=None) -> Order:
        """
        Creates a server-side immutable transaction snapshot and initial local Order.
        Server verifies that medicine, pharmacy, inventory, and stock exist in MedFinder DB.
        """
        try:
            inv = Inventory.objects.select_related("medicine", "pharmacy").get(id=inventory_id)
        except Inventory.DoesNotExist:
            raise CommerceError("Selected inventory item does not exist.")

        if inv.quantity < quantity:
            raise OutOfStockError(f"Insufficient stock available (Requested: {quantity}, Available: {inv.quantity}).")

        if not inv.pharmacy.is_active:
            raise CommerceError("Selected pharmacy is currently inactive.")

        unit_price = Decimal(str(inv.price))
        total_amount = unit_price * Decimal(quantity)
        order_reference = f"MF-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

        snapshot_data = {
            "session_id": session_id,
            "order_reference": order_reference,
            "medicine_id": inv.medicine.id,
            "medicine_name": inv.medicine.name,
            "medicine_brand": inv.medicine.brand,
            "pharmacy_id": inv.pharmacy.id,
            "pharmacy_name": inv.pharmacy.name,
            "pharmacy_address": f"{inv.pharmacy.address}, {inv.pharmacy.city}",
            "inventory_id": inv.id,
            "quantity": quantity,
            "unit_price": float(unit_price),
            "total_amount": float(total_amount),
            "currency": "INR",
            "stock_snapshot": inv.quantity,
            "created_at": timezone.now().isoformat(),
            "status": "APPROVED"
        }

        order = Order.objects.create(
            order_reference=order_reference,
            session_id=session_id,
            user=user if (user and user.is_authenticated) else None,
            medicine=inv.medicine,
            pharmacy=inv.pharmacy,
            inventory=inv,
            quantity=quantity,
            unit_price=unit_price,
            total_amount=total_amount,
            currency="INR",
            status="APPROVED",
            snapshot_data=snapshot_data,
            approved_at=timezone.now()
        )

        # Log Audit Trail
        AgentAuditLog.objects.create(
            session_id=session_id,
            user=user if (user and user.is_authenticated) else None,
            event_type="transaction_snapshot_created",
            state="APPROVED",
            payload={
                "order_reference": order_reference,
                "medicine": inv.medicine.name,
                "pharmacy": inv.pharmacy.name,
                "total_amount": float(total_amount),
                "quantity": quantity
            }
        )

        return order

    @classmethod
    def create_razorpay_test_order(cls, order_reference: str, user=None) -> dict:
        """
        Revalidates live inventory and creates a Razorpay Test Mode Order.
        Amount is converted to the smallest currency unit (paise: ₹22 -> 2200).
        """
        try:
            order = Order.objects.select_related("medicine", "pharmacy", "inventory", "reservation").get(order_reference=order_reference)
        except Order.DoesNotExist:
            raise CommerceError("Order reference not found.")

        # Prescription Required Enforcement Gate
        if order.medicine.prescription_required and not order.prescription_uploaded and not (order.reservation and order.reservation.prescription_uploaded):
            raise CommerceError(f"A valid doctor prescription upload is required before online or offline payment for {order.medicine.name}.")

        # Revalidation Gate: Recheck Medicine, Pharmacy, Price, and Stock
        try:
            inv = Inventory.objects.select_related("medicine", "pharmacy").get(id=order.inventory.id)
        except Inventory.DoesNotExist:
            raise CommerceError("This option has changed. Please review your order.")

        # 1. Medicine recheck
        if inv.medicine.id != order.medicine.id:
            raise CommerceError("This option has changed. Please review your order.")

        # 2. Pharmacy recheck
        if inv.pharmacy.id != order.pharmacy.id or not inv.pharmacy.is_active:
            raise CommerceError("This option has changed. Please review your order.")

        # 3. Price recheck
        current_price = Decimal(str(inv.price))
        if current_price != order.unit_price:
            AgentAuditLog.objects.create(
                session_id=order.session_id,
                user=user,
                event_type="price_change_detected",
                state="EVALUATING",
                payload={
                    "order_reference": order_reference,
                    "previous_price": float(order.unit_price),
                    "current_price": float(current_price)
                }
            )
            raise PriceMismatchError(
                old_price=float(order.unit_price),
                new_price=float(current_price),
                message="This option has changed. Please review your order."
            )

        # 4. Stock recheck
        if inv.quantity < order.quantity:
            AgentAuditLog.objects.create(
                session_id=order.session_id,
                user=user,
                event_type="out_of_stock_detected",
                state="FAILED",
                payload={"order_reference": order_reference, "available_stock": inv.quantity}
            )
            raise OutOfStockError("This option has changed. Please review your order.")

        # Log Revalidation Passed
        AgentAuditLog.objects.create(
            session_id=order.session_id,
            user=user,
            event_type="inventory_revalidated",
            state="PAYMENT_PENDING",
            payload={
                "order_reference": order_reference,
                "verified_stock": inv.quantity,
                "verified_price": float(current_price)
            }
        )

        # Convert to Paise (Smallest Currency Unit)
        amount_in_paise = int(order.total_amount * 100)

        # Call Razorpay Test Orders API
        client = cls.get_razorpay_client()
        razorpay_payload = {
            "amount": amount_in_paise,
            "currency": "INR",
            "receipt": order.order_reference,
            "notes": {
                "medfinder_order_id": order.order_reference,
                "medicine_id": str(order.medicine.id),
                "medicine_name": order.medicine.name,
                "pharmacy_id": str(order.pharmacy.id),
                "pharmacy_name": order.pharmacy.name
            }
        }

        try:
            rzp_order = client.order.create(data=razorpay_payload)
        except Exception as e:
            AgentAuditLog.objects.create(
                session_id=order.session_id,
                user=user,
                event_type="razorpay_order_failed",
                state="FAILED",
                payload={"order_reference": order_reference, "error": str(e)}
            )
            raise CommerceError(f"Razorpay API Error: {str(e)}")

        order.razorpay_order_id = rzp_order["id"]
        order.status = "PAYMENT_PENDING"
        order.save(update_fields=["razorpay_order_id", "status"])

        # Log Razorpay Order Created
        AgentAuditLog.objects.create(
            session_id=order.session_id,
            user=user,
            event_type="razorpay_order_created",
            state="PAYMENT_PENDING",
            payload={
                "order_reference": order_reference,
                "razorpay_order_id": rzp_order["id"],
                "amount_paise": amount_in_paise,
                "currency": "INR"
            }
        )

        return {
            "success": True,
            "key_id": settings.RAZORPAY_KEY_ID,
            "razorpay_order_id": rzp_order["id"],
            "order_reference": order.order_reference,
            "amount": amount_in_paise,
            "currency": "INR",
            "medicine_name": order.medicine.name,
            "pharmacy_name": order.pharmacy.name,
            "unit_price": float(order.unit_price),
            "total_amount": float(order.total_amount),
            "quantity": order.quantity
        }

    @classmethod
    def create_reservation_payment_order(cls, reservation_id: int, user=None) -> dict:
        """
        Creates a Razorpay Test Order directly for an existing customer Reservation.
        """
        from .models import Reservation
        try:
            res_query = Reservation.objects.select_related("medicine", "pharmacy").filter(id=reservation_id)
            if user and user.is_authenticated and not user.is_superuser:
                res_query = res_query.filter(customer=user)
            reservation = res_query.get()
        except Reservation.DoesNotExist:
            raise CommerceError("Reservation not found.")

        if reservation.is_paid:
            raise CommerceError("This reservation has already been paid.")

        # Prescription Required Enforcement Gate
        if reservation.medicine.prescription_required and not reservation.prescription_uploaded:
            raise CommerceError(f"A valid doctor prescription upload is required before online or offline payment for {reservation.medicine.name}.")

        # Find corresponding inventory
        inv = Inventory.objects.filter(medicine=reservation.medicine, pharmacy=reservation.pharmacy).first()
        if not inv:
            raise CommerceError("Inventory not found for this pharmacy.")

        if inv.quantity < reservation.quantity:
            raise OutOfStockError("This medicine is currently out of stock.")

        # Create or fetch existing Order for this reservation
        order = Order.objects.filter(reservation=reservation, status__in=["PENDING_APPROVAL", "APPROVED", "PAYMENT_PENDING"]).first()
        if not order:
            unit_price = Decimal(str(inv.price))
            total_amount = unit_price * Decimal(reservation.quantity)
            order_reference = f"MF-RES-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

            order = Order.objects.create(
                order_reference=order_reference,
                session_id=f"res_{reservation.id}",
                user=reservation.customer,
                medicine=reservation.medicine,
                pharmacy=reservation.pharmacy,
                inventory=inv,
                reservation=reservation,
                quantity=reservation.quantity,
                unit_price=unit_price,
                total_amount=total_amount,
                currency="INR",
                status="APPROVED",
                approved_at=timezone.now()
            )

        return cls.create_razorpay_test_order(order.order_reference, user=user)

    @classmethod
    def verify_payment_signature(cls, order_reference: str, razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str, user=None) -> dict:

        """
        Verifies Razorpay HMAC SHA256 payment signature server-side.
        If valid: marks Order as PAID, decrements stock in MedFinder DB, and logs audit trail.
        If invalid: marks Order as PAYMENT_FAILED and rejects.
        """
        try:
            order = Order.objects.select_related("medicine", "pharmacy", "inventory").get(order_reference=order_reference)
        except Order.DoesNotExist:
            return {"success": False, "message": "Order reference not found."}

        # Check Order Match
        if order.razorpay_order_id and order.razorpay_order_id != razorpay_order_id:
            order.status = "PAYMENT_FAILED"
            order.failed_at = timezone.now()
            order.save()
            return {"success": False, "message": "Razorpay order ID mismatch."}

        # Verify HMAC SHA256 Signature
        key_secret = getattr(settings, "RAZORPAY_KEY_SECRET", "")
        generated_signature = hmac.new(
            key_secret.encode("utf-8"),
            f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        is_valid = hmac.compare_digest(generated_signature, razorpay_signature)

        if not is_valid:
            order.status = "PAYMENT_FAILED"
            order.failed_at = timezone.now()
            order.save(update_fields=["status", "failed_at"])

            AgentAuditLog.objects.create(
                session_id=order.session_id,
                user=user,
                event_type="payment_signature_verification_failed",
                state="PAYMENT_FAILED",
                payload={
                    "order_reference": order_reference,
                    "razorpay_order_id": razorpay_order_id,
                    "razorpay_payment_id": razorpay_payment_id
                }
            )
            return {"success": False, "message": "Payment verification failed: Invalid signature."}

        # Successful Payment Transition
        with transaction.atomic():
            order.status = "PAID"
            order.razorpay_payment_id = razorpay_payment_id
            order.razorpay_signature = razorpay_signature
            order.paid_at = timezone.now()
            order.save()

            # Mark Reservation Paid if linked
            if order.reservation:
                order.reservation.is_paid = True
                order.reservation.payment_method = "Online"
                order.reservation.status = "Accepted"
                order.reservation.save(update_fields=["is_paid", "payment_method", "status"])
                try:
                    from .views import notify_reservation_update
                    notify_reservation_update(order.reservation, "PAID", user or order.user)
                except Exception:
                    pass

            # Decrement Stock safely
            if order.inventory:
                inv = Inventory.objects.select_for_update().get(id=order.inventory.id)
                inv.quantity = max(0, inv.quantity - order.quantity)
                inv.save(update_fields=["quantity"])

            # Log Audit Trail
            AgentAuditLog.objects.create(
                session_id=order.session_id,

                user=user,
                event_type="payment_verified",
                state="PAID",
                payload={
                    "order_reference": order_reference,
                    "razorpay_order_id": razorpay_order_id,
                    "razorpay_payment_id": razorpay_payment_id,
                    "amount_paid": float(order.total_amount)
                }
            )

            AgentAuditLog.objects.create(
                session_id=order.session_id,
                user=user,
                event_type="order_paid",
                state="PAID",
                payload={
                    "order_reference": order_reference,
                    "medicine": order.medicine.name,
                    "pharmacy": order.pharmacy.name,
                    "total": float(order.total_amount),
                    "status": "CONFIRMED"
                }
            )

        return {
            "success": True,
            "status": "PAID",
            "order_reference": order.order_reference,
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "total_amount": float(order.total_amount),
            "medicine_name": order.medicine.name,
            "pharmacy_name": order.pharmacy.name,
            "message": "Payment verified and order confirmed successfully!"
        }

    @classmethod
    def record_payment_failure(cls, order_reference: str, reason: str = "Payment cancelled by user", user=None) -> dict:
        """Records payment failure or checkout dismissal."""
        try:
            order = Order.objects.get(order_reference=order_reference)
            order.status = "PAYMENT_FAILED"
            order.failed_at = timezone.now()
            order.save(update_fields=["status", "failed_at"])

            AgentAuditLog.objects.create(
                session_id=order.session_id,
                user=user,
                event_type="payment_failed",
                state="PAYMENT_FAILED",
                payload={
                    "order_reference": order_reference,
                    "reason": reason
                }
            )
            return {"success": True, "status": "PAYMENT_FAILED", "order_reference": order_reference}
        except Order.DoesNotExist:
            return {"success": False, "message": "Order not found."}

    @classmethod
    def process_webhook(cls, raw_body: bytes, signature_header: str, event_id: str) -> dict:
        """
        Idempotent Razorpay Webhook processor.
        Verifies HMAC SHA256 signature using RAW request body and webhook secret.
        """
        webhook_secret = getattr(settings, "RAZORPAY_WEBHOOK_SECRET", "")
        if not webhook_secret:
            raise CommerceError("RAZORPAY_WEBHOOK_SECRET is not configured.")

        # 1. Compute and Verify Signature on RAW body
        computed_sig = hmac.new(
            webhook_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(computed_sig, signature_header or ""):
            return {
                "success": False,
                "status": "INVALID_SIGNATURE",
                "message": "Webhook signature verification failed."
            }

        # 2. Parse payload safely
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except Exception:
            return {"success": False, "status": "MALFORMED_JSON", "message": "Invalid JSON body."}

        event_type = payload.get("event", "unknown")
        event_id = event_id or payload.get("id") or f"evt_{uuid.uuid4().hex[:12]}"

        # 3. Webhook Idempotency Check
        webhook_event, created = WebhookEvent.objects.get_or_create(
            event_id=event_id,
            defaults={
                "event_type": event_type,
                "payload": payload,
                "status": "PROCESSING",
                "received_at": timezone.now()
            }
        )

        if not created and webhook_event.status in ["PROCESSED", "DUPLICATE"]:
            return {
                "success": True,
                "status": "DUPLICATE_IGNORED",
                "event_id": event_id,
                "message": "Webhook event already processed."
            }

        # 4. Handle Successful Payment Events
        if event_type in ["payment.captured", "order.paid"]:
            payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
            rzp_order_id = payment_entity.get("order_id")
            rzp_payment_id = payment_entity.get("id")

            if rzp_order_id:
                try:
                    order = Order.objects.select_related("medicine", "pharmacy", "inventory").get(razorpay_order_id=rzp_order_id)
                    if order.status != "PAID":
                        with transaction.atomic():
                            order.status = "PAID"
                            order.razorpay_payment_id = rzp_payment_id or order.razorpay_payment_id
                            order.paid_at = timezone.now()
                            order.save()

                            if order.reservation:
                                order.reservation.is_paid = True
                                order.reservation.payment_method = "Online"
                                order.reservation.status = "Accepted"
                                order.reservation.save(update_fields=["is_paid", "payment_method", "status"])
                                try:
                                    from .views import notify_reservation_update
                                    notify_reservation_update(order.reservation, "PAID", order.user)
                                except Exception:
                                    pass

                            if order.inventory:
                                inv = Inventory.objects.select_for_update().get(id=order.inventory.id)
                                inv.quantity = max(0, inv.quantity - order.quantity)
                                inv.save(update_fields=["quantity"])

                            AgentAuditLog.objects.create(
                                session_id=order.session_id,
                                event_type="webhook_received",
                                state="PAID",
                                payload={
                                    "event_id": event_id,
                                    "event_type": event_type,
                                    "order_reference": order.order_reference,
                                    "razorpay_order_id": rzp_order_id
                                }
                            )
                except Order.DoesNotExist:
                    pass

        webhook_event.status = "PROCESSED"
        webhook_event.processed_at = timezone.now()
        webhook_event.save(update_fields=["status", "processed_at"])

        return {
            "success": True,
            "status": "PROCESSED",
            "event_id": event_id,
            "event_type": event_type
        }
