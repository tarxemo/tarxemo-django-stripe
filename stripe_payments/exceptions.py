"""
Custom exceptions for Stripe payment operations.
Mirrors the exception hierarchy in tarxemo-django-clickpesa.
"""


class StripePaymentsException(Exception):
    """Base exception for all tarxemo-django-stripe errors."""

    def __init__(self, message, error_code=None, stripe_error=None, response_data=None):
        self.message = message
        self.error_code = error_code          # Internal code (string)
        self.stripe_error = stripe_error      # Raw stripe.error.StripeError if available
        self.response_data = response_data    # Raw response dict if available
        super().__init__(self.message)

    def __repr__(self):
        return (
            f"{self.__class__.__name__}("
            f"message={self.message!r}, "
            f"error_code={self.error_code!r})"
        )


# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────

class ConfigurationError(StripePaymentsException):
    """Raised when required Stripe settings are missing or invalid."""
    pass


# ──────────────────────────────────────────────
# Authentication / API connectivity
# ──────────────────────────────────────────────

class AuthenticationError(StripePaymentsException):
    """Raised when Stripe API key authentication fails."""
    pass


class APIError(StripePaymentsException):
    """Raised when the Stripe API returns an unexpected error (5xx, network, etc.)."""
    pass


class RateLimitError(StripePaymentsException):
    """Raised when Stripe rate-limits your API calls (429)."""
    pass


# ──────────────────────────────────────────────
# Input validation
# ──────────────────────────────────────────────

class ValidationError(StripePaymentsException):
    """Raised when input validation fails before hitting the Stripe API."""
    pass


class InvalidAmountError(ValidationError):
    """Raised when the payment amount is invalid (zero, negative, non-numeric)."""
    pass


class InvalidCurrencyError(ValidationError):
    """Raised when a currency code is not supported or recognised by Stripe."""
    pass


class DuplicateOrderReferenceError(ValidationError):
    """Raised when the supplied order_reference already exists in the database."""
    pass


class InvalidEmailError(ValidationError):
    """Raised when a customer email address is invalid."""
    pass


# ──────────────────────────────────────────────
# Payment operations
# ──────────────────────────────────────────────

class PaymentError(StripePaymentsException):
    """Raised when a payment operation fails."""
    pass


class PaymentDeclinedError(PaymentError):
    """Raised when a card / payment method is declined by the issuer."""
    pass


class PaymentRequiresActionError(PaymentError):
    """
    Raised when the payment requires additional customer action
    (e.g. 3D Secure authentication).
    Inspect .client_secret to continue on the frontend.
    """

    def __init__(self, message, client_secret=None, **kwargs):
        super().__init__(message, **kwargs)
        self.client_secret = client_secret


class CheckoutSessionError(PaymentError):
    """Raised when creating or managing a Checkout Session fails."""
    pass


# ──────────────────────────────────────────────
# Refund operations
# ──────────────────────────────────────────────

class RefundError(StripePaymentsException):
    """Raised when a refund operation fails."""
    pass


class RefundNotFoundError(RefundError):
    """Raised when a refund cannot be found."""
    pass


class AlreadyRefundedError(RefundError):
    """Raised when a payment has already been fully refunded."""
    pass


class RefundAmountExceedsChargeError(RefundError):
    """Raised when the requested refund amount exceeds the original charge."""
    pass


# ──────────────────────────────────────────────
# Subscription operations
# ──────────────────────────────────────────────

class SubscriptionError(StripePaymentsException):
    """Raised when a subscription operation fails."""
    pass


class SubscriptionNotFoundError(SubscriptionError):
    """Raised when a subscription cannot be found in the database."""
    pass


class SubscriptionAlreadyCanceledError(SubscriptionError):
    """Raised when trying to cancel an already-canceled subscription."""
    pass


# ──────────────────────────────────────────────
# Customer operations
# ──────────────────────────────────────────────

class CustomerError(StripePaymentsException):
    """Raised when a Stripe Customer operation fails."""
    pass


class CustomerNotFoundError(CustomerError):
    """Raised when a Stripe customer cannot be found."""
    pass


# ──────────────────────────────────────────────
# Webhook
# ──────────────────────────────────────────────

class WebhookError(StripePaymentsException):
    """Raised when webhook signature verification or processing fails."""
    pass


class WebhookSignatureError(WebhookError):
    """Raised when the webhook signature does not match the expected secret."""
    pass
