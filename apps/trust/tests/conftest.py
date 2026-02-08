import pytest
from django.test import Client

from apps.accounts.models import CustomUser
from apps.contacts.models import Contact
from apps.folders.models import Folder
from apps.trust.models import Transaction


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
    client.get("/dash/")  # Set daily dash session to avoid redirect
    return client


@pytest.fixture
def folder():
    folder = Folder.objects.create(
        app="contacts",
        name="Mahatmas",
    )
    folder.save()
    return folder


@pytest.fixture
def contact(user, folder):
    contact = Contact.objects.create(
        user=user,
        folder=folder,
        name="Mohandas Gandhi",
        company="Gandhi, PC",
        address="225 Paper Street, Porbandar, India",
        phone1="406.363.1234",
        phone1_label="Work",
        phone2="123.456.2222",
        phone2_label="Mobile",
        phone3="123.456.5555",
        phone3_label="Other",
        email="gandhi@gandhi.com",
        website="gandhi.com",
        notes="The Mahatma",
    )
    contact.save()
    return contact


@pytest.fixture
def contact_data(contact):
    contact_data = contact.__dict__.copy()
    keys = "_state id google_id map intake_id".split()

    for key in keys:
        del contact_data[key]

    return {k: v for k, v in contact_data.items() if v is not None}


@pytest.fixture
def transaction(contact):
    transaction = Transaction.objects.create(
        contact=contact,
        date="2022-12-29",
        type="Deposit",
        description="Retainer",
        amount=2000.00,
        confirmed=0,
    )
    transaction.save()
    return transaction


@pytest.fixture
def transaction_data(transaction):
    transaction_data = transaction.__dict__.copy()

    keys = "_state id".split()

    for key in keys:
        del transaction_data[key]

    transaction_data["contact"] = transaction_data["contact_id"]
    del transaction_data["entered"]

    # Filter out None values - Django test client rejects them
    return {k: v for k, v in transaction_data.items() if v is not None}
