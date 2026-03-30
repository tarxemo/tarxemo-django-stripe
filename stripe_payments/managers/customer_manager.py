"""
High-level CustomerManager — wraps CustomerService with DB persistence.
"""
import logging

from ..services.customer_service import CustomerService
from ..models import StripeCustomer
from ..exceptions import CustomerError, CustomerNotFoundError

logger = logging.getLogger("stripe_payments.customer_manager")


class CustomerManager:
    """
    High-level manager that keeps StripeCustomer records in sync with Stripe.

    Usage:
        from stripe_payments.managers.customer_manager import CustomerManager

        mgr = CustomerManager()
        customer = mgr.get_or_create_customer(request.user)
        print(customer.stripe_customer_id)   # cus_xxx
    """

    def __init__(self):
        self._service = CustomerService()

    def get_or_create_customer(self, user, **extra_attrs) -> StripeCustomer:
        """
        Return the existing StripeCustomer for a user, or create a new one
        on Stripe and in the local database.

        Args:
            user: Django user object.
            **extra_attrs: Optional fields like phone, address (dict), metadata.

        Returns:
            StripeCustomer instance.
        """
        try:
            return StripeCustomer.objects.get(user=user)
        except StripeCustomer.DoesNotExist:
            pass

        email = getattr(user, "email", None)
        name = (
            user.get_full_name() if hasattr(user, "get_full_name") else str(user)
        )

        customer_data = self._service.create_customer(
            email=email,
            name=name or None,
            phone=extra_attrs.get("phone"),
            metadata={"user_id": str(user.pk), **(extra_attrs.get("metadata") or {})},
            address=extra_attrs.get("address"),
        )

        sc = StripeCustomer.objects.create(
            user=user,
            stripe_customer_id=customer_data["id"],
            email=email,
            name=name or None,
            raw_response=customer_data,
        )
        logger.info(
            "CustomerManager: Created Stripe Customer %s for user %s",
            sc.stripe_customer_id,
            user.pk,
        )
        return sc

    def sync_customer(self, user) -> StripeCustomer:
        """
        Pull latest Customer data from Stripe and update local record.

        Args:
            user: Django user.

        Returns:
            Updated StripeCustomer.
        """
        try:
            sc = StripeCustomer.objects.get(user=user)
        except StripeCustomer.DoesNotExist:
            raise CustomerNotFoundError(
                f"No StripeCustomer record found for user {user.pk}."
            )

        data = self._service.retrieve_customer(sc.stripe_customer_id)
        sc.email = data.get("email") or sc.email
        sc.name = data.get("name") or sc.name
        sc.raw_response = data
        sc.save(update_fields=["email", "name", "raw_response", "updated_at"])
        return sc

    def list_payment_methods(self, user, type: str = "card") -> list:
        """List saved payment methods for a user's Stripe Customer."""
        try:
            sc = StripeCustomer.objects.get(user=user)
        except StripeCustomer.DoesNotExist:
            raise CustomerNotFoundError(
                f"No StripeCustomer record found for user {user.pk}."
            )
        return self._service.list_payment_methods(sc.stripe_customer_id, type=type)
