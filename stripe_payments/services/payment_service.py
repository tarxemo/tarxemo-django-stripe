"""
Low-level Stripe service: PaymentIntent and Checkout Session operations.
"""
import logging
import stripe
from decimal import Decimal

from ..constants import (
    STRIPE_API_VERSION,
    ZERO_DECIMAL_CURRENCIES,
    DEFAULT_TIMEOUT,
    MAX_RETRIES,
)
from ..exceptions import (
    ConfigurationError,
    PaymentError,
    PaymentDeclinedError,
    PaymentRequiresActionError,
    CheckoutSessionError,
    ValidationError,
    InvalidAmountError,
    InvalidCurrencyError,
    DuplicateOrderReferenceError,
    APIError,
)
from ..utils import get_stripe_api_key, amount_to_stripe_units

logger = logging.getLogger("stripe_payments.payment_service")


class PaymentService:
    """
    Low-level service that wraps the Stripe PaymentIntent and Checkout
    Session APIs.  Use PaymentManager for the high-level, database-aware API.
    """

    def __init__(self):
        api_key = get_stripe_api_key()
        stripe.api_key = api_key
        stripe.api_version = STRIPE_API_VERSION

    # ──────────────────────────────────────────────────────────────────────────
    # PaymentIntent
    # ──────────────────────────────────────────────────────────────────────────

    def create_payment_intent(
        self,
        amount: Decimal,
        currency: str,
        order_reference: str,
        *,
        customer_id: str = None,
        payment_method_types: list = None,
        description: str = None,
        metadata: dict = None,
        capture_method: str = "automatic",
        confirm: bool = False,
        payment_method_id: str = None,
        return_url: str = None,
        receipt_email: str = None,
        statement_descriptor: str = None,
    ) -> dict:
        """
        Create a Stripe PaymentIntent.

        Args:
            amount: Amount in major currency units (e.g. Decimal('9.99')).
            currency: ISO-4217 currency code (e.g. 'usd').
            order_reference: Your unique order ID — stored in Stripe metadata.
            customer_id: Stripe Customer ID to associate (optional).
            payment_method_types: List of accepted methods, defaults to ['card'].
            description: Human-readable charge description.
            metadata: Extra key-value pairs stored on the Stripe object.
            capture_method: 'automatic' | 'manual'.
            confirm: If True, confirm immediately (requires payment_method_id).
            payment_method_id: Stripe PaymentMethod ID to confirm with.
            return_url: URL to redirect after 3DS authentication.
            receipt_email: Customer email for Stripe receipt.
            statement_descriptor: Appears on customer's bank statement (22 chars max).

        Returns:
            Raw Stripe PaymentIntent dict.

        Raises:
            InvalidAmountError, InvalidCurrencyError, PaymentDeclinedError,
            PaymentRequiresActionError, APIError, PaymentError
        """
        self._validate_amount(amount)
        self._validate_currency(currency)

        stripe_amount = amount_to_stripe_units(amount, currency)

        params = {
            "amount": stripe_amount,
            "currency": currency.lower(),
            "capture_method": capture_method,
            "metadata": {
                "order_reference": order_reference,
                **(metadata or {}),
            },
        }

        if payment_method_types:
            params["payment_method_types"] = payment_method_types
        else:
            params["automatic_payment_methods"] = {"enabled": True}

        if customer_id:
            params["customer"] = customer_id
        if description:
            params["description"] = description
        if receipt_email:
            params["receipt_email"] = receipt_email
        if statement_descriptor:
            params["statement_descriptor"] = statement_descriptor[:22]
        if confirm:
            params["confirm"] = True
            if payment_method_id:
                params["payment_method"] = payment_method_id
            if return_url:
                params["return_url"] = return_url

        try:
            intent = stripe.PaymentIntent.create(**params)
            logger.info(
                "PaymentIntent created: %s for order %s",
                intent["id"],
                order_reference,
            )
            return dict(intent)
        except stripe.error.CardError as e:
            raise PaymentDeclinedError(
                message=e.user_message or str(e),
                error_code=e.code,
                stripe_error=e,
            )
        except stripe.error.InvalidRequestError as e:
            raise ValidationError(
                message=str(e.user_message or e),
                error_code=e.code,
                stripe_error=e,
            )
        except stripe.error.AuthenticationError as e:
            raise ConfigurationError(
                message="Stripe API key is invalid or not set.",
                stripe_error=e,
            )
        except stripe.error.StripeError as e:
            raise APIError(
                message=f"Stripe API error: {e}",
                stripe_error=e,
            )

    def retrieve_payment_intent(self, payment_intent_id: str) -> dict:
        """Fetch the latest state of a PaymentIntent from Stripe."""
        try:
            return dict(stripe.PaymentIntent.retrieve(payment_intent_id))
        except stripe.error.InvalidRequestError as e:
            raise PaymentError(
                message=f"PaymentIntent {payment_intent_id!r} not found on Stripe.",
                stripe_error=e,
            )
        except stripe.error.StripeError as e:
            raise APIError(message=str(e), stripe_error=e)

    def cancel_payment_intent(self, payment_intent_id: str, reason: str = None) -> dict:
        """Cancel a PaymentIntent that has not yet been captured."""
        try:
            params = {}
            if reason:
                params["cancellation_reason"] = reason
            return dict(stripe.PaymentIntent.cancel(payment_intent_id, **params))
        except stripe.error.InvalidRequestError as e:
            raise PaymentError(message=str(e), stripe_error=e)
        except stripe.error.StripeError as e:
            raise APIError(message=str(e), stripe_error=e)

    def capture_payment_intent(self, payment_intent_id: str, amount: Decimal = None, currency: str = None) -> dict:
        """Capture a PaymentIntent that was created with capture_method='manual'."""
        try:
            params = {}
            if amount is not None and currency is not None:
                params["amount_to_capture"] = amount_to_stripe_units(amount, currency)
            return dict(stripe.PaymentIntent.capture(payment_intent_id, **params))
        except stripe.error.StripeError as e:
            raise APIError(message=str(e), stripe_error=e)

    # ──────────────────────────────────────────────────────────────────────────
    # Checkout Session
    # ──────────────────────────────────────────────────────────────────────────

    def create_checkout_session(
        self,
        line_items: list,
        success_url: str,
        cancel_url: str,
        order_reference: str,
        *,
        mode: str = "payment",
        currency: str = "usd",
        customer_id: str = None,
        customer_email: str = None,
        payment_method_types: list = None,
        metadata: dict = None,
        allow_promotion_codes: bool = False,
        billing_address_collection: str = "auto",
        expires_after_seconds: int = 1800,
        locale: str = "auto",
    ) -> dict:
        """
        Create a Stripe Checkout Session (hosted payment page).

        Args:
            line_items: List of dicts with 'price' (or 'price_data') and 'quantity'.
            success_url: URL to redirect after successful payment (include {CHECKOUT_SESSION_ID}).
            cancel_url: URL to redirect when customer cancels.
            order_reference: Your unique order ID.
            mode: 'payment' | 'subscription' | 'setup'.
            currency: ISO-4217 currency (only needed with price_data).
            customer_id: Stripe Customer ID (optional).
            customer_email: Pre-fill checkout email (optional).
            payment_method_types: ['card', 'sepa_debit', ...] — defaults to Stripe automatic methods.
            metadata: Extra key-value pairs.
            allow_promotion_codes: Whether to show promo code field.
            billing_address_collection: 'auto' | 'required'.
            expires_after_seconds: Session expiry (min 1800 — 30 min).
            locale: Checkout page locale (e.g. 'en', 'de', 'fr').

        Returns:
            Raw Stripe Checkout Session dict (contains .url for redirect).
        """
        params = {
            "line_items": line_items,
            "mode": mode,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "allow_promotion_codes": allow_promotion_codes,
            "billing_address_collection": billing_address_collection,
            "locale": locale,
            "metadata": {
                "order_reference": order_reference,
                **(metadata or {}),
            },
        }

        if payment_method_types:
            params["payment_method_types"] = payment_method_types

        if customer_id:
            params["customer"] = customer_id
        elif customer_email:
            params["customer_email"] = customer_email

        # expires_at must be at least 30 minutes from now
        import time
        params["expires_at"] = int(time.time()) + max(expires_after_seconds, 1800)

        try:
            session = stripe.checkout.Session.create(**params)
            logger.info(
                "Checkout Session created: %s for order %s",
                session["id"],
                order_reference,
            )
            return dict(session)
        except stripe.error.InvalidRequestError as e:
            raise CheckoutSessionError(message=str(e.user_message or e), stripe_error=e)
        except stripe.error.StripeError as e:
            raise APIError(message=str(e), stripe_error=e)

    def retrieve_checkout_session(self, session_id: str) -> dict:
        """Fetch a Checkout Session from Stripe."""
        try:
            return dict(stripe.checkout.Session.retrieve(session_id))
        except stripe.error.InvalidRequestError as e:
            raise CheckoutSessionError(
                message=f"Checkout Session {session_id!r} not found.",
                stripe_error=e,
            )
        except stripe.error.StripeError as e:
            raise APIError(message=str(e), stripe_error=e)

    def expire_checkout_session(self, session_id: str) -> dict:
        """Manually expire a Checkout Session."""
        try:
            return dict(stripe.checkout.Session.expire(session_id))
        except stripe.error.StripeError as e:
            raise APIError(message=str(e), stripe_error=e)

    # ──────────────────────────────────────────────────────────────────────────
    # Internal validators
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_amount(amount: Decimal):
        try:
            amount = Decimal(str(amount))
        except Exception:
            raise InvalidAmountError(f"Amount must be a valid number, got: {amount!r}")
        if amount <= Decimal("0"):
            raise InvalidAmountError(f"Amount must be positive, got: {amount}")

    @staticmethod
    def _validate_currency(currency: str):
        if not currency or len(currency) != 3 or not currency.isalpha():
            raise InvalidCurrencyError(
                f"Currency must be a 3-letter ISO code (e.g. 'usd'), got: {currency!r}"
            )
