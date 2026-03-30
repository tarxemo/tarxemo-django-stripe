from django.apps import AppConfig


class StripePaymentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'stripe_payments'
    verbose_name = 'Stripe Payments'

    def ready(self):
        """
        Import signals and handlers here to ensure they are registered.
        """
        import stripe_payments.handlers
