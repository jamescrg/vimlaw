"""
Tests for authentication and authorization scenarios.

Tests that unauthenticated users are redirected to login page.
The app uses @login_required decorator which returns 302 redirect to login.
"""

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def unauthenticated_client():
    """Client that is not logged in."""
    return Client()


# -----------------------------------------------------
# Settings app - unauthenticated access tests
# -----------------------------------------------------
def test_settings_index_requires_login(unauthenticated_client):
    response = unauthenticated_client.get("/settings/")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


def test_users_index_requires_login(unauthenticated_client):
    response = unauthenticated_client.get("/settings/users/")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


def test_profile_index_requires_login(unauthenticated_client):
    response = unauthenticated_client.get("/settings/profile/")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


# -----------------------------------------------------
# Activity app - unauthenticated access tests
# -----------------------------------------------------
def test_time_index_requires_login(unauthenticated_client):
    response = unauthenticated_client.get("/activity/")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


def test_time_add_requires_login(unauthenticated_client):
    response = unauthenticated_client.get("/activity/time/add")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


def test_expenses_index_requires_login(unauthenticated_client):
    response = unauthenticated_client.get("/activity/expenses/")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


# -----------------------------------------------------
# Matters app - unauthenticated access tests
# -----------------------------------------------------
def test_matters_index_requires_login(unauthenticated_client):
    response = unauthenticated_client.get("/matters/")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


def test_matters_add_requires_login(unauthenticated_client):
    response = unauthenticated_client.get("/matters/add")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


# -----------------------------------------------------
# Contacts app - unauthenticated access tests
# -----------------------------------------------------
def test_contacts_index_requires_login(unauthenticated_client):
    response = unauthenticated_client.get("/contacts/")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


# -----------------------------------------------------
# Invoicing app - unauthenticated access tests
# -----------------------------------------------------
def test_invoices_index_requires_login(unauthenticated_client):
    response = unauthenticated_client.get("/invoicing/")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


def test_payments_index_requires_login(unauthenticated_client):
    response = unauthenticated_client.get("/invoicing/payments/")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


# -----------------------------------------------------
# Trust app - unauthenticated access tests
# -----------------------------------------------------
def test_trust_index_requires_login(unauthenticated_client):
    response = unauthenticated_client.get("/trust/")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


# -----------------------------------------------------
# Intakes app - unauthenticated access tests
# -----------------------------------------------------
def test_intakes_index_requires_login(unauthenticated_client):
    response = unauthenticated_client.get("/intakes/")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


# -----------------------------------------------------
# Agenda app - unauthenticated access tests
# -----------------------------------------------------
def test_agenda_tasks_requires_login(unauthenticated_client):
    response = unauthenticated_client.get("/agenda/tasks/list/")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url


def test_agenda_events_requires_login(unauthenticated_client):
    response = unauthenticated_client.get("/events/list/")
    assert response.status_code == 302
    assert "/accounts/login/" in response.url
