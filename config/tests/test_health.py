from unittest.mock import patch

import pytest
from django.db import OperationalError
from django.urls import reverse


def test_liveness_does_not_require_authentication_or_database(client):
    with patch("config.health.connection.cursor") as cursor:
        response = client.get(reverse("health-live"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response["Cache-Control"] == "no-store"
    cursor.assert_not_called()


@pytest.mark.django_db
def test_readiness_checks_database(client):
    response = client.get(reverse("health-ready"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_returns_503_when_database_is_unavailable(client):
    with patch("config.health.connection.cursor", side_effect=OperationalError):
        response = client.get(reverse("health-ready"))

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
