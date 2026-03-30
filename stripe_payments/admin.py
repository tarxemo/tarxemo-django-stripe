from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse

from stripe_payments.models import (
    StripeCustomer,
    StripePaymentTransaction,
    StripeRefundTransaction,
    StripeSubscription,
    StripeWebhookEvent
)


@admin.register(StripeCustomer)
class StripeCustomerAdmin(admin.ModelAdmin):
    list_display = ('user', 'stripe_customer_id', 'email', 'name', 'created_at')
    search_fields = ('user__username', 'stripe_customer_id', 'email', 'name')
    readonly_fields = ('stripe_customer_id', 'created_at', 'updated_at', 'raw_response')
    list_filter = ('created_at',)


@admin.register(StripePaymentTransaction)
class StripePaymentTransactionAdmin(admin.ModelAdmin):
    list_display = (
        'order_reference',
        'status_badge',
        'amount_display',
        'customer_display',
        'payment_method_display',
        'created_at'
    )
    list_filter = ('status', 'currency', 'created_at')
    search_fields = (
        'order_reference',
        'stripe_payment_intent_id',
        'stripe_checkout_session_id',
        'customer_email',
        'customer_name'
    )
    readonly_fields = (
        'stripe_payment_intent_id',
        'stripe_checkout_session_id',
        'order_reference',
        'amount',
        'currency',
        'amount_received',
        'client_secret',
        'checkout_url',
        'receipt_url',
        'raw_response',
        'created_at',
        'updated_at',
        'completed_at'
    )
    actions = ['refresh_status']

    def status_badge(self, obj):
        colors = {
            'succeeded': '#28a745',
            'processing': '#ffc107',
            'requires_payment_method': '#dc3545',
            'requires_action': '#17a2b8',
            'canceled': '#6c757d',
        }
        color = colors.get(obj.status, '#333')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 5px; border-radius: 3px;">{}</span>',
            color,
            obj.status
        )
    status_badge.short_description = 'Status'

    def amount_display(self, obj):
        return f"{obj.currency.upper()} {obj.amount}"
    amount_display.short_description = 'Amount'

    def customer_display(self, obj):
        if obj.user:
            return format_html('<a href="{}">{}</a>',
                               reverse('admin:auth_user_change', args=[obj.user.pk]),
                               obj.user.username)
        return obj.customer_email or obj.customer_name or "Unknown"
    customer_display.short_description = 'Customer'

    def payment_method_display(self, obj):
        if obj.card_brand:
            return f"{obj.card_brand} **** {obj.card_last4}"
        return obj.payment_method_type or "-"
    payment_method_display.short_description = 'Payment Method'

    def refresh_status(self, request, queryset):
        from stripe_payments.managers.payment_manager import PaymentManager
        manager = PaymentManager()
        count = 0
        for obj in queryset:
            try:
                manager.sync_payment_status(obj.order_reference)
                count += 1
            except Exception as e:
                self.message_user(request, f"Error syncing {obj.order_reference}: {str(e)}", level='ERROR')
        self.message_user(request, f"Successfully synced {count} transactions.")
    refresh_status.short_description = "Sync status from Stripe"


@admin.register(StripeRefundTransaction)
class StripeRefundTransactionAdmin(admin.ModelAdmin):
    list_display = ('stripe_refund_id', 'order_reference', 'status', 'amount', 'currency', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('stripe_refund_id', 'order_reference')
    readonly_fields = ('stripe_refund_id', 'payment_transaction', 'order_reference', 'amount', 'currency', 'raw_response')


@admin.register(StripeSubscription)
class StripeSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('stripe_subscription_id', 'user', 'status_badge', 'amount', 'currency', 'current_period_end', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('stripe_subscription_id', 'user__username', 'stripe_customer_id')

    def status_badge(self, obj):
        colors = {
            'active': '#28a745',
            'trialing': '#17a2b8',
            'past_due': '#ffc107',
            'canceled': '#dc3545',
            'unpaid': '#6c757d',
        }
        color = colors.get(obj.status, '#333')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 5px; border-radius: 3px;">{}</span>',
            color,
            obj.status
        )
    status_badge.short_description = 'Status'


@admin.register(StripeWebhookEvent)
class StripeWebhookEventAdmin(admin.ModelAdmin):
    list_display = ('stripe_event_id', 'event_type', 'processing_status', 'received_at')
    list_filter = ('event_type', 'processing_status', 'received_at')
    search_fields = ('stripe_event_id', 'event_type')
    readonly_fields = ('stripe_event_id', 'event_type', 'payload', 'processing_status', 'error_message', 'received_at', 'processed_at')
