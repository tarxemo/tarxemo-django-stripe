from django.urls import path
from .views import StripeWebhookView

app_name = 'stripe_payments'

urlpatterns = [
    path('webhook/', StripeWebhookView.as_view(), name='stripe_webhook'),
]
