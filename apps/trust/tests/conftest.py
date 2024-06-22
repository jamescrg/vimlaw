import pytest

from django.test import Client

from accounts.models import CustomUser
from apps.contacts.models import Contact
from apps.folders.models import Folder
from apps.trust.models import Transaction


@pytest.fixture
def user():
    user = CustomUser.objects.create_user("Ollie", "ollie@gmail.com", "clawboy")
    return user


@pytest.fixture
def client(user):
    client = Client()
    client.login(username="Ollie", password="clawboy")
    return client


@pytest.fixture
def folder(user):
    folder = Folder.objects.create(
        user=user,
        page="contacts",
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
    contact_data = contact.__dict__
    keys = "_state id google_id map intake_id".split()
    for key in keys:
        del contact_data[key]
    return contact_data


@pytest.fixture
def transaction(contact):
    transaction = Transaction.objects.create(
        contact=contact,
        date="2022-12-29",
        type="Deposit",
        description="Retainer",
        amount=2000.00,
        entered=0,
        confirmed=0,
    )
    transaction.save()
    return transaction


@pytest.fixture
def transaction_data(transaction):
    transaction_data = transaction.__dict__
    keys = "_state id".split()
    for key in keys:
        del transaction_data[key]
    return transaction_data
