import pytest
from django.test import Client

from apps.accounts.models import CustomUser
from apps.billing.payments.models import Payment
from apps.matters.models import Matter


@pytest.fixture
def user():
    user = CustomUser.objects.create(
        username="Ollie", email="ollie@gmail.com", user_rate=100
    )
    user.set_password("clawboy")
    user.save()

    return user


@pytest.fixture
def client(user):
    client = Client()

    client.login(username="Ollie", password="clawboy")

    return client


@pytest.fixture
def matter():
    matter = Matter.objects.create(
        name="Sample Test Matter",
        description="Awaiting response from OC",
        status="Open",
        practice_area="General",
    )

    return matter


@pytest.fixture
def payment(user, matter):
    payment = Payment.objects.create(
        matter=matter,
        date="2024-05-01",
        amount=1000,
        payment_method="CARD",
    )

    return payment


@pytest.fixture
def payment_data(payment):
    exclude_keys = {"_state", "id", "matter_id"}

    payment_data = {
        key: value for key, value in payment.__dict__.items() if key not in exclude_keys
    }

    payment_data["matter"] = payment.matter

    return payment_data
