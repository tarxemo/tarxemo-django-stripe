"""
High-level SubscriptionManager — database-aware, signal-emitting.
"""
import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from ..services.customer_service import CustomerService, SubscriptionService
from ..models import StripeSubscription, StripeCustomer
from ..constants import SubscriptionStatus
from ..exceptions import (
    SubscriptionError,
    SubscriptionNotFoundError,
    SubscriptionAlreadyCanceledError,
    CustomerError,
)
from ..signals import (
    subscription_status_changed,
    subscription_created,
    subscription_activated,
    subscription_canceled,
    subscription_past_due,
    invoice_payment_succeeded,
    invoice_payment_failed,
)
from ..utils import amount_from_stripe_units

logger = logging.getLogger("stripe_payments.subscription_manager")


class SubscriptionManager:
    """
    High-level manager for Stripe Subscription operations.

    Usage:
        from stripe_payments.managers.subscription_manager import SubscriptionManager

        mgr = SubscriptionManager()

        # Create subscription (user must have a StripeCustomer record)
        sub = mgr.create_subscription(
            user=request.user,
            price_id='price_xxx',
            trial_period_days=14,
        )

        # Cancel at period end
        mgr.cancel_subscription(user=request.user, at_period_end=True)

        # Manual portal redirect
        url = mgr.get_billing_portal_url(user=request.user, return_url='https://myapp.com/account')
    """

    def __init__(self):
        self._customer_service = CustomerService()
        self._subscription_service = SubscriptionService()

    # ──────────────────────────────────────────────────────────────────────────
    # Create subscription
    # ──────────────────────────────────────────────────────────────────────────

    def create_subscription(
        self,
        user,
        price_id: str,
        *,
        trial_period_days: int = None,
        metadata: dict = None,
        payment_behavior: str = "default_incomplete",
        default_payment_method: str = None,
        coupon: str = None,
        promotion_code: str = None,
        auto_create_customer: bool = True,
    ) -> StripeSubscription:
        """
        Create a Stripe Subscription for a Django user.

        If the user doesn't have a StripeCustomer record and
        auto_create_customer=True, a Stripe Customer is created automatically.

        Args:
            user: Django user.
            price_id: Stripe Price ID (price_…).
            trial_period_days: Free trial days.
            metadata: Key-value pairs stored on Stripe.
            payment_behavior: 'default_incomplete' leaves invoice unpaid until
                              a payment method is added (recommended for SCA compliance).
            default_payment_method: Stripe PaymentMethod ID.
            coupon: Stripe Coupon ID.
            promotion_code: Stripe PromotionCode ID.
            auto_create_customer: Create a Stripe Customer if one doesn't exist.

        Returns:
            StripeSubscription instance.
        """
        stripe_customer = self._get_or_create_stripe_customer(
            user, auto_create_customer
        )

        sub_data = self._subscription_service.create_subscription(
            customer_id=stripe_customer.stripe_customer_id,
            price_id=price_id,
            trial_period_days=trial_period_days,
            metadata={
                "user_id": str(user.pk),
                **(metadata or {}),
            },
            payment_behavior=payment_behavior,
            payment_settings={
                "save_default_payment_method": "on_subscription",
                "payment_method_options": {
                    "card": {"request_three_d_secure": "automatic"}
                },
            },
            expand=["latest_invoice.payment_intent"],
            default_payment_method=default_payment_method,
            coupon=coupon,
            promotion_code=promotion_code,
        )

        amount = amount_from_stripe_units(
            sub_data.get("plan", {}).get("amount", 0),
            sub_data.get("plan", {}).get("currency", "usd"),
        )

        with transaction.atomic():
            sub = StripeSubscription.objects.create(
                stripe_subscription_id=sub_data["id"],
                stripe_customer_id=stripe_customer.stripe_customer_id,
                stripe_price_id=price_id,
                stripe_product_id=sub_data.get("plan", {}).get("product"),
                status=sub_data["status"],
                amount=amount,
                currency=sub_data.get("plan", {}).get("currency", "usd"),
                interval=sub_data.get("plan", {}).get("interval"),
                interval_count=sub_data.get("plan", {}).get("interval_count", 1),
                trial_start=self._ts(sub_data.get("trial_start")),
                trial_end=self._ts(sub_data.get("trial_end")),
                current_period_start=self._ts(sub_data.get("current_period_start")),
                current_period_end=self._ts(sub_data.get("current_period_end")),
                cancel_at_period_end=sub_data.get("cancel_at_period_end", False),
                metadata=metadata or {},
                raw_response=sub_data,
                user=user,
            )

        subscription_status_changed.send(
            sender=StripeSubscription,
            instance=sub,
            new_status=sub.status,
            old_status=None,
            created=True,
        )
        subscription_created.send(
            sender=StripeSubscription,
            instance=sub,
            stripe_event=sub_data,
        )

        logger.info(
            "SubscriptionManager: Created subscription %s for user %s",
            sub_data["id"],
            user.pk,
        )
        return sub

    # ──────────────────────────────────────────────────────────────────────────
    # Cancel subscription
    # ──────────────────────────────────────────────────────────────────────────

    def cancel_subscription(
        self,
        user=None,
        subscription_id: str = None,
        *,
        at_period_end: bool = True,
        cancellation_details: dict = None,
    ) -> StripeSubscription:
        """
        Cancel a Stripe Subscription.

        Either pass user (takes the latest active sub) or explicit subscription_id.

        Args:
            user: Django user (looks up their active subscription).
            subscription_id: Stripe Subscription ID (sub_…) — takes priority.
            at_period_end: Keep access until billing period ends.
            cancellation_details: {'comment': str, 'feedback': str}.

        Returns:
            Updated StripeSubscription.
        """
        sub = self._resolve_subscription(user, subscription_id)

        if sub.is_canceled():
            raise SubscriptionAlreadyCanceledError(
                f"Subscription {sub.stripe_subscription_id} is already canceled."
            )

        old_status = sub.status
        sub_data = self._subscription_service.cancel_subscription(
            sub.stripe_subscription_id,
            at_period_end=at_period_end,
            cancellation_details=cancellation_details,
        )

        with transaction.atomic():
            sub.status = sub_data.get("status", sub.status)
            sub.cancel_at_period_end = sub_data.get("cancel_at_period_end", False)
            sub.canceled_at = self._ts(sub_data.get("canceled_at"))
            sub.ended_at = self._ts(sub_data.get("ended_at"))
            sub.raw_response = sub_data
            sub.save()

        if sub.status != old_status:
            subscription_status_changed.send(
                sender=StripeSubscription,
                instance=sub,
                new_status=sub.status,
                old_status=old_status,
                created=False,
            )
        subscription_canceled.send(
            sender=StripeSubscription,
            instance=sub,
            stripe_event=sub_data,
        )

        logger.info(
            "SubscriptionManager: Cancelled subscription %s (at_period_end=%s)",
            sub.stripe_subscription_id,
            at_period_end,
        )
        return sub

    # ──────────────────────────────────────────────────────────────────────────
    # Sync status
    # ──────────────────────────────────────────────────────────────────────────

    def sync_subscription_status(self, stripe_subscription_id: str) -> StripeSubscription:
        """
        Pull the latest status from Stripe and update the local record.

        Returns:
            Updated StripeSubscription.
        """
        sub = StripeSubscription.objects.filter(
            stripe_subscription_id=stripe_subscription_id
        ).first()
        if sub is None:
            raise SubscriptionNotFoundError(
                f"Subscription '{stripe_subscription_id}' not found in database."
            )

        old_status = sub.status
        data = self._subscription_service.retrieve_subscription(stripe_subscription_id)
        new_status = data.get("status", old_status)

        with transaction.atomic():
            sub.status = new_status
            sub.cancel_at_period_end = data.get("cancel_at_period_end", False)
            sub.canceled_at = self._ts(data.get("canceled_at"))
            sub.ended_at = self._ts(data.get("ended_at"))
            sub.current_period_start = self._ts(data.get("current_period_start"))
            sub.current_period_end = self._ts(data.get("current_period_end"))
            sub.raw_response = data
            sub.save()

        if new_status != old_status:
            subscription_status_changed.send(
                sender=StripeSubscription,
                instance=sub,
                new_status=new_status,
                old_status=old_status,
                created=False,
            )
            if new_status == SubscriptionStatus.ACTIVE.value:
                subscription_activated.send(
                    sender=StripeSubscription,
                    instance=sub,
                    stripe_event=data,
                )
            elif new_status == SubscriptionStatus.PAST_DUE.value:
                subscription_past_due.send(
                    sender=StripeSubscription,
                    instance=sub,
                    stripe_event=data,
                )

        return sub

    # ──────────────────────────────────────────────────────────────────────────
    # Billing portal
    # ──────────────────────────────────────────────────────────────────────────

    def get_billing_portal_url(self, user, return_url: str) -> str:
        """
        Generate a Stripe Billing Portal URL for the given user.
        Lets them manage payment methods, subscriptions, and download invoices.

        Args:
            user: Django user (must have a StripeCustomer record).
            return_url: URL to redirect back to your site when they're done.

        Returns:
            Stripe Billing Portal session URL (str).
        """
        try:
            sc = StripeCustomer.objects.get(user=user)
        except StripeCustomer.DoesNotExist:
            raise CustomerError(
                f"User {user.pk} has no StripeCustomer record. "
                "Create one with CustomerManager.get_or_create_customer() first."
            )

        session = self._subscription_service.create_billing_portal_session(
            customer_id=sc.stripe_customer_id,
            return_url=return_url,
        )
        return session["url"]

    # ──────────────────────────────────────────────────────────────────────────
    # Lookups
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def get_subscription_by_id(stripe_subscription_id: str) -> StripeSubscription | None:
        return StripeSubscription.objects.filter(
            stripe_subscription_id=stripe_subscription_id
        ).first()

    @staticmethod
    def get_active_subscription_for_user(user) -> StripeSubscription | None:
        return (
            StripeSubscription.objects.filter(
                user=user,
                status__in=[
                    SubscriptionStatus.ACTIVE.value,
                    SubscriptionStatus.TRIALING.value,
                ],
            )
            .order_by("-created_at")
            .first()
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Private
    # ──────────────────────────────────────────────────────────────────────────

    def _get_or_create_stripe_customer(self, user, auto_create: bool) -> StripeCustomer:
        try:
            return StripeCustomer.objects.get(user=user)
        except StripeCustomer.DoesNotExist:
            if not auto_create:
                raise CustomerError(
                    f"User {user.pk} has no StripeCustomer record. "
                    "Set auto_create_customer=True or create one first."
                )
            email = getattr(user, "email", None)
            name = (
                user.get_full_name()
                if hasattr(user, "get_full_name")
                else str(user)
            )
            customer_data = self._customer_service.create_customer(
                email=email,
                name=name,
                metadata={"user_id": str(user.pk)},
            )
            return StripeCustomer.objects.create(
                user=user,
                stripe_customer_id=customer_data["id"],
                email=email,
                name=name,
                raw_response=customer_data,
            )

    def _resolve_subscription(self, user, subscription_id: str) -> StripeSubscription:
        if subscription_id:
            sub = StripeSubscription.objects.filter(
                stripe_subscription_id=subscription_id
            ).first()
            if not sub:
                raise SubscriptionNotFoundError(
                    f"Subscription '{subscription_id}' not found."
                )
            return sub
        if user:
            sub = self.get_active_subscription_for_user(user)
            if not sub:
                sub = (
                    StripeSubscription.objects.filter(user=user)
                    .order_by("-created_at")
                    .first()
                )
            if not sub:
                raise SubscriptionNotFoundError(
                    f"No subscription found for user {user.pk}."
                )
            return sub
        raise SubscriptionError("Either user or subscription_id must be provided.")

    @staticmethod
    def _ts(unix_timestamp) -> timezone.datetime | None:
        """Convert a Unix timestamp int to a timezone-aware datetime, or None."""
        if unix_timestamp is None:
            return None
        from datetime import datetime, timezone as dt_tz
        return datetime.fromtimestamp(unix_timestamp, tz=dt_tz.utc)
