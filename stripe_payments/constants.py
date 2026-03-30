"""
Constants and enums for Stripe payment operations.
Mirrors the pattern used in tarxemo-django-clickpesa.
"""

from enum import Enum


class PaymentIntentStatus(str, Enum):
    """Stripe PaymentIntent statuses."""
    REQUIRES_PAYMENT_METHOD = "requires_payment_method"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    REQUIRES_ACTION = "requires_action"
    PROCESSING = "processing"
    REQUIRES_CAPTURE = "requires_capture"
    CANCELED = "canceled"
    SUCCEEDED = "succeeded"


class RefundStatus(str, Enum):
    """Stripe Refund statuses."""
    PENDING = "pending"
    REQUIRES_ACTION = "requires_action"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class SubscriptionStatus(str, Enum):
    """Stripe Subscription statuses."""
    INCOMPLETE = "incomplete"
    INCOMPLETE_EXPIRED = "incomplete_expired"
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    UNPAID = "unpaid"
    PAUSED = "paused"


class PaymentMethodType(str, Enum):
    """Supported Stripe payment method types."""
    CARD = "card"
    SEPA_DEBIT = "sepa_debit"
    IDEAL = "ideal"
    BANCONTACT = "bancontact"
    GIROPAY = "giropay"
    SOFORT = "sofort"
    LINK = "link"
    PAYPAL = "paypal"
    ALIPAY = "alipay"
    WECHAT_PAY = "wechat_pay"
    KLARNA = "klarna"
    AFTERPAY_CLEARPAY = "afterpay_clearpay"
    AFFIRM = "affirm"
    US_BANK_ACCOUNT = "us_bank_account"


class CheckoutSessionStatus(str, Enum):
    """Stripe Checkout Session statuses."""
    OPEN = "open"
    COMPLETE = "complete"
    EXPIRED = "expired"


class Currency(str, Enum):
    """
    Common supported currencies in Stripe.
    Stripe supports 135+ currencies — these cover the most common ones.
    """
    USD = "usd"
    EUR = "eur"
    GBP = "gbp"
    JPY = "jpy"
    AUD = "aud"
    CAD = "cad"
    CHF = "chf"
    CNY = "cny"
    SEK = "sek"
    NOK = "nok"
    DKK = "dkk"
    NZD = "nzd"
    SGD = "sgd"
    HKD = "hkd"
    MXN = "mxn"
    BRL = "brl"
    INR = "inr"
    ZAR = "zar"
    KES = "kes"
    TZS = "tzs"
    UGX = "ugx"
    GHS = "ghs"
    NGN = "ngn"
    EGP = "egp"
    # Add more as needed per Stripe docs


class WebhookEventType(str, Enum):
    """Stripe webhook event types handled by this library."""
    # PaymentIntent events
    PAYMENT_INTENT_SUCCEEDED = "payment_intent.succeeded"
    PAYMENT_INTENT_FAILED = "payment_intent.payment_failed"
    PAYMENT_INTENT_CANCELED = "payment_intent.canceled"
    PAYMENT_INTENT_PROCESSING = "payment_intent.processing"
    PAYMENT_INTENT_REQUIRES_ACTION = "payment_intent.requires_action"

    # Checkout session events
    CHECKOUT_SESSION_COMPLETED = "checkout.session.completed"
    CHECKOUT_SESSION_EXPIRED = "checkout.session.expired"
    CHECKOUT_SESSION_ASYNC_PAYMENT_SUCCEEDED = "checkout.session.async_payment_succeeded"
    CHECKOUT_SESSION_ASYNC_PAYMENT_FAILED = "checkout.session.async_payment_failed"

    # Refund events
    CHARGE_REFUNDED = "charge.refunded"
    REFUND_CREATED = "refund.created"
    REFUND_UPDATED = "refund.updated"
    REFUND_FAILED = "refund.failed"

    # Subscription events
    CUSTOMER_SUBSCRIPTION_CREATED = "customer.subscription.created"
    CUSTOMER_SUBSCRIPTION_UPDATED = "customer.subscription.updated"
    CUSTOMER_SUBSCRIPTION_DELETED = "customer.subscription.deleted"
    CUSTOMER_SUBSCRIPTION_TRIAL_WILL_END = "customer.subscription.trial_will_end"

    # Invoice events
    INVOICE_PAYMENT_SUCCEEDED = "invoice.payment_succeeded"
    INVOICE_PAYMENT_FAILED = "invoice.payment_failed"
    INVOICE_UPCOMING = "invoice.upcoming"


# Default settings
DEFAULT_CURRENCY = Currency.USD
DEFAULT_TIMEOUT = 30       # seconds for HTTP requests
MAX_RETRIES = 3

# Stripe API versions — pin this for stability in production
STRIPE_API_VERSION = "2024-06-20"

# Zero-decimal currencies (Stripe expects amounts in units, not cents)
ZERO_DECIMAL_CURRENCIES = {
    "bif", "clp", "gnf", "jpy", "kmf", "krw", "mga", "pyg",
    "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf",
}
