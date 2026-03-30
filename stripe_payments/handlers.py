"""
Signal handlers for Stripe payment events.
This file is imported by StripePaymentsConfig.ready() to ensure signals are registered.
"""

# Import signals to ensure they are available
from .signals import (
    payment_status_changed,
    refund_status_changed,
    subscription_status_changed,
)

# You can define global signal handlers here if needed, 
# for example for internal logging or analytics.
# Most business logic should be in the user's application signals.py.
