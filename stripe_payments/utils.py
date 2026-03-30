"""
Utility functions for tarxemo-django-stripe.
"""
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings

from .exceptions import ConfigurationError
from .constants import ZERO_DECIMAL_CURRENCIES


# ──────────────────────────────────────────────
# Settings helpers
# ──────────────────────────────────────────────

def get_stripe_api_key() -> str:
    """
    Return the Stripe secret API key from Django settings.

    Looks for STRIPE_SECRET_KEY in settings.
    Raises ConfigurationError if not set or if a test key is used in production.
    """
    key = getattr(settings, "STRIPE_SECRET_KEY", None)
    if not key:
        raise ConfigurationError(
            "STRIPE_SECRET_KEY is not configured in Django settings. "
            "Add it to your settings.py:\n\n"
            "    STRIPE_SECRET_KEY = 'sk_live_...'\n\n"
            "Use environment variables — never hard-code keys:\n"
            "    import os\n"
            "    STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')"
        )

    # Warn (not block) if test key is used when DEBUG=False
    if not settings.DEBUG and key.startswith("sk_test_"):
        import warnings
        warnings.warn(
            "You are using a Stripe TEST key (sk_test_…) in a non-DEBUG environment. "
            "Make sure this is intentional (e.g., staging). "
            "In production, use your live key (sk_live_…).",
            RuntimeWarning,
            stacklevel=2,
        )

    return key


def get_webhook_secret() -> str:
    """
    Return the Stripe webhook endpoint secret from Django settings.

    Looks for STRIPE_WEBHOOK_SECRET in settings.
    """
    secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", None)
    if not secret:
        raise ConfigurationError(
            "STRIPE_WEBHOOK_SECRET is not configured in Django settings. "
            "Add it to your settings.py:\n\n"
            "    STRIPE_WEBHOOK_SECRET = 'whsec_...'\n\n"
            "Find it in the Stripe Dashboard → Developers → Webhooks → "
            "your endpoint → Signing secret."
        )
    return secret


def get_publishable_key() -> str:
    """Return the Stripe publishable key for use in frontend JS."""
    key = getattr(settings, "STRIPE_PUBLISHABLE_KEY", None)
    if not key:
        raise ConfigurationError(
            "STRIPE_PUBLISHABLE_KEY is not configured in Django settings."
        )
    return key


# ──────────────────────────────────────────────
# Amount conversion helpers
# ──────────────────────────────────────────────

def amount_to_stripe_units(amount: Decimal, currency: str) -> int:
    """
    Convert a human-readable amount to Stripe's smallest currency unit.

    Examples:
        9.99 USD  → 999   (cents)
        1000 JPY  → 1000  (zero-decimal)
        5.50 EUR  → 550   (cents)

    Args:
        amount: Decimal amount in major currency units.
        currency: ISO-4217 currency code (case-insensitive).

    Returns:
        Integer amount in Stripe's smallest unit.
    """
    amount = Decimal(str(amount))
    if currency.lower() in ZERO_DECIMAL_CURRENCIES:
        return int(amount)
    # Round to nearest cent to avoid floating-point artefacts
    cents = (amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def amount_from_stripe_units(amount_units: int, currency: str) -> Decimal:
    """
    Convert from Stripe's smallest unit back to major currency units.

    Args:
        amount_units: Integer from Stripe (e.g. 999 for $9.99).
        currency: ISO-4217 currency code.

    Returns:
        Decimal in major units.
    """
    if currency.lower() in ZERO_DECIMAL_CURRENCIES:
        return Decimal(str(amount_units))
    return (Decimal(str(amount_units)) / 100).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


# ──────────────────────────────────────────────
# Misc
# ──────────────────────────────────────────────

def generate_order_reference(prefix: str = "ORDER") -> str:
    """
    Generate a unique order reference.

    Usage:
        ref = generate_order_reference("INV")   # e.g. INV-A3F9B2C1D4E5
    """
    import uuid
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def mask_secret(key: str, visible: int = 6) -> str:
    """
    Mask a secret key for safe logging.

    e.g.:  sk_live_abc...  → sk_live_***...abc
    """
    if not key or len(key) <= visible * 2:
        return "***"
    return f"{key[:visible]}***{key[-4:]}"
