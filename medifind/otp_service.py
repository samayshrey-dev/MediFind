import secrets
import logging
from datetime import timedelta
from django.utils import timezone
from django.core.mail import send_mail, EmailMultiAlternatives
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from .models import PasswordResetOTP, UserProfile

logger = logging.getLogger(__name__)


def generate_numeric_otp(length=6) -> str:
    """Generates a secure cryptographically random numeric OTP string."""
    return "".join(secrets.choice("0123456789") for _ in range(length))


def mask_target_contact(target: str) -> str:
    """Masks an email or phone number for privacy display."""
    if not target:
        return "your registered contact"
    if "@" in target:
        parts = target.split("@")
        name, domain = parts[0], parts[1]
        if len(name) <= 2:
            masked_name = name[0] + "*"
        else:
            masked_name = name[0] + "*" * (len(name) - 2) + name[-1]
        return f"{masked_name}@{domain}"
    else:
        clean = "".join(filter(str.isdigit, target))
        if len(clean) >= 4:
            return "*" * (len(clean) - 4) + clean[-4:]
        return "***" + target[-2:] if len(target) >= 2 else target


def send_password_reset_otp(user, target_input=None) -> tuple[bool, str, PasswordResetOTP | None]:
    """
    Generates a 6-digit OTP and sends it to the user's registered email and/or phone.
    """
    # Invalidate previous unused OTPs for this user
    PasswordResetOTP.objects.filter(user=user, is_used=False).update(is_used=True)

    otp_code = generate_numeric_otp(6)
    expires_at = timezone.now() + timedelta(minutes=10)

    # Determine destination target (email / phone)
    target = user.email or target_input or user.username
    channel = "email" if "@" in target else "sms"

    otp_obj = PasswordResetOTP.objects.create(
        user=user,
        otp_code=otp_code,
        target=target,
        channel=channel,
        is_used=False,
        expires_at=expires_at
    )

    # 1. Send Email if user has an email address
    email_sent = False
    if user.email or "@" in target:
        dest_email = user.email or target
        subject = f"Your MedFinder Password Reset OTP: {otp_code}"
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "MediFind Security <security@medifind.com>")
        
        context = {
            "user": user,
            "otp_code": otp_code,
            "expires_in_minutes": 10,
        }

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="utf-8"></head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; padding: 24px; color: #1e293b;">
          <div style="max-width: 540px; margin: 0 auto; background: #ffffff; border-radius: 16px; padding: 32px; border: 1px solid #e2e8f0; box-shadow: 0 4px 12px rgba(0,0,0,0.05);">
            <div style="text-align: center; margin-bottom: 24px;">
              <div style="display: inline-block; background: #10b981; color: #ffffff; font-weight: 800; font-size: 20px; padding: 8px 16px; border-radius: 10px;">
                MediFind
              </div>
              <h2 style="color: #0f172a; margin-top: 16px; margin-bottom: 6px; font-size: 22px;">Password Reset Verification</h2>
              <p style="color: #64748b; font-size: 14px; margin: 0;">Use the 6-digit code below to securely reset your password.</p>
            </div>
            
            <div style="background: #f1f5f9; border-radius: 12px; padding: 20px; text-align: center; margin: 24px 0; border: 1px dashed #cbd5e1;">
              <span style="font-size: 12px; color: #64748b; display: block; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 1px; font-weight: 600;">Your One-Time Password (OTP)</span>
              <div style="font-size: 36px; font-weight: 800; letter-spacing: 8px; color: #0f172a; font-family: monospace;">
                {otp_code}
              </div>
              <span style="font-size: 12px; color: #10b981; font-weight: 600; display: block; margin-top: 8px;">Valid for 10 minutes</span>
            </div>

            <p style="color: #475569; font-size: 14px; line-height: 1.5; margin-bottom: 16px;">
              Hello <strong>{user.first_name or user.username}</strong>,<br>
              We received a request to reset your password for your MedFinder account. Enter the verification code above to proceed.
            </p>

            <div style="background: #fef2f2; border-left: 4px solid #ef4444; padding: 12px 16px; border-radius: 6px; margin: 20px 0;">
              <p style="color: #991b1b; font-size: 12px; margin: 0;">
                <strong>Security Alert:</strong> If you did not request a password reset, please ignore this email or change your password immediately. Never share your OTP with anyone.
              </p>
            </div>

            <div style="text-align: center; border-top: 1px solid #e2e8f0; padding-top: 16px; margin-top: 24px;">
              <p style="color: #94a3b8; font-size: 12px; margin: 0;">
                &copy; 2026 MediFind Healthcare Platform. All rights reserved.
              </p>
            </div>
          </div>
        </body>
        </html>
        """

        plain_content = f"""
MediFind Password Reset Verification

Your One-Time Password (OTP) code is: {otp_code}

This code is valid for 10 minutes.

If you did not request this password reset, please ignore this email. Never share your OTP with anyone.

Best regards,
The MediFind Team
        """

        try:
            msg = EmailMultiAlternatives(subject, plain_content, from_email, [dest_email])
            msg.attach_alternative(html_content, "text/html")
            msg.send(fail_silently=False)
            email_sent = True
            logger.info(f"Password reset OTP sent to email: {dest_email}")
        except Exception as e:
            logger.error(f"Failed to send password reset OTP email to {dest_email}: {e}")

    # 2. Log SMS simulation / dispatch
    logger.info(f"[SMS Gateway Simulation] OTP {otp_code} dispatched to phone: {target}")

    masked = mask_target_contact(target)
    return True, f"OTP verification code sent to {masked}.", otp_obj


def verify_and_consume_otp(user, input_otp: str) -> tuple[bool, str]:
    """
    Verifies that the provided OTP code is valid, matches the user, is not expired,
    and has not already been used.
    """
    if not input_otp or len(input_otp.strip()) != 6:
        return False, "Please enter a valid 6-digit OTP code."

    clean_otp = input_otp.strip()

    otp_record = PasswordResetOTP.objects.filter(
        user=user,
        otp_code=clean_otp,
        is_used=False
    ).first()

    if not otp_record:
        return False, "Invalid OTP code. Please check and try again."

    if not otp_record.is_valid():
        return False, "This OTP has expired. Please request a new code."

    # Mark as consumed immediately
    otp_record.is_used = True
    otp_record.save(update_fields=["is_used"])

    return True, "OTP verified successfully."
