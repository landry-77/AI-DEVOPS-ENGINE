import logging
from abc import ABC, abstractmethod
from django.conf import settings

logger = logging.getLogger(__name__)


class PaymentBackend(ABC):
    @abstractmethod
    def create_checkout_session(self, customer_email: str, organization_name: str, price_id: str = None, success_url: str = None, cancel_url: str = None) -> dict:
        ...

    @abstractmethod
    def handle_webhook(self, payload: bytes, signature: str = None) -> dict:
        ...


class StripeBackend(PaymentBackend):
    def __init__(self):
        import stripe as stripe_lib
        self.stripe = stripe_lib
        self.stripe.api_key = settings.STRIPE_SECRET_KEY

    def create_checkout_session(self, customer_email: str, organization_name: str, price_id: str = None, success_url: str = None, cancel_url: str = None) -> dict:
        price_id = price_id or settings.STRIPE_ENTERPRISE_PRICE_ID
        success_url = success_url or settings.STRIPE_SUCCESS_URL
        cancel_url = cancel_url or settings.STRIPE_CANCEL_URL
        session = self.stripe.checkout.Session.create(
            customer_email=customer_email,
            payment_method_types=['card'],
            mode='subscription',
            line_items=[{'price': price_id, 'quantity': 1}],
            metadata={"organization_name": organization_name},
            success_url=success_url + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=cancel_url,
        )
        return {"url": session.url, "session_id": session.id}

    def handle_webhook(self, payload: bytes, signature: str = None) -> dict:
        try:
            event = self.stripe.Webhook.construct_event(payload, signature, settings.STRIPE_WEBHOOK_SIGNING_SECRET)
            event_type = event['type']
            data = event['data']['object']
            if event_type == 'checkout.session.completed':
                org_name = data['metadata'].get('organization_name')
                logger.info(f"[Stripe] Subscription completed for {org_name}")
                return {"event": event_type, "organization_name": org_name, "status": "completed"}
            elif event_type == 'customer.subscription.deleted':
                customer = data.get('customer')
                logger.info(f"[Stripe] Subscription cancelled for customer {customer}")
                return {"event": event_type, "customer": customer, "status": "cancelled"}
            return {"event": event_type, "status": "ignored"}
        except (ValueError, Exception) as e:
            logger.error(f"[Stripe] Webhook error: {e}")
            return {"event": "error", "status": "failed", "error": str(e)}


class ManualInvoiceBackend(PaymentBackend):
    def create_checkout_session(self, customer_email: str, organization_name: str, price_id: str = None, success_url: str = None, cancel_url: str = None) -> dict:
        logger.info(f"[ManualInvoice] Checkout requested for {organization_name} ({customer_email})")
        return {
            "url": settings.PAYMENT_MANUAL_REDIRECT_URL or "/dashboard/",
            "session_id": None,
            "manual": True,
            "message": "Invoice will be sent manually. Our team will contact you at " + customer_email,
        }

    def handle_webhook(self, payload: bytes, signature: str = None) -> dict:
        logger.info("[ManualInvoice] Webhook received (no-op for manual billing)")
        return {"event": "manual_webhook", "status": "noop"}


BACKEND_MAP = {
    "stripe": StripeBackend,
    "manual": ManualInvoiceBackend,
}


def get_payment_backend() -> PaymentBackend:
    backend_name = getattr(settings, "PAYMENT_GATEWAY", "stripe").lower()
    backend_cls = BACKEND_MAP.get(backend_name)
    if not backend_cls:
        logger.warning(f"Unknown PAYMENT_GATEWAY '{backend_name}', falling back to stripe")
        backend_cls = StripeBackend
    return backend_cls()
