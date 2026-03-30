"""
High-level PaymentManager — database-aware, signal-emitting.
Mirrors PaymentManager in tarxemo-django-clickpesa.
"""
import logging
import uuid
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from ..services.payment_service import PaymentService
from ..services.customer_service import CustomerService
from ..models import StripePaymentTransaction, StripeCustomer
from ..constants import PaymentIntentStatus, CheckoutSessionStatus, Currency
from ..exceptions import (
    DuplicateOrderReferenceError,
    PaymentError,
    PaymentRequiresActionError,
    ValidationError,
)
from ..signals import (
    payment_status_changed,
    payment_succeeded,
    payment_failed,
    payment_canceled,
    payment_processing,
    payment_requires_action,
    checkout_session_completed,
    checkout_session_expired,
)
from ..utils import amount_from_stripe_units

logger = logging.getLogger("stripe_payments.payment_manager")


class PaymentManager:
    """
    High-level manager for Stripe payment operations.

    Handles:
      - Creating PaymentIntents (API + DB record + signals)
      - Creating Checkout Sessions (API + DB record + signals)
      - Polling / syncing payment status from Stripe
      - Retrieving transactions by reference or ID

    Usage:
        from stripe_payments.managers.payment_manager import PaymentManager

        mgr = PaymentManager()

        # --- PaymentIntent flow (for custom frontend) ---
        payment = mgr.create_payment(
            amount=Decimal('29.99'),
            currency='usd',
            order_reference='ORDER-001',
            user=request.user,
        )
        client_secret = payment.client_secret   # pass to Stripe.js

        # --- Checkout Session flow (redirect) ---
        payment = mgr.create_checkout_session(
            line_items=[{'price': 'price_xxx', 'quantity': 1}],
            success_url='https://example.com/success?ref={CHECKOUT_SESSION_ID}',
            cancel_url='https://example.com/cancel',
            order_reference='ORDER-002',
        )
        redirect(payment.checkout_url)
    """

    def __init__(self):
        self._payment_service = PaymentService()

    # ──────────────────────────────────────────────────────────────────────────
    # PaymentIntent flow
    # ──────────────────────────────────────────────────────────────────────────

    def create_payment(
        self,
        amount: Decimal,
        currency: str,
        order_reference: str,
        *,
        user=None,
        description: str = None,
        metadata: dict = None,
        payment_method_types: list = None,
        capture_method: str = "automatic",
        statement_descriptor: str = None,
        receipt_email: str = None,
    ) -> StripePaymentTransaction:
        """
        Create a Stripe PaymentIntent and persist the database record.

        Args:
            amount: Decimal amount in major units (e.g. Decimal('9.99')).
            currency: ISO-4217 code (e.g. 'usd', 'eur', 'tzs').
            order_reference: Your unique reference (max 200 chars).
            user: Optional Django user to associate.
            description: Charge description visible on Stripe dashboard.
            metadata: Key-value dict stored on the Stripe object.
            payment_method_types: Accepted payment methods (default: automatic).
            capture_method: 'automatic' | 'manual' (authorize then capture).
            statement_descriptor: Text on customer's bank statement (22 chars).
            receipt_email: Customer email for Stripe-sent receipt.

        Returns:
            StripePaymentTransaction instance (access .client_secret for frontend).

        Raises:
            DuplicateOrderReferenceError: order_reference already exists in DB.
            ValidationError: Invalid amount, currency, etc.
            PaymentError: Stripe API failure.
        """
        # Guard: unique reference
        if StripePaymentTransaction.objects.filter(
            order_reference=order_reference
        ).exists():
            raise DuplicateOrderReferenceError(
                f"Order reference '{order_reference}' already exists. "
                "Use get_payment_by_reference() to retrieve the existing record."
            )

        # Resolve Stripe customer if Django user provided
        stripe_customer_id = None
        customer_email = None
        customer_name = None
        if user:
            stripe_customer_id, customer_email, customer_name = (
                self._resolve_stripe_customer(user)
            )

        # Call Stripe API
        intent = self._payment_service.create_payment_intent(
            amount=amount,
            currency=currency,
            order_reference=order_reference,
            customer_id=stripe_customer_id,
            payment_method_types=payment_method_types,
            description=description,
            metadata=metadata,
            capture_method=capture_method,
            statement_descriptor=statement_descriptor,
            receipt_email=receipt_email or customer_email,
        )

        # Persist to DB inside an atomic block
        with transaction.atomic():
            payment = StripePaymentTransaction.objects.create(
                stripe_payment_intent_id=intent["id"],
                order_reference=order_reference,
                status=intent["status"],
                amount=amount,
                amount_received=amount_from_stripe_units(
                    intent.get("amount_received", 0), currency
                ),
                currency=currency.lower(),
                client_secret=intent.get("client_secret"),
                stripe_customer_id=stripe_customer_id,
                customer_email=customer_email,
                customer_name=customer_name,
                description=description,
                metadata=metadata or {},
                raw_response=intent,
                user=user,
            )

        # Fire signal
        payment_status_changed.send(
            sender=StripePaymentTransaction,
            instance=payment,
            new_status=payment.status,
            old_status=None,
            created=True,
        )

        logger.info(
            "PaymentManager: Created payment %s (order=%s, %s %s)",
            intent["id"],
            order_reference,
            currency.upper(),
            amount,
        )
        return payment

    # ──────────────────────────────────────────────────────────────────────────
    # Checkout Session flow
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
        user=None,
        metadata: dict = None,
        payment_method_types: list = None,
        allow_promotion_codes: bool = False,
        billing_address_collection: str = "auto",
        expires_after_seconds: int = 1800,
        locale: str = "auto",
    ) -> StripePaymentTransaction:
        """
        Create a Stripe Checkout Session and persist the database record.

        The returned transaction has .checkout_url — redirect the customer there.

        Args:
            line_items: List of {'price': 'price_xxx', 'quantity': 1} dicts.
                        Or use price_data for dynamic pricing.
            success_url: Redirect URL after success (can include {CHECKOUT_SESSION_ID}).
            cancel_url: Redirect URL when customer cancels.
            order_reference: Your unique order ID.
            mode: 'payment' | 'subscription' | 'setup'.
            currency: Default currency (for price_data line items).
            user: Optional Django user.
            metadata: Extra data stored on Stripe.
            allow_promotion_codes: Show promo code field.
            billing_address_collection: 'auto' | 'required'.
            expires_after_seconds: Session TTL in seconds (min 1800).
            locale: Checkout page locale.

        Returns:
            StripePaymentTransaction instance with .checkout_url set.
        """
        if StripePaymentTransaction.objects.filter(
            order_reference=order_reference
        ).exists():
            raise DuplicateOrderReferenceError(
                f"Order reference '{order_reference}' already exists."
            )

        stripe_customer_id = None
        customer_email = None
        customer_name = None
        if user:
            stripe_customer_id, customer_email, customer_name = (
                self._resolve_stripe_customer(user)
            )

        session = self._payment_service.create_checkout_session(
            line_items=line_items,
            success_url=success_url,
            cancel_url=cancel_url,
            order_reference=order_reference,
            mode=mode,
            currency=currency,
            customer_id=stripe_customer_id,
            customer_email=customer_email if not stripe_customer_id else None,
            payment_method_types=payment_method_types,
            metadata=metadata,
            allow_promotion_codes=allow_promotion_codes,
            billing_address_collection=billing_address_collection,
            expires_after_seconds=expires_after_seconds,
            locale=locale,
        )

        # Derive amount from line items if possible
        amount = self._extract_session_amount(session, currency)
        payment_intent_id = session.get("payment_intent")
        client_secret = None
        if payment_intent_id and isinstance(payment_intent_id, str):
            # Expand the PI to get client_secret in subscription mode
            pi_data = self._payment_service.retrieve_payment_intent(payment_intent_id)
            client_secret = pi_data.get("client_secret")

        with transaction.atomic():
            payment = StripePaymentTransaction.objects.create(
                stripe_checkout_session_id=session["id"],
                stripe_payment_intent_id=payment_intent_id if isinstance(payment_intent_id, str) else None,
                order_reference=order_reference,
                status=PaymentIntentStatus.REQUIRES_PAYMENT_METHOD.value,
                checkout_status=session.get("status", CheckoutSessionStatus.OPEN.value),
                amount=amount,
                currency=currency.lower(),
                checkout_url=session.get("url"),
                client_secret=client_secret,
                stripe_customer_id=stripe_customer_id,
                customer_email=customer_email,
                customer_name=customer_name,
                metadata=metadata or {},
                raw_response=session,
                user=user,
            )

        payment_status_changed.send(
            sender=StripePaymentTransaction,
            instance=payment,
            new_status=payment.status,
            old_status=None,
            created=True,
        )

        logger.info(
            "PaymentManager: Checkout Session %s created (order=%s), URL=%s",
            session["id"],
            order_reference,
            session.get("url"),
        )
        return payment

    # ──────────────────────────────────────────────────────────────────────────
    # Status sync
    # ──────────────────────────────────────────────────────────────────────────

    def sync_payment_status(self, order_reference: str) -> StripePaymentTransaction:
        """
        Pull the latest status from Stripe and update the local record.
        Emits signals if status changed.

        Args:
            order_reference: Your order reference.

        Returns:
            Updated StripePaymentTransaction.

        Raises:
            PaymentError: If transaction not found locally or API call fails.
        """
        payment = self.get_payment_by_reference(order_reference)
        if payment is None:
            raise PaymentError(
                f"Payment with order_reference='{order_reference}' not found in database."
            )

        old_status = payment.status

        # Prefer PaymentIntent for status
        if payment.stripe_payment_intent_id:
            data = self._payment_service.retrieve_payment_intent(
                payment.stripe_payment_intent_id
            )
            new_status = data.get("status", old_status)
            amount_received = amount_from_stripe_units(
                data.get("amount_received", 0), payment.currency
            )
        elif payment.stripe_checkout_session_id:
            data = self._payment_service.retrieve_checkout_session(
                payment.stripe_checkout_session_id
            )
            new_status = self._map_checkout_status_to_pi_status(
                data.get("status", "open")
            )
            amount_received = payment.amount_received
        else:
            raise PaymentError("Transaction has no Stripe ID to sync from.")

        with transaction.atomic():
            payment.status = new_status
            payment.amount_received = amount_received
            if new_status == PaymentIntentStatus.SUCCEEDED.value:
                payment.completed_at = payment.completed_at or timezone.now()
                # Extract card details if available
                self._populate_card_details(payment, data)
            payment.raw_response = data
            payment.save()

        if new_status != old_status:
            payment_status_changed.send(
                sender=StripePaymentTransaction,
                instance=payment,
                new_status=new_status,
                old_status=old_status,
                created=False,
            )
            self._emit_convenience_signal(payment, new_status, data)

        logger.info(
            "PaymentManager: Synced payment %s: %s → %s",
            order_reference,
            old_status,
            new_status,
        )
        return payment

    # ──────────────────────────────────────────────────────────────────────────
    # Lookups
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def get_payment_by_reference(order_reference: str) -> StripePaymentTransaction | None:
        """Return a payment transaction by order reference, or None."""
        return StripePaymentTransaction.objects.filter(
            order_reference=order_reference
        ).first()

    @staticmethod
    def get_payment_by_intent_id(payment_intent_id: str) -> StripePaymentTransaction | None:
        """Return a payment transaction by Stripe PaymentIntent ID, or None."""
        return StripePaymentTransaction.objects.filter(
            stripe_payment_intent_id=payment_intent_id
        ).first()

    @staticmethod
    def get_payment_by_session_id(session_id: str) -> StripePaymentTransaction | None:
        """Return a payment transaction by Stripe Checkout Session ID, or None."""
        return StripePaymentTransaction.objects.filter(
            stripe_checkout_session_id=session_id
        ).first()

    # ──────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_stripe_customer(user) -> tuple:
        """
        Resolve the Stripe Customer ID for a Django user.
        Returns (stripe_customer_id, email, name).
        """
        try:
            sc = StripeCustomer.objects.get(user=user)
            return sc.stripe_customer_id, sc.email, sc.name
        except StripeCustomer.DoesNotExist:
            email = getattr(user, "email", None)
            name = (
                user.get_full_name()
                if hasattr(user, "get_full_name")
                else str(user)
            )
            return None, email, name

    @staticmethod
    def _extract_session_amount(session: dict, currency: str) -> Decimal:
        """Try to extract the total amount from a Checkout Session."""
        try:
            total = session.get("amount_total")
            if total:
                return amount_from_stripe_units(total, currency)
        except Exception:
            pass
        return Decimal("0.00")

    @staticmethod
    def _map_checkout_status_to_pi_status(checkout_status: str) -> str:
        mapping = {
            "open": PaymentIntentStatus.REQUIRES_PAYMENT_METHOD.value,
            "complete": PaymentIntentStatus.SUCCEEDED.value,
            "expired": PaymentIntentStatus.CANCELED.value,
        }
        return mapping.get(checkout_status, PaymentIntentStatus.REQUIRES_PAYMENT_METHOD.value)

    @staticmethod
    def _populate_card_details(payment: StripePaymentTransaction, data: dict):
        """Populate card info from PaymentIntent or Charge data."""
        charges = data.get("charges", {}).get("data", [])
        if charges:
            pm_details = charges[0].get("payment_method_details", {})
            card = pm_details.get("card", {})
            if card:
                payment.card_brand = card.get("brand")
                payment.card_last4 = card.get("last4")
                payment.card_exp_month = card.get("exp_month")
                payment.card_exp_year = card.get("exp_year")
                payment.card_country = card.get("country")
                payment.payment_method_type = pm_details.get("type")

    @staticmethod
    def _emit_convenience_signal(payment, new_status: str, data: dict):
        """Emit a specific convenience signal based on the new status."""
        if new_status == PaymentIntentStatus.SUCCEEDED.value:
            payment_succeeded.send(
                sender=StripePaymentTransaction,
                instance=payment,
                stripe_event=data,
            )
        elif new_status == PaymentIntentStatus.CANCELED.value:
            payment_canceled.send(
                sender=StripePaymentTransaction,
                instance=payment,
                stripe_event=data,
            )
        elif new_status == PaymentIntentStatus.PROCESSING.value:
            payment_processing.send(
                sender=StripePaymentTransaction,
                instance=payment,
                stripe_event=data,
            )
        elif new_status == PaymentIntentStatus.REQUIRES_ACTION.value:
            payment_requires_action.send(
                sender=StripePaymentTransaction,
                instance=payment,
                stripe_event=data,
                client_secret=payment.client_secret,
            )
