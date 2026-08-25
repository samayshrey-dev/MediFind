"""
MediFind Security & Defense Middleware
Applies comprehensive OWASP / HIPAA / DPDP compliant HTTP security headers:
- Content Security Policy (CSP)
- Permissions-Policy
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- Referrer-Policy: strict-origin-when-cross-origin
- Cross-Origin-Opener-Policy: same-origin-allow-popups
"""

class MediFindSecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # 1. Content Security Policy
        # Allows necessary CDN assets (Bootstrap, FontAwesome, Leaflet, Razorpay, Google Fonts)
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com https://checkout.razorpay.com https://www.googletagmanager.com",
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com https://fonts.googleapis.com",
            "font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com data:",
            "img-src 'self' data: https: blob:",
            "connect-src 'self' https://nominatim.openstreetmap.org https://api.razorpay.com https://lumberjack.razorpay.com https://www.google-analytics.com https://analytics.google.com https://region1.google-analytics.com",
            "frame-src 'self' https://api.razorpay.com https://checkout.razorpay.com",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self' https://checkout.razorpay.com",
        ]
        response.headers['Content-Security-Policy'] = "; ".join(csp_directives)

        # 2. Permissions Policy (Least privilege hardware access)
        response.headers['Permissions-Policy'] = "camera=(), microphone=(), geolocation=(self), payment=(self)"

        # 3. Prevent MIME Sniffing
        response.headers['X-Content-Type-Options'] = "nosniff"

        # 4. Prevent Clickjacking
        response.headers['X-Frame-Options'] = "DENY"

        # 5. Strict Referrer Policy
        response.headers['Referrer-Policy'] = "strict-origin-when-cross-origin"

        # 6. Cross-Origin-Opener-Policy
        response.headers['Cross-Origin-Opener-Policy'] = "same-origin-allow-popups"

        return response
