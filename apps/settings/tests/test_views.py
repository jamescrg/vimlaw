import pytest
from django.urls import reverse
from pytest_django.asserts import assertTemplateUsed

pytestmark = pytest.mark.django_db


def test_index(client):
    response = client.get("/settings/")
    assert response.status_code == 200

    response = client.get(reverse("settings:settings"))
    assertTemplateUsed(response, "settings/session/index.html")

    assert "contacts_token" in response.context
