import logging

from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views import View

from stripe_payments.services.webhook_service import WebhookService
from stripe_payments.managers.payment_manager import PaymentManager
from stripe_payments.managers.refund_manager import RefundManager
from stripe_payments.managers.subscription_manager import SubscriptionManager
from stripe_payments.models import StripeWebhookEvent
from stripe_payments.constants import WebhookEventType

logger = logging.getLogger("stripe_payments.views")


@method_decorator(csrf_exempt, name='dispatch')
class StripeWebhookView(View):
    """
    Stripe Webhook Endpoint.

    Processes incoming events and delegates them to the appropriate managers.
    Ensures idempotency by logging every event in StripeWebhookEvent.
    """

    def post(self, request, *args, **kwargs):
        payload = request.body
        sig_header = request.headers.get('Stripe-Signature')

        if not sig_header:
            return HttpResponse("No Stripe-Signature header provided.", status=400)

        # 1. Verify and reconstruct the event
        svc = WebhookService()
        try:
            event = svc.construct_event(payload, sig_header)
        except Exception as e:
            logger.warning("Webhook verification failed: %s", str(e))
            return HttpResponse(str(e), status=400)

        event_id = event['id']
        event_type = event['type']

        # 2. Idempotency check: Have we seen this event before?
        db_event, created = StripeWebhookEvent.objects.get_or_create(
            stripe_event_id=event_id,
            defaults={
                'event_type': event_type,
                'payload': event.to_dict(),
                'processing_status': 'RECEIVED'
            }
        )

        if not created and db_event.processing_status == 'PROCESSED':
            logger.debug("Webhook already processed: %s", event_id)
            return HttpResponse("OK")

        # 3. Process the event
        db_event.processing_status = 'PROCESSING'
        db_event.save(update_fields=['processing_status'])

        try:
            self.process_event(event)
            db_event.mark_processed()
        except Exception as e:
            logger.exception("Error processing webhook %s (%s): %s", event_id, event_type, str(e))
            db_event.mark_failed(str(e))
            # Generally, we return 200 to Stripe unless we WANT a retry
            # If the error is transient, we might return 500
            return HttpResponse("Error during processing.", status=500)

        return HttpResponse("OK")

    def process_event(self, event):
        """
        Main routing logic for Stripe events.
        """
        event_type = event['type']
        data_object = event['data']['object']

        # --- Payment Intent Events ---
        if event_type.startswith('payment_intent.'):
            # For any PI change, sync the status in DB
            ref = data_object.get('metadata', {}).get('order_reference')
            if ref:
                PaymentManager().sync_payment_status(ref)
            else:
                logger.warning("PaymentIntent event without order_reference in metadata: %s", event['id'])

        # --- Checkout Session Events ---
        elif event_type == WebhookEventType.CHECKOUT_SESSION_COMPLETED:
            ref = data_object.get('metadata', {}).get('order_reference')
            if ref:
                PaymentManager().sync_payment_status(ref)

        # --- Refund Events ---
        elif event_type.startswith('charge.refunded') or event_type.startswith('refund.'):
            refund_id = data_object.get('id')
            if refund_id and refund_id.startswith('re_'):
                RefundManager().sync_refund_status(refund_id)

        # --- Subscription Events ---
        elif event_type.startswith('customer.subscription.'):
            sub_id = data_object.get('id')
            if sub_id:
                SubscriptionManager().sync_subscription_status(sub_id)

        # --- Invoice Events ---
        elif event_type.startswith('invoice.'):
            # We mostly care about subscription invoices
            sub_id = data_object.get('subscription')
            if sub_id:
                SubscriptionManager().sync_subscription_status(sub_id)

        else:
            logger.debug("Unhandled Stripe event type: %s", event_type)
