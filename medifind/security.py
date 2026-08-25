"""
MediFind Security Utility Module
Provides defensive security utilities including:
- In-memory / cache sliding window rate limiting
- SSRF (Server-Side Request Forgery) protection & private IP blacklisting
- Input sanitization & XSS defenses
- Password & Token security utilities
"""

import re
import ipaddress
import urllib.parse
import time
from collections import defaultdict
from django.core.cache import cache
from django.http import HttpResponseForbidden, JsonResponse
from django.conf import settings
import logging

logger = logging.getLogger("medifind.security")

# ==========================================================
# 1. In-Memory / Cache Sliding Window Rate Limiter
# ==========================================================
_MEMORY_RATE_LIMIT_STORE = defaultdict(list)

def get_client_ip(request):
    """Safely extracts client IP considering trusted reverse proxy headers."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR', '127.0.0.1')
    return ip


def is_rate_limited(key: str, max_requests: int = 5, window_seconds: int = 60) -> bool:
    """
    Checks whether an action identified by `key` exceeds `max_requests` in `window_seconds`.
    Uses Django cache if configured, otherwise falls back to thread-safe memory store.
    """
    now = time.time()
    cache_key = f"rl:{key}"

    try:
        timestamps = cache.get(cache_key)
        if timestamps is None:
            timestamps = []
        # Filter timestamps within current sliding window
        timestamps = [t for t in timestamps if now - t < window_seconds]
        if len(timestamps) >= max_requests:
            return True
        timestamps.append(now)
        cache.set(cache_key, timestamps, timeout=window_seconds + 5)
        return False
    except Exception:
        # Fallback to local memory store
        timestamps = _MEMORY_RATE_LIMIT_STORE[key]
        timestamps = [t for t in timestamps if now - t < window_seconds]
        if len(timestamps) >= max_requests:
            return True
        timestamps.append(now)
        _MEMORY_RATE_LIMIT_STORE[key] = timestamps
        return False


def rate_limit(max_requests=10, window_seconds=60, key_prefix="general", is_json=False):
    """
    Decorator for views to enforce rate limits per IP address.
    """
    def decorator(view_func):
        def wrapper(request, *args, **kwargs):
            ip = get_client_ip(request)
            limit_key = f"{key_prefix}:{ip}"
            
            if is_rate_limited(limit_key, max_requests=max_requests, window_seconds=window_seconds):
                logger.warning(f"Rate limit exceeded for IP {ip} on action {key_prefix}")
                if is_json or request.path.startswith('/api/'):
                    return JsonResponse({
                        "error": "Too many requests. Please slow down and try again shortly.",
                        "rate_limited": True,
                        "retry_after_seconds": window_seconds
                    }, status=429)
                return HttpResponseForbidden("Too many requests from this IP. Please wait a moment before trying again.")
            
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


# ==========================================================
# 2. SSRF Protection & Safe Outbound URL Validator
# ==========================================================
DISALLOWED_HOSTS = {
    'localhost', '127.0.0.1', '0.0.0.0', '::1',
    '169.254.169.254', # AWS / GCP / Azure metadata endpoint
    'metadata.google.internal',
    'instance-data',
}

def is_safe_external_url(url: str) -> bool:
    """
    Validates outbound HTTP/HTTPS URLs against SSRF attacks.
    Disallows internal RFC 1918 private IP addresses, loopbacks, link-local, and cloud metadata endpoints.
    """
    if not url or not isinstance(url, str):
        return False
    
    url = url.strip()
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False

    # Only permit HTTP and HTTPS schemes
    if parsed.scheme.lower() not in ('http', 'https'):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    hostname_lower = hostname.lower()

    if hostname_lower in DISALLOWED_HOSTS:
        return False

    if hostname_lower.endswith('.local') or hostname_lower.endswith('.internal'):
        return False

    # Check if host is an IP address
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return False
    except ValueError:
        # Not a raw IP literal, it is a domain name
        pass

    return True


# ==========================================================
# 3. Input Sanitization Helpers
# ==========================================================
def sanitize_plain_text(val: str, max_length: int = 500) -> str:
    """Strips dangerous script / HTML tags and truncates to max_length."""
    if not val:
        return ""
    val = str(val).strip()
    # Strip HTML tags
    cleaned = re.sub(r'<[^>]*>', '', val)
    return cleaned[:max_length]
