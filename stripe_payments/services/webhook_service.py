"""
Low-level Stripe service: Webhook signature verification and event parsing.
"""
import logging
import stripe

from ..constants import STRIPE_API_VERSION
from ..exceptions import WebhookSignatureError, WebhookError, ConfigurationError
from ..utils import get_stripe_api_key, get_webhook_secret

logger = logging.getLogger("stripe_payments.webhook_service")


class WebhookService:
    """
    Handles Stripe webhook signature verification and event construction.
    Should be used in the webhook view before any business logic.
    """

    def __init__(self):
        stripe.api_key = get_stripe_api_key()
        stripe.api_version = STRIPE_API_VERSION

    def construct_event(self, payload: bytes, sig_header: str) -> stripe.Event:
        """
        Verify the Stripe webhook signature and construct the Event object.

        This MUST be called with the raw request body bytes — not the decoded
        JSON, because Stripe signs the raw bytes.

        Args:
            payload: Raw request body bytes (request.body in Django views).
            sig_header: 'Stripe-Signature' header value.

        Returns:
            A verified stripe.Event object.

        Raises:
            WebhookSignatureError: If the signature does not match.
            WebhookError: If the payload cannot be parsed.
            ConfigurationError: If the webhook secret is not configured.
        """
        webhook_secret = get_webhook_secret()

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )
            logger.debug(
                "Webhook signature verified: %s (%s)",
                event["id"],
                event["type"],
            )
            return event
        except stripe.error.SignatureVerificationError as e:
            logger.warning(
                "Webhook signature verification failed: %s",
                str(e),
            )
            raise WebhookSignatureError(
                message="Stripe webhook signature verification failed. "
                        "Ensure STRIPE_WEBHOOK_SECRET is correct and "
                        "you are passing raw request.body (not parsed JSON).",
                stripe_error=e,
            )
        except ValueError as e:
            raise WebhookError(
                message=f"Invalid webhook payload: {e}",
            )

    @staticmethod
    def get_event_data_object(event: stripe.Event) -> dict:
        """
        Extract the primary data object from a Stripe Event.

        Returns:
            The event.data.object as a plain dict.
        """
        return dict(event["data"]["object"])
