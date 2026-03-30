"""
Low-level Stripe service: Refund operations.
"""
import logging
import stripe
from decimal import Decimal

from ..constants import STRIPE_API_VERSION
from ..exceptions import (
    RefundError,
    RefundNotFoundError,
    AlreadyRefundedError,
    RefundAmountExceedsChargeError,
    APIError,
    ValidationError,
)
from ..utils import get_stripe_api_key, amount_to_stripe_units

logger = logging.getLogger("stripe_payments.refund_service")


class RefundService:
    """
    Low-level service wrapping the Stripe Refunds API.
    Use RefundManager for the high-level, database-aware API.
    """

    def __init__(self):
        stripe.api_key = get_stripe_api_key()
        stripe.api_version = STRIPE_API_VERSION

    def create_refund(
        self,
        payment_intent_id: str,
        amount: Decimal = None,
        currency: str = "usd",
        reason: str = None,
        metadata: dict = None,
        refund_application_fee: bool = False,
        reverse_transfer: bool = False,
    ) -> dict:
        """
        Create a Stripe Refund.

        Args:
            payment_intent_id: Stripe PaymentIntent ID (pi_…).
            amount: Amount to refund in major units. If None, refunds the full amount.
            currency: Currency code — used only for unit conversion.
            reason: 'duplicate' | 'fraudulent' | 'requested_by_customer'.
            metadata: Extra key-value pairs stored on the Refund object.
            refund_application_fee: Whether to refund the Stripe application fee.
            reverse_transfer: Whether to reverse the transfer to the destination account.

        Returns:
            Raw Stripe Refund dict.
        """
        if not payment_intent_id:
            raise ValidationError("payment_intent_id is required.")

        params = {
            "payment_intent": payment_intent_id,
            "metadata": metadata or {},
        }

        if amount is not None:
            params["amount"] = amount_to_stripe_units(Decimal(str(amount)), currency)

        if reason:
            params["reason"] = reason

        if refund_application_fee:
            params["refund_application_fee"] = True

        if reverse_transfer:
            params["reverse_transfer"] = True

        try:
            refund = stripe.Refund.create(**params)
            logger.info(
                "Refund created: %s for PaymentIntent %s (amount=%s %s)",
                refund["id"],
                payment_intent_id,
                amount,
                currency.upper(),
            )
            return dict(refund)
        except stripe.error.InvalidRequestError as e:
            msg = str(e.user_message or e)
            if "already been refunded" in msg.lower():
                raise AlreadyRefundedError(message=msg, stripe_error=e)
            if "greater than" in msg.lower() or "exceeds" in msg.lower():
                raise RefundAmountExceedsChargeError(message=msg, stripe_error=e)
            raise RefundError(message=msg, stripe_error=e)
        except stripe.error.StripeError as e:
            raise APIError(message=str(e), stripe_error=e)

    def retrieve_refund(self, refund_id: str) -> dict:
        """Fetch a Refund from Stripe."""
        try:
            return dict(stripe.Refund.retrieve(refund_id))
        except stripe.error.InvalidRequestError as e:
            raise RefundNotFoundError(
                message=f"Refund {refund_id!r} not found on Stripe.",
                stripe_error=e,
            )
        except stripe.error.StripeError as e:
            raise APIError(message=str(e), stripe_error=e)

    def cancel_refund(self, refund_id: str) -> dict:
        """Cancel a pending refund (only possible before it's processed)."""
        try:
            return dict(stripe.Refund.cancel(refund_id))
        except stripe.error.InvalidRequestError as e:
            raise RefundError(
                message=f"Cannot cancel refund {refund_id!r}: {e}",
                stripe_error=e,
            )
        except stripe.error.StripeError as e:
            raise APIError(message=str(e), stripe_error=e)
