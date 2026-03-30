"""
Low-level Stripe service: Customer and Subscription operations.
"""
import logging
import stripe
from decimal import Decimal

from ..constants import STRIPE_API_VERSION
from ..exceptions import (
    CustomerError,
    CustomerNotFoundError,
    SubscriptionError,
    SubscriptionNotFoundError,
    SubscriptionAlreadyCanceledError,
    APIError,
    ValidationError,
)
from ..utils import get_stripe_api_key

logger = logging.getLogger("stripe_payments.customer_service")


class CustomerService:
    """
    Low-level service for Stripe Customer operations.
    """

    def __init__(self):
        stripe.api_key = get_stripe_api_key()
        stripe.api_version = STRIPE_API_VERSION

    def create_customer(
        self,
        email: str,
        name: str = None,
        phone: str = None,
        metadata: dict = None,
        address: dict = None,
    ) -> dict:
        """
        Create a Stripe Customer.

        Args:
            email: Customer email address.
            name: Full name.
            phone: Phone number in E.164 format.
            metadata: Key-value pairs stored on Stripe.
            address: Dict with city, country, line1, line2, postal_code, state.

        Returns:
            Raw Stripe Customer dict.
        """
        if not email:
            raise ValidationError("Customer email is required.")

        params = {"email": email, "metadata": metadata or {}}
        if name:
            params["name"] = name
        if phone:
            params["phone"] = phone
        if address:
            params["address"] = address

        try:
            customer = stripe.Customer.create(**params)
            logger.info("Stripe Customer created: %s (%s)", customer["id"], email)
            return dict(customer)
        except stripe.error.InvalidRequestError as e:
            raise CustomerError(message=str(e.user_message or e), stripe_error=e)
        except stripe.error.StripeError as e:
            raise APIError(message=str(e), stripe_error=e)

    def retrieve_customer(self, customer_id: str) -> dict:
        """Retrieve a Stripe Customer by ID."""
        try:
            return dict(stripe.Customer.retrieve(customer_id))
        except stripe.error.InvalidRequestError as e:
            raise CustomerNotFoundError(
                message=f"Customer {customer_id!r} not found on Stripe.",
                stripe_error=e,
            )
        except stripe.error.StripeError as e:
            raise APIError(message=str(e), stripe_error=e)

    def update_customer(self, customer_id: str, **kwargs) -> dict:
        """Update a Stripe Customer's attributes."""
        try:
            return dict(stripe.Customer.modify(customer_id, **kwargs))
        except stripe.error.InvalidRequestError as e:
            raise CustomerError(message=str(e.user_message or e), stripe_error=e)
        except stripe.error.StripeError as e:
            raise APIError(message=str(e), stripe_error=e)

    def delete_customer(self, customer_id: str) -> dict:
        """Delete a Stripe Customer (irreversible — use with caution)."""
        try:
            return dict(stripe.Customer.delete(customer_id))
        except stripe.error.InvalidRequestError as e:
            raise CustomerError(message=str(e.user_message or e), stripe_error=e)
        except stripe.error.StripeError as e:
            raise APIError(message=str(e), stripe_error=e)

    def list_payment_methods(self, customer_id: str, type: str = "card") -> list:
        """List saved PaymentMethods for a customer."""
        try:
            result = stripe.PaymentMethod.list(customer=customer_id, type=type)
            return [dict(pm) for pm in result.auto_paging_iter()]
        except stripe.error.StripeError as e:
            raise APIError(message=str(e), stripe_error=e)

    def attach_payment_method(self, payment_method_id: str, customer_id: str) -> dict:
        """Attach a PaymentMethod to a Customer."""
        try:
            pm = stripe.PaymentMethod.attach(payment_method_id, customer=customer_id)
            return dict(pm)
        except stripe.error.StripeError as e:
            raise CustomerError(message=str(e), stripe_error=e)

    def detach_payment_method(self, payment_method_id: str) -> dict:
        """Detach a PaymentMethod from its Customer."""
        try:
            return dict(stripe.PaymentMethod.detach(payment_method_id))
        except stripe.error.StripeError as e:
            raise CustomerError(message=str(e), stripe_error=e)


class SubscriptionService:
    """
    Low-level service for Stripe Subscription operations.
    """

    def __init__(self):
        stripe.api_key = get_stripe_api_key()
        stripe.api_version = STRIPE_API_VERSION

    def create_subscription(
        self,
        customer_id: str,
        price_id: str,
        *,
        trial_period_days: int = None,
        metadata: dict = None,
        payment_behavior: str = "default_incomplete",
        payment_settings: dict = None,
        expand: list = None,
        cancel_at_period_end: bool = False,
        coupon: str = None,
        promotion_code: str = None,
        collection_method: str = "charge_automatically",
        default_payment_method: str = None,
    ) -> dict:
        """
        Create a Stripe Subscription.

        Args:
            customer_id: Stripe Customer ID.
            price_id: Stripe Price ID (price_…).
            trial_period_days: Free trial days before first charge.
            metadata: Key-value pairs stored on Stripe.
            payment_behavior: 'default_incomplete' | 'allow_incomplete' | 'error_if_incomplete'.
            payment_settings: dict with save_default_payment_method, etc.
            expand: List of Stripe fields to expand in response.
            cancel_at_period_end: If True, cancels at end of current period.
            coupon: Stripe Coupon ID to apply.
            promotion_code: Stripe PromotionCode ID.
            collection_method: 'charge_automatically' | 'send_invoice'.
            default_payment_method: Stripe PaymentMethod ID to use for this subscription.

        Returns:
            Raw Stripe Subscription dict.
        """
        params = {
            "customer": customer_id,
            "items": [{"price": price_id}],
            "payment_behavior": payment_behavior,
            "metadata": metadata or {},
            "cancel_at_period_end": cancel_at_period_end,
            "collection_method": collection_method,
        }

        if trial_period_days:
            params["trial_period_days"] = trial_period_days
        if payment_settings:
            params["payment_settings"] = payment_settings
        if expand:
            params["expand"] = expand
        if coupon:
            params["coupon"] = coupon
        if promotion_code:
            params["promotion_code"] = promotion_code
        if default_payment_method:
            params["default_payment_method"] = default_payment_method

        try:
            sub = stripe.Subscription.create(**params)
            logger.info(
                "Subscription created: %s for customer %s (price=%s)",
                sub["id"],
                customer_id,
                price_id,
            )
            return dict(sub)
        except stripe.error.InvalidRequestError as e:
            raise SubscriptionError(message=str(e.user_message or e), stripe_error=e)
        except stripe.error.StripeError as e:
            raise APIError(message=str(e), stripe_error=e)

    def retrieve_subscription(self, subscription_id: str) -> dict:
        """Retrieve a Subscription from Stripe."""
        try:
            return dict(stripe.Subscription.retrieve(subscription_id))
        except stripe.error.InvalidRequestError as e:
            raise SubscriptionNotFoundError(
                message=f"Subscription {subscription_id!r} not found.",
                stripe_error=e,
            )
        except stripe.error.StripeError as e:
            raise APIError(message=str(e), stripe_error=e)

    def update_subscription(self, subscription_id: str, **kwargs) -> dict:
        """Update a Subscription (e.g., change price, add trial)."""
        try:
            return dict(stripe.Subscription.modify(subscription_id, **kwargs))
        except stripe.error.StripeError as e:
            raise SubscriptionError(message=str(e), stripe_error=e)

    def cancel_subscription(
        self,
        subscription_id: str,
        *,
        at_period_end: bool = True,
        prorate: bool = False,
        cancellation_details: dict = None,
    ) -> dict:
        """
        Cancel a Stripe Subscription.

        Args:
            subscription_id: Stripe Subscription ID.
            at_period_end: If True, keep active until billing period ends.
                           If False, cancel immediately.
            prorate: Whether to prorate the final invoice.
            cancellation_details: dict with 'comment', 'feedback' (optional).
        """
        try:
            if at_period_end:
                params = {"cancel_at_period_end": True}
                if cancellation_details:
                    params["cancellation_details"] = cancellation_details
                return dict(stripe.Subscription.modify(subscription_id, **params))
            else:
                return dict(stripe.Subscription.cancel(subscription_id))
        except stripe.error.InvalidRequestError as e:
            msg = str(e.user_message or e)
            if "already canceled" in msg.lower():
                raise SubscriptionAlreadyCanceledError(message=msg, stripe_error=e)
            raise SubscriptionError(message=msg, stripe_error=e)
        except stripe.error.StripeError as e:
            raise APIError(message=str(e), stripe_error=e)

    def list_invoices(self, subscription_id: str, limit: int = 10) -> list:
        """List invoices for a subscription."""
        try:
            result = stripe.Invoice.list(subscription=subscription_id, limit=limit)
            return [dict(inv) for inv in result.auto_paging_iter()]
        except stripe.error.StripeError as e:
            raise APIError(message=str(e), stripe_error=e)

    def get_upcoming_invoice(self, customer_id: str, subscription_id: str = None) -> dict:
        """Preview the next invoice for a customer / subscription."""
        try:
            params = {"customer": customer_id}
            if subscription_id:
                params["subscription"] = subscription_id
            return dict(stripe.Invoice.upcoming(**params))
        except stripe.error.InvalidRequestError as e:
            raise SubscriptionError(message=str(e.user_message or e), stripe_error=e)
        except stripe.error.StripeError as e:
            raise APIError(message=str(e), stripe_error=e)

    def create_billing_portal_session(self, customer_id: str, return_url: str) -> dict:
        """
        Create a Stripe Billing Portal session.
        Lets customers manage their subscriptions and payment methods without your UI.
        """
        try:
            session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
            )
            return dict(session)
        except stripe.error.StripeError as e:
            raise SubscriptionError(message=str(e), stripe_error=e)
