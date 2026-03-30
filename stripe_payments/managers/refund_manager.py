"""
High-level RefundManager — database-aware, signal-emitting.
"""
import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from ..services.refund_service import RefundService
from ..models import StripeRefundTransaction, StripePaymentTransaction
from ..constants import RefundStatus
from ..exceptions import (
    PaymentError,
    RefundError,
    AlreadyRefundedError,
    RefundAmountExceedsChargeError,
    ValidationError,
)
from ..signals import refund_status_changed, refund_created, refund_succeeded, refund_failed
from ..utils import amount_from_stripe_units

logger = logging.getLogger("stripe_payments.refund_manager")


class RefundManager:
    """
    High-level manager for Stripe refund operations.

    Usage:
        from stripe_payments.managers.refund_manager import RefundManager

        mgr = RefundManager()
        refund = mgr.create_refund(
            order_reference='ORDER-001',
            amount=Decimal('5.00'),   # partial refund — omit for full
            reason='requested_by_customer',
            initiated_by=request.user,
        )
    """

    VALID_REASONS = {"duplicate", "fraudulent", "requested_by_customer"}

    def __init__(self):
        self._refund_service = RefundService()

    def create_refund(
        self,
        order_reference: str,
        amount: Decimal = None,
        reason: str = "requested_by_customer",
        *,
        metadata: dict = None,
        initiated_by=None,
        refund_application_fee: bool = False,
        reverse_transfer: bool = False,
    ) -> StripeRefundTransaction:
        """
        Create a Stripe Refund and persist the database record.

        Args:
            order_reference: The original payment's order reference.
            amount: Amount to refund in major units. If None, refunds the full amount.
            reason: 'duplicate' | 'fraudulent' | 'requested_by_customer'.
            metadata: Key-value pairs stored on the Stripe Refund object.
            initiated_by: Django user who authorised this refund (audit trail).
            refund_application_fee: Whether to refund Stripe's application fee.
            reverse_transfer: Whether to reverse platform transfer.

        Returns:
            StripeRefundTransaction instance.

        Raises:
            PaymentError: Original payment not found or has no PaymentIntent.
            AlreadyRefundedError: Payment already fully refunded.
            RefundAmountExceedsChargeError: Requested amount exceeds original charge.
            RefundError: General refund failure.
        """
        # Validate reason
        if reason and reason not in self.VALID_REASONS:
            raise ValidationError(
                f"Invalid refund reason '{reason}'. "
                f"Must be one of: {self.VALID_REASONS}"
            )

        # Find original payment
        payment = StripePaymentTransaction.objects.filter(
            order_reference=order_reference
        ).first()
        if payment is None:
            raise PaymentError(
                f"No payment found with order_reference='{order_reference}'."
            )

        if not payment.stripe_payment_intent_id:
            raise RefundError(
                f"Payment '{order_reference}' has no associated PaymentIntent — "
                "only PaymentIntent-based payments can be refunded via this manager."
            )

        if not payment.is_successful():
            raise RefundError(
                f"Payment '{order_reference}' has status '{payment.status}' "
                "and cannot be refunded. Only succeeded payments are refundable."
            )

        # Validate refund amount against original
        if amount is not None:
            total_already_refunded = self._get_total_refunded(payment)
            max_refundable = payment.amount_received - total_already_refunded
            if Decimal(str(amount)) > max_refundable:
                raise RefundAmountExceedsChargeError(
                    f"Requested refund ({amount}) exceeds refundable amount ({max_refundable})."
                )

        # Call Stripe API
        refund_data = self._refund_service.create_refund(
            payment_intent_id=payment.stripe_payment_intent_id,
            amount=amount,
            currency=payment.currency,
            reason=reason,
            metadata=metadata,
            refund_application_fee=refund_application_fee,
            reverse_transfer=reverse_transfer,
        )

        # Persist
        refund_amount = amount_from_stripe_units(
            refund_data.get("amount", 0), payment.currency
        )
        with transaction.atomic():
            refund = StripeRefundTransaction.objects.create(
                stripe_refund_id=refund_data["id"],
                payment_transaction=payment,
                order_reference=order_reference,
                status=refund_data.get("status", RefundStatus.PENDING.value),
                amount=refund_amount,
                currency=payment.currency,
                reason=reason,
                metadata=metadata or {},
                raw_response=refund_data,
                initiated_by=initiated_by,
            )

        # Signals
        refund_status_changed.send(
            sender=StripeRefundTransaction,
            instance=refund,
            new_status=refund.status,
            old_status=None,
            created=True,
        )
        refund_created.send(
            sender=StripeRefundTransaction,
            instance=refund,
            stripe_event=refund_data,
        )
        if refund.is_successful():
            refund_succeeded.send(
                sender=StripeRefundTransaction,
                instance=refund,
                stripe_event=refund_data,
            )

        logger.info(
            "RefundManager: Created refund %s for order %s (%s %s)",
            refund_data["id"],
            order_reference,
            payment.currency.upper(),
            refund_amount,
        )
        return refund

    def sync_refund_status(self, stripe_refund_id: str) -> StripeRefundTransaction:
        """
        Pull the latest status of a Refund from Stripe and update the local record.

        Args:
            stripe_refund_id: Stripe Refund ID (re_…).

        Returns:
            Updated StripeRefundTransaction.
        """
        refund = StripeRefundTransaction.objects.filter(
            stripe_refund_id=stripe_refund_id
        ).first()
        if refund is None:
            raise RefundError(
                f"Refund '{stripe_refund_id}' not found in local database."
            )

        old_status = refund.status
        data = self._refund_service.retrieve_refund(stripe_refund_id)
        new_status = data.get("status", old_status)

        with transaction.atomic():
            refund.status = new_status
            if new_status == RefundStatus.SUCCEEDED.value:
                refund.completed_at = refund.completed_at or timezone.now()
            elif new_status == RefundStatus.FAILED.value:
                refund.failure_reason = data.get("failure_reason")
            refund.raw_response = data
            refund.save()

        if new_status != old_status:
            refund_status_changed.send(
                sender=StripeRefundTransaction,
                instance=refund,
                new_status=new_status,
                old_status=old_status,
                created=False,
            )
            if new_status == RefundStatus.SUCCEEDED.value:
                refund_succeeded.send(
                    sender=StripeRefundTransaction,
                    instance=refund,
                    stripe_event=data,
                )
            elif new_status == RefundStatus.FAILED.value:
                refund_failed.send(
                    sender=StripeRefundTransaction,
                    instance=refund,
                    stripe_event=data,
                )

        return refund

    # ── Lookups ───────────────────────────────────────────────────────────────

    @staticmethod
    def get_refund_by_stripe_id(stripe_refund_id: str) -> StripeRefundTransaction | None:
        return StripeRefundTransaction.objects.filter(
            stripe_refund_id=stripe_refund_id
        ).first()

    @staticmethod
    def get_refunds_for_order(order_reference: str):
        return StripeRefundTransaction.objects.filter(
            order_reference=order_reference
        ).order_by("-created_at")

    # ── Private ───────────────────────────────────────────────────────────────

    @staticmethod
    def _get_total_refunded(payment: StripePaymentTransaction) -> Decimal:
        from django.db.models import Sum
        result = StripeRefundTransaction.objects.filter(
            payment_transaction=payment,
            status__in=[RefundStatus.SUCCEEDED.value, RefundStatus.PENDING.value],
        ).aggregate(total=Sum("amount"))
        return result["total"] or Decimal("0.00")
