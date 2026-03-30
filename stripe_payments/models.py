"""
Database models for Stripe payment transactions.
Mirrors the model structure of tarxemo-django-clickpesa.
"""

from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.validators import MinValueValidator

from .constants import (
    PaymentIntentStatus,
    RefundStatus,
    SubscriptionStatus,
    CheckoutSessionStatus,
    Currency,
    ZERO_DECIMAL_CURRENCIES,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helper
# ──────────────────────────────────────────────────────────────────────────────

def _amount_from_stripe(amount_cents: int, currency: str) -> Decimal:
    """Convert Stripe amount (smallest unit) to display decimal."""
    if currency.lower() in ZERO_DECIMAL_CURRENCIES:
        return Decimal(str(amount_cents))
    return Decimal(str(amount_cents)) / 100


def _amount_to_stripe(amount: Decimal, currency: str) -> int:
    """Convert decimal display amount to Stripe's smallest unit (e.g., cents)."""
    if currency.lower() in ZERO_DECIMAL_CURRENCIES:
        return int(amount)
    return int(amount * 100)


# ──────────────────────────────────────────────────────────────────────────────
# Stripe Customer
# ──────────────────────────────────────────────────────────────────────────────

class StripeCustomer(models.Model):
    """
    Maps a Django user to a Stripe Customer object.
    Creating a Stripe Customer first is best-practice for subscriptions and
    saving payment methods.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="stripe_customer",
        help_text="The Django user linked to this Stripe Customer.",
    )
    stripe_customer_id = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Stripe Customer ID (cus_…)",
    )
    email = models.EmailField(blank=True, null=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    raw_response = models.JSONField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "stripe_customers"
        verbose_name = "Stripe Customer"
        verbose_name_plural = "Stripe Customers"
        indexes = [
            models.Index(fields=["stripe_customer_id"]),
        ]

    def __str__(self):
        return f"{self.user} → {self.stripe_customer_id}"


# ──────────────────────────────────────────────────────────────────────────────
# Payment Intent / Checkout Session Transaction
# ──────────────────────────────────────────────────────────────────────────────

class StripePaymentTransaction(models.Model):
    """
    Stores a Stripe PaymentIntent or Checkout Session record.
    Every payment (card, bank, wallet, etc.) creates one row here.
    """

    # ── Identifiers ───────────────────────────────────────────────────────────
    stripe_payment_intent_id = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        blank=True,
        null=True,
        help_text="Stripe PaymentIntent ID (pi_…)",
    )
    stripe_checkout_session_id = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        blank=True,
        null=True,
        help_text="Stripe Checkout Session ID (cs_…)",
    )
    order_reference = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Your unique order reference — stored in Stripe metadata.",
    )

    # ── Status ────────────────────────────────────────────────────────────────
    status = models.CharField(
        max_length=50,
        choices=[(s.value, s.value) for s in PaymentIntentStatus],
        default=PaymentIntentStatus.REQUIRES_PAYMENT_METHOD.value,
        db_index=True,
    )
    # For Checkout Sessions
    checkout_status = models.CharField(
        max_length=20,
        choices=[(s.value, s.value) for s in CheckoutSessionStatus],
        blank=True,
        null=True,
    )

    # ── Amount ────────────────────────────────────────────────────────────────
    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Amount in major currency units (e.g. 9.99 for $9.99).",
    )
    amount_received = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Amount actually captured by Stripe.",
    )
    currency = models.CharField(
        max_length=3,
        default=Currency.USD.value,
        db_index=True,
    )

    # ── Payment method info ───────────────────────────────────────────────────
    payment_method_type = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="e.g., card, sepa_debit, klarna …",
    )
    payment_method_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Stripe PaymentMethod ID (pm_…)",
    )
    # Card-specific details (populated from Stripe charge object)
    card_brand = models.CharField(max_length=50, blank=True, null=True)
    card_last4 = models.CharField(max_length=4, blank=True, null=True)
    card_exp_month = models.PositiveSmallIntegerField(blank=True, null=True)
    card_exp_year = models.PositiveSmallIntegerField(blank=True, null=True)
    card_country = models.CharField(max_length=2, blank=True, null=True)

    # ── Customer / payer ─────────────────────────────────────────────────────
    stripe_customer_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Stripe Customer ID (cus_…) if payment was made by a customer.",
    )
    customer_email = models.EmailField(blank=True, null=True)
    customer_name = models.CharField(max_length=255, blank=True, null=True)

    # ── Stripe URLs ───────────────────────────────────────────────────────────
    checkout_url = models.URLField(
        max_length=2048,
        blank=True,
        null=True,
        help_text="Stripe-hosted Checkout URL (for redirect flows).",
    )
    receipt_url = models.URLField(max_length=2048, blank=True, null=True)

    # ── Failure info ──────────────────────────────────────────────────────────
    failure_code = models.CharField(max_length=100, blank=True, null=True)
    failure_message = models.TextField(blank=True, null=True)

    # ── Client secret (for frontend confirmation) ─────────────────────────────
    client_secret = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text=(
            "Stripe client_secret — expose only to the authenticated customer "
            "who owns this payment. NEVER log or store permanently in plaintext "
            "in a public context."
        ),
    )

    # ── Metadata / audit ─────────────────────────────────────────────────────
    description = models.TextField(blank=True, null=True)
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Project-specific metadata attached to the Stripe object.",
    )
    raw_response = models.JSONField(
        blank=True,
        null=True,
        help_text="Full raw Stripe API response — for debugging only.",
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    # ── Django user link (optional) ───────────────────────────────────────────
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stripe_payments",
    )

    class Meta:
        db_table = "stripe_payment_transactions"
        ordering = ["-created_at"]
        verbose_name = "Payment Transaction"
        verbose_name_plural = "Payment Transactions"
        indexes = [
            models.Index(fields=["order_reference"]),
            models.Index(fields=["status"]),
            models.Index(fields=["currency"]),
            models.Index(fields=["stripe_customer_id"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return f"Payment {self.order_reference} — {self.status} ({self.currency} {self.amount})"

    # ── Status helpers ────────────────────────────────────────────────────────

    def is_successful(self) -> bool:
        """Return True if the payment completed successfully."""
        return self.status == PaymentIntentStatus.SUCCEEDED.value

    def is_pending(self) -> bool:
        """Return True if the payment is still in progress."""
        return self.status in [
            PaymentIntentStatus.PROCESSING.value,
            PaymentIntentStatus.REQUIRES_PAYMENT_METHOD.value,
            PaymentIntentStatus.REQUIRES_CONFIRMATION.value,
            PaymentIntentStatus.REQUIRES_ACTION.value,
            PaymentIntentStatus.REQUIRES_CAPTURE.value,
        ]

    def is_failed(self) -> bool:
        """Return True if payment has been permanently failed."""
        return self.status == PaymentIntentStatus.CANCELED.value

    def requires_action(self) -> bool:
        """Return True if the customer must complete additional authentication."""
        return self.status == PaymentIntentStatus.REQUIRES_ACTION.value


# ──────────────────────────────────────────────────────────────────────────────
# Refund Transaction
# ──────────────────────────────────────────────────────────────────────────────

class StripeRefundTransaction(models.Model):
    """
    Stores individual Stripe Refund records.
    Multiple refunds can exist per payment (partial refunds).
    """

    stripe_refund_id = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Stripe Refund ID (re_…)",
    )
    payment_transaction = models.ForeignKey(
        StripePaymentTransaction,
        on_delete=models.CASCADE,
        related_name="refunds",
        help_text="The original payment this refund belongs to.",
    )
    order_reference = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Copied from the original payment for easy lookup.",
    )

    # ── Status ────────────────────────────────────────────────────────────────
    status = models.CharField(
        max_length=30,
        choices=[(s.value, s.value) for s in RefundStatus],
        default=RefundStatus.PENDING.value,
        db_index=True,
    )

    # ── Amount ────────────────────────────────────────────────────────────────
    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Refund amount in major currency units.",
    )
    currency = models.CharField(max_length=3, default=Currency.USD.value)

    # ── Reason ────────────────────────────────────────────────────────────────
    reason = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="duplicate | fraudulent | requested_by_customer | other",
    )
    failure_reason = models.TextField(blank=True, null=True)

    # ── Audit ─────────────────────────────────────────────────────────────────
    metadata = models.JSONField(default=dict, blank=True)
    raw_response = models.JSONField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stripe_refunds_initiated",
    )

    class Meta:
        db_table = "stripe_refund_transactions"
        ordering = ["-created_at"]
        verbose_name = "Refund Transaction"
        verbose_name_plural = "Refund Transactions"
        indexes = [
            models.Index(fields=["order_reference"]),
            models.Index(fields=["status"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return f"Refund {self.stripe_refund_id} — {self.currency} {self.amount} ({self.status})"

    def is_successful(self) -> bool:
        return self.status == RefundStatus.SUCCEEDED.value

    def is_pending(self) -> bool:
        return self.status in [RefundStatus.PENDING.value, RefundStatus.REQUIRES_ACTION.value]

    def is_failed(self) -> bool:
        return self.status == RefundStatus.FAILED.value


# ──────────────────────────────────────────────────────────────────────────────
# Subscription
# ──────────────────────────────────────────────────────────────────────────────

class StripeSubscription(models.Model):
    """
    Stores Stripe Subscription records.
    Links a Django user to a recurring billing plan.
    """

    stripe_subscription_id = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Stripe Subscription ID (sub_…)",
    )
    stripe_customer_id = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Stripe Customer ID (cus_…)",
    )
    stripe_price_id = models.CharField(
        max_length=255,
        help_text="Stripe Price ID (price_…) for the subscribed plan.",
    )
    stripe_product_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Stripe Product ID (prod_…)",
    )

    # ── Status ────────────────────────────────────────────────────────────────
    status = models.CharField(
        max_length=30,
        choices=[(s.value, s.value) for s in SubscriptionStatus],
        default=SubscriptionStatus.INCOMPLETE.value,
        db_index=True,
    )

    # ── Billing amounts ───────────────────────────────────────────────────────
    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        help_text="Recurring billing amount in major currency units.",
    )
    currency = models.CharField(max_length=3, default=Currency.USD.value)
    interval = models.CharField(
        max_length=10,
        blank=True,
        null=True,
        help_text="Billing interval: day, week, month, year.",
    )
    interval_count = models.PositiveIntegerField(
        default=1,
        help_text="Number of intervals between billings.",
    )

    # ── Trial ─────────────────────────────────────────────────────────────────
    trial_start = models.DateTimeField(blank=True, null=True)
    trial_end = models.DateTimeField(blank=True, null=True)

    # ── Period ────────────────────────────────────────────────────────────────
    current_period_start = models.DateTimeField(blank=True, null=True)
    current_period_end = models.DateTimeField(blank=True, null=True)
    cancel_at_period_end = models.BooleanField(default=False)
    canceled_at = models.DateTimeField(blank=True, null=True)
    ended_at = models.DateTimeField(blank=True, null=True)

    # ── Audit ─────────────────────────────────────────────────────────────────
    metadata = models.JSONField(default=dict, blank=True)
    raw_response = models.JSONField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stripe_subscriptions",
    )

    class Meta:
        db_table = "stripe_subscriptions"
        ordering = ["-created_at"]
        verbose_name = "Subscription"
        verbose_name_plural = "Subscriptions"
        indexes = [
            models.Index(fields=["stripe_customer_id"]),
            models.Index(fields=["status"]),
            models.Index(fields=["current_period_end"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return f"Subscription {self.stripe_subscription_id} — {self.status}"

    def is_active(self) -> bool:
        return self.status in [
            SubscriptionStatus.ACTIVE.value,
            SubscriptionStatus.TRIALING.value,
        ]

    def is_canceled(self) -> bool:
        return self.status == SubscriptionStatus.CANCELED.value

    def is_past_due(self) -> bool:
        return self.status == SubscriptionStatus.PAST_DUE.value

    def is_in_trial(self) -> bool:
        if not self.trial_end:
            return False
        return (
            self.status == SubscriptionStatus.TRIALING.value
            and timezone.now() < self.trial_end
        )


# ──────────────────────────────────────────────────────────────────────────────
# Webhook Event Log
# ──────────────────────────────────────────────────────────────────────────────

class StripeWebhookEvent(models.Model):
    """
    Idempotency log for Stripe webhook events.
    Every incoming webhook is recorded here first — before processing —
    to prevent double-processing on retries.
    """

    PROCESSING_STATUS = [
        ("RECEIVED", "Received"),
        ("PROCESSING", "Processing"),
        ("PROCESSED", "Processed"),
        ("FAILED", "Failed"),
        ("IGNORED", "Ignored"),
    ]

    stripe_event_id = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Stripe Event ID (evt_…) — used for idempotency.",
    )
    event_type = models.CharField(
        max_length=100,
        db_index=True,
        help_text="e.g., payment_intent.succeeded",
    )
    processing_status = models.CharField(
        max_length=20,
        choices=PROCESSING_STATUS,
        default="RECEIVED",
        db_index=True,
    )
    error_message = models.TextField(blank=True, null=True)

    # Store the full event payload for debugging / replay
    payload = models.JSONField(help_text="Full Stripe event JSON payload.")

    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "stripe_webhook_events"
        ordering = ["-received_at"]
        verbose_name = "Webhook Event"
        verbose_name_plural = "Webhook Events"
        indexes = [
            models.Index(fields=["event_type"]),
            models.Index(fields=["processing_status"]),
            models.Index(fields=["-received_at"]),
        ]

    def __str__(self):
        return f"{self.event_type} [{self.stripe_event_id}] — {self.processing_status}"

    def mark_processed(self):
        self.processing_status = "PROCESSED"
        self.processed_at = timezone.now()
        self.save(update_fields=["processing_status", "processed_at"])

    def mark_failed(self, error: str):
        self.processing_status = "FAILED"
        self.error_message = error
        self.processed_at = timezone.now()
        self.save(update_fields=["processing_status", "error_message", "processed_at"])

    def mark_ignored(self):
        self.processing_status = "IGNORED"
        self.processed_at = timezone.now()
        self.save(update_fields=["processing_status", "processed_at"])