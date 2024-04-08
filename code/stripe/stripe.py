import logging
from datetime import datetime

import stripe
from authentication.models import User
from app.models import AppPlan, AppSubscription
from django.conf import settings

celery_logger = logging.getLogger("celery")
django_logger = logging.getLogger("django")


class StripeSubscriptionService:
    """Use this service to work with stripe subscription system"""

    def __init__(self, user: User = None, plan: AppPlan = None) -> None:
        """
        :param user: Stripe customer's user
        :param plan: subscription plan
        """

        self.user: User = user
        self.plan: AppPlan = plan
        stripe.api_key = settings.STRIPE_SECRET_KEY

    def update_or_create_customer(self, payment_method: str) -> User:
        """Creates customer for stripe if does not exist for current user
        else returns existed stripe customer for current user

        :param payment_method: token returned by Stripe.js
        :return: User instance
        """
        if not self.user.stripe_customer_id:
            try:
                resp = stripe.Customer.create(
                    payment_method=payment_method,
                    email=self.user.email,
                    invoice_settings={"default_payment_method": payment_method},
                )
            except stripe.error.InvalidRequestError as e:
                django_logger.error(e)
                return
            self.user.stripe_customer_id = resp["id"]
            self.user.save()
            django_logger.info(f"New Stripe customer {resp['id']} was created")
        else:
            # * Attach payment method to stripe customer
            try:
                pm = stripe.PaymentMethod.attach(payment_method, customer=self.user.stripe_customer_id)
                stripe.Customer.modify(
                    self.user.stripe_customer_id,
                    invoice_settings={"default_payment_method": pm.stripe_id},
                )
                # * Try to update payment method if subscription present
                try:
                    self.user.app_subscription.card = pm.card.last4
                    self.user.app_subscription.save(update_fields=["card"])
                except User.app_subscription.RelatedObjectDoesNotExist as e:
                    django_logger.error(e)
            except stripe.error.AuthenticationError as e:
                django_logger.error(e)
                return
            django_logger.info(f"Source of Stripe customer {self.user.stripe_customer_id} was updated")
        return self.user

    def create_subscription(self) -> AppSubscription:
        """Creates subscription on stripe and
        subscription object with all required data

        :return: user's AppSubscription instance
        """
        try:
            resp = stripe.Subscription.create(
                customer=self.user.stripe_customer_id,
                items=[
                    {"price": self.plan.price_token},
                ],
            )
        except stripe.error.InvalidRequestError as e:
            django_logger.error(e)
            return
        except stripe.error.AuthenticationError as e:
            django_logger.error(e)
            return
        try:
            customer = stripe.Customer.retrieve(resp["customer"])
            card = customer.retrieve_payment_method(customer["invoice_settings"]["default_payment_method"])["card"]
        except stripe.error.InvalidRequestError as e:
            django_logger.error(e)
        subscription, _ = AppSubscription.objects.update_or_create(
            user=self.user,
            defaults={
                "subscription_id": resp["id"],
                "start_date": datetime.fromtimestamp(resp["start_date"]),
                "current_period_end": datetime.fromtimestamp(resp["current_period_end"]),
                "cancel_at_period_end": resp["cancel_at_period_end"],
                "plan": self.plan,
                "is_active": True,
                "card": card.get("last4", ""),
                "canceled_at": None,
            },
        )
        return subscription

    def modify_subscription(self) -> AppSubscription:
        """Modifies existed subscription on stripe and
        subscription object with all required data

        :return: user's StripeSubscription instance
        """
        try:
            subscription = stripe.Subscription.retrieve(self.user.app_subscription.subscription_id)
            resp = stripe.Subscription.modify(
                subscription["id"],
                cancel_at_period_end=False,
                proration_behavior="create_prorations",
                items=[
                    {
                        "id": subscription["items"]["data"][0]["id"],
                        "price": self.plan.price_token,
                    },
                ],
            )
        except (stripe.error.InvalidRequestError, stripe.error.AuthenticationError) as e:
            django_logger.error(e)
            return

        subscription, _ = AppSubscription.objects.update_or_create(
            user=self.user,
            defaults={
                "start_date": datetime.fromtimestamp(resp["start_date"]),
                "current_period_end": datetime.fromtimestamp(resp["current_period_end"]),
                "cancel_at_period_end": resp["cancel_at_period_end"],
                "plan": self.plan,
                "is_active": True,
                "canceled_at": None,
            },
        )
        return subscription

    def cancel_subscription_immediately(self) -> AppSubscription:
        """Cancel immediately current subscription on stripe
        and set inactive current user subscription.
        WARNING! We shouldn't use it for real users

        :return: user's Stripe subscription instance
        """
        try:
            resp = stripe.Subscription.delete(self.user.app_subscription.subscription_id)
        except (stripe.error.InvalidRequestError, stripe.error.AuthenticationError) as e:
            celery_logger.error(e)
            return
        self.user.app_subscription.canceled_at = datetime.fromtimestamp(resp["canceled_at"])
        self.user.app_subscription.cancel_at_period_end = resp["cancel_at_period_end"]
        self.user.app_subscription.current_period_end = resp["current_period_end"]
        self.user.app_subscription.is_active = False
        self.user.app_subscription.save()
        return self.user.app_subscription

    def cancel_subscription_at_period_end(self) -> AppSubscription:
        """Cancel at period end current subscription on stripe
        and set inactive current user subscription

        :return: user's Stripe subscription instance
        """
        try:
            resp = stripe.Subscription.modify(
                self.user.app_subscription.subscription_id,
                cancel_at_period_end=True,
            )
        except stripe.error.InvalidRequestError as e:
            celery_logger.error(e)
            return
        except stripe.error.AuthenticationError as e:
            celery_logger.error(e)
            return
        self.user.app_subscription.canceled_at = datetime.fromtimestamp(resp["canceled_at"])
        self.user.app_subscription.current_period_end = datetime.fromtimestamp(resp["current_period_end"])
        self.user.app_subscription.cancel_at_period_end = resp["cancel_at_period_end"]
        self.user.app_subscription.save()
        return self.user.app_subscription

    @staticmethod
    def finalize_invoice(invoice_id) -> None:
        """Finalizes a draft invoice manually and attempt to pay it

        :param invoice_id: Stripe invoice ID
        """
        try:
            stripe.Invoice.finalize_invoice(invoice_id)
            stripe.Invoice.pay(invoice_id)
        except stripe.error.InvalidRequestError as e:
            django_logger.error(e)
            return
        except stripe.error.AuthenticationError as e:
            django_logger.error(e)
            return
