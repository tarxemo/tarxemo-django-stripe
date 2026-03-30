"""
Django signals for Stripe payment events.
Mirrors the pattern in tarxemo-django-clickpesa/signals.py.

Usage:
    from django.dispatch import receiver
    from stripe_payments.signals import payment_succeeded, refund_created

    @receiver(payment_succeeded)
    def on_payment_success(sender, instance, stripe_event, **kwargs):
        ...
"""
from django.dispatch import Signal

# ──────────────────────────────────────────────
# PaymentIntent signals
# ──────────────────────────────────────────────

# Emitted whenever a StripePaymentTransaction status changes.
# Args:
#   sender   – StripePaymentTransaction class
#   instance – StripePaymentTransaction instance
#   new_status – The new status string
#   old_status – The previous status string (None if newly created)
#   created  – True if the record was just created
payment_status_changed = Signal()

# Convenience alias signals
payment_succeeded   = Signal()   # instance, stripe_event
payment_failed      = Signal()   # instance, stripe_event, failure_reason
payment_canceled    = Signal()   # instance, stripe_event
payment_processing  = Signal()   # instance, stripe_event
payment_requires_action = Signal()  # instance, stripe_event, client_secret

# ──────────────────────────────────────────────
# Checkout Session signals
# ──────────────────────────────────────────────

checkout_session_completed = Signal()   # instance, stripe_event
checkout_session_expired   = Signal()   # instance, stripe_event

# ──────────────────────────────────────────────
# Refund signals
# ──────────────────────────────────────────────

# Emitted whenever a StripeRefundTransaction status changes.
# Args:
#   sender   – StripeRefundTransaction class
#   instance – StripeRefundTransaction instance
#   new_status – The new status string
#   old_status – Previous status (None if newly created)
#   created  – True if the record was just created
refund_status_changed = Signal()

refund_created   = Signal()   # instance, stripe_event
refund_succeeded = Signal()   # instance, stripe_event
refund_failed    = Signal()   # instance, stripe_event

# ──────────────────────────────────────────────
# Subscription signals
# ──────────────────────────────────────────────

# Emitted whenever a StripeSubscription status changes.
# Args:  sender, instance, new_status, old_status, created
subscription_status_changed = Signal()

subscription_created        = Signal()   # instance, stripe_event
subscription_activated      = Signal()   # instance, stripe_event
subscription_canceled       = Signal()   # instance, stripe_event
subscription_past_due       = Signal()   # instance, stripe_event
subscription_trial_ending   = Signal()   # instance, stripe_event, trial_end (datetime)
invoice_payment_succeeded   = Signal()   # subscription_instance, invoice_data
invoice_payment_failed      = Signal()   # subscription_instance, invoice_data
